#!/usr/bin/env python3
"""
SMC/ICT Trading Bot Runner for NAS100

This script demonstrates how to run the complete SMC/ICT trading bot
with data loading, backtesting, and performance analysis.

Compatible with TradeLocker bot engine.
"""

import backtrader as bt
import pandas as pd
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import warnings
warnings.filterwarnings('ignore')

# Import our custom modules
from bot import SMCICTStrategy
from data_loader import NAS100DataLoader, TradeLockerDataAdapter


class SMCBotRunner:
    """
    Main runner class for the SMC/ICT trading bot
    """
    
    def __init__(self, initial_capital=100000, commission=0.001):
        """
        Initialize the bot runner
        
        Args:
            initial_capital (float): Starting capital
            commission (float): Commission rate (0.001 = 0.1%)
        """
        self.initial_capital = initial_capital
        self.commission = commission
        self.cerebro = None
        self.results = None
        
    def setup_cerebro(self, strategy_params=None):
        """
        Setup Cerebro engine with strategy and parameters
        
        Args:
            strategy_params (dict): Strategy parameters to override defaults
        """
        self.cerebro = bt.Cerebro()
        
        # Add strategy with custom parameters
        if strategy_params:
            self.cerebro.addstrategy(SMCICTStrategy, **strategy_params)
        else:
            self.cerebro.addstrategy(SMCICTStrategy)
        
        # Set broker parameters
        self.cerebro.broker.setcash(self.initial_capital)
        self.cerebro.broker.setcommission(commission=self.commission)
        
        # Add analyzers for performance metrics
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
        
        print("Cerebro engine configured successfully")
    
    def load_data(self, days=30, use_real_data=True):
        """
        Load NAS100 data for backtesting
        
        Args:
            days (int): Number of days of data to load
            use_real_data (bool): Whether to try fetching real data first
            
        Returns:
            bool: True if data loaded successfully
        """
        loader = NAS100DataLoader()
        
        if use_real_data:
            try:
                end_date = datetime.now().strftime('%Y-%m-%d')
                start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
                
                print(f"Fetching real NAS100 data from {start_date} to {end_date}...")
                data_15m, data_daily = loader.fetch_data(start_date, end_date)
                
                if data_15m is None or data_daily is None or len(data_15m) < 100:
                    raise Exception("Insufficient real data")
                    
            except Exception as e:
                print(f"Could not fetch real data: {e}")
                print("Generating sample data instead...")
                data_15m, data_daily = loader.generate_sample_data(days=days)
        else:
            print("Generating sample data...")
            data_15m, data_daily = loader.generate_sample_data(days=days)
        
        if data_15m is None or data_daily is None:
            print("Failed to load data")
            return False
        
        # Create Backtrader feeds
        feed_15m, feed_daily = loader.create_backtrader_feeds(data_15m, data_daily)
        
        # Add data feeds to Cerebro
        self.cerebro.adddata(feed_15m, name='NAS100_15m')
        self.cerebro.adddata(feed_daily, name='NAS100_daily')
        
        print(f"Data loaded successfully:")
        print(f"  - 15-minute bars: {len(data_15m)}")
        print(f"  - Daily bars: {len(data_daily)}")
        print(f"  - Date range: {data_15m.index[0]} to {data_15m.index[-1]}")
        
        return True
    
    def run_backtest(self):
        """
        Run the backtest
        
        Returns:
            dict: Performance results
        """
        if self.cerebro is None:
            raise ValueError("Cerebro not configured. Call setup_cerebro() first.")
        
        print("\n" + "="*60)
        print("STARTING SMC/ICT BOT BACKTEST")
        print("="*60)
        
        # Record start time and portfolio value
        start_time = datetime.now()
        start_value = self.cerebro.broker.getvalue()
        
        # Run the backtest
        self.results = self.cerebro.run()
        
        # Record end time and portfolio value
        end_time = datetime.now()
        end_value = self.cerebro.broker.getvalue()
        
        print("\n" + "="*60)
        print("BACKTEST COMPLETED")
        print("="*60)
        
        # Calculate performance metrics
        performance = self.calculate_performance(start_value, end_value, start_time, end_time)
        
        return performance
    
    def calculate_performance(self, start_value, end_value, start_time, end_time):
        """
        Calculate and display performance metrics
        
        Args:
            start_value (float): Starting portfolio value
            end_value (float): Ending portfolio value
            start_time (datetime): Backtest start time
            end_time (datetime): Backtest end time
            
        Returns:
            dict: Performance metrics
        """
        if not self.results:
            return {}
        
        # Get analyzer results
        strategy = self.results[0]
        trades_analyzer = strategy.analyzers.trades.get_analysis()
        sharpe_analyzer = strategy.analyzers.sharpe.get_analysis()
        drawdown_analyzer = strategy.analyzers.drawdown.get_analysis()
        returns_analyzer = strategy.analyzers.returns.get_analysis()
        
        # Calculate basic metrics
        total_return = (end_value - start_value) / start_value * 100
        duration = end_time - start_time
        
        # Extract trade statistics
        total_trades = trades_analyzer.total.total if 'total' in trades_analyzer else 0
        winning_trades = trades_analyzer.won.total if 'won' in trades_analyzer else 0
        losing_trades = trades_analyzer.lost.total if 'lost' in trades_analyzer else 0
        
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Average trade metrics
        avg_win = trades_analyzer.won.pnl.average if 'won' in trades_analyzer and trades_analyzer.won.total > 0 else 0
        avg_loss = trades_analyzer.lost.pnl.average if 'lost' in trades_analyzer and trades_analyzer.lost.total > 0 else 0
        
        # Risk metrics
        max_drawdown = drawdown_analyzer.max.drawdown if 'max' in drawdown_analyzer else 0
        sharpe_ratio = sharpe_analyzer.get('sharperatio', 0) if sharpe_analyzer else 0
        
        # Compile performance dictionary
        performance = {
            'start_value': start_value,
            'end_value': end_value,
            'total_return_pct': total_return,
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate_pct': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': abs(avg_win / avg_loss) if avg_loss != 0 else 0,
            'max_drawdown_pct': max_drawdown,
            'sharpe_ratio': sharpe_ratio,
            'duration': duration
        }
        
        # Display results
        self.display_performance(performance)
        
        return performance
    
    def display_performance(self, performance):
        """
        Display performance results in a formatted way
        
        Args:
            performance (dict): Performance metrics
        """
        print("\n" + "="*60)
        print("PERFORMANCE SUMMARY")
        print("="*60)
        
        print(f"Initial Capital:      ${performance['start_value']:,.2f}")
        print(f"Final Value:          ${performance['end_value']:,.2f}")
        print(f"Total Return:         {performance['total_return_pct']:+.2f}%")
        print(f"Duration:             {performance['duration']}")
        
        print("\n" + "-"*40)
        print("TRADE STATISTICS")
        print("-"*40)
        
        print(f"Total Trades:         {performance['total_trades']}")
        print(f"Winning Trades:       {performance['winning_trades']}")
        print(f"Losing Trades:        {performance['losing_trades']}")
        print(f"Win Rate:             {performance['win_rate_pct']:.2f}%")
        
        if performance['total_trades'] > 0:
            print(f"Average Win:          ${performance['avg_win']:,.2f}")
            print(f"Average Loss:         ${performance['avg_loss']:,.2f}")
            print(f"Profit Factor:        {performance['profit_factor']:.2f}")
        
        print("\n" + "-"*40)
        print("RISK METRICS")
        print("-"*40)
        
        print(f"Max Drawdown:         {performance['max_drawdown_pct']:.2f}%")
        sharpe_display = f"{performance['sharpe_ratio']:.3f}" if performance['sharpe_ratio'] is not None else "N/A"
        print(f"Sharpe Ratio:         {sharpe_display}")
        
        print("\n" + "="*60)
    
    def plot_results(self, save_plot=False, filename='smc_bot_results.png'):
        """
        Plot backtest results
        
        Args:
            save_plot (bool): Whether to save the plot to file
            filename (str): Filename for saved plot
        """
        if self.cerebro is None:
            print("No results to plot. Run backtest first.")
            return
        
        try:
            # Plot with Backtrader's built-in plotting
            self.cerebro.plot(style='candlestick', barup='green', bardown='red')
            
            if save_plot:
                plt.savefig(filename, dpi=300, bbox_inches='tight')
                print(f"Plot saved as {filename}")
            
            plt.show()
            
        except Exception as e:
            print(f"Error plotting results: {e}")
            print("Plotting requires matplotlib and may not work in all environments")


def main():
    """
    Main function to run the SMC/ICT bot
    """
    print("SMC/ICT Trading Bot for NAS100")
    print("="*50)
    
    # Initialize bot runner
    runner = SMCBotRunner(
        initial_capital=100000,  # $100,000 starting capital
        commission=0.001         # 0.1% commission
    )
    
    # Custom strategy parameters (optional)
    strategy_params = {
        'risk_per_trade': 500,      # $500 risk per trade
        'target_rr': 3.0,           # 1:3 risk-reward ratio
        'max_trades_per_day': 1,    # Maximum 1 trade per day
        'atr_multiplier': 1.5,      # ATR multiplier for stop loss
        'ote_fib_low': 0.618,       # OTE Fibonacci low level
        'ote_fib_high': 0.79,       # OTE Fibonacci high level
    }
    
    # Setup Cerebro engine
    runner.setup_cerebro(strategy_params)
    
    # Load data (30 days of data)
    if not runner.load_data(days=30, use_real_data=True):
        print("Failed to load data. Exiting.")
        return
    
    # Run backtest
    try:
        performance = runner.run_backtest()
        
        # Optionally plot results (comment out if running headless)
        # runner.plot_results(save_plot=True)
        
        # Save performance to file
        import json
        with open('smc_bot_performance.json', 'w') as f:
            # Convert datetime objects to strings for JSON serialization
            perf_copy = performance.copy()
            if 'duration' in perf_copy:
                perf_copy['duration'] = str(perf_copy['duration'])
            json.dump(perf_copy, f, indent=2)
        
        print("\nPerformance results saved to 'smc_bot_performance.json'")
        
        # Recommendations based on performance
        print("\n" + "="*60)
        print("RECOMMENDATIONS")
        print("="*60)
        
        if performance['win_rate_pct'] >= 60:
            print("✅ Good win rate! Strategy shows promise.")
        else:
            print("⚠️  Low win rate. Consider adjusting entry criteria.")
        
        if performance['profit_factor'] >= 1.5:
            print("✅ Good profit factor! Wins are significantly larger than losses.")
        else:
            print("⚠️  Low profit factor. Consider improving risk-reward ratio.")
        
        if performance['max_drawdown_pct'] <= 10:
            print("✅ Low drawdown. Good risk management.")
        else:
            print("⚠️  High drawdown. Consider reducing position sizes.")
        
        if performance['total_trades'] >= 10:
            print("✅ Sufficient trade sample for analysis.")
        else:
            print("⚠️  Low trade count. Consider longer backtest period.")
        
    except Exception as e:
        print(f"Error running backtest: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main() 