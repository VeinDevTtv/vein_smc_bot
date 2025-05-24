import backtrader as bt

# Helper functions for ICT/SMC pattern detection
def calc_ote_levels(low, high):
    """Calculate the Optimal Trade Entry fib retracement levels (62% and 79%)."""
    range = high - low
    level62 = low + 0.618 * range
    level79 = low + 0.79 * range
    return level62, level79

def find_fvg(data, lookback=5):
    """Detect the most recent Fair Value Gap (FVG) in the last `lookback` bars.
    Returns (gap_top, gap_bottom) if an FVG is found, otherwise None."""
    # We need at least 3 bars to define a gap (prev, current, next)
    # Check each sequence of 3 bars within lookback window for gap condition
    for idx in range(-lookback, -2):  # idx is the "current" candle index in the trio
        # Define the trio: prev = idx-1, curr = idx, next = idx+1
        prev_high = data.high[idx-1] 
        prev_low  = data.low[idx-1]
        curr_high = data.high[idx]
        curr_low  = data.low[idx]
        next_high = data.high[idx+1]
        next_low  = data.low[idx+1]
        # Check bullish gap: previous high < next low (curr candle presumably bullish)
        if prev_high < next_low:
            gap_top = next_low
            gap_bottom = prev_high
            return (gap_top, gap_bottom)
        # Check bearish gap: previous low > next high (curr candle bearish)
        if prev_low > next_high:
            gap_top = prev_low
            gap_bottom = next_high
            return (gap_top, gap_bottom)
    return None

def find_last_order_block(data, end_index, direction='bullish'):
    """Find the last Order Block candle (bearish candle for bullish OB, or bullish candle for bearish OB)
    before the bar at end_index. Returns (ob_high, ob_low) price range of the OB."""
    if direction == 'bullish':
        # For a bullish setup, find last down (bearish) candle
        for i in range(end_index, end_index-10, -1):  # scan up to 10 bars back
            if data.close[i] < data.open[i]:  # down candle
                return data.high[i], data.low[i]
    else:  # bearish direction, find last up candle
        for i in range(end_index, end_index-10, -1):
            if data.close[i] > data.open[i]:  # up candle
                return data.high[i], data.low[i]
    return None

class IctSmcStrategy(bt.Strategy):
    params = dict(
        risk_per_trade=0.005,   # 0.5% of equity risk
        rr_tp1=3.0,            # first target R:R (3R)
        rr_tp2=5.0,            # second target R:R (5R)
        killzone_london=(2, 5), # London killzone hours (NY time 2:00-5:00)
        killzone_ny=(8.5, 11)   # NY killzone hours (8:30-11:00, 8.5 used for 8:30)
    )
    
    def __init__(self):
        # Data aliases for clarity
        self.data5m = self.datas[0]    # 5-minute data
        self.data1h = self.datas[1]    # 1-hour data
        # Variables for 1H market structure bias
        self.htf_bias = None           # 'bullish' or 'bearish'
        self.last_swing_high = None
        self.last_swing_low = None
        self.last_h1_bar_time = None   # track last processed 1H bar time
        # Order and trade management references
        self.entry_order = None
        self.stop_order = None
        self.tp1_order = None
        self.tp2_order = None
        # Track entry details for logging
        self.entry_price = None
        self.stop_price = None
        self.entry_reason = None
        self.initial_risk_cash = None  # amount of cash risked initially

    def log(self, text, dt=None):
        """Logging function for this strategy (prints to console or file)."""
        dt = dt or self.data.datetime.datetime(0)
        print(f'{dt}: {text}')

    def notify_order(self, order):
        """Monitor order status to handle fills and modifications."""
        if order.status in [order.Submitted, order.Accepted]:
            return  # Order is active and pending
        if order.status == order.Completed:
            # Order filled
            if order is self.entry_order:
                # Entry filled: record price and place stop loss & take-profit orders
                self.entry_price = order.executed.price
                # Calculate position size from order execution (could also use order.executed.size)
                position_size = order.executed.size
                # Determine stop-loss price (stored from setup) and place stop order
                stop_price = self.stop_price
                if position_size > 0:
                    # Long position stop (sell stop)
                    self.stop_order = self.sell(exectype=bt.Order.Stop, price=stop_price, size=position_size)
                else:
                    # Short position stop (buy stop)
                    self.stop_order = self.buy(exectype=bt.Order.Stop, price=stop_price, size=-position_size)
                # Set take-profit orders
                # If position is large enough, use partial profits
                if position_size > 1:
                    half_size = int(abs(position_size) / 2)  # half of the position
                else:
                    half_size = abs(position_size)  # if size=1, we'll use single target
                # Calculate profit target prices based on R:R multiples
                if position_size > 0:  # long
                    tp1_price = self.entry_price + self.params.rr_tp1 * (self.entry_price - self.stop_price)
                    tp2_price = self.entry_price + self.params.rr_tp2 * (self.entry_price - self.stop_price)
                else:  # short
                    tp1_price = self.entry_price - self.params.rr_tp1 * (self.stop_price - self.entry_price)
                    tp2_price = self.entry_price - self.params.rr_tp2 * (self.stop_price - self.entry_price)
                if position_size > 1:
                    # Place two limit orders for partial take-profits
                    self.tp1_order = (self.sell(limitprice=tp1_price, size=half_size) if position_size > 0 
                                      else self.buy(limitprice=tp1_price, size=half_size))
                    remaining_size = abs(position_size) - half_size
                    self.tp2_order = (self.sell(limitprice=tp2_price, size=remaining_size) if position_size > 0 
                                      else self.buy(limitprice=tp2_price, size=remaining_size))
                else:
                    # If size is 1, use a single take-profit at the larger R:R (using TP2 for ambition or TP1 for safety)
                    self.tp1_order = None
                    # Use TP2 price if we aim for full 5R with single position, or tp1_price for 3R. Here choose 3R to be conservative:
                    tp_final = tp1_price
                    self.tp2_order = (self.sell(limitprice=tp_final, size=abs(position_size)) if position_size > 0 
                                      else self.buy(limitprice=tp_final, size=abs(position_size)))
                # Log the entry details
                self.log(f"Entered {'LONG' if position_size>0 else 'SHORT'} @ {self.entry_price:.2f}, Stop @ {self.stop_price:.2f}, TP1 @ {tp1_price:.2f}, TP2 @ {tp2_price:.2f}. Reason: {self.entry_reason}")
            elif order is self.tp1_order:
                # Partial take-profit filled
                self.log(f"Partial profit taken at {order.executed.price:.2f} (approx {self.params.rr_tp1}R). Moving stop to breakeven.")
                # Adjust stop loss to break-even for remaining position
                if self.stop_order:  # cancel old stop
                    self.cancel(self.stop_order)
                # Place new stop at entry price for remaining position
                remaining_size = abs(self.position.size)
                if remaining_size > 0:
                    # Long remaining -> sell stop at entry; short remaining -> buy stop at entry
                    if self.position.size > 0:
                        self.stop_order = self.sell(exectype=bt.Order.Stop, price=self.entry_price, size=remaining_size)
                    else:
                        self.stop_order = self.buy(exectype=bt.Order.Stop, price=self.entry_price, size=remaining_size)
            elif order is self.tp2_order:
                # Final take-profit filled
                self.log(f"Final profit taken at {order.executed.price:.2f}. Trade closed.")
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            # Handle canceled or rejected orders if needed
            pass

    def notify_trade(self, trade):
        """Log final trade outcome (called when a trade is closed)."""
        if not trade.isclosed:
            return
        # Calculate R multiples achieved based on initial risk
        pnl = trade.pnl  # profit/loss in currency
        if self.initial_risk_cash:
            R = pnl / self.initial_risk_cash
        else:
            R = None
        outcome = "WIN" if trade.pnl > 0 else "LOSS" if trade.pnl < 0 else "BREAKEVEN"
        if R is not None:
            self.log(f"Trade closed: PnL={pnl:.2f}, Return={R:.2f}R, Outcome={outcome}, Reason: {self.entry_reason}")
        else:
            self.log(f"Trade closed: PnL={pnl:.2f}, Outcome={outcome}, Reason: {self.entry_reason}")
        # Reset trade-related variables for safety
        self.entry_order = self.stop_order = self.tp1_order = self.tp2_order = None
        self.entry_price = self.stop_price = self.entry_reason = None
        self.initial_risk_cash = None

    def next(self):
        """Main logic executed on each new bar (5-minute bars as the smallest timeframe)."""
        # Ensure we have both timeframes ready
        if len(self.data1h) == 0 or len(self.data5m) == 0:
            return

        # Update 1H market structure bias at the close of each 1H bar
        current_h1_time = self.data1h.datetime.datetime(0)
        if self.last_h1_bar_time is None or current_h1_time > self.last_h1_bar_time:
            # A new 1H bar has closed
            idx = len(self.data1h) - 1  # index of the newly closed 1H bar
            if idx >= 2:  # need at least 3 bars to identify swings
                # Identify recent swing high/low on 1H (simple 3-bar fractal approach)
                prev_bar = idx - 1
                # Swing High: high[prev_bar] higher than bars before and after
                if self.data1h.high[prev_bar] > self.data1h.high[idx] and self.data1h.high[prev_bar] > self.data1h.high[prev_bar-1]:
                    self.last_swing_high = self.data1h.high[prev_bar]
                # Swing Low: low[prev_bar] lower than bars before and after
                if self.data1h.low[prev_bar] < self.data1h.low[idx] and self.data1h.low[prev_bar] < self.data1h.low[prev_bar-1]:
                    self.last_swing_low = self.data1h.low[prev_bar]
                # Determine bias flip on break of structure
                if self.htf_bias != 'bullish' and self.last_swing_high and self.data1h.close[0] > self.last_swing_high:
                    self.htf_bias = 'bullish'
                    self.log(f"1H BOS upward – bias set to BULLISH (price broke above {self.last_swing_high:.1f})")
                elif self.htf_bias != 'bearish' and self.last_swing_low and self.data1h.close[0] < self.last_swing_low:
                    self.htf_bias = 'bearish'
                    self.log(f"1H BOS downward – bias set to BEARISH (price broke below {self.last_swing_low:.1f})")
            # Update last seen 1H bar time
            self.last_h1_bar_time = current_h1_time

        # No trade logic if bias is not established yet
        if not self.htf_bias:
            return

        # Check if within allowed trading session (killzones)
        dt = self.data.datetime.datetime(0)  # current 5m bar timestamp
        hour = dt.hour + dt.minute/60.0
        # London killzone filter
        london_start, london_end = self.p.killzone_london  # e.g. (2, 5)
        ny_start, ny_end = self.p.killzone_ny             # e.g. (8.5, 11) for 8:30-11:00
        in_killzone = (london_start <= hour < london_end) or (ny_start <= hour < ny_end)
        if not in_killzone:
            return  # skip setup detection outside killzone times

        # Only one trade at a time – skip if an active trade is open or entry order pending
        if self.position:  # an open position
            return
        if self.entry_order and self.entry_order.alive():  # a pending entry order
            return

        # Identify ICT pattern on 5M: liquidity sweep + structure break
        data = self.data5m  # alias for clarity
        # We will look back a few bars for the characteristic pattern:
        # e.g., for longs: bar[-2] made a low (sweep) and bar[-1] broke above bar[-2]'s high (BOS)
        long_setup = False
        short_setup = False
        setup_bar_index = None  # index of the bar where structure break occurred
        sweep_price = None
        # We require at least 3 bars back to evaluate pattern
        if len(data) >= 3:
            # Bullish setup check (if bias is bullish)
            if self.htf_bias == 'bullish':
                # Condition: find a recent swing low that was taken out (liquidity sweep)
                # and subsequent bar that closed above a prior high.
                # We'll check the last 3-4 bars for simplicity.
                # Check scenario 1: Bar -2 is sweep low, Bar -1 is BOS up
                if data.low[-2] == min(data.low[-2], data.low[-3], data.low[-4], data.low[-1], data.low[0]):  # bar -2 is a local low compared to surrounding
                    if data.close[-1] > data.high[-2]:  # bar -1 closed above the high of the sweep bar -2
                        long_setup = True
                        setup_bar_index = -1
                        sweep_price = data.low[-2]
                        self.entry_reason = f"Liquidity sweep below {sweep_price:.2f} then bullish BOS on 5m"
                # Check scenario 2: Bar -3 sweep, Bar -2 BOS (one bar earlier)
                if not long_setup and len(data) >= 4:
                    if data.low[-3] == min(data.low[-3], data.low[-4], data.low[-2], data.low[-1], data.low[0]):
                        if data.close[-2] > data.high[-3]:
                            long_setup = True
                            setup_bar_index = -2
                            sweep_price = data.low[-3]
                            self.entry_reason = f"Liquidity sweep below {sweep_price:.2f} then bullish BOS on 5m"
            # Bearish setup check (if bias is bearish)
            if self.htf_bias == 'bearish':
                # Scenario 1: Bar -2 is sweep high, Bar -1 is BOS down
                if data.high[-2] == max(data.high[-2], data.high[-3], data.high[-4], data.high[-1], data.high[0]):
                    if data.close[-1] < data.low[-2]:
                        short_setup = True
                        setup_bar_index = -1
                        sweep_price = data.high[-2]
                        self.entry_reason = f"Liquidity sweep above {sweep_price:.2f} then bearish BOS on 5m"
                # Scenario 2: Bar -3 sweep, Bar -2 BOS
                if not short_setup and len(data) >= 4:
                    if data.high[-3] == max(data.high[-3], data.high[-4], data.high[-2], data.high[-1], data.high[0]):
                        if data.close[-2] < data.low[-3]:
                            short_setup = True
                            setup_bar_index = -2
                            sweep_price = data.high[-3]
                            self.entry_reason = f"Liquidity sweep above {sweep_price:.2f} then bearish BOS on 5m"

        # If a setup pattern is identified, prepare entry
        if long_setup or short_setup:
            direction = 'long' if long_setup else 'short'
            # Determine entry zone (OB/FVG) and entry price
            if direction == 'long':
                # Find order block (last down candle before the structure break bar)
                ob = find_last_order_block(data, setup_bar_index, direction='bullish')
                if ob:
                    ob_high, ob_low = ob
                else:
                    # Fallback: use the sweep bar as OB if none found
                    ob_high, ob_low = data.high[setup_bar_index-1], data.low[setup_bar_index-1]
                # Optionally, check for a Fair Value Gap in the impulse move
                fvg = find_fvg(data, lookback=5)
                if fvg:
                    fvg_top, fvg_bottom = fvg
                else:
                    fvg_top, fvg_bottom = None, None
                # Define entry zone as either the OB or FVG area
                if fvg and (fvg_bottom < ob_high): 
                    # If an FVG exists overlapping the OB, refine zone to the combined range
                    zone_top = max(ob_high, fvg_top)
                    zone_bottom = min(ob_low, fvg_bottom)
                else:
                    zone_top, zone_bottom = ob_high, ob_low
                # Calculate OTE fib levels for the swing (sweep low to BOS high)
                swing_low = sweep_price
                swing_high = data.high[setup_bar_index] if setup_bar_index is not None else data.high[-1]
                ote_62, ote_79 = calc_ote_levels(swing_low, swing_high)
                # Choose an entry price within the zone (midpoint of OB/FVG zone, constrained to OTE range)
                entry_price = (zone_top + zone_bottom) / 2
                # Ensure entry is not above 62% level (to remain in OTE zone)
                entry_price = min(entry_price, ote_79)
                # Set stop just below the sweep low
                stop_price = sweep_price * 0.999  # small buffer below sweep low
            else:  # short_setup
                ob = find_last_order_block(data, setup_bar_index, direction='bearish')
                if ob:
                    ob_high, ob_low = ob
                else:
                    ob_high, ob_low = data.high[setup_bar_index-1], data.low[setup_bar_index-1]
                fvg = find_fvg(data, lookback=5)
                if fvg:
                    fvg_top, fvg_bottom = fvg
                else:
                    fvg_top, fvg_bottom = None, None
                if fvg and (fvg_top > ob_low):
                    zone_top = max(ob_high, fvg_top)
                    zone_bottom = min(ob_low, fvg_bottom)
                else:
                    zone_top, zone_bottom = ob_high, ob_low
                # Swing from sweep high down to BOS low
                swing_high = sweep_price
                swing_low = data.low[setup_bar_index] if setup_bar_index is not None else data.low[-1]
                ote_62, ote_79 = calc_ote_levels(swing_low, swing_high)  # note: this returns lower<->higher, here swing_high > swing_low
                # For short, OTE range between 21%-38% retracement (since fib of downswing if we use same function might need inversion)
                # Simpler: mirror logic by inverting high/low for fib if needed
                # We'll just use the zone midpoint for entry and adjust near fib 70%.
                entry_price = (zone_top + zone_bottom) / 2
                entry_price = max(entry_price, ote_62)  # ensure entry not below 62% (for short, 62% of downmove)
                stop_price = sweep_price * 1.001  # just above sweep high
            # Compute position size based on 0.5% risk
            risk_cash = self.params.risk_per_trade * self.broker.getvalue()
            if direction == 'long':
                risk_per_unit = entry_price - stop_price
            else:
                risk_per_unit = stop_price - entry_price
            if risk_per_unit <= 0:
                return  # invalid risk distance, skip
            size = risk_cash / risk_per_unit
            size = int(size)  # use integer number of contracts/shares
            if size <= 0:
                size = 1  # minimum 1 unit
            # Remember the stop price for later order placement
            self.stop_price = stop_price
            # Calculate and store initial risk in cash for logging R later
            self.initial_risk_cash = risk_per_unit * size
            # Send entry order (market or limit into the zone):
            if direction == 'long':
                # Place a limit buy at the desired entry price
                self.entry_order = self.buy(size=size, exectype=bt.Order.Limit, price=entry_price)
            else:
                # Place a limit sell (short) order
                self.entry_order = self.sell(size=size, exectype=bt.Order.Limit, price=entry_price)
            self.log(f"Signal -> {direction.upper()} setup: entry={entry_price:.2f}, stop={stop_price:.2f}, size={size}. Bias={self.htf_bias.upper()}, Reason: {self.entry_reason}")
