# ============================================================================
#  NAS100 ICT/SMC BOT  –  TradeLocker Backtrader script (margin-safe)
#    • 5-minute primary feed
#    • automatic 1-hour bias (pseudo bars)
#    • London / New-York kill-zones in UTC
#    • correct margin + risk calc with 100-point contract multiplier
# ============================================================================

import backtrader as bt
import math
from datetime import time

CONTRACT_MULT = 100       # NAS100 CFD = 100 USD per index point

class NAS100_ICT_SMC(bt.Strategy):
    params = dict(
        risk_per_trade=0.005,          # 0.5 %
        leverage=15,                   # TradeLocker demo default
        killzone_london=(time(7,0), time(10,0)),   # 07-10 UTC
        killzone_ny    =(time(12,30), time(15,0)), # 12:30-15:00 UTC
        use_killzones=True,
        rr_target=2.0,                 # 2 : 1 R-R
        tick_size=0.01,
        stop_buffer=0.01,
        ht_bars=12                     # 12×5m = 60 min pseudo HTF bar
    )

    # ----------------------------------------------------------------------
    def __init__(self):
        self.data5   = self.datas[0]               # 5-minute
        self.data1h  = self.datas[1] if len(self.datas) > 1 else None

        # pseudo 1-hour candle cache
        self._ht_high = self._ht_low = self._ht_close = None
        self._bar_count = 0

        self.bias = None      # 'long' / 'short'
        self.swg_high = None
        self.swg_low  = None

        self.entry_ord = self.stop_ord = self.target_ord = None

    # ----------------------------------------------------------------------
    def log(self, txt):
        dt = self.data.datetime.datetime(0)
        print(f"{dt:%Y-%m-%d %H:%M:%S}  {txt}")

    def in_kz(self):
        if not self.p.use_killzones:
            return True
        t = self.data.datetime.time(0)
        kz1s,kz1e = self.p.killzone_london
        kz2s,kz2e = self.p.killzone_ny
        return (kz1s <= t <= kz1e) or (kz2s <= t <= kz2e)

    # ----------------------------------------------------------------------
    def _update_htf(self):
        """Build 60-min bar if no real 1h feed."""
        if self.data1h:
            return
        if self._bar_count % self.p.ht_bars == 0:
            self._ht_high = float(self.data5.high[0])
            self._ht_low  = float(self.data5.low[0])
        else:
            self._ht_high = max(self._ht_high, float(self.data5.high[0]))
            self._ht_low  = min(self._ht_low,  float(self.data5.low[0]))

        self._ht_close = float(self.data5.close[0])
        self._bar_count += 1

        if self._bar_count % self.p.ht_bars == 0:
            if self.swg_high and self._ht_close > self.swg_high and self.bias != "long":
                self.bias = "long";  self.log("Bias flip -> LONG")
            if self.swg_low and self._ht_close < self.swg_low and self.bias != "short":
                self.bias = "short"; self.log("Bias flip -> SHORT")
            self.swg_high = self._ht_high
            self.swg_low  = self._ht_low

    # ----------------------------------------------------------------------
    def next(self):
        self._update_htf()

        # cancel stale entry if bias changed or left kill-zone
        if self.entry_ord and self.entry_ord.alive():
            if (not self.in_kz()) or (self.bias and
               ((self.entry_ord.isbuy() and self.bias!="long") or
                (self.entry_ord.issell() and self.bias!="short"))):
                self.cancel(self.entry_ord)

        if (self.position or
            (self.entry_ord and self.entry_ord.alive()) or
            not self.bias or
            not self.in_kz()):
            return

        recent_low  = min(self.data5.low.get(-10, 10))
        recent_high = max(self.data5.high.get(-10,10))

        if (self.bias=="long" and
            self.data5.low[0] < recent_low and
            self.data5.close[0] > recent_high):
            self._place_long(recent_low)

        if (self.bias=="short" and
            self.data5.high[0] > recent_high and
            self.data5.close[0] < recent_low):
            self._place_short(recent_high)

    # ----------------------------------------------------------------------
    # SIZE / ORDER HELPERS
    def _max_affordable(self, entry):
        cash = self.broker.get_cash()
        return (cash * self.p.leverage) / (entry * CONTRACT_MULT)

    def _risk_size(self, entry, stop):
        equity     = self.broker.getvalue()
        risk_cash  = equity * self.p.risk_per_trade
        risk_unit  = abs(entry - stop) * CONTRACT_MULT
        if risk_unit <= 0:
            return 0
        size = risk_cash / risk_unit
        size = min(size, self._max_affordable(entry))
        return math.floor(size*100)/100.0    # 0.01-lot precision

    def _round(self, price):
        return round(price / self.p.tick_size) * self.p.tick_size

    # LONG
    def _place_long(self, sweep_low):
        swing_low  = float(sweep_low)
        swing_high = float(self.data5.close[0])
        entry  = self._round(swing_low + 0.705*(swing_high-swing_low))
        stop   = self._round(swing_low - self.p.stop_buffer)
        size   = self._risk_size(entry, stop)
        if size<=0: return
        target = self._round(entry + self.p.rr_target*(entry-stop))
        o = self.buy_bracket(price=entry, stopprice=stop, limitprice=target,
                             size=size)
        self.entry_ord,self.target_ord,self.stop_ord = o
        self.log(f"LONG order entry {entry:.2f} SL {stop:.2f} TP {target:.2f} size {size}")

    # SHORT
    def _place_short(self, sweep_high):
        swing_high = float(sweep_high)
        swing_low  = float(self.data5.close[0])
        entry  = self._round(swing_high - 0.705*(swing_high-swing_low))
        stop   = self._round(swing_high + self.p.stop_buffer)
        size   = self._risk_size(entry, stop)
        if size<=0: return
        target = self._round(entry - self.p.rr_target*(stop-entry))
        o = self.sell_bracket(price=entry, stopprice=stop, limitprice=target,
                              size=size)
        self.entry_ord,self.target_ord,self.stop_ord = o
        self.log(f"SHORT order entry {entry:.2f} SL {stop:.2f} TP {target:.2f} size {size}")

    # ----------------------------------------------------------------------
    def notify_order(self, order):
        if order.status in (order.Completed,order.Canceled,order.Margin,order.Rejected):
            px = order.executed.price or order.created.price
            self.log(f"{order.getordername()} {order.getstatusname()} @ {px:.2f}")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"TRADE CLOSED  P/L {trade.pnl:.2f}")

# ----------------------------------------------------------------------------
#  In TradeLocker just attach a 5-minute NAS100 feed and run.  The script
#  builds its own 1-hour bias and now sizes correctly with the 100-point
#  contract multiplier, so margin rejections disappear.
# ----------------------------------------------------------------------------
