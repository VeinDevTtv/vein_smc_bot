import backtrader as bt
import math
from datetime import datetime, time

class NAS100_ICT_SMC_Strategy(bt.Strategy):
    params = dict(
        risk_per_trade=0.005,       # Risk 0.5% of equity per trade
        leverage=50,                # Leverage for margin calculation (e.g. 50x)
        killzone_london=(time(2, 0), time(5, 0)),   # London Killzone (NY 2:00-5:00 AM):contentReference[oaicite:8]{index=8}
        killzone_ny=(time(8, 30), time(11, 0)),     # New York Killzone (NY 8:30-11:00 AM):contentReference[oaicite:9]{index=9}
        use_killzones=True, 
        rr_target=2.0,              # Reward:Risk target (e.g. 2.0 for 2:1)
        tick_size=0.01,             # Instrument tick size for rounding prices
        stop_loss_buffer=0.01       # Extra buffer for stop-loss beyond liquidity level
    )

    def __init__(self):
        # Data0: 5-minute data, Data1: 1-hour data for bias
        self.data5 = self.datas[0]
        self.data1h = self.datas[1] if len(self.datas) > 1 else None
        # Variables for tracking market structure and orders
        self.current_bias = None
        self.last_high_level = None
        self.last_low_level = None
        self.entry_order = None
        self.stop_order = None
        self.target_order = None

    def log(self, txt, dt=None):
        """Log messages with timestamp (to console)."""
        dt = dt or self.data.datetime.datetime(0)
        if isinstance(dt, float):
            dt = bt.num2date(dt)
        print(f"{dt:%Y-%m-%d %H:%M:%S} - {txt}")

    def in_killzone(self):
        """Return True if current time is within a defined killzone window."""
        if not self.p.use_killzones:
            return True
        current_dt = self.data.datetime.datetime(0)
        t = current_dt.time()
        kz1_start, kz1_end = self.p.killzone_london
        kz2_start, kz2_end = self.p.killzone_ny
        if kz1_start <= t <= kz1_end or kz2_start <= t <= kz2_end:
            return True
        return False

    def update_bias(self):
        """Update 1-hour bias based on market structure breaks (fractals/BOS)."""
        if not self.data1h or len(self.data1h) < 5:
            return  # need enough hourly bars
        # Identify recent swing high/low on 1H using a 5-bar fractal (bar -3 as center)
        idx = -3  # center of the fractal when we have at least 5 bars
        if len(self.data1h) >= 5:
            # Swing High fractal: high at idx is greater than highs of two bars on each side
            if (self.data1h.high[idx] > self.data1h.high[idx-1] and 
                self.data1h.high[idx] > self.data1h.high[idx-2] and 
                self.data1h.high[idx] > self.data1h.high[idx+1] and 
                self.data1h.high[idx] > self.data1h.high[idx+2]):
                self.last_high_level = float(self.data1h.high[idx])
            # Swing Low fractal: low at idx is lower than lows of two bars on each side
            if (self.data1h.low[idx] < self.data1h.low[idx-1] and 
                self.data1h.low[idx] < self.data1h.low[idx-2] and 
                self.data1h.low[idx] < self.data1h.low[idx+1] and 
                self.data1h.low[idx] < self.data1h.low[idx+2]):
                self.last_low_level = float(self.data1h.low[idx])
        # Determine bias flip on break of structure: 
        last_close = float(self.data1h.close[-1])
        new_bias = self.current_bias
        if self.last_high_level and last_close > self.last_high_level:
            new_bias = "long"
        elif self.last_low_level and last_close < self.last_low_level:
            new_bias = "short"
        if new_bias and new_bias != self.current_bias:
            self.current_bias = new_bias
            self.log(f"Higher timeframe bias changed to {new_bias.upper()}")

    def next(self):
        """Main strategy logic executed on each new 5-minute bar."""
        # Ensure sufficient data before processing
        if len(self.data5) < 20:
            return
        if self.data1h and len(self.data1h) < 5:
            return
        # Update bias at the start of each bar (especially when a new 1H bar closes)
        if self.data1h:
            self.update_bias()
        # Cancel pending entry if conditions invalidated (left killzone or bias changed)
        if self.entry_order and self.entry_order.alive():
            if (not self.in_killzone()) or (self.current_bias and 
               ((self.entry_order.isbuy() and self.current_bias != "long") or 
                (self.entry_order.issell() and self.current_bias != "short"))):
                self.cancel(self.entry_order)
        # If already in a position, rely on bracket orders for exit – no new entries
        if self.position:
            return
        # If an entry order is already pending, do not look for new entries
        if self.entry_order and self.entry_order.alive():
            return
        # Only trade during killzone times
        if not self.in_killzone():
            return
        # Require a determined bias to look for setups
        if self.current_bias is None:
            return

        # Determine setup direction based on bias
        if self.current_bias == "long":
            # Long setup: look for a sweep of recent lows and then BOS upwards
            N = 10  # lookback for liquidity low
            if len(self.data5.low) < N:
                recent_low = min(self.data5.low)  # if history shorter, take min of all
            else:
                recent_low = min(self.data5.low.get(-N, N))
            if self.data5.low[0] < recent_low:
                # Liquidity sweep down (current low breaks recent low)
                M = 5  # lookback for a local swing high
                if len(self.data5.high) < M:
                    recent_high = max(self.data5.high)
                else:
                    recent_high = max(self.data5.high.get(-M, M))
                if self.data5.close[0] > recent_high:
                    # Structure break up (current close breaks recent swing high)
                    swing_low = float(self.data5.low[0])
                    swing_high = float(self.data5.close[0])
                    # Optimal Trade Entry at ~70.5% retrace into the impulse range:contentReference[oaicite:10]{index=10}
                    ote_price = swing_low + 0.705 * (swing_high - swing_low)
                    entry_price = round(ote_price, 2)
                    stop_price = round(swing_low - self.p.stop_loss_buffer, 2)
                    # Risk management: position size for 0.5% equity risk
                    equity = self.broker.getvalue()
                    risk_amount = equity * self.p.risk_per_trade
                    stop_distance = entry_price - stop_price  # positive value (long)
                    if stop_distance <= 0:
                        return  # invalid stop distance
                    pos_size = risk_amount / stop_distance
                    # Margin cap enforcement: adjust size if not enough free margin
                    if self.p.leverage:
                        margin_needed = (entry_price * pos_size) / self.p.leverage
                        available_margin = self.broker.get_cash()
                        if margin_needed > available_margin:
                            max_pos = (available_margin * self.p.leverage) / entry_price
                            pos_size = max_pos
                    # Round position size to 2 decimal places (tick size for volume if needed)
                    pos_size = math.floor(pos_size * 100) / 100.0
                    if pos_size <= 0:
                        return  # cannot trade if size is zero
                    # Define profit target at RR multiple
                    risk_per_unit = entry_price - stop_price
                    target_price = round(entry_price + self.p.rr_target * risk_per_unit, 2)
                    # Place bracket order: buy limit, with attached stop and target
                    orders = self.buy_bracket(price=entry_price, limitprice=target_price, 
                                               stopprice=stop_price, size=pos_size)
                    self.entry_order = orders[0]      # main entry order
                    self.target_order = orders[1]     # take-profit order
                    self.stop_order = orders[2]       # stop-loss order
                    self.log(f"Placed LONG entry order at {entry_price:.2f}, SL {stop_price:.2f}, TP {target_price:.2f}, size {pos_size}")
        elif self.current_bias == "short":
            # Short setup: look for a sweep of recent highs and then BOS downwards
            N = 10  # lookback for liquidity high
            if len(self.data5.high) < N:
                recent_high = max(self.data5.high)
            else:
                recent_high = max(self.data5.high.get(-N, N))
            if self.data5.high[0] > recent_high:
                # Liquidity sweep up (current high breaks recent high)
                M = 5  # lookback for a local swing low
                if len(self.data5.low) < M:
                    recent_low = min(self.data5.low)
                else:
                    recent_low = min(self.data5.low.get(-M, M))
                if self.data5.close[0] < recent_low:
                    # Structure break down (current close breaks recent swing low)
                    swing_high = float(self.data5.high[0])
                    swing_low = float(self.data5.close[0])
                    # Optimal Trade Entry ~70.5% retracement of the drop
                    ote_price = swing_high - 0.705 * (swing_high - swing_low)
                    entry_price = round(ote_price, 2)
                    stop_price = round(swing_high + self.p.stop_loss_buffer, 2)
                    # Risk management: 0.5% equity risk
                    equity = self.broker.getvalue()
                    risk_amount = equity * self.p.risk_per_trade
                    stop_distance = stop_price - entry_price  # positive value (short)
                    if stop_distance <= 0:
                        return
                    pos_size = risk_amount / stop_distance
                    # Margin cap enforcement
                    if self.p.leverage:
                        margin_needed = (entry_price * pos_size) / self.p.leverage
                        available_margin = self.broker.get_cash()
                        if margin_needed > available_margin:
                            max_pos = (available_margin * self.p.leverage) / entry_price
                            pos_size = max_pos
                    pos_size = math.floor(pos_size * 100) / 100.0
                    if pos_size <= 0:
                        return
                    # Profit target at RR multiple
                    risk_per_unit = stop_price - entry_price
                    target_price = round(entry_price - self.p.rr_target * risk_per_unit, 2)
                    # Place bracket order: sell limit, with attached stop and target
                    orders = self.sell_bracket(price=entry_price, limitprice=target_price, 
                                                stopprice=stop_price, size=pos_size)
                    self.entry_order = orders[0]
                    self.target_order = orders[1]
                    self.stop_order = orders[2]
                    self.log(f"Placed SHORT entry order at {entry_price:.2f}, SL {stop_price:.2f}, TP {target_price:.2f}, size {pos_size}")

    def notify_order(self, order):
        """Monitor order statuses and log fills or cancellations."""
        if order.status in [order.Submitted, order.Accepted]:
            # Order accepted by broker (not yet executed or canceled)
            return
        if order.status == order.Completed:
            if order.isbuy():
                # Buy executed (could be long entry or short-cover exit)
                if order == self.entry_order:
                    self.log(f"LONG entry executed at {order.executed.price:.2f}, size {order.executed.size}")
                else:
                    # A buy that is not the entry means it’s covering a short (exit)
                    created_price = order.created.price  # initial order price
                    if order.executed.price >= created_price:
                        self.log(f"SHORT stop-loss hit at {order.executed.price:.2f}")
                    else:
                        self.log(f"SHORT take-profit hit at {order.executed.price:.2f}")
            elif order.issell():
                # Sell executed (could be short entry or long exit)
                if order == self.entry_order:
                    self.log(f"SHORT entry executed at {order.executed.price:.2f}, size {order.executed.size}")
                else:
                    # A sell not the entry means it's closing a long position
                    created_price = order.created.price
                    if order.executed.price <= created_price:
                        self.log(f"LONG stop-loss hit at {order.executed.price:.2f}")
                    else:
                        self.log(f"LONG take-profit hit at {order.executed.price:.2f}")
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            # Handle cancellations or rejections
            if order == self.entry_order:
                self.log(f"Entry order canceled/rejected (Reason: {order.getstatusname()})")
            # If main order is canceled, ensure any attached stop/limit are canceled as well
            if self.stop_order and self.stop_order.alive():
                self.cancel(self.stop_order)
            if self.target_order and self.target_order.alive():
                self.cancel(self.target_order)

    def notify_trade(self, trade):
        """Log final PnL when trade is closed (both target or stop)."""
        if trade.isclosed:
            pnl = trade.pnl
            self.log(f"Trade closed. P/L: {pnl:.2f}")
