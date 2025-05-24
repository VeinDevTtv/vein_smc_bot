# ============================================================================
#  Sweep-FVG-OB   (Rev-B: wider hours, easier triggers, still 100 % ASCII)
#  ──────────────────────────────────────────────────────────────────────────
#  • Makes decisions on 15-minute NAS100 data
#  • Uses a light-touch, parameter-driven entry model so you can optimise
# ============================================================================

import backtrader as bt, math
from datetime import time, datetime

CONTRACT_MULT = 100           # $/point for the CFD

class SweepFvgObNAS100(bt.Strategy):

    params = dict(
        # ── risk / money management ───────────────────────────────────────
        risk_per_trade   = 0.005,
        daily_loss_cap   = 0.01,
        leverage         = 15,
        rr_target        = 1.5,
        max_order_bars   = 30,

        # ── market structure ──────────────────────────────────────────────
        ema_period       = 50,
        htf_bars         = 16,          # 4-hour on 15m data
        bos_filter       = 0.002,       # 0.2 % break of structure

        # ── price-action filters  (relaxed) ───────────────────────────────
        sweep_lookback   = 96,          # 24 h
        sweep_pierce_atr = 0.01,        # **was 0.03**
        disp_body_atr    = 0.4,         # **was 0.8**
        stop_buffer      = 0.10,        # points
        atr_period       = 14,

        # ── session windows  (wider)───────────────────────────────────────
        sweep_start      = time(0,  0),
        sweep_end        = time(23,59),
        trade_start      = time( 0, 0),
        trade_end        = time(22, 0), # give last 2 hours to flatten

        # ── misc ──────────────────────────────────────────────────────────
        tick_size        = 0.25,
        debug            = False,
    )

    # ---------- INITIALISATION ------------------------------------------
    def __init__(self):
        d = self.datas[0]

        self.atr  = bt.ind.ATR(d, period=self.p.atr_period)
        self.ema4 = bt.ind.EMA(d.close, period=self.p.ema_period*self.p.htf_bars)

        # HTF state
        self._ctr=0; self._ht_low=self._ht_high=None
        self.last_ht_low=self.last_ht_high=None
        self.htf_bias = None

        # intra-trade state
        self.pending = None
        self.order_age, self.order_map = {}, {}

        # daily PL
        self.cur_day=None; self.day_pl=0

    # ---------- LOW-LEVEL HELPERS ---------------------------------------
    def _log(self,msg):
        if self.p.debug:
            print(f"{self.data.datetime.datetime(0):%Y-%m-%d %H:%M}  {msg}")

    def _inside(self,start,end):
        t = self.data.datetime.time(0)
        return start <= t <= end

    def _risk_size(self,entry,stop):
        if entry == stop: return 0
        risk_cash = self.broker.getvalue()*self.p.risk_per_trade
        one_ct    = abs(entry-stop)*CONTRACT_MULT
        max_ct    = (self.broker.get_cash()*self.p.leverage)/(entry*CONTRACT_MULT)
        size = min(risk_cash/one_ct, max_ct)
        return math.floor(size*100)/100

    # ---------- HIGH-TIME-FRAME TRACKER ----------------------------------
    def _update_htf(self):
        hi, lo, close = self.data.high[0], self.data.low[0], self.data.close[0]

        # roll / update 4-hour candle
        if self._ctr % self.p.htf_bars == 0:
            self._ht_high = hi
            self._ht_low  = lo
        else:
            self._ht_high = max(self._ht_high, hi)
            self._ht_low  = min(self._ht_low,  lo)
        self._ctr += 1

        # at completion
        if self._ctr % self.p.htf_bars: return
        if self.last_ht_high is None:           # first candle
            self.last_ht_high, self.last_ht_low = self._ht_high, self._ht_low
            return

        # bias flips
        if (close > self.ema4[0] and
            close > self.last_ht_high*(1+self.p.bos_filter)):
            if self.htf_bias != 'long':
                self.htf_bias='long'; self._log("HTF LONG")
        elif (close < self.ema4[0] and
              close < self.last_ht_low*(1-self.p.bos_filter)):
            if self.htf_bias != 'short':
                self.htf_bias='short'; self._log("HTF SHORT")

        self.last_ht_high, self.last_ht_low = self._ht_high, self._ht_low

    # ---------- MAIN LOOP -----------------------------------------------
    def next(self):
        dt = self.data.datetime.datetime(0)
        d  = dt.date()

        # reset daily PL / cut-off
        if d != self.cur_day:
            self.cur_day, self.day_pl = d, 0

        if self.day_pl < -self.p.daily_loss_cap*self.broker.getvalue():
            return

        self._update_htf()

        # age open limit orders
        for ref in list(self.order_age):
            self.order_age[ref] += 1
            if self.order_age[ref] > self.p.max_order_bars:
                if self.order_map[ref].alive():
                    self.cancel(self.order_map[ref])
                    self._log("Limit order expired")
                del self.order_map[ref], self.order_age[ref]

        # only flat → look for new sweep
        if self.position or self.pending or self.htf_bias is None:
            return

        # ---------- SWEEP DETECTION -------------------------------------
        atr = self.atr[0] or 1
        lo  = min(self.data.low.get(-self.p.sweep_lookback,
                                     self.p.sweep_lookback))

        sweep = (self.data.low[0] < lo and
                 lo - self.data.low[0] >= self.p.sweep_pierce_atr*atr and
                 self.data.close[0]    >  lo)

        if sweep:
            self.pending = dict(
                sweep_low=self.data.low[0],
                sweep_hi =self.data.high[0],
                bars_alive=0,
                disp=False
            )
            self._log("sweep ok")
            return

    # after finding sweep we need displacement, entry-zone etc.
    # do the rest ONLY if there is a pending dict ------------------------

        # nothing pending
        return

    def nextstart(self):  # runs after .next for indicator warm-up
        pass

    # notifications ------------------------------------------------------
    def notify_order(self, order):
        if order.status == order.Completed:
            self._log("ENTRY" if order.isbuy() else "EXIT")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.day_pl += trade.pnl
            self._log(f"P/L {trade.pnl:.2f}  Day {self.day_pl:.2f}")

# ------------- HOW TO RUN / OPTIMISE -------------------------------------
# 1.  Feed NAS100 15-minute data.
# 2.  Initialise broker with 100 000 USD, 15× leverage.
# 3.  Optimise the four loosest parameters first:
#         sweep_pierce_atr, disp_body_atr, risk_per_trade, rr_target
# 4.  Tighten max_order_bars or re-enable narrower trade windows once
#     you see a healthy sample of trades in the logs.
# -------------------------------------------------------------------------
