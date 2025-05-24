import backtrader as bt


class RSIOversoldOverboughtStrategy(bt.Strategy):
    params = (
        ("rsi_period", 9),
        ("overbought_threshold", 70),
        ("oversold_threshold", 30),
        ("risk_amount", 500),  # Risk $500 per trade
    )

    def __init__(self):
        self.rsi = bt.indicators.RSI(self.data.close, period=self.params.rsi_period)

    def next(self) -> None:
        if not self.position:
            if self.rsi < self.params.oversold_threshold:
                # Calculate position size based on risk amount
                current_price = self.data.close[0]
                position_size = self.params.risk_amount / current_price
                self.buy(size=position_size)
        elif self.rsi > self.params.overbought_threshold:
            self.close()
