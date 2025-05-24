import backtrader as bt


class RSIOversoldOverboughtStrategy(bt.Strategy):
    params = (
        ("rsi_period", 9),
        ("overbought_threshold", 70),
        ("oversold_threshold", 30),
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.params.rsi_period)

    def next(self) -> None:
        if not self.position:
            if self.rsi < self.params.oversold_threshold:
                self.buy()
        elif self.rsi > self.params.overbought_threshold:
            self.close()
