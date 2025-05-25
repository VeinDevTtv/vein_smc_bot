import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import backtrader as bt
import pytz


class NAS100DataLoader:
    """
    Data loader for NAS100 (NASDAQ-100) data compatible with TradeLocker format
    """
    
    def __init__(self):
        self.symbol = "^NDX"  # NASDAQ-100 index
        self.timezone = pytz.timezone('US/Eastern')
    
    def fetch_data(self, start_date, end_date, interval_15m="15m", interval_daily="1d"):
        """
        Fetch NAS100 data for both 15-minute and daily timeframes
        
        Args:
            start_date (str): Start date in 'YYYY-MM-DD' format
            end_date (str): End date in 'YYYY-MM-DD' format
            interval_15m (str): 15-minute interval
            interval_daily (str): Daily interval
            
        Returns:
            tuple: (data_15m, data_daily) as pandas DataFrames
        """
        
        # Fetch 15-minute data
        ticker = yf.Ticker(self.symbol)
        
        try:
            # Get 15-minute data
            data_15m = ticker.history(
                start=start_date,
                end=end_date,
                interval=interval_15m,
                prepost=False,
                auto_adjust=True,
                back_adjust=False
            )
            
            # Get daily data
            data_daily = ticker.history(
                start=start_date,
                end=end_date,
                interval=interval_daily,
                prepost=False,
                auto_adjust=True,
                back_adjust=False
            )
            
            # Clean and format data
            data_15m = self.clean_data(data_15m)
            data_daily = self.clean_data(data_daily)
            
            print(f"Fetched {len(data_15m)} 15-minute bars and {len(data_daily)} daily bars")
            
            return data_15m, data_daily
            
        except Exception as e:
            print(f"Error fetching data: {e}")
            return None, None
    
    def clean_data(self, df):
        """
        Clean and format the data for Backtrader
        
        Args:
            df (pd.DataFrame): Raw data from yfinance
            
        Returns:
            pd.DataFrame: Cleaned data
        """
        if df is None or df.empty:
            return df
        
        # Remove any rows with NaN values
        df = df.dropna()
        
        # Ensure column names are correct for Backtrader
        df.columns = [col.lower() for col in df.columns]
        
        # Rename columns to match Backtrader expectations
        column_mapping = {
            'adj close': 'close',
            'adjclose': 'close'
        }
        df = df.rename(columns=column_mapping)
        
        # Ensure we have the required columns
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            if col not in df.columns:
                if col == 'volume':
                    df[col] = 0  # Set volume to 0 if not available
                else:
                    raise ValueError(f"Required column '{col}' not found in data")
        
        # Sort by datetime index
        df = df.sort_index()
        
        return df
    
    def create_backtrader_feeds(self, data_15m, data_daily):
        """
        Create Backtrader data feeds from pandas DataFrames
        
        Args:
            data_15m (pd.DataFrame): 15-minute data
            data_daily (pd.DataFrame): Daily data
            
        Returns:
            tuple: (feed_15m, feed_daily) Backtrader data feeds
        """
        
        # Create 15-minute data feed
        feed_15m = bt.feeds.PandasData(
            dataname=data_15m,
            datetime=None,  # Use index as datetime
            open=0,
            high=1,
            low=2,
            close=3,
            volume=4,
            openinterest=-1,  # Not used
            timeframe=bt.TimeFrame.Minutes,
            compression=15
        )
        
        # Create daily data feed
        feed_daily = bt.feeds.PandasData(
            dataname=data_daily,
            datetime=None,  # Use index as datetime
            open=0,
            high=1,
            low=2,
            close=3,
            volume=4,
            openinterest=-1,  # Not used
            timeframe=bt.TimeFrame.Days,
            compression=1
        )
        
        return feed_15m, feed_daily
    
    def generate_sample_data(self, days=30):
        """
        Generate sample NAS100-like data for testing
        
        Args:
            days (int): Number of days to generate
            
        Returns:
            tuple: (data_15m, data_daily) as pandas DataFrames
        """
        
        # Generate date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        
        # Generate 15-minute timestamps
        timestamps_15m = pd.date_range(
            start=start_date,
            end=end_date,
            freq='15T'
        )
        
        # Filter for market hours (9:30 AM to 4:00 PM ET)
        market_hours = []
        for ts in timestamps_15m:
            if ts.weekday() < 5:  # Monday to Friday
                et_time = ts.tz_localize('UTC').tz_convert('US/Eastern')
                if 9.5 <= et_time.hour + et_time.minute/60 <= 16:
                    market_hours.append(ts)
        
        timestamps_15m = pd.DatetimeIndex(market_hours)
        
        # Generate daily timestamps
        timestamps_daily = pd.date_range(
            start=start_date.date(),
            end=end_date.date(),
            freq='D'
        )
        timestamps_daily = timestamps_daily[timestamps_daily.weekday < 5]  # Weekdays only
        
        # Generate realistic NAS100 price data
        base_price = 15000  # Approximate NAS100 level
        
        # 15-minute data
        np.random.seed(42)  # For reproducible results
        returns_15m = np.random.normal(0, 0.002, len(timestamps_15m))  # 0.2% volatility
        prices_15m = [base_price]
        
        for ret in returns_15m[1:]:
            prices_15m.append(prices_15m[-1] * (1 + ret))
        
        # Create OHLC data for 15-minute
        data_15m = []
        for i, price in enumerate(prices_15m):
            high = price * (1 + abs(np.random.normal(0, 0.001)))
            low = price * (1 - abs(np.random.normal(0, 0.001)))
            open_price = price * (1 + np.random.normal(0, 0.0005))
            close_price = price
            volume = np.random.randint(1000, 10000)
            
            data_15m.append([open_price, high, low, close_price, volume])
        
        df_15m = pd.DataFrame(
            data_15m,
            index=timestamps_15m,
            columns=['open', 'high', 'low', 'close', 'volume']
        )
        
        # Daily data (aggregate from 15-minute)
        daily_data = []
        for date in timestamps_daily:
            day_data = df_15m[df_15m.index.date == date.date()]
            if not day_data.empty:
                open_price = day_data.iloc[0]['open']
                high_price = day_data['high'].max()
                low_price = day_data['low'].min()
                close_price = day_data.iloc[-1]['close']
                volume = day_data['volume'].sum()
                
                daily_data.append([open_price, high_price, low_price, close_price, volume])
        
        df_daily = pd.DataFrame(
            daily_data,
            index=timestamps_daily[:len(daily_data)],
            columns=['open', 'high', 'low', 'close', 'volume']
        )
        
        print(f"Generated {len(df_15m)} 15-minute bars and {len(df_daily)} daily bars")
        
        return df_15m, df_daily


class TradeLockerDataAdapter:
    """
    Adapter to format data for TradeLocker compatibility
    """
    
    @staticmethod
    def format_for_tradelocker(df, symbol="NAS100"):
        """
        Format DataFrame for TradeLocker bot engine
        
        Args:
            df (pd.DataFrame): OHLCV data
            symbol (str): Trading symbol
            
        Returns:
            pd.DataFrame: TradeLocker formatted data
        """
        
        # Create a copy to avoid modifying original
        formatted_df = df.copy()
        
        # Add symbol column
        formatted_df['symbol'] = symbol
        
        # Ensure datetime index is timezone-aware
        if formatted_df.index.tz is None:
            formatted_df.index = formatted_df.index.tz_localize('UTC')
        
        # Add timestamp column
        formatted_df['timestamp'] = formatted_df.index
        
        # Reorder columns for TradeLocker
        column_order = ['symbol', 'timestamp', 'open', 'high', 'low', 'close', 'volume']
        formatted_df = formatted_df[column_order]
        
        return formatted_df
    
    @staticmethod
    def save_to_csv(df, filename):
        """
        Save data to CSV file for TradeLocker import
        
        Args:
            df (pd.DataFrame): Data to save
            filename (str): Output filename
        """
        df.to_csv(filename, index=False)
        print(f"Data saved to {filename}")


def main():
    """
    Example usage of the data loader
    """
    
    # Initialize data loader
    loader = NAS100DataLoader()
    
    # Option 1: Fetch real data (requires internet connection)
    try:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        
        print("Fetching real NAS100 data...")
        data_15m, data_daily = loader.fetch_data(start_date, end_date)
        
        if data_15m is None or data_daily is None:
            raise Exception("Failed to fetch real data")
            
    except Exception as e:
        print(f"Could not fetch real data: {e}")
        print("Generating sample data instead...")
        
        # Option 2: Generate sample data
        data_15m, data_daily = loader.generate_sample_data(days=30)
    
    # Create Backtrader feeds
    feed_15m, feed_daily = loader.create_backtrader_feeds(data_15m, data_daily)
    
    # Format for TradeLocker
    adapter = TradeLockerDataAdapter()
    tl_data_15m = adapter.format_for_tradelocker(data_15m, "NAS100")
    tl_data_daily = adapter.format_for_tradelocker(data_daily, "NAS100")
    
    # Save to CSV files
    adapter.save_to_csv(tl_data_15m, "nas100_15m_data.csv")
    adapter.save_to_csv(tl_data_daily, "nas100_daily_data.csv")
    
    print("\nData summary:")
    print(f"15-minute data: {len(data_15m)} bars")
    print(f"Daily data: {len(data_daily)} bars")
    print(f"Date range: {data_15m.index[0]} to {data_15m.index[-1]}")
    
    return feed_15m, feed_daily


if __name__ == "__main__":
    main() 