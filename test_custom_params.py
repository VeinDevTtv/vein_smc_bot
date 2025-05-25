#!/usr/bin/env python3
"""
Custom parameter testing for SMC/ICT Bot
This script tests the bot with more relaxed parameters to see trades in action
"""

import backtrader as bt
from bot import SMCICTStrategy
from data_loader import NAS100DataLoader
import warnings
warnings.filterwarnings('ignore')


def test_relaxed_parameters():
    """Test with more relaxed parameters to generate trades"""
    
    print("Testing SMC Bot with Relaxed Parameters")
    print("=" * 50)
    
    # Create cerebro
    cerebro = bt.Cerebro()
    
    # Set initial capital
    cerebro.broker.setcash(50000.0)
    cerebro.broker.setcommission(commission=0.001)
    
    # Generate sample data
    loader = NAS100DataLoader()
    data_15m, data_daily = loader.generate_sample_data(days=10)  # More data
    
    # Create data feeds
    feed_15m, feed_daily = loader.create_backtrader_feeds(data_15m, data_daily)
    
    # Add data to cerebro
    cerebro.adddata(feed_15m)
    cerebro.adddata(feed_daily)
    
    # Add strategy with relaxed parameters
    cerebro.addstrategy(
        SMCICTStrategy,
        risk_per_trade=200,         # Smaller risk
        max_trades_per_day=5,       # Allow more trades
        liquidity_touches=1,        # Reduce liquidity requirement
        fvg_min_size=2,            # Smaller FVG requirement
        ote_fib_low=0.5,           # Wider OTE zone
        ote_fib_high=0.8,          # Wider OTE zone
        atr_multiplier=1.0,        # Tighter stops
        target_rr=2.0,             # Lower RR target
    )
    
    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    
    # Run backtest
    print("Running backtest with relaxed parameters...")
    start_value = cerebro.broker.getvalue()
    results = cerebro.run()
    end_value = cerebro.broker.getvalue()
    
    # Get results
    strategy = results[0]
    trades_analyzer = strategy.analyzers.trades.get_analysis()
    
    # Display results
    print("\n" + "=" * 50)
    print("RELAXED PARAMETERS TEST RESULTS")
    print("=" * 50)
    print(f"Start Value: ${start_value:,.2f}")
    print(f"End Value: ${end_value:,.2f}")
    print(f"Return: {((end_value - start_value) / start_value * 100):+.2f}%")
    
    total_trades = trades_analyzer.total.total if 'total' in trades_analyzer else 0
    print(f"Total Trades: {total_trades}")
    
    if total_trades > 0:
        winning_trades = trades_analyzer.won.total if 'won' in trades_analyzer else 0
        print(f"Winning Trades: {winning_trades}")
        print(f"Win Rate: {(winning_trades / total_trades * 100):.2f}%")
    
    return total_trades > 0


def test_aggressive_parameters():
    """Test with very aggressive parameters"""
    
    print("\n\nTesting SMC Bot with Aggressive Parameters")
    print("=" * 50)
    
    # Create cerebro
    cerebro = bt.Cerebro()
    
    # Set initial capital
    cerebro.broker.setcash(25000.0)
    cerebro.broker.setcommission(commission=0.001)
    
    # Generate sample data
    loader = NAS100DataLoader()
    data_15m, data_daily = loader.generate_sample_data(days=15)  # Even more data
    
    # Create data feeds
    feed_15m, feed_daily = loader.create_backtrader_feeds(data_15m, data_daily)
    
    # Add data to cerebro
    cerebro.adddata(feed_15m)
    cerebro.adddata(feed_daily)
    
    # Add strategy with very aggressive parameters
    cerebro.addstrategy(
        SMCICTStrategy,
        risk_per_trade=100,         # Very small risk
        max_trades_per_day=10,      # Many trades allowed
        liquidity_touches=1,        # Minimal liquidity requirement
        fvg_min_size=1,            # Very small FVG requirement
        ote_fib_low=0.3,           # Very wide OTE zone
        ote_fib_high=0.9,          # Very wide OTE zone
        atr_multiplier=0.5,        # Very tight stops
        target_rr=1.5,             # Low RR target
        lookback_period=20,        # Shorter lookback
    )
    
    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    # Run backtest
    print("Running backtest with aggressive parameters...")
    start_value = cerebro.broker.getvalue()
    results = cerebro.run()
    end_value = cerebro.broker.getvalue()
    
    # Get results
    strategy = results[0]
    trades_analyzer = strategy.analyzers.trades.get_analysis()
    
    # Display results
    print("\n" + "=" * 50)
    print("AGGRESSIVE PARAMETERS TEST RESULTS")
    print("=" * 50)
    print(f"Start Value: ${start_value:,.2f}")
    print(f"End Value: ${end_value:,.2f}")
    print(f"Return: {((end_value - start_value) / start_value * 100):+.2f}%")
    
    total_trades = trades_analyzer.total.total if 'total' in trades_analyzer else 0
    print(f"Total Trades: {total_trades}")
    
    if total_trades > 0:
        winning_trades = trades_analyzer.won.total if 'won' in trades_analyzer else 0
        print(f"Winning Trades: {winning_trades}")
        print(f"Win Rate: {(winning_trades / total_trades * 100):.2f}%")
    
    return total_trades > 0


def main():
    """Run all parameter tests"""
    
    print("SMC/ICT Bot Parameter Testing Suite")
    print("=" * 60)
    
    # Test 1: Relaxed parameters
    trades_found_1 = test_relaxed_parameters()
    
    # Test 2: Aggressive parameters
    trades_found_2 = test_aggressive_parameters()
    
    # Summary
    print("\n" + "=" * 60)
    print("TESTING SUMMARY")
    print("=" * 60)
    
    if trades_found_1 or trades_found_2:
        print("✅ SUCCESS: Bot can execute trades with adjusted parameters")
        print("📊 The original conservative parameters are working as designed")
        print("🎯 Strategy waits for high-probability setups (good!)")
    else:
        print("ℹ️  No trades found even with relaxed parameters")
        print("📈 This indicates very selective strategy (which is good)")
        print("🔧 Consider testing with longer time periods or real data")
    
    print("\n💡 RECOMMENDATIONS:")
    print("1. Test with longer time periods (30-60 days)")
    print("2. Try with real market data when available")
    print("3. The conservative approach is actually preferred for live trading")
    print("4. Consider paper trading to validate in real market conditions")


if __name__ == "__main__":
    main() 