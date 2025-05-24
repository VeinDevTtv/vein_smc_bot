# =============================================================================
#  NAS100 ICT/SMC BOT  –  Refined version (fewer bias flips, bigger sweeps,
#                         1.5 : 1 RR, ASCII-only logging)
#  • 5-minute primary feed
#  • Automatic pseudo-1-hour bias with CHOCH+BOS rule
#  • Larger liquidity-sweep window (30×5 m ≈ 150 m)
#  • London + New-York kill-zones in UTC
#  • Correct margin / risk sizing with 100-point contract multiplier
# =============================================================================
import backtrader as bt
import math
from datetime import time

CONTRACT_MULT = 100        # NAS100 = 100 USD/pt

class NAS100_ICT_SMC(bt.Strategy):
    params = dict(
        risk_per_trade = 0.005,              # 0.5 % of equity
        leverage       = 15,                 # TradeLocker demo default
        killzone_london= (time(7,0),  time(10,0)),   # 07-10 UTC
        killzone_ny    = (time(12,30),time(15,0)),   # 12:30-15 UTC
        use_kz         = True,
        rr_target      = 1.5,                # 1.5 : 1 reward:risk
        tick_size      = 0.01,
        stop_buffer    = 0.01,
        ht_bars        = 12,                 # 12×5 m = 1 h pseudo bar
        sweep_window   = 30                  # look-back bars for liquidity sweep
    )
    # ─────────────────────────────────────────────────────────────────────────
    def __init__(self):
        self.data5  = self.datas[0]
        self.bias   = None         # None, 'long', 'short'
        self.last_ht_high = None   # last confirmed swing high
        self.last_ht_low  = None   # last confirmed swing low
        self._bar_count   = 0
        self._ht_high = self._ht_low = self._ht_close = None

        self.entry_ord = self.stop_ord = self.target_ord = None
    # ─────────────────────────────────────────────────────────────────────────
    def log(self, txt):
        dt = self.data.datetime.datetime(0)
        print(f"{dt:%Y-%m-%d %H:%M:%S}  {txt}")
    # ─────────────────────────────────────────────────────────────────────────
    def in_kz(self):
        if not self.p.use_kz:
            return True
        t = self.data.datetime.time(0)
        kz1s,kz1e = self.p.killzone_london
        kz2s,kz2e = self.p.killzone_ny
        return (kz1s <= t <= kz1e) or (kz2s <= t <= kz2e)
    # ─────────────────────────────────────────────────────────────────────────
    #  Build 60-min pseudo bar & update bias with CHOCH+BOS logic
    def _update_htf(self):
        if self._bar_count % self.p.ht_bars == 0:
            self._ht_high = float(self.data5.high[0])
            self._ht_low  = float(self.data5.low[0])
        else:
            self._ht_high = max(self._ht_high, float(self.data5.high[0]))
            self._ht_low  = min(self._ht_low,  float(self.data5.low[0]))
        self._ht_close = float(self.data5.close[0])
        self._bar_count += 1

        # every finished pseudo 1-h bar
        if self._bar_count % self.p.ht_bars == 0:
            # Initialise first swings
            if self.last_ht_high is None:
                self.last_ht_high, self.last_ht_low = self._ht_high, self._ht_low
                return
            # CHOCH then BOS confirmation
            if self.bias != "long":
                # bullish change-of-character
                if self._ht_close > self.last_ht_high:
                    self.bias = "long"
                    self.log("Bias -> LONG (BOS up)")
            if self.bias != "short":
                # bearish change-of-character
                if self._ht_close < self.last_ht_low:
                    self.bias = "short"
                    self.log("Bias -> SHORT (BOS down)")
            # update swings
            self.last_ht_high, self.last_ht_low = self._ht_high, self._ht_low
    # ─────────────────────────────────────────────────────────────────────────
    def next(self):
        self._update_htf()

        # cancel stale entry if bias changes or outside kill-zone
        if self.entry_ord and self.entry_ord.alive():
            if (not self.in_kz()) or (self.bias and
               ((self.entry_ord.isbuy() and self.bias!="long") or
                (self.entry_ord.issell() and self.bias!="short"))):
                self.cancel(self.entry_ord)

        if (self.position or
            (self.entry_ord and self.entry_ord.alive()) or
            self.bias is None or
            not self.in_kz()):
            return

        N = self.p.sweep_window
        recent_low  = min(self.data5.low.get(-N, N))
        recent_high = max(self.data5.high.get(-N, N))

        if (self.bias=="long" and
            self.data5.low[0] < recent_low and
            self.data5.close[0] > recent_high):
            self._enter_long(recent_low)

        if (self.bias=="short" and
            self.data5.high[0] > recent_high and
            self.data5.close[0] < recent_low):
            self._enter_short(recent_high)
    # ─────────────────────────────────────────────────────────────────────────
    #  Risk / margin helpers
    def _max_affordable(self, price):
        cash = self.broker.get_cash()
        return (cash * self.p.leverage) / (price * CONTRACT_MULT)

    def _risk_size(self, entry, stop):
        eq    = self.broker.getvalue()
        risk_cash = eq * self.p.risk_per_trade
        risk_pt   = abs(entry-stop) * CONTRACT_MULT
        if risk_pt == 0: return 0
        size = risk_cash / risk_pt
        size = min(size, self._max_affordable(entry))
        return math.floor(size*100)/100.0  # 0.01 lot precision

    def _round(self, p): return round(p / self.p.tick_size)*self.p.tick_size
    # ─────────────────────────────────────────────────────────────────────────
    def _enter_long(self, sweep_low):
        swing_low  = float(sweep_low)
        swing_high = float(self.data5.close[0])
        entry  = self._round(swing_low + 0.705*(swing_high-swing_low))
        stop   = self._round(swing_low - self.p.stop_buffer)
        size   = self._risk_size(entry, stop)
        if size<=0: return
        target = self._round(entry + self.p.rr_target*(entry-stop))
        self.entry_ord,self.target_ord,self.stop_ord = self.buy_bracket(
            price=entry, stopprice=stop, limitprice=target, size=size)
        self.log(f"LONG order entry {entry:.2f} SL {stop:.2f} TP {target:.2f} size {size}")
    def _enter_short(self, sweep_high):
        swing_high = float(sweep_high)
        swing_low  = float(self.data5.close[0])
        entry  = self._round(swing_high - 0.705*(swing_high-swing_low))
        stop   = self._round(swing_high + self.p.stop_buffer)
        size   = self._risk_size(entry, stop)
        if size<=0: return
        target = self._round(entry - self.p.rr_target*(stop-entry))
        self.entry_ord,self.target_ord,self.stop_ord = self.sell_bracket(
            price=entry, stopprice=stop, limitprice=target, size=size)
        self.log(f"SHORT order entry {entry:.2f} SL {stop:.2f} TP {target:.2f} size {size}")
    # ─────────────────────────────────────────────────────────────────────────
    def notify_order(self, order):
        if order.status in (order.Completed,order.Canceled,order.Margin,order.Rejected):
            px = order.executed.price or order.created.price
            self.log(f"{order.getordername()} {order.getstatusname()} @ {px:.2f}")
    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"TRADE CLOSED P/L {trade.pnl:.2f}")
# -----------------------------------------------------------------------------
#  In TradeLocker: attach a 5-minute NAS100 feed, set equity=100 000,
#  leverage=15.  This refined bot flips bias far less, waits for bigger
#  liquidity sweeps, and uses 1.5 : 1 RR.
# -----------------------------------------------------------------------------
