# ============================================================================
#  Sweep-FVG-OB NAS100 Bot   (15-minute, TradeLocker-ready, no get_order_by_ref)
#  – 0.5 % risk, 1.5 R target, single position, daily loss-cap, debug flag
# ============================================================================

import backtrader as bt
import math
from datetime import time

CONTRACT_MULT = 100      # NAS100 = $100 / pt

class SweepFvgObNAS100(bt.Strategy):
    params = dict(
        # ===== risk & money-management =====================================
        risk_per_trade = 0.005,     # 0.5 %
        daily_loss_cap = 0.01,      # 1 % stop-day
        leverage       = 15,
        rr_target      = 1.5,
        tick_size      = 0.01,
        stop_buffer    = 0.1,       # 0.1 pt below sweep low
        # ===== HTF (pseudo 4-hour) =========================================
        ema_period = 50,            # 50-EMA
        htf_bars   = 16,            # 16×15 m = 4 h candle
        bos_filter = 0.002,         # 0.2 % break filter
        # ===== session windows (UTC) =======================================
        ny_sweep_start = time(13, 30),
        ny_sweep_end   = time(14, 30),
        trade_start    = time(13, 30),
        trade_end      = time(19, 0),
        # ===== sweep / displacement thresholds =============================
        sweep_lookback   = 96,      # 24-hour lows
        sweep_pierce_atr = 0.05,    # 5 % ATR pierce
        disp_body_atr    = 1.0,     # body ≥ ATR
        atr_period       = 14,
        # ===== order handling ==============================================
        max_order_bars = 20,        # cancel after 20 bars
        debug = False
    )

    # ---------------------------------------------------------------------
    def __init__(self):
        self.data15 = self.datas[0]
        self.atr15  = bt.ind.ATR(self.data15, period=self.p.atr_period)

        # pseudo 4-hour builder
        self._bar_ctr = 0
        self._ht_high = self._ht_low = self._ht_close = None
        self.last_ht_high = self.last_ht_low = None
        self.htf_bias = None                        # 'long' / 'short'
        self.ema4h = bt.ind.EMA(
            self.data15.close,
            period=self.p.ema_period * self.p.htf_bars
        )

        # state
        self.order_age = {}        # {order_object: age}
        self.pending_setup = None  # sweep / displacement dict
        self.stop_ord = None       # live stop reference
        self.cur_day = None
        self.daily_loss = 0.0

    # ---------------------------------------------------------------------
    # utility helpers
    def _log(self, txt):
        dt = self.data.datetime.datetime(0)
        print(f"{dt:%Y-%m-%d %H:%M:%S}  {txt}")

    def _utc_time(self):
        return self.data.datetime.time(0)

    def _in_window(self, start, end):
        t = self._utc_time()
        return start <= t <= end

    def _max_affordable(self, price):
        cash = self.broker.get_cash()
        return (cash * self.p.leverage) / (price * CONTRACT_MULT)

    def _risk_size(self, entry, stop):
        risk_cash = self.broker.getvalue() * self.p.risk_per_trade
        risk_pt   = abs(entry - stop) * CONTRACT_MULT
        if risk_pt == 0:
            return 0
        size = risk_cash / risk_pt
        size = min(size, self._max_affordable(entry))
        return math.floor(size * 100) / 100.0  # round down to 0.01 lots

    # ---------------------------------------------------------------------
    # pseudo 4-hour bar update + bias
    def _update_htf(self):
        if self._bar_ctr % self.p.htf_bars == 0:
            self._ht_high = float(self.data15.high[0])
            self._ht_low  = float(self.data15.low[0])
        else:
            self._ht_high = max(self._ht_high, float(self.data15.high[0]))
            self._ht_low  = min(self._ht_low,  float(self.data15.low[0]))

        self._ht_close = float(self.data15.close[0])
        self._bar_ctr += 1

        if self._bar_ctr % self.p.htf_bars != 0:
            return  # evaluate only at 4-hour close

        # initialise swings
        if self.last_ht_high is None:
            self.last_ht_high, self.last_ht_low = self._ht_high, self._ht_low
            return

        # bullish break
        if (self._ht_close > self.ema4h[0] and
            self._ht_close > self.last_ht_high * (1 + self.p.bos_filter)):
            if self.htf_bias != 'long':
                self.htf_bias = 'long'
                self._log("HTF bias -> LONG")

        # bearish break
        elif (self._ht_close < self.ema4h[0] and
              self._ht_close < self.last_ht_low * (1 - self.p.bos_filter)):
            if self.htf_bias != 'short':
                self.htf_bias = 'short'
                self._log("HTF bias -> SHORT")

        # update swings
        self.last_ht_high, self.last_ht_low = self._ht_high, self._ht_low

    # ---------------------------------------------------------------------
    def next(self):
        # daily reset
        today = self.data.datetime.date(0)
        if today != self.cur_day:
            self.cur_day = today
            self.daily_loss = 0.0

        self._update_htf()

        # age / cancel pending limits
        for o in list(self.order_age):
            self.order_age[o] += 1
            if self.order_age[o] > self.p.max_order_bars:
                if o.alive():
                    self.cancel(o)
                    self._log("Limit aged out")
                del self.order_age[o]

        # global filters
        if (self.daily_loss <= -self.p.daily_loss_cap * self.broker.getvalue() or
            self.htf_bias is None):
            return

        if self.position:
            return  # single position model

        if not self._in_window(self.p.trade_start, self.p.trade_end):
            return

        # -------- sweep detection ----------------------------------------
        if self.pending_setup is None:
            if not self._in_window(self.p.ny_sweep_start, self.p.ny_sweep_end):
                return

            atr = self.atr15[0] or 1
            recent_low = min(
                self.data15.low.get(-self.p.sweep_lookback, self.p.sweep_lookback)
            )
            sweep_ok = (
                self.data15.low[0] < recent_low and
                (recent_low - self.data15.low[0]) >= self.p.sweep_pierce_atr * atr and
                self.data15.close[0] > recent_low
            )

            if self.htf_bias == 'long' and sweep_ok:
                self.pending_setup = {'sweep_low': self.data15.low[0], 'displacement': False}
                if self.p.debug:
                    self._log("debug: sweep detected")
            else:
                if self.p.debug:
                    self._log("debug: no sweep")

            return

        # -------- displacement detection ----------------------------------
        if not self.pending_setup['displacement']:
            body = abs(self.data15.close[0] - self.data15.open[0])
            if (body >= self.p.disp_body_atr * (self.atr15[0] or 1) and
                self.data15.close[0] > self.data15.open[0]):
                p = self.pending_setup
                p['displacement'] = True
                p['disp_high'] = self.data15.high[0]
                p['fvg_high']  = self.data15.low[0]
                p['fvg_low']   = self.data15.high[-2]
                p['ob_high']   = self.data15.high[-1]
                p['ob_low']    = self.data15.low[-1]
                if self.p.debug:
                    self._log("debug: displacement confirmed")
            else:
                if self.p.debug:
                    self._log("debug: waiting for displacement")
            return

        # -------- build entry zone & score --------------------------------
        p = self.pending_setup
        swing_low  = p['sweep_low']
        swing_high = p['disp_high']

        fvg_mid = (p['fvg_high'] + p['fvg_low']) / 2
        ob_mid  = (p['ob_high']  + p['ob_low'])  / 2
        ote_low = swing_low + 0.62 * (swing_high - swing_low)
        ote_high = swing_low + 0.79 * (swing_high - swing_low)

        zone_low  = max(min(fvg_mid, ob_mid, ote_low, ote_high), swing_low)
        zone_high = min(max(fvg_mid, ob_mid, ote_low, ote_high), swing_high)
        entry     = round(((zone_high + zone_low) / 2) / 0.25) * 0.25

        score = 0
        if self._in_window(self.p.ny_sweep_start, self.p.ny_sweep_end): score += 1
        score += 1  # HTF bias
        score += 1  # sweep
        score += 1  # FVG
        score += 1  # OB
        score += 1  # OTE

        if score < 4:
            if self.p.debug:
                self._log("debug: confluence <4")
            self.pending_setup = None
            return

        stop  = round((swing_low - self.p.stop_buffer) / self.p.tick_size) * self.p.tick_size
        size  = self._risk_size(entry, stop)
        if size <= 0:
            self.pending_setup = None
            return

        target = round(entry + self.p.rr_target * (entry - stop), 2)
        brkt = self.buy_bracket(price=entry, stopprice=stop, limitprice=target, size=size)
        self.order_age[brkt[0]] = 0  # track main limit order
        self.stop_ord = brkt[2]

        self._log(f"LIMIT placed {entry:.2f}  SL {stop:.2f}  TP {target:.2f}  size {size}")
        self.pending_setup = None  # reset until next sweep

    # ---------------------------------------------------------------------
    # Backtrader callbacks
    def notify_order(self, order):
        if order.status == order.Completed:
            if order.isbuy():
                self._log(f"ENTRY filled {order.executed.price:.2f}")
            elif order.issell():
                self._log("EXIT filled")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.daily_loss += trade.pnl
            self._log(f"TRADE closed  P/L {trade.pnl:.2f}   Day {self.daily_loss:.2f}")

# ---------------------------------------------------------------------------
#  Attach NAS100-15m data in TradeLocker, equity 100 k, leverage 15.
#  Set params.debug = True to print every gate decision while tuning.
# ---------------------------------------------------------------------------
