# ============================================================================
#  ICT / SMC “Sweep-FVG-OB” BOT for NAS100 (15-minute) – TradeLocker edition
#  Author: ChatGPT (o3, May-2025)
#
#  STRATEGY LOGIC  (recap)
#   1.  MAJOR FILTERS  (4-hour chart)
#         – Price above 50-EMA 4H   AND   last 4H BOS is UP   -> BIAS = LONG
#           (reverse for SHORT bias)
#         – Optional DXY check stub (left as TODO).
#   2.  NY SWEEP WINDOW  (13:30–14:30 UTC)
#         – Detect sell-side sweep (price pierces lowest low of last 48 lows
#           by ≥0.1×ATR and closes back above).
#   3.  DISPLACEMENT  (next candle after sweep)
#         – Bullish impulse body ≥1.2×15m ATR  -> mark FVG.
#   4.  ORDER BLOCK
#         – Last down-candle before displacement.  OB50 = its mid-point.
#   5.  ENTRY ZONE  (confluence)
#         – Overlap of • lower-half of FVG  • OB50 area  • 0.62-0.79 OTE.
#         – Score  +1  for each (sweep, FVG, OB, OTE, time-window, HTF bias).
#           Need score ≥5 to place limit at zone-mid.
#   6.  RISK
#         – 0.5 % equity risk per trade.  SL = 1 pip (0.1) below sweep low.
#         – TP1 = 1.5R (risk×1.5)  TP2 optional -> here full close at 1.5R.
#         – BE when price ≥1R.
#   7.  ADMIN
#         – One open position max.  Daily loss cap = 1 % → disable new trades.
#         – News-blackout placeholder (not implemented – TradeLocker has no feed).
# ============================================================================

import backtrader as bt
import math
from datetime import time, datetime, timedelta

# ---------- CONSTANTS -------------------------------------------------------
CONTRACT_MULT = 100      # NAS100 CFD = $100 / index point
POINT = 0.1              # “1 pip” in spec = 0.1 index point
DATA_TIMEFRAME_MIN = 15  # primary feed = 15-minute

# ---------- STRATEGY --------------------------------------------------------
class SweepFvgObNAS100(bt.Strategy):
    params = dict(
        # Risk / MM
        risk_per_trade=0.005,              # 0.5 % of equity
        daily_loss_cap=0.01,               # 1 % – disable new trades after hit
        leverage=15,
        rr_target=1.5,
        tick_size=0.01,
        stop_buffer=0.1,                   # 0.1 pt below sweep low
        # HTF
        ema_period=50,
        htf_bars=16,                       # 16×15m = 4h
        bos_filter=0.002,                  # 0.2 % break filter
        # Session windows (UTC)
        ny_sweep_start=time(13,30),
        ny_sweep_end=  time(14,30),
        trade_start=time(13,30),
        trade_end=  time(19,0),
        # Sweep parameters
        sweep_lookback=48,                 # 48×15m = 12h lows
        sweep_pierce_atr=0.1,
        disp_body_atr=1.2,
        atr_period=14,
        # Order aging
        max_order_bars=20                  # cancel if limit not filled in 20 bars
    )

    # --- INIT ---------------------------------------------------------------
    def __init__(self):
        self.data15 = self.datas[0]
        # build 4-hour pseudo feed
        self._ht_high = self._ht_low = self._ht_close = None
        self._bar_count = 0
        self.ema4h = bt.ind.EMA(self.data15.close, period=self.p.ema_period*self.p.htf_bars)
        self.htf_bias = None   # 'long' / 'short'

        # 15m ATR
        self.atr15 = bt.ind.ATR(self.data15, period=self.p.atr_period)

        # trade / risk state
        self.order_refs = {}      # { main_entry_ref : age_count }
        self.daily_loss = 0.0
        self.last_trade_day = None

        # sweep / setup buffers
        self.pending_setup = None   # dict with sweep info awaiting displacement

    # --- HELPERS ------------------------------------------------------------
    def _log(self, txt):
        dt = self.data.datetime.datetime(0)
        print(f"{dt:%Y-%m-%d %H:%M:%S}  {txt}")

    def _utc_t(self):
        return self.data.datetime.time(0)

    def _in_window(self, start, end):
        t = self._utc_t()
        return start <= t <= end

    def _max_affordable(self, price):
        cash = self.broker.get_cash()
        return (cash * self.p.leverage) / (price * CONTRACT_MULT)

    def _risk_size(self, entry, stop):
        risk_cash = self.broker.getvalue() * self.p.risk_per_trade
        risk_pt   = abs(entry - stop) * CONTRACT_MULT
        if risk_pt <= 0: return 0
        size = risk_cash / risk_pt
        return min(size, self._max_affordable(entry))

    # --- HTF UPDATE ---------------------------------------------------------
    def _update_htf(self):
        if self._bar_count % self.p.htf_bars == 0:
            self._ht_high = float(self.data15.high[0])
            self._ht_low  = float(self.data15.low[0])
        else:
            self._ht_high = max(self._ht_high, float(self.data15.high[0]))
            self._ht_low  = min(self._ht_low,  float(self.data15.low[0]))

        self._ht_close = float(self.data15.close[0])
        self._bar_count += 1

        if self._bar_count % self.p.htf_bars != 0:
            return  # only evaluate on 4-h close

        # Decide bias
        if self.ema4h[0] is None:
            return
        if self._ht_close > self.ema4h[0]:
            # look for bullish BOS
            if (self._ht_close > self._ht_high * (1+self.p.bos_filter)):
                if self.htf_bias != 'long':
                    self.htf_bias = 'long'
                    self._log("HTF bias: LONG")
        elif self._ht_close < self.ema4h[0]:
            if (self._ht_close < self._ht_low  * (1-self.p.bos_filter)):
                if self.htf_bias != 'short':
                    self.htf_bias = 'short'
                    self._log("HTF bias: SHORT")

    # --- NEXT ---------------------------------------------------------------
    def next(self):
        # daily P/L reset
        today = self.data.datetime.date(0)
        if self.last_trade_day != today:
            self.daily_loss = 0.0
            self.last_trade_day = today

        self._update_htf()

        # Age and cancel stale entry orders
        for ref in list(self.order_refs):
            self.order_refs[ref] += 1
            if self.order_refs[ref] > self.p.max_order_bars:
                o = self.broker.get_order_by_ref(ref)
                if o and o.alive():
                    self.cancel(o); self._log("Limit aged out – canceled")
                del self.order_refs[ref]

        # If daily loss cap hit or no HTF bias -> stop
        if (self.daily_loss <= -self.p.daily_loss_cap*self.broker.getvalue() or
                self.htf_bias is None):
            return

        # If trade open (one max)
        if self.position:
            # BE move
            if not self.position.break_even and abs(self.position.pnl) >= self.position.risk:
                # Move stop to entry
                for o in self.broker.orders:
                    if o.exectype == bt.Order.Stop and o.alive():
                        new_price = self.position.price
                        self.cancel(o)
                        if self.position.size > 0:
                            self.sell(exectype=bt.Order.Stop, price=new_price,
                                      size=self.position.size)
                        else:
                            self.buy(exectype=bt.Order.Stop, price=new_price,
                                     size=-self.position.size)
                        self.position.break_even = True
            return

        # Outside trading window?
        if not self._in_window(self.p.trade_start, self.p.trade_end):
            return

        # ---- Detect NY sweep & displacement --------------------------------
        if self.pending_setup is None:
            # 1) Liquidity sweep only in 13:30–14:30
            if not self._in_window(self.p.ny_sweep_start, self.p.ny_sweep_end):
                return
            atr = self.atr15[0] or 1
            recent_low  = min(self.data15.low.get(-self.p.sweep_lookback, self.p.sweep_lookback))
            sweep = (self.data15.low[0] < recent_low and
                     (recent_low - self.data15.low[0]) >= self.p.sweep_pierce_atr*atr and
                     self.data15.close[0] > recent_low)
            if self.htf_bias == 'long' and sweep:
                # record sweep data
                self.pending_setup = dict(
                    sweep_low=self.data15.low[0],
                    disp_found=False,
                    disp_high=None,
                    disp_low=None)
                self._log("Sweep detected – waiting for displacement")
            return

        # We have sweep recorded – wait for displacement candle
        if not self.pending_setup['disp_found']:
            atr = self.atr15[0] or 1
            body = abs(self.data15.close[0]-self.data15.open[0])
            if (body >= self.p.disp_body_atr*atr and
                    self.data15.close[0] > self.data15.open[0]):  # bullish impulse
                self.pending_setup['disp_found']=True
                self.pending_setup['disp_high']=self.data15.high[0]
                self.pending_setup['disp_low']=self.data15.low[0]
                # mark FVG coords
                self.pending_setup['fvg_high']=self.data15.low[0]
                prev_high=self.data15.high[-2]
                self.pending_setup['fvg_low']=prev_high
                # order block (last down candle before impulse)
                self.pending_setup['ob_high']=self.data15.high[-1]
                self.pending_setup['ob_low']=self.data15.low[-1]
                self._log("Displacement found – monitoring retrace")
            return

        # We have displacement – wait retrace into confluence zone
        setup=self.pending_setup
        # Overlap zone
        fvg_mid=(setup['fvg_high']+setup['fvg_low'])/2
        ob50=(setup['ob_high']+setup['ob_low'])/2
        swing_low=setup['sweep_low']
        swing_high=setup['disp_high']
        ote_low=swing_low+0.62*(swing_high-swing_low)
        ote_high=swing_low+0.79*(swing_high-swing_low)
        zone_low=max(min(fvg_mid,ob50,ote_low,ote_high), swing_low)  # ensure above sweep
        zone_high=min(max(fvg_mid,ob50,ote_low,ote_high), swing_high)
        if zone_high-zone_low < 0.01:
            # tiny zone – treat mid
            entry=(zone_high+zone_low)/2
        else:
            entry=(zone_high+zone_low)/2
        entry=round(entry/0.25)*0.25  # round to 0.25 pts

        # Confluence score
        score=0
        if self._in_window(self.p.ny_sweep_start, self.p.ny_sweep_end): score+=1
        score+=1  # HTF bias
        score+=1  # sweep
        score+=1  # FVG
        score+=1  # OB
        score+=1  # OTE
        if score<5:
            return

        # risk sizing
        stop=round((swing_low-self.p.stop_buffer)/self.p.tick_size)*self.p.tick_size
        size=self._risk_size(entry,stop)
        if size<=0:
            self.pending_setup=None; return

        target=round(entry+self.p.rr_target*(entry-stop),2)
        o=self.buy_bracket(price=entry, stopprice=stop, limitprice=target, size=size)
        self.order_refs[o[0].ref]=0
        self._log(f"LIMIT placed {entry:.2f} SL {stop:.2f} TP {target:.2f} size {size}")
        # clear setup
        self.pending_setup=None

    # --- ORDER / TRADE ------------------------------------------------------
    def notify_order(self, order):
        if order.status==order.Completed and order.isbuy():
            self.position.risk=abs(order.executed.price - self.broker.get_order_by_ref(order.ref+1).created.price)*CONTRACT_MULT*order.executed.size
            self.position.break_even=False
            self._log(f"ENTRY filled {order.executed.price:.2f}")
        elif order.status==order.Completed and order.issell():
            if order.exectype==bt.Order.Limit:
                self._log("TP hit")
            elif order.exectype==bt.Order.Stop:
                self._log("STOP hit")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.daily_loss+=trade.pnl
            self._log(f"TRADE closed P/L {trade.pnl:.2f}  Daily P/L {self.daily_loss:.2f}")

# ----------------------------------------------------------------------------
#  USAGE IN TRADELOCKER
#    * Attach a 15-minute NAS100 feed.
#    * The script builds its own 4-hour bars; no extra feed needed.
#    * Default equity 100 000, leverage 15.
# ----------------------------------------------------------------------------
