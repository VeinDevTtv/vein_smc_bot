#!/usr/bin/env python3
"""
Test script for SMC/ICT Trading Bot

This script runs a quick test of the bot with sample data to verify
all components are working correctly.
"""

import sys
import traceback
from datetime import datetime

def test_imports():
    """Test if all required modules can be imported"""
    print("Testing imports...")
    
    try:
        import backtrader as bt
        print("✅ Backtrader imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import Backtrader: {e}")
        return False
    
    try:
        import pandas as pd
        import numpy as np
        print("✅ Pandas and NumPy imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import Pandas/NumPy: {e}")
        return False
    
    try:
        from bot import SMCICTStrategy
        print("✅ SMC/ICT Strategy imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import SMC/ICT Strategy: {e}")
        return False
    
    try:
        from data_loader import NAS100DataLoader, TradeLockerDataAdapter
        print("✅ Data loader imported successfully")
    except ImportError as e:
        print(f"❌ Failed to import Data loader: {e}")
        return False
    
    return True

def test_data_generation():
    """Test data generation functionality"""
    print("\nTesting data generation...")
    
    try:
        from data_loader import NAS100DataLoader
        
        loader = NAS100DataLoader()
        data_15m, data_daily = loader.generate_sample_data(days=5)
        
        if data_15m is None or data_daily is None:
            print("❌ Data generation returned None")
            return False
        
        if len(data_15m) == 0 or len(data_daily) == 0:
            print("❌ Generated data is empty")
            return False
        
        print(f"✅ Generated {len(data_15m)} 15-minute bars and {len(data_daily)} daily bars")
        
        # Test data format
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in data_15m.columns:
                print(f"❌ Missing column '{col}' in 15-minute data")
                return False
            if col not in data_daily.columns:
                print(f"❌ Missing column '{col}' in daily data")
                return False
        
        print("✅ Data format is correct")
        return True
        
    except Exception as e:
        print(f"❌ Data generation failed: {e}")
        traceback.print_exc()
        return False

def test_strategy_initialization():
    """Test strategy initialization"""
    print("\nTesting strategy initialization...")
    
    try:
        import backtrader as bt
        from bot import SMCICTStrategy
        from data_loader import NAS100DataLoader
        
        # Create minimal cerebro setup
        cerebro = bt.Cerebro()
        
        # Generate sample data
        loader = NAS100DataLoader()
        data_15m, data_daily = loader.generate_sample_data(days=5)
        
        # Create data feeds
        feed_15m, feed_daily = loader.create_backtrader_feeds(data_15m, data_daily)
        
        # Add data to cerebro
        cerebro.adddata(feed_15m)
        cerebro.adddata(feed_daily)
        
        # Add strategy
        cerebro.addstrategy(SMCICTStrategy)
        
        print("✅ Strategy initialized successfully")
        return True
        
    except Exception as e:
        print(f"❌ Strategy initialization failed: {e}")
        traceback.print_exc()
        return False

def test_quick_backtest():
    """Run a quick backtest to verify everything works"""
    print("\nTesting quick backtest...")
    
    try:
        import backtrader as bt
        from bot import SMCICTStrategy
        from data_loader import NAS100DataLoader
        
        # Create cerebro
        cerebro = bt.Cerebro()
        
        # Set initial capital
        cerebro.broker.setcash(10000.0)  # Smaller amount for testing
        
        # Generate sample data
        loader = NAS100DataLoader()
        data_15m, data_daily = loader.generate_sample_data(days=5)
        
        # Create data feeds
        feed_15m, feed_daily = loader.create_backtrader_feeds(data_15m, data_daily)
        
        # Add data to cerebro
        cerebro.adddata(feed_15m)
        cerebro.adddata(feed_daily)
        
        # Add strategy with test parameters
        cerebro.addstrategy(
            SMCICTStrategy,
            risk_per_trade=100,  # Smaller risk for testing
            max_trades_per_day=5  # Allow more trades for testing
        )
        
        # Record start values
        start_value = cerebro.broker.getvalue()
        
        # Run backtest
        print("Running backtest...")
        results = cerebro.run()
        
        # Record end values
        end_value = cerebro.broker.getvalue()
        
        print(f"✅ Backtest completed successfully")
        print(f"   Start value: ${start_value:,.2f}")
        print(f"   End value: ${end_value:,.2f}")
        print(f"   Return: {((end_value - start_value) / start_value * 100):+.2f}%")
        
        return True
        
    except Exception as e:
        print(f"❌ Backtest failed: {e}")
        traceback.print_exc()
        return False

def test_tradelocker_compatibility():
    """Test TradeLocker data format compatibility"""
    print("\nTesting TradeLocker compatibility...")
    
    try:
        from data_loader import NAS100DataLoader, TradeLockerDataAdapter
        
        # Generate sample data
        loader = NAS100DataLoader()
        data_15m, data_daily = loader.generate_sample_data(days=2)
        
        # Test TradeLocker adapter
        adapter = TradeLockerDataAdapter()
        tl_data = adapter.format_for_tradelocker(data_15m, "NAS100")
        
        # Check format
        required_columns = ['symbol', 'timestamp', 'open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in tl_data.columns:
                print(f"❌ Missing column '{col}' in TradeLocker format")
                return False
        
        # Check symbol column
        if not all(tl_data['symbol'] == 'NAS100'):
            print("❌ Symbol column not set correctly")
            return False
        
        print("✅ TradeLocker format is correct")
        return True
        
    except Exception as e:
        print(f"❌ TradeLocker compatibility test failed: {e}")
        traceback.print_exc()
        return False

def main():
    """Run all tests"""
    print("SMC/ICT Trading Bot - Test Suite")
    print("=" * 50)
    print(f"Test started at: {datetime.now()}")
    print()
    
    tests = [
        ("Import Test", test_imports),
        ("Data Generation Test", test_data_generation),
        ("Strategy Initialization Test", test_strategy_initialization),
        ("Quick Backtest Test", test_quick_backtest),
        ("TradeLocker Compatibility Test", test_tradelocker_compatibility),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"Running {test_name}...")
        try:
            if test_func():
                passed += 1
            else:
                print(f"❌ {test_name} FAILED")
        except Exception as e:
            print(f"❌ {test_name} FAILED with exception: {e}")
        
        print()
    
    print("=" * 50)
    print(f"TEST RESULTS: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED! The bot is ready to use.")
        return True
    else:
        print("⚠️  Some tests failed. Please check the errors above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 