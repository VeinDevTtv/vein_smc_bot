# Live Testing Guide for SMC/ICT Bot

## 🎯 Testing Approaches

### 1. **Paper Trading (Recommended First Step)**
```python
# Modify run_smc_bot.py for paper trading
strategy_params = {
    'risk_per_trade': 50,       # Start small
    'max_trades_per_day': 3,    # Allow more opportunities
    'target_rr': 2.0,           # Lower RR for more trades
}
```

### 2. **Extended Backtesting**
```bash
# Test with longer periods
python run_smc_bot.py  # Modify days=60 in the script
```

### 3. **Real Data Testing**
- Wait for market hours (9:30 AM - 4:00 PM ET)
- The bot will automatically try to fetch real NAS100 data
- If rate limited, it falls back to sample data

### 4. **TradeLocker Integration**
1. Export data: `python data_loader.py`
2. Upload `nas100_15m_data.csv` to TradeLocker
3. Import the bot strategy code
4. Run in TradeLocker's paper trading environment

## 🔧 Parameter Tuning for More Trades

### Conservative (Current Settings)
```python
risk_per_trade=500,
liquidity_touches=2,
fvg_min_size=5,
ote_fib_low=0.618,
ote_fib_high=0.79,
```

### Moderate (More Trades)
```python
risk_per_trade=200,
liquidity_touches=1,
fvg_min_size=3,
ote_fib_low=0.5,
ote_fib_high=0.8,
```

### Aggressive (Most Trades)
```python
risk_per_trade=100,
liquidity_touches=1,
fvg_min_size=1,
ote_fib_low=0.3,
ote_fib_high=0.9,
```

## 📊 Monitoring Strategy Performance

### Key Metrics to Watch:
- **Win Rate**: Target 50-60%
- **Profit Factor**: Target >1.5
- **Max Drawdown**: Keep <15%
- **Average RR**: Target >2.0

### Red Flags:
- Win rate <40%
- Profit factor <1.2
- Drawdown >20%
- Too many trades (overtrading)

## 🎯 Real Market Validation

### Phase 1: Demo Account (1-2 weeks)
- Start with smallest position sizes
- Monitor all signals and entries
- Track performance vs backtest

### Phase 2: Small Live Account (1 month)
- Use 1-2% of intended capital
- Validate psychological aspects
- Confirm execution quality

### Phase 3: Full Implementation
- Scale up gradually
- Maintain strict risk management
- Regular performance reviews

## 🚨 Important Notes

1. **Market Conditions**: ICT strategies work best in trending markets
2. **News Events**: Avoid trading during major economic releases
3. **Session Times**: Best performance during London/New York overlap
4. **Patience**: Quality over quantity - wait for perfect setups
5. **Discipline**: Stick to the rules, don't override the system

## 📈 Expected Performance

### Realistic Expectations:
- **Monthly Return**: 5-15%
- **Win Rate**: 50-65%
- **Max Drawdown**: 8-12%
- **Trades per Month**: 10-20

### Warning Signs:
- Consistent losses over 2 weeks
- Drawdown exceeding 15%
- Emotional trading decisions
- Deviating from strategy rules 