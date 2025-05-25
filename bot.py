import backtrader as bt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import deque


class SMCICTStrategy(bt.Strategy):
    """
    Smart Money Concepts (SMC) / Inner Circle Trader (ICT) Strategy
    
    This strategy implements modern ICT concepts for NAS100 on 15-minute timeframe:
    - Daily bias determination
    - Liquidity zones identification
    - Fair Value Gaps (FVG)
    - Order Blocks (OB)
    - Breaker Blocks
    - Break of Structure (BoS)
    - Optimal Trade Entry (OTE) using Fibonacci retracements
    """
    
    params = (
        ('risk_per_trade', 500),  # Fixed risk per trade in dollars
        ('atr_multiplier', 1.5),  # ATR multiplier for stop loss
        ('target_rr', 3.0),       # Risk-reward ratio
        ('trail_after_rr', 2.0),  # Trail stop after this RR
        ('max_trades_per_day', 1), # Maximum trades per day
        ('lookback_period', 50),   # Lookback period for swing highs/lows
        ('liquidity_touches', 2),  # Minimum touches for liquidity zone
        ('fvg_min_size', 5),      # Minimum FVG size in points
        ('ote_fib_low', 0.618),   # OTE Fibonacci low level
        ('ote_fib_high', 0.79),   # OTE Fibonacci high level
    )
    
    def __init__(self):
        """Initialize strategy components and indicators"""
        
        # Data feeds
        self.data_15m = self.datas[0]  # 15-minute data
        self.data_daily = self.datas[1] if len(self.datas) > 1 else None  # Daily data
        
        # ATR for dynamic stop loss
        self.atr = bt.indicators.ATR(self.data_15m, period=14)
        
        # Track daily bias
        self.daily_bias = 0  # 1 = bullish, -1 = bearish, 0 = neutral
        
        # Structure tracking
        self.swing_highs = deque(maxlen=self.params.lookback_period)
        self.swing_lows = deque(maxlen=self.params.lookback_period)
        self.last_bos_direction = 0  # 1 = bullish BoS, -1 = bearish BoS
        
        # Liquidity zones
        self.liquidity_zones = []  # List of liquidity zones
        
        # Fair Value Gaps
        self.fvgs = []  # List of active FVGs
        
        # Order Blocks
        self.order_blocks = []  # List of active order blocks
        
        # Breaker Blocks
        self.breaker_blocks = []  # List of active breaker blocks
        
        # Trade management
        self.trades_today = 0
        self.current_date = None
        self.entry_price = 0
        self.stop_loss = 0
        self.take_profit = 0
        self.position_size = 0
        self.trail_activated = False
        
        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0
        self.max_drawdown = 0
        self.peak_equity = 0
        
        self.log("SMC/ICT Strategy initialized for NAS100 15m timeframe")
    
    def log(self, txt, dt=None):
        """Logging function with timestamp"""
        dt = dt or self.datas[0].datetime.date(0)
        print(f'{dt.isoformat()} {txt}')
    
    def next(self):
        """Main strategy logic executed on each bar"""
        
        # Reset daily trade counter
        current_date = self.data_15m.datetime.date(0)
        if self.current_date != current_date:
            self.current_date = current_date
            self.trades_today = 0
        
        # Skip if max trades per day reached
        if self.trades_today >= self.params.max_trades_per_day:
            return
        
        # Update daily bias
        self.update_daily_bias()
        
        # Update market structure
        self.update_swing_points()
        self.update_liquidity_zones()
        self.update_fvgs()
        self.update_order_blocks()
        self.update_breaker_blocks()
        
        # Check for Break of Structure
        self.check_break_of_structure()
        
        # Manage existing positions
        if self.position:
            self.manage_position()
        else:
            # Look for new trade opportunities
            self.check_entry_conditions()
    
    def update_daily_bias(self):
        """Update daily bias based on daily timeframe"""
        if self.data_daily and len(self.data_daily) > 1:
            current_close = self.data_daily.close[0]
            prev_high = self.data_daily.high[-1]
            prev_low = self.data_daily.low[-1]
            
            if current_close > prev_high:
                self.daily_bias = 1  # Bullish
            elif current_close < prev_low:
                self.daily_bias = -1  # Bearish
            else:
                # Keep previous bias if no clear signal
                pass
    
    def update_swing_points(self):
        """Identify and update swing highs and lows"""
        if len(self.data_15m) < 5:
            return
        
        # Check for swing high (current high > 2 previous and 2 next highs)
        if (len(self.data_15m) >= 5 and
            self.data_15m.high[-2] > self.data_15m.high[-4] and
            self.data_15m.high[-2] > self.data_15m.high[-3] and
            self.data_15m.high[-2] > self.data_15m.high[-1] and
            self.data_15m.high[-2] > self.data_15m.high[0]):
            
            swing_high = {
                'price': self.data_15m.high[-2],
                'index': len(self.data_15m) - 2,
                'datetime': self.data_15m.datetime[-2]
            }
            self.swing_highs.append(swing_high)
        
        # Check for swing low
        if (len(self.data_15m) >= 5 and
            self.data_15m.low[-2] < self.data_15m.low[-4] and
            self.data_15m.low[-2] < self.data_15m.low[-3] and
            self.data_15m.low[-2] < self.data_15m.low[-1] and
            self.data_15m.low[-2] < self.data_15m.low[0]):
            
            swing_low = {
                'price': self.data_15m.low[-2],
                'index': len(self.data_15m) - 2,
                'datetime': self.data_15m.datetime[-2]
            }
            self.swing_lows.append(swing_low)
    
    def update_liquidity_zones(self):
        """Identify liquidity zones (equal highs/lows)"""
        # Clean old liquidity zones
        self.liquidity_zones = [zone for zone in self.liquidity_zones 
                               if not zone.get('swept', False)]
        
        # Check for equal highs
        if len(self.swing_highs) >= self.params.liquidity_touches:
            recent_highs = list(self.swing_highs)[-10:]  # Last 10 swing highs
            for i, high1 in enumerate(recent_highs[:-1]):
                touches = 1
                for high2 in recent_highs[i+1:]:
                    if abs(high1['price'] - high2['price']) <= 10:  # Within 10 points
                        touches += 1
                
                if touches >= self.params.liquidity_touches:
                    liquidity_zone = {
                        'type': 'resistance',
                        'price': high1['price'],
                        'touches': touches,
                        'swept': False
                    }
                    
                    # Check if already exists
                    exists = any(abs(zone['price'] - liquidity_zone['price']) <= 10 
                               for zone in self.liquidity_zones 
                               if zone['type'] == 'resistance')
                    
                    if not exists:
                        self.liquidity_zones.append(liquidity_zone)
        
        # Check for equal lows
        if len(self.swing_lows) >= self.params.liquidity_touches:
            recent_lows = list(self.swing_lows)[-10:]  # Last 10 swing lows
            for i, low1 in enumerate(recent_lows[:-1]):
                touches = 1
                for low2 in recent_lows[i+1:]:
                    if abs(low1['price'] - low2['price']) <= 10:  # Within 10 points
                        touches += 1
                
                if touches >= self.params.liquidity_touches:
                    liquidity_zone = {
                        'type': 'support',
                        'price': low1['price'],
                        'touches': touches,
                        'swept': False
                    }
                    
                    # Check if already exists
                    exists = any(abs(zone['price'] - liquidity_zone['price']) <= 10 
                               for zone in self.liquidity_zones 
                               if zone['type'] == 'support')
                    
                    if not exists:
                        self.liquidity_zones.append(liquidity_zone)
        
        # Check for liquidity grabs
        current_high = self.data_15m.high[0]
        current_low = self.data_15m.low[0]
        current_close = self.data_15m.close[0]
        
        for zone in self.liquidity_zones:
            if zone['type'] == 'resistance' and not zone['swept']:
                if current_high > zone['price'] and current_close < zone['price']:
                    zone['swept'] = True
                    self.log(f"Liquidity grab above resistance at {zone['price']}")
            
            elif zone['type'] == 'support' and not zone['swept']:
                if current_low < zone['price'] and current_close > zone['price']:
                    zone['swept'] = True
                    self.log(f"Liquidity grab below support at {zone['price']}")
    
    def update_fvgs(self):
        """Identify Fair Value Gaps"""
        if len(self.data_15m) < 3:
            return
        
        # Clean filled FVGs
        current_high = self.data_15m.high[0]
        current_low = self.data_15m.low[0]
        
        self.fvgs = [fvg for fvg in self.fvgs 
                    if not self.is_fvg_filled(fvg, current_high, current_low)]
        
        # Check for new bullish FVG
        if (self.data_15m.low[0] > self.data_15m.high[-2] and
            self.data_15m.low[0] - self.data_15m.high[-2] >= self.params.fvg_min_size):
            
            fvg = {
                'type': 'bullish',
                'top': self.data_15m.low[0],
                'bottom': self.data_15m.high[-2],
                'index': len(self.data_15m),
                'filled': False
            }
            self.fvgs.append(fvg)
            self.log(f"Bullish FVG identified: {fvg['bottom']:.2f} - {fvg['top']:.2f}")
        
        # Check for new bearish FVG
        if (self.data_15m.high[0] < self.data_15m.low[-2] and
            self.data_15m.low[-2] - self.data_15m.high[0] >= self.params.fvg_min_size):
            
            fvg = {
                'type': 'bearish',
                'top': self.data_15m.low[-2],
                'bottom': self.data_15m.high[0],
                'index': len(self.data_15m),
                'filled': False
            }
            self.fvgs.append(fvg)
            self.log(f"Bearish FVG identified: {fvg['bottom']:.2f} - {fvg['top']:.2f}")
    
    def is_fvg_filled(self, fvg, current_high, current_low):
        """Check if FVG is filled"""
        if fvg['type'] == 'bullish':
            return current_low <= fvg['bottom']
        else:  # bearish
            return current_high >= fvg['top']
    
    def update_order_blocks(self):
        """Identify Order Blocks"""
        if len(self.data_15m) < 10:
            return
        
        # Clean old order blocks (keep only recent ones)
        self.order_blocks = self.order_blocks[-20:]  # Keep last 20
        
        # Look for bullish order block (last up candle before down move)
        for i in range(5, len(self.data_15m)):
            if (self.data_15m.close[-i] > self.data_15m.open[-i] and  # Up candle
                self.data_15m.close[-i+1] < self.data_15m.open[-i+1] and  # Next candle down
                self.data_15m.close[-i+2] < self.data_15m.close[-i+1]):  # Continued down move
                
                ob = {
                    'type': 'bullish',
                    'top': self.data_15m.high[-i],
                    'bottom': self.data_15m.low[-i],
                    'index': len(self.data_15m) - i,
                    'invalidated': False
                }
                
                # Check if already exists
                exists = any(abs(existing_ob['top'] - ob['top']) <= 5 and
                           abs(existing_ob['bottom'] - ob['bottom']) <= 5
                           for existing_ob in self.order_blocks
                           if existing_ob['type'] == 'bullish')
                
                if not exists:
                    self.order_blocks.append(ob)
                    self.log(f"Bullish Order Block: {ob['bottom']:.2f} - {ob['top']:.2f}")
                break
        
        # Look for bearish order block (last down candle before up move)
        for i in range(5, len(self.data_15m)):
            if (self.data_15m.close[-i] < self.data_15m.open[-i] and  # Down candle
                self.data_15m.close[-i+1] > self.data_15m.open[-i+1] and  # Next candle up
                self.data_15m.close[-i+2] > self.data_15m.close[-i+1]):  # Continued up move
                
                ob = {
                    'type': 'bearish',
                    'top': self.data_15m.high[-i],
                    'bottom': self.data_15m.low[-i],
                    'index': len(self.data_15m) - i,
                    'invalidated': False
                }
                
                # Check if already exists
                exists = any(abs(existing_ob['top'] - ob['top']) <= 5 and
                           abs(existing_ob['bottom'] - ob['bottom']) <= 5
                           for existing_ob in self.order_blocks
                           if existing_ob['type'] == 'bearish')
                
                if not exists:
                    self.order_blocks.append(ob)
                    self.log(f"Bearish Order Block: {ob['bottom']:.2f} - {ob['top']:.2f}")
                break
        
        # Check for order block invalidation
        current_close = self.data_15m.close[0]
        for ob in self.order_blocks:
            if not ob['invalidated']:
                if ob['type'] == 'bullish' and current_close < ob['bottom']:
                    ob['invalidated'] = True
                elif ob['type'] == 'bearish' and current_close > ob['top']:
                    ob['invalidated'] = True
    
    def update_breaker_blocks(self):
        """Identify Breaker Blocks (invalidated order blocks that become resistance/support)"""
        for ob in self.order_blocks:
            if ob['invalidated']:
                # Convert to breaker block
                breaker = {
                    'type': 'bearish' if ob['type'] == 'bullish' else 'bullish',
                    'top': ob['top'],
                    'bottom': ob['bottom'],
                    'original_type': ob['type']
                }
                
                # Check if already exists
                exists = any(abs(bb['top'] - breaker['top']) <= 5 and
                           abs(bb['bottom'] - breaker['bottom']) <= 5
                           for bb in self.breaker_blocks)
                
                if not exists:
                    self.breaker_blocks.append(breaker)
                    self.log(f"Breaker Block formed: {breaker['type']} at {breaker['bottom']:.2f} - {breaker['top']:.2f}")
    
    def check_break_of_structure(self):
        """Check for Break of Structure"""
        if not self.swing_highs or not self.swing_lows:
            return
        
        current_close = self.data_15m.close[0]
        last_swing_high = max(self.swing_highs, key=lambda x: x['index'])['price']
        last_swing_low = min(self.swing_lows, key=lambda x: x['index'])['price']
        
        # Bullish BoS
        if current_close > last_swing_high and self.last_bos_direction != 1:
            self.last_bos_direction = 1
            self.log(f"Bullish Break of Structure at {current_close:.2f}")
        
        # Bearish BoS
        elif current_close < last_swing_low and self.last_bos_direction != -1:
            self.last_bos_direction = -1
            self.log(f"Bearish Break of Structure at {current_close:.2f}")
    
    def check_entry_conditions(self):
        """Check for trade entry conditions"""
        if not self.swing_highs or not self.swing_lows:
            return
        
        current_price = self.data_15m.close[0]
        
        # Check for long entry
        if self.daily_bias == 1:  # Bullish bias
            if self.check_long_conditions(current_price):
                self.enter_long()
        
        # Check for short entry
        elif self.daily_bias == -1:  # Bearish bias
            if self.check_short_conditions(current_price):
                self.enter_short()
    
    def check_long_conditions(self, current_price):
        """Check conditions for long entry"""
        # 1. Liquidity grab below recent swing low
        liquidity_grabbed = any(zone['type'] == 'support' and zone['swept'] 
                               for zone in self.liquidity_zones)
        
        # 2. Price in bullish FVG
        in_bullish_fvg = any(fvg['type'] == 'bullish' and 
                            fvg['bottom'] <= current_price <= fvg['top']
                            for fvg in self.fvgs)
        
        # 3. Bullish order block support
        ob_support = any(ob['type'] == 'bullish' and not ob['invalidated'] and
                        ob['bottom'] <= current_price <= ob['top']
                        for ob in self.order_blocks)
        
        # 4. Bullish BoS
        bullish_bos = self.last_bos_direction == 1
        
        # 5. OTE zone (61.8% - 79% retracement)
        in_ote_zone = self.check_ote_zone(current_price, 'bullish')
        
        return (liquidity_grabbed and in_bullish_fvg and 
                ob_support and bullish_bos and in_ote_zone)
    
    def check_short_conditions(self, current_price):
        """Check conditions for short entry"""
        # 1. Liquidity grab above recent swing high
        liquidity_grabbed = any(zone['type'] == 'resistance' and zone['swept'] 
                               for zone in self.liquidity_zones)
        
        # 2. Price in bearish FVG
        in_bearish_fvg = any(fvg['type'] == 'bearish' and 
                            fvg['bottom'] <= current_price <= fvg['top']
                            for fvg in self.fvgs)
        
        # 3. Bearish order block resistance
        ob_resistance = any(ob['type'] == 'bearish' and not ob['invalidated'] and
                           ob['bottom'] <= current_price <= ob['top']
                           for ob in self.order_blocks)
        
        # 4. Bearish BoS
        bearish_bos = self.last_bos_direction == -1
        
        # 5. OTE zone (61.8% - 79% retracement)
        in_ote_zone = self.check_ote_zone(current_price, 'bearish')
        
        return (liquidity_grabbed and in_bearish_fvg and 
                ob_resistance and bearish_bos and in_ote_zone)
    
    def check_ote_zone(self, current_price, direction):
        """Check if price is in Optimal Trade Entry zone"""
        if not self.swing_highs or not self.swing_lows:
            return False
        
        if direction == 'bullish':
            # Get recent swing low to high
            recent_low = min(self.swing_lows, key=lambda x: x['index'])['price']
            recent_high = max(self.swing_highs, key=lambda x: x['index'])['price']
            
            if recent_high > recent_low:
                range_size = recent_high - recent_low
                fib_618 = recent_high - (range_size * self.params.ote_fib_low)
                fib_79 = recent_high - (range_size * self.params.ote_fib_high)
                
                return fib_79 <= current_price <= fib_618
        
        else:  # bearish
            # Get recent swing high to low
            recent_high = max(self.swing_highs, key=lambda x: x['index'])['price']
            recent_low = min(self.swing_lows, key=lambda x: x['index'])['price']
            
            if recent_high > recent_low:
                range_size = recent_high - recent_low
                fib_618 = recent_low + (range_size * self.params.ote_fib_low)
                fib_79 = recent_low + (range_size * self.params.ote_fib_high)
                
                return fib_618 <= current_price <= fib_79
        
        return False
    
    def enter_long(self):
        """Enter long position"""
        if self.position:
            return
        
        current_price = self.data_15m.close[0]
        atr_value = self.atr[0]
        
        # Calculate stop loss (below liquidity grab)
        liquidity_zones_support = [zone for zone in self.liquidity_zones 
                                  if zone['type'] == 'support' and zone['swept']]
        if liquidity_zones_support:
            stop_loss = min(zone['price'] for zone in liquidity_zones_support) - (atr_value * self.params.atr_multiplier)
        else:
            stop_loss = current_price - (atr_value * self.params.atr_multiplier)
        
        # Calculate position size based on fixed risk
        risk_per_point = abs(current_price - stop_loss)
        if risk_per_point > 0:
            position_size = self.params.risk_per_trade / risk_per_point
        else:
            return
        
        # Calculate take profit (1:3 RR)
        take_profit = current_price + (abs(current_price - stop_loss) * self.params.target_rr)
        
        # Place order
        self.order = self.buy(size=position_size)
        self.entry_price = current_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.position_size = position_size
        self.trail_activated = False
        self.trades_today += 1
        
        self.log(f"LONG ENTRY: Price={current_price:.2f}, Size={position_size:.2f}, "
                f"SL={stop_loss:.2f}, TP={take_profit:.2f}")
    
    def enter_short(self):
        """Enter short position"""
        if self.position:
            return
        
        current_price = self.data_15m.close[0]
        atr_value = self.atr[0]
        
        # Calculate stop loss (above liquidity grab)
        liquidity_zones_resistance = [zone for zone in self.liquidity_zones 
                                     if zone['type'] == 'resistance' and zone['swept']]
        if liquidity_zones_resistance:
            stop_loss = max(zone['price'] for zone in liquidity_zones_resistance) + (atr_value * self.params.atr_multiplier)
        else:
            stop_loss = current_price + (atr_value * self.params.atr_multiplier)
        
        # Calculate position size based on fixed risk
        risk_per_point = abs(stop_loss - current_price)
        if risk_per_point > 0:
            position_size = self.params.risk_per_trade / risk_per_point
        else:
            return
        
        # Calculate take profit (1:3 RR)
        take_profit = current_price - (abs(stop_loss - current_price) * self.params.target_rr)
        
        # Place order
        self.order = self.sell(size=position_size)
        self.entry_price = current_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.position_size = position_size
        self.trail_activated = False
        self.trades_today += 1
        
        self.log(f"SHORT ENTRY: Price={current_price:.2f}, Size={position_size:.2f}, "
                f"SL={stop_loss:.2f}, TP={take_profit:.2f}")
    
    def manage_position(self):
        """Manage existing position"""
        if not self.position:
            return
        
        current_price = self.data_15m.close[0]
        
        # Check for stop loss
        if self.position.size > 0:  # Long position
            if current_price <= self.stop_loss:
                self.close()
                self.log(f"STOP LOSS HIT: Price={current_price:.2f}")
                return
            
            # Check for take profit
            if current_price >= self.take_profit:
                self.close()
                self.log(f"TAKE PROFIT HIT: Price={current_price:.2f}")
                return
            
            # Trail stop after 2R
            if not self.trail_activated:
                profit = current_price - self.entry_price
                risk = self.entry_price - self.stop_loss
                if profit >= (risk * self.params.trail_after_rr):
                    self.stop_loss = self.entry_price  # Move to breakeven
                    self.trail_activated = True
                    self.log(f"TRAILING STOP ACTIVATED: Moved SL to breakeven at {self.stop_loss:.2f}")
        
        else:  # Short position
            if current_price >= self.stop_loss:
                self.close()
                self.log(f"STOP LOSS HIT: Price={current_price:.2f}")
                return
            
            # Check for take profit
            if current_price <= self.take_profit:
                self.close()
                self.log(f"TAKE PROFIT HIT: Price={current_price:.2f}")
                return
            
            # Trail stop after 2R
            if not self.trail_activated:
                profit = self.entry_price - current_price
                risk = self.stop_loss - self.entry_price
                if profit >= (risk * self.params.trail_after_rr):
                    self.stop_loss = self.entry_price  # Move to breakeven
                    self.trail_activated = True
                    self.log(f"TRAILING STOP ACTIVATED: Moved SL to breakeven at {self.stop_loss:.2f}")
        
        # Check for breaker block or order block rejection
        self.check_structure_rejection(current_price)
    
    def check_structure_rejection(self, current_price):
        """Check for rejection from breaker blocks or order blocks"""
        # Check breaker block rejection
        for bb in self.breaker_blocks:
            if bb['bottom'] <= current_price <= bb['top']:
                if self.position.size > 0 and bb['type'] == 'bearish':  # Long position hitting bearish breaker
                    self.close()
                    self.log(f"REJECTION FROM BEARISH BREAKER BLOCK: Price={current_price:.2f}")
                    return
                elif self.position.size < 0 and bb['type'] == 'bullish':  # Short position hitting bullish breaker
                    self.close()
                    self.log(f"REJECTION FROM BULLISH BREAKER BLOCK: Price={current_price:.2f}")
                    return
        
        # Check order block rejection
        for ob in self.order_blocks:
            if not ob['invalidated'] and ob['bottom'] <= current_price <= ob['top']:
                if self.position.size > 0 and ob['type'] == 'bearish':  # Long position hitting bearish OB
                    self.close()
                    self.log(f"REJECTION FROM BEARISH ORDER BLOCK: Price={current_price:.2f}")
                    return
                elif self.position.size < 0 and ob['type'] == 'bullish':  # Short position hitting bullish OB
                    self.close()
                    self.log(f"REJECTION FROM BULLISH ORDER BLOCK: Price={current_price:.2f}")
                    return
    
    def notify_order(self, order):
        """Track order status"""
        if order.status in [order.Submitted, order.Accepted]:
            return
        
        if order.status in [order.Completed]:
            if order.isbuy():
                self.log(f"BUY EXECUTED: Price={order.executed.price:.2f}, "
                        f"Size={order.executed.size:.2f}, Cost={order.executed.value:.2f}")
            else:
                self.log(f"SELL EXECUTED: Price={order.executed.price:.2f}, "
                        f"Size={order.executed.size:.2f}, Cost={order.executed.value:.2f}")
            
            self.total_trades += 1
            
        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            self.log(f"ORDER CANCELED/REJECTED: {order.status}")
        
        self.order = None
    
    def notify_trade(self, trade):
        """Track trade performance"""
        if not trade.isclosed:
            return
        
        pnl = trade.pnl
        self.total_pnl += pnl
        
        if pnl > 0:
            self.winning_trades += 1
        
        # Update drawdown tracking
        current_equity = self.broker.getvalue()
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
        else:
            drawdown = (self.peak_equity - current_equity) / self.peak_equity * 100
            if drawdown > self.max_drawdown:
                self.max_drawdown = drawdown
        
        self.log(f"TRADE CLOSED: PnL={pnl:.2f}, Total PnL={self.total_pnl:.2f}")
    
    def stop(self):
        """Print final performance statistics"""
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        avg_rr = self.total_pnl / self.total_trades if self.total_trades > 0 else 0
        
        self.log("="*50)
        self.log("FINAL PERFORMANCE STATISTICS")
        self.log("="*50)
        self.log(f"Total Trades: {self.total_trades}")
        self.log(f"Winning Trades: {self.winning_trades}")
        self.log(f"Win Rate: {win_rate:.2f}%")
        self.log(f"Total PnL: ${self.total_pnl:.2f}")
        self.log(f"Average PnL per Trade: ${avg_rr:.2f}")
        self.log(f"Max Drawdown: {self.max_drawdown:.2f}%")
        self.log(f"Final Portfolio Value: ${self.broker.getvalue():.2f}")
        self.log("="*50)


def run_backtest():
    """Run the backtest with sample data"""
    
    # Create Cerebro engine
    cerebro = bt.Cerebro()
    
    # Add strategy
    cerebro.addstrategy(SMCICTStrategy)
    
    # Set initial capital
    cerebro.broker.setcash(100000.0)
    
    # Set commission
    cerebro.broker.setcommission(commission=0.001)  # 0.1% commission
    
    # Note: You would need to add your data feeds here
    # Example:
    # data_15m = bt.feeds.PandasData(dataname=your_15m_dataframe)
    # data_daily = bt.feeds.PandasData(dataname=your_daily_dataframe)
    # cerebro.adddata(data_15m)
    # cerebro.adddata(data_daily)
    
    print("SMC/ICT Strategy ready for NAS100 15-minute timeframe")
    print("Add your data feeds and run cerebro.run() to start backtesting")
    
    # Uncomment to run when data is available
    # results = cerebro.run()
    # cerebro.plot()


if __name__ == '__main__':
    run_backtest()
