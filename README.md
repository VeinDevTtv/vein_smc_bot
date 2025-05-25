# SMC/ICT Trading Bot for NAS100

A comprehensive Smart Money Concepts (SMC) and Inner Circle Trader (ICT) trading bot built with Backtrader framework, specifically designed for NAS100 on the 15-minute timeframe. Compatible with TradeLocker's bot engine.

## 🎯 Features

### Core ICT Concepts Implemented

- **Daily Bias Determination**: Uses daily timeframe to establish bullish/bearish market bias
- **Liquidity Zones**: Identifies equal highs/lows and tracks liquidity grabs
- **Fair Value Gaps (FVG)**: Detects and tracks bullish/bearish FVGs using 3-candle structures
- **Order Blocks (OB)**: Identifies institutional order blocks and tracks their invalidation
- **Breaker Blocks**: Converts invalidated order blocks into new support/resistance levels
- **Break of Structure (BoS)**: Monitors market structure breaks for trend confirmation
- **Optimal Trade Entry (OTE)**: Uses Fibonacci retracements (61.8%-79%) for precise entries

### Risk Management

- **Fixed Risk Per Trade**: $500 per trade (configurable)
- **Dynamic Stop Loss**: Uses ATR (1.5x multiplier) for adaptive stop placement
- **Risk-Reward Ratio**: 1:3 target (configurable)
- **Trailing Stop**: Moves to breakeven after 2R profit
- **Daily Trade Limit**: Maximum 1 trade per day
- **Position Sizing**: Automatically calculated based on risk per trade

### Performance Tracking

- **Comprehensive Logging**: Every entry, exit, and rejection logged with reasons
- **Performance Analytics**: Win rate, average RR, max drawdown tracking
- **Trade Analysis**: Detailed breakdown of winning vs losing trades
- **Sharpe Ratio**: Risk-adjusted return calculation
- **Drawdown Monitoring**: Real-time drawdown tracking and alerts

## 📋 Requirements

### System Requirements
- Python 3.8 or higher
- Windows 10/11 (for TradeLocker compatibility)
- Minimum 4GB RAM
- Internet connection for data fetching

### Python Dependencies
```
backtrader==1.9.78.123
pandas>=1.5.0
numpy>=1.21.0
TA-Lib>=0.4.25
matplotlib>=3.5.0
yfinance>=0.2.0
requests>=2.28.0
websocket-client>=1.4.0
python-dateutil>=2.8.0
pytz>=2022.1
```

## 🚀 Installation

1. **Clone the repository**:
```bash
git clone <repository-url>
cd vein_smc_bot
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
```

3. **Install TA-Lib** (if not already installed):
   - Windows: Download from https://www.lfd.uci.edu/~gohlke/pythonlibs/#ta-lib
   - Linux/Mac: `pip install TA-Lib`

## 📊 Usage

### Quick Start

Run the bot with default settings:
```bash
python run_smc_bot.py
```

### Custom Configuration

Modify strategy parameters in `run_smc_bot.py`:

```python
strategy_params = {
    'risk_per_trade': 500,      # Risk per trade in dollars
    'target_rr': 3.0,           # Risk-reward ratio
    'max_trades_per_day': 1,    # Maximum trades per day
    'atr_multiplier': 1.5,      # ATR multiplier for stop loss
    'ote_fib_low': 0.618,       # OTE Fibonacci low level (61.8%)
    'ote_fib_high': 0.79,       # OTE Fibonacci high level (79%)
    'liquidity_touches': 2,     # Minimum touches for liquidity zone
    'fvg_min_size': 5,         # Minimum FVG size in points
}
```

### Data Loading

The bot can use either real market data or generated sample data:

```python
# Load real data (requires internet)
runner.load_data(days=30, use_real_data=True)

# Use sample data for testing
runner.load_data(days=30, use_real_data=False)
```

## 🔧 File Structure

```
vein_smc_bot/
├── bot.py                 # Main SMC/ICT strategy implementation
├── data_loader.py         # Data fetching and formatting utilities
├── run_smc_bot.py        # Complete bot runner with backtesting
├── requirements.txt       # Python dependencies
├── README.md             # This file
└── .git/                 # Git repository files
```

## 📈 Strategy Logic

### Entry Conditions

**Long Entry (Buy)**:
1. Daily bias = bullish (daily close > previous day's high)
2. Liquidity grab below recent swing low
3. Price trades into bullish FVG
4. Bullish order block support confirmed
5. Break of structure to the upside
6. Price in OTE zone (61.8%-79% retracement)

**Short Entry (Sell)**:
1. Daily bias = bearish (daily close < previous day's low)
2. Liquidity grab above recent swing high
3. Price trades into bearish FVG
4. Bearish order block resistance confirmed
5. Break of structure to the downside
6. Price in OTE zone (61.8%-79% retracement)

### Exit Conditions

- **Stop Loss**: Below/above liquidity grab + ATR buffer
- **Take Profit**: 1:3 risk-reward ratio
- **Trailing Stop**: Move to breakeven after 2R profit
- **Structure Rejection**: Exit if price rejects from breaker blocks or order blocks

## 📊 Performance Metrics

The bot tracks and reports:

- **Total Return**: Overall portfolio performance
- **Win Rate**: Percentage of winning trades
- **Profit Factor**: Ratio of gross profit to gross loss
- **Average Win/Loss**: Average profit and loss per trade
- **Maximum Drawdown**: Largest peak-to-trough decline
- **Sharpe Ratio**: Risk-adjusted return measure
- **Trade Count**: Total number of trades executed

## 🔄 TradeLocker Integration

### Data Format Compatibility

The bot includes a `TradeLockerDataAdapter` class that formats data for TradeLocker compatibility:

```python
from data_loader import TradeLockerDataAdapter

adapter = TradeLockerDataAdapter()
tl_data = adapter.format_for_tradelocker(dataframe, "NAS100")
adapter.save_to_csv(tl_data, "nas100_data.csv")
```

### Bot Engine Compatibility

The strategy is designed to work with TradeLocker's bot engine:
- Uses standard Backtrader framework
- Implements proper order management
- Includes comprehensive logging
- Handles multiple timeframes
- Supports real-time data feeds

## ⚙️ Configuration Options

### Strategy Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `risk_per_trade` | 500 | Fixed risk amount per trade ($) |
| `atr_multiplier` | 1.5 | ATR multiplier for stop loss |
| `target_rr` | 3.0 | Target risk-reward ratio |
| `trail_after_rr` | 2.0 | Trail stop after this RR |
| `max_trades_per_day` | 1 | Maximum trades per day |
| `lookback_period` | 50 | Lookback period for swing points |
| `liquidity_touches` | 2 | Minimum touches for liquidity zone |
| `fvg_min_size` | 5 | Minimum FVG size in points |
| `ote_fib_low` | 0.618 | OTE Fibonacci low level |
| `ote_fib_high` | 0.79 | OTE Fibonacci high level |

### Broker Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `initial_capital` | 100000 | Starting capital ($) |
| `commission` | 0.001 | Commission rate (0.1%) |

## 📝 Logging

The bot provides detailed logging for:

- **Market Structure**: Swing highs/lows, BoS events
- **Liquidity Events**: Liquidity grabs and zone formations
- **FVG Detection**: New FVG formations and fills
- **Order Block Activity**: OB formations and invalidations
- **Trade Execution**: Entry/exit details with reasoning
- **Performance Metrics**: Real-time P&L and statistics

## 🧪 Testing

### Backtesting

Run comprehensive backtests:
```bash
python run_smc_bot.py
```

### Sample Data Generation

For testing without internet connection:
```python
from data_loader import NAS100DataLoader

loader = NAS100DataLoader()
data_15m, data_daily = loader.generate_sample_data(days=30)
```

## 📊 Example Output

```
SMC/ICT Trading Bot for NAS100
==================================================
Cerebro engine configured successfully
Generating sample data...
Generated 624 15-minute bars and 22 daily bars
Data loaded successfully:
  - 15-minute bars: 624
  - Daily bars: 22
  - Date range: 2024-12-07 14:30:00 to 2025-01-06 21:00:00

============================================================
STARTING SMC/ICT BOT BACKTEST
============================================================

2024-12-09 SMC/ICT Strategy initialized for NAS100 15m timeframe
2024-12-09 Bullish FVG identified: 14987.23 - 15012.45
2024-12-09 Liquidity grab below support at 14965.12
2024-12-09 Bullish Break of Structure at 15023.67
2024-12-09 LONG ENTRY: Price=15018.45, Size=12.50, SL=14978.23, TP=15138.89

============================================================
PERFORMANCE SUMMARY
============================================================
Initial Capital:      $100,000.00
Final Value:          $102,450.00
Total Return:         +2.45%
Duration:             0:00:01.234567

----------------------------------------
TRADE STATISTICS
----------------------------------------
Total Trades:         8
Winning Trades:       5
Losing Trades:        3
Win Rate:             62.50%
Average Win:          $890.50
Average Loss:         -$425.30
Profit Factor:        2.09

----------------------------------------
RISK METRICS
----------------------------------------
Max Drawdown:         3.25%
Sharpe Ratio:         1.456
============================================================
```

## 🚨 Risk Disclaimer

This trading bot is for educational and research purposes only. Trading involves substantial risk of loss and is not suitable for all investors. Past performance does not guarantee future results. Always:

- Test thoroughly on demo accounts
- Start with small position sizes
- Monitor performance closely
- Understand the risks involved
- Never risk more than you can afford to lose

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 📞 Support

For questions, issues, or feature requests:
- Open an issue on GitHub
- Check the documentation
- Review the code comments

## 🔄 Updates

The bot is actively maintained and updated with:
- Bug fixes and improvements
- New ICT concepts and features
- Performance optimizations
- Enhanced TradeLocker compatibility

---

**Happy Trading! 📈** 