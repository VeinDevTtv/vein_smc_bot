# ============================================================================
#  Sweep-FVG-OB NAS100 Bot  (15-minute, TradeLocker-ready)
#  – includes debug switch and refined thresholds
# ============================================================================

import backtrader as bt, math
from datetime import time

CONTRACT_MULT = 100    # $100 per NAS100 point
POINT          = 0.1   # 1 "pip" = 0.1
TF_MIN         = 15    # primary resolution

class SweepFvgObNAS100(bt.Strategy):
    params = dict(
        # ----- risk / money management -------------------------------------
        risk_per_trade = 0.005,      # 0.5 % of equity
        daily_loss_cap = 0.01,       # 1 % stop-day
        leverage       = 15,
        rr_target      = 1.5,
        tick_size      = 0.01,
        stop_buffer    = 0.1,        # pts under sweep low
        # ----- HTF bias (pseudo 4h) ----------------------------------------
        ema_period     = 50,
        htf_bars       = 16,         # 16×15 m = 4 h
        bos_filter     = 0.002,      # 0.2 %
        # ----- session windows (UTC) ---------------------------------------
        ny_sweep_start = time(13,30),
        ny_sweep_end   = time(14,30),
        trade_start    = time(13,30),
        trade_end      = time(19,0),
        # ----- sweep / displacement thresholds -----------------------------
        sweep_lookback   = 96,       # 24 h lows
        sweep_pierce_atr = 0.05,     # 5 % ATR
        disp_body_atr    = 1.0,      # body ≥ ATR
        atr_period       = 14,
        # ----- order handling ----------------------------------------------
        max_order_bars = 20,         # cancel after 20 bars
        # ----- debug --------------------------------------------------------
        debug = False
    )

    # ────────────────────────────────────────────────────────────────────
    def __init__(self):
        self.data15 = self.datas[0]
        self.atr15  = bt.ind.ATR(self.data15, period=self.p.atr_period)
        # pseudo 4-hour bar builder
        self._bar_counter = 0
        self._ht_high = self._ht_low = self._ht_close = None
        self.htf_bias      = None                 # 'long'/'short'
        self.last_ht_high  = self.last_ht_low = None
        self.ema4h         = bt.ind.EMA(self.data15.close,
                                        period=self.p.ema_period*self.p.htf_bars)
        # trade / order state
        self.order_age = {}        # {ref:bars_since_placement}
        self.pending   = None      # dict holding sweep+displacement info
        self.daily_loss = 0.0
        self.current_day = None

    # ────────────────────────────────────────────────────────────────────
    # utilities
    def _log(self, msg):
        dt = self.data.datetime.datetime(0)
        print(f"{dt:%Y-%m-%d %H:%M:%S}  {msg}")

    def _utc_time(self):    return self.data.datetime.time(0)
    def _in_window(self,start,end):
        t=self._utc_time(); return start<=t<=end

    # margin-safe size
    def _max_affordable(self, price):
        cash = self.broker.get_cash()
        return (cash*self.p.leverage)/(price*CONTRACT_MULT)
    def _risk_size(self, entry, stop):
        risk_cash = self.broker.getvalue()*self.p.risk_per_trade
        risk_pt   = abs(entry-stop)*CONTRACT_MULT
        if risk_pt==0: return 0
        size = risk_cash/risk_pt
        size = min(size, self._max_affordable(entry))
        return math.floor(size*100)/100.0

    # ────────────────────────────────────────────────────────────────────
    def _update_htf(self):
        if self._bar_counter % self.p.htf_bars == 0:
            self._ht_high = float(self.data15.high[0])
            self._ht_low  = float(self.data15.low[0])
        else:
            self._ht_high = max(self._ht_high,float(self.data15.high[0]))
            self._ht_low  = min(self._ht_low, float(self.data15.low[0]))
        self._ht_close=float(self.data15.close[0])
        self._bar_counter+=1
        if self._bar_counter % self.p.htf_bars: return

        # initialise swings
        if self.last_ht_high is None:
            self.last_ht_high,self.last_ht_low=self._ht_high,self._ht_low;return

        # bias logic with 0.2 % break filter
        if (self._ht_close>self.ema4h[0] and
            self._ht_close>self.last_ht_high*(1+self.p.bos_filter)):
            if self.htf_bias!='long': self.htf_bias='long'; self._log("HTF LONG")
        elif (self._ht_close<self.ema4h[0] and
              self._ht_close<self.last_ht_low*(1-self.p.bos_filter)):
            if self.htf_bias!='short': self.htf_bias='short';self._log("HTF SHORT")

        self.last_ht_high,self.last_ht_low=self._ht_high,self._ht_low

    # ────────────────────────────────────────────────────────────────────
    def next(self):
        # daily reset
        d=self.data.datetime.date(0)
        if d!=self.current_day:
            self.current_day=d; self.daily_loss=0.0

        self._update_htf()

        # age / cancel old entry orders
        for ref in list(self.order_age):
            self.order_age[ref]+=1
            if self.order_age[ref]>self.p.max_order_bars:
                ord=self.broker.get_order_by_ref(ref)
                if ord and ord.alive(): self.cancel(ord); self._log("limit aged")
                del self.order_age[ref]

        # guard rails
        if (self.daily_loss <= -self.p.daily_loss_cap*self.broker.getvalue() or
            self.htf_bias is None): return
        if self.position: return

        t = self._utc_time()
        if not self._in_window(self.p.trade_start,self.p.trade_end): return

        # -----------------------------------------------------------------
        # sweep detection
        if self.pending is None:
            if not self._in_window(self.p.ny_sweep_start,self.p.ny_sweep_end):
                if self.p.debug: self._log("debug: outside sweep win"); return
            atr = self.atr15[0] or 1
            lo  = min(self.data15.low.get(-self.p.sweep_lookback,
                                          self.p.sweep_lookback))
            sweep = (self.data15.low[0] < lo and
                     (lo-self.data15.low[0]) >= self.p.sweep_pierce_atr*atr and
                     self.data15.close[0] > lo)
            if self.htf_bias=='long' and sweep:
                self.pending=dict(sweep_low=self.data15.low[0],disp=False)
                if self.p.debug: self._log("debug: sweep ok")
            else:
                if self.p.debug: self._log("debug: no sweep")
            return

        # -----------------------------------------------------------------
        # displacement
        if not self.pending['disp']:
            body=abs(self.data15.close[0]-self.data15.open[0])
            if body >= self.p.disp_body_atr*(self.atr15[0] or 1) and \
               self.data15.close[0] > self.data15.open[0]:
                p=self.pending
                p['disp']=True
                p['disp_high']=self.data15.high[0]
                p['disp_low']=self.data15.low[0]
                # FVG & OB
                p['fvg_high']=self.data15.low[0]
                p['fvg_low']=self.data15.high[-2]
                p['ob_high']=self.data15.high[-1]
                p['ob_low']=self.data15.low[-1]
                if self.p.debug: self._log("debug: displacement ok")
            else:
                if self.p.debug: self._log("debug: no disp")
            return

        # -----------------------------------------------------------------
        # entry zone & confluence
        p=self.pending
        swing_low=p['sweep_low']; swing_high=p['disp_high']
        fvg_mid=(p['fvg_high']+p['fvg_low'])/2
        ob50=(p['ob_high']+p['ob_low'])/2
        ote_low=swing_low+0.62*(swing_high-swing_low)
        ote_high=swing_low+0.79*(swing_high-swing_low)
        zone_low=max(min(fvg_mid,ob50,ote_low,ote_high), swing_low)
        zone_high=min(max(fvg_mid,ob50,ote_low,ote_high), swing_high)
        entry = round(((zone_high+zone_low)/2)/0.25)*0.25

        score=0
        if self._in_window(self.p.ny_sweep_start,self.p.ny_sweep_end): score+=1
        score+=1  # HTF bias
        score+=1  # sweep
        score+=1  # FVG
        score+=1  # OB
        score+=1  # OTE
        if score<4:
            if self.p.debug: self._log("debug: score<4")
            self.pending=None; return

        stop = round((swing_low-self.p.stop_buffer)/self.p.tick_size)*self.p.tick_size
        size=self._risk_size(entry,stop)
        if size<=0: self.pending=None; return
        target = round(entry+self.p.rr_target*(entry-stop),2)

        o=self.buy_bracket(price=entry,stopprice=stop,limitprice=target,size=size)
        self.order_age[o[0].ref]=0
        self._log(f"LIMIT set {entry:.2f} SL {stop:.2f} TP {target:.2f} size {size}")
        self.pending=None   # reset

    # -----------------------------------------------------------------------
    def notify_order(self, order):
        if order.status==order.Completed and order.isbuy():
            self._log(f"ENTRY filled {order.executed.price:.2f}")
        elif order.status==order.Completed and order.issell():
            if order.exectype==bt.Order.Limit: self._log("TP hit")
            else: self._log("STOP hit")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.daily_loss+=trade.pnl
            self._log(f"TRADE P/L {trade.pnl:.2f}   Daily {self.daily_loss:.2f}")

# ---------------------------------------------------------------------------
#  Attach a 15-minute NAS100 feed in TradeLocker, run from mid-2024 onward,
#  set equity 100 000 leverage 15.  To see internal filters, set debug=True
#  in the params block.
# ---------------------------------------------------------------------------
