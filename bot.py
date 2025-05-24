# ============================================================================
#  Sweep-FVG-OB NAS100 Bot  (15m, pure ASCII log)
# ============================================================================

import backtrader as bt, math
from datetime import time

CONTRACT_MULT = 100  # $100 per NAS100 point

class SweepFvgObNAS100(bt.Strategy):
    params = dict(
        risk_per_trade=0.005,
        daily_loss_cap=0.01,
        leverage=15,
        rr_target=1.5,
        tick_size=0.01,
        stop_buffer=0.2,
        ema_period=50,
        htf_bars=16,
        bos_filter=0.002,
        sweep_start=time(13,0),
        sweep_end=time(15,0),
        trade_start=time(13,0),
        trade_end=time(19,0),
        sweep_lookback=96,
        sweep_pierce_atr=0.03,
        disp_body_atr=0.8,
        atr_period=14,
        max_order_bars=20,
        debug=True
    )

    def __init__(self):
        self.data15  = self.datas[0]
        self.atr15   = bt.ind.ATR(self.data15, period=self.p.atr_period)
        self.ema4h   = bt.ind.EMA(self.data15.close,
                         period=self.p.ema_period*self.p.htf_bars)

        # HTF vars
        self._ctr=0; self._ht_high=self._ht_low=self._ht_close=None
        self.last_ht_high=self.last_ht_low=None; self.htf_bias=None

        # runtime state
        self.order_age, self.order_book = {}, {}
        self.pending=None
        self.cur_day=None; self.daily_loss=0

    # ------------- helpers ----------------------------------------------
    def _log(self,msg):
        print(f"{self.data.datetime.datetime(0):%Y-%m-%d %H:%M:%S}  {msg}")

    def _in_win(self,s,e):
        t=self.data.datetime.time(0); return s<=t<=e

    def _risk_size(self,entry,stop):
        risk_cash=self.broker.getvalue()*self.p.risk_per_trade
        risk_pt =abs(entry-stop)*CONTRACT_MULT
        if risk_pt==0: return 0
        max_aff=(self.broker.get_cash()*self.p.leverage)/(entry*CONTRACT_MULT)
        sz=min(risk_cash/risk_pt,max_aff)
        return math.floor(sz*100)/100

    # ------------- HTF update -------------------------------------------
    def _update_htf(self):
        if self._ctr%self.p.htf_bars==0:
            self._ht_high=float(self.data15.high[0])
            self._ht_low =float(self.data15.low[0])
        else:
            self._ht_high=max(self._ht_high,float(self.data15.high[0]))
            self._ht_low =min(self._ht_low ,float(self.data15.low[0]))
        self._ht_close=float(self.data15.close[0]); self._ctr+=1
        if self._ctr%self.p.htf_bars: return
        if self.last_ht_high is None:
            self.last_ht_high,self.last_ht_low=self._ht_high,self._ht_low;return
        if (self._ht_close>self.ema4h[0] and
            self._ht_close>self.last_ht_high*(1+self.p.bos_filter)):
            if self.htf_bias!='long': self.htf_bias='long'; self._log("HTF LONG")
        elif (self._ht_close<self.ema4h[0] and
              self._ht_close<self.last_ht_low*(1-self.p.bos_filter)):
            if self.htf_bias!='short': self.htf_bias='short'; self._log("HTF SHORT")
        self.last_ht_high,self.last_ht_low=self._ht_high,self._ht_low

    # ------------- main --------------------------------------------------
    def next(self):
        # reset daily P/L
        d=self.data.datetime.date(0)
        if d!=self.cur_day: self.cur_day=d; self.daily_loss=0

        self._update_htf()

        # age limits
        for ref in list(self.order_age):
            self.order_age[ref]+=1
            if self.order_age[ref]>self.p.max_order_bars:
                if self.order_book[ref].alive():
                    self.cancel(self.order_book[ref]); self._log("Limit aged")
                del self.order_age[ref]; del self.order_book[ref]

        # master guards
        if (self.daily_loss <= -self.p.daily_loss_cap*self.broker.getvalue() or
            self.htf_bias is None or self.position or
            not self._in_win(self.p.trade_start,self.p.trade_end)):
            return

        # -------- sweep ---------------------------------------------------
        if self.pending is None:
            if not self._in_win(self.p.sweep_start,self.p.sweep_end):
                if self.p.debug: self._log("dbg: outside sweep")
                return
            atr=self.atr15[0] or 1
            lo=min(self.data15.low.get(-self.p.sweep_lookback,
                                       self.p.sweep_lookback))
            sweep=(self.data15.low[0]<lo and
                   (lo-self.data15.low[0])>=self.p.sweep_pierce_atr*atr and
                   self.data15.close[0]>lo)
            if self.htf_bias=='long' and sweep:
                self.pending={'sweep_low':self.data15.low[0],'disp':False}
                if self.p.debug:self._log("dbg: sweep ok")
            else:
                if self.p.debug:self._log("dbg: no sweep")
            return

        # -------- displacement -------------------------------------------
        if not self.pending['disp']:
            body=abs(self.data15.close[0]-self.data15.open[0])
            if (body>=self.p.disp_body_atr*(self.atr15[0] or 1) and
                self.data15.close[0]>self.data15.open[0]):
                p=self.pending; p['disp']=True
                p.update(disp_high=self.data15.high[0],
                         fvg_high=self.data15.low[0],
                         fvg_low=self.data15.high[-2],
                         ob_high=self.data15.high[-1],
                         ob_low=self.data15.low[-1])
                if self.p.debug:self._log("dbg: disp ok")
            else:
                if self.p.debug:self._log("dbg: wait disp")
            return

        # -------- entry zone & score -------------------------------------
        p=self.pending; sw_low,sw_hi=p['sweep_low'],p['disp_high']
        fvg_mid=(p['fvg_high']+p['fvg_low'])/2
        ob_mid =(p['ob_high'] +p['ob_low']) /2
        ote_l  =sw_low+0.62*(sw_hi-sw_low)
        ote_h  =sw_low+0.79*(sw_hi-sw_low)
        z_lo   =max(min(fvg_mid,ob_mid,ote_l,ote_h),sw_low)
        z_hi   =min(max(fvg_mid,ob_mid,ote_l,ote_h),sw_hi)
        entry  =round(((z_hi+z_lo)/2)/0.25)*0.25
        score=sum([ self._in_win(self.p.sweep_start,self.p.sweep_end),
                    1,1,1,1,1])  # bias+sweep+fvg+ob+ote
        if score<3:
            if self.p.debug:self._log("dbg: score<3"); self.pending=None; return
        stop=round((sw_low-self.p.stop_buffer)/self.p.tick_size)*self.p.tick_size
        if stop>=entry:
            if self.p.debug:self._log("dbg: stop>=entry"); self.pending=None;return
        sz=self._risk_size(entry,stop)
        if sz<=0: self.pending=None; return
        tp=round(entry+self.p.rr_target*(entry-stop),2)
        brkt=self.buy_bracket(price=entry,stopprice=stop,limitprice=tp,size=sz)
        main=brkt[0]
        self.order_age[main.ref]=0; self.order_book[main.ref]=main
        self._log(f"LIMIT {entry:.2f} SL {stop:.2f} TP {tp:.2f} sz {sz}")
        self.pending=None

    # notifications
    def notify_order(self,o):
        if o.status==o.Completed:
            self._log("ENTRY" if o.isbuy() else "EXIT")
    def notify_trade(self,t):
        if t.isclosed:
            self.daily_loss+=t.pnl
            self._log(f"P/L {t.pnl:.2f}  Day {self.daily_loss:.2f}")

# ---------------------------------------------------------------------------
# Attach NAS100 15-minute data, equity 100 000, leverage 15.
# ---------------------------------------------------------------------------
