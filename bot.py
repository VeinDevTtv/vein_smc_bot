# ─────────────────────────────────────────────────────────────────────────────
#  NAS100 ICT/SMC BOT  –  TradeLocker-ready Backtrader script
#      • 5-minute primary data
#      • automatic 1-hour bias feed (internal resample)
#      • London + New-York kill-zones in ***UTC***
# ─────────────────────────────────────────────────────────────────────────────
import backtrader as bt
import math
from datetime import time


class NAS100_ICT_SMC(bt.Strategy):
    params = dict(
        risk_per_trade=0.005,            # 0.5 % of equity
        leverage=15,                     # TradeLocker demo default (adjust if live)
        # Kill-zones **in UTC**  (NY = UTC-4/-5, London = UTC+0/1)
        killzone_london=(time(7, 0), time(10, 0)),   # 07:00-10:00 UTC
        killzone_ny=(time(12, 30), time(15, 0)),     # 12:30-15:00 UTC
        use_killzones=True,
        rr_target=2.0,                   # 2 : 1 R-R
        tick_size=0.01,
        stop_buffer=0.01,                # extra 0.01 past liquidity wick
        ht_bars=12                       # 12 × 5-min = 60 min (for auto resample)
    )

    # ─────────────────────────────────────────────────────────────────────────
    def __init__(self):
        self.data5 = self.datas[0]                # 5-minute feed always present
        # If TradeLocker injected a second feed – use it; else create pseudo 1h
        self.data1h = self.datas[1] if len(self.datas) > 1 else None

        # pseudo-1h candle cache (if data1h is None)
        self._ht_open  = None
        self._ht_high  = None
        self._ht_low   = None
        self._ht_close = None
        self._bar_count = 0

        # state vars
        self.bias = None           # 'long' / 'short'
        self.swg_high = None       # last swing high on HTF
        self.swg_low  = None       # last swing low  on HTF

        # order refs
        self.entry_ord  = None
        self.stop_ord   = None
        self.target_ord = None

    # ─────────────────────────────────────────────────────────────────────────
    #  LOGGING HELP
    def log(self, txt):
        dt = self.data.datetime.datetime(0)
        print(f"{dt:%Y-%m-%d %H:%M:%S}  {txt}")

    # ─────────────────────────────────────────────────────────────────────────
    #  KILL-ZONE FILTER  (UTC times)
    def in_kz(self):
        if not self.p.use_killzones:
            return True
        t = self.data.datetime.time(0)
        kz1s, kz1e = self.p.killzone_london
        kz2s, kz2e = self.p.killzone_ny
        return (kz1s <= t <= kz1e) or (kz2s <= t <= kz2e)

    # ─────────────────────────────────────────────────────────────────────────
    #  BUILD / UPDATE 1-HOUR BAR   (only if no real 1h feed provided)
    def _update_pseudo_htf(self):
        if self.data1h:
            return                                    # real 1h exists
        if self._bar_count % self.p.ht_bars == 0:
            # start a new HTF candle
            self._ht_open = float(self.data5.open[0])
            self._ht_high = float(self.data5.high[0])
            self._ht_low  = float(self.data5.low[0])
        else:
            # update high/low intra-candle
            self._ht_high = max(self._ht_high, float(self.data5.high[0]))
            self._ht_low  = min(self._ht_low,  float(self.data5.low[0]))

        self._ht_close = float(self.data5.close[0])
        self._bar_count += 1

        # on completion of 12th bar → evaluate swing / bias
        if self._bar_count % self.p.ht_bars == 0:
            # simple BOS test: close > prev swing high   OR   close < prev swing low
            if self.swg_high and self._ht_close > self.swg_high:
                if self.bias != 'long':
                    self.bias = 'long'
                    self.log(f"Bias flip → LONG  (HTF close {self._ht_close:.2f} > swing-high)")
            if self.swg_low and self._ht_close < self.swg_low:
                if self.bias != 'short':
                    self.bias = 'short'
                    self.log(f"Bias flip → SHORT (HTF close {self._ht_close:.2f} < swing-low)")

            # update swing levels with the finished candle
            self.swg_high = self._ht_high
            self.swg_low  = self._ht_low

    # ─────────────────────────────────────────────────────────────────────────
    #  MAIN NEXT()
    def next(self):
        # build / update 1-hour bias
        self._update_pseudo_htf()

        # cancel stale entry if bias changed or left kill-zone
        if self.entry_ord and self.entry_ord.alive():
            if not self.in_kz() or (self.bias and
                    ((self.entry_ord.isbuy() and self.bias != 'long') or
                     (self.entry_ord.issell() and self.bias != 'short'))):
                self.cancel(self.entry_ord)

        # skip if we already hold, have pending entry, lack bias, or outside KZ
        if self.position or (self.entry_ord and self.entry_ord.alive()) or not self.bias or not self.in_kz():
            return

        # ── detect liquidity sweep + structure break on 5-minute ────────────
        lows  = [self.data5.low[-i]  for i in range(1, 11)]  # last 10 lows
        highs = [self.data5.high[-i] for i in range(1, 11)]
        recent_low  = min(lows)
        recent_high = max(highs)

        # LONG setup: sweep low then close above recent high
        if self.bias == 'long' and self.data5.low[0] < recent_low and self.data5.close[0] > recent_high:
            self._place_long(recent_low)

        # SHORT setup: sweep high then close below recent low
        if self.bias == 'short' and self.data5.high[0] > recent_high and self.data5.close[0] < recent_low:
            self._place_short(recent_high)

    # ─────────────────────────────────────────────────────────────────────────
    #  ENTRY HELPERS
    def _risk_size(self, entry, stop):
        equity = self.broker.getvalue()
        risk_cash = equity * self.p.risk_per_trade
        risk_per_unit = abs(entry - stop)
        if risk_per_unit == 0:
            return 0
        raw_size = risk_cash / risk_per_unit
        # margin cap
        margin_need = entry * raw_size / self.p.leverage
        if margin_need > self.broker.get_cash():
            raw_size = self.broker.get_cash() * self.p.leverage / entry
        return math.floor(raw_size * 100) / 100.0  # round down to 0.01 lots

    def _round(self, price):
        return round(price / self.p.tick_size) * self.p.tick_size

    def _place_long(self, sweep_low):
        swing_low  = float(sweep_low)
        swing_high = float(self.data5.close[0])
        # 70.5 % OTE
        entry      = self._round(swing_low + 0.705 * (swing_high - swing_low))
        stop       = self._round(swing_low - self.p.stop_buffer)
        size       = self._risk_size(entry, stop)
        if size <= 0:
            return
        target     = self._round(entry + self.p.rr_target * (entry - stop))
        o = self.buy_bracket(price=entry, stopprice=stop, limitprice=target,
                             size=size)
        self.entry_ord, self.target_ord, self.stop_ord = o
        self.log(f"LONG order  entry {entry:.2f}  SL {stop:.2f}  TP {target:.2f}  size {size}")

    def _place_short(self, sweep_high):
        swing_high = float(sweep_high)
        swing_low  = float(self.data5.close[0])
        entry      = self._round(swing_high - 0.705 * (swing_high - swing_low))
        stop       = self._round(swing_high + self.p.stop_buffer)
        size       = self._risk_size(entry, stop)
        if size <= 0:
            return
        target     = self._round(entry - self.p.rr_target * (stop - entry))
        o = self.sell_bracket(price=entry, stopprice=stop, limitprice=target,
                              size=size)
        self.entry_ord, self.target_ord, self.stop_ord = o
        self.log(f"SHORT order entry {entry:.2f}  SL {stop:.2f}  TP {target:.2f}  size {size}")

    # ─────────────────────────────────────────────────────────────────────────
    #  ORDER / TRADE NOTIFICATIONS
    def notify_order(self, order):
        if order.status in (order.Completed, order.Canceled, order.Margin, order.Rejected):
            self.log(f"{order.getordername()} {order.getstatusname()}  @ {order.executed.price if order.executed.price else order.created.price}")

    def notify_trade(self, trade):
        if trade.isclosed:
            self.log(f"TRADE CLOSED  P/L {trade.pnl:.2f}")

# ─────────────────────────────────────────────────────────────────────────────
#  STAND-ALONE TEST (works in TradeLocker desktop too)
#    – feeds coming from TradeLocker, so only the Strategy is needed there –
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    cerebro = bt.Cerebro()

    # === 5-minute CSV / placeholder feed for local test ====================
    # Replace with TradeLocker’s built-in data connector when running in TL.
    #
    # data5 = bt.feeds.GenericCSVData(
    #     dataname='nas100_5m.csv',
    #     datetime=0,   timeframe=bt.TimeFrame.Minutes, compression=5,
    #     open=1, high=2, low=3, close=4, volume=5, dtformat='%Y-%m-%d %H:%M:%S'
    # )
    # cerebro.adddata(data5)
    #
    # # Auto-resample to 1-hour for bias
    # cerebro.resampledata(data5, timeframe=bt.TimeFrame.Minutes, compression=60)
    #
    # =======================================================================

    cerebro.addstrategy(NAS100_ICT_SMC)
    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.0, leverage=15)

    print('Starting Equity:', cerebro.broker.getvalue())
    cerebro.run()
    print('Final Equity:   ', cerebro.broker.getvalue())
