"""
Asset Strength Matrix - Backend API Server v3.0
Twelve Data (800 calls/day) + CoinGecko (unlimited)
Daily refresh at 8am EST
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from datetime import datetime, timedelta
import os
import time
import pytz

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})
# Configuration
TWELVE_DATA_API_KEY = os.getenv('TWELVE_DATA_API_KEY', 'YOUR_API_KEY_HERE')
TWELVE_DATA_URL = 'https://api.twelvedata.com'
COINGECKO_URL = 'https://api.coingecko.com/api/v3'

# Cache with daily 8am EST expiration
cache = {}
DAILY_REFRESH_HOUR = 8  # 8am EST
EST = pytz.timezone('US/Eastern')

# CoinGecko symbol mapping
CRYPTO_MAP = {
    'BTC': 'bitcoin',
    'BTC-USD': 'bitcoin',
    'BITCOIN': 'bitcoin',
    'ETH': 'ethereum',
    'ETH-USD': 'ethereum',
    'ETHEREUM': 'ethereum',
    'SOL': 'solana',
    'SOLANA': 'solana',
    'ADA': 'cardano',
    'CARDANO': 'cardano',
    'XRP': 'ripple',
    'RIPPLE': 'ripple',
    'DOT': 'polkadot',
    'POLKADOT': 'polkadot',
    'DOGE': 'dogecoin',
    'DOGECOIN': 'dogecoin',
    'MATIC': 'matic-network',
    'POLYGON': 'matic-network',
    'LINK': 'chainlink',
    'CHAINLINK': 'chainlink',
    'UNI': 'uniswap',
    'UNISWAP': 'uniswap',
    'AVAX': 'avalanche-2',
    'AVALANCHE': 'avalanche-2',
    'HYPE': 'hyperliquid',
}

# Symbol mapping for commodities
SYMBOL_MAP = {
    'GOLD': 'GLD',
    'SILVER': 'SLV',
    'OIL': 'USO',
    'SPX': 'SPY',
}


def get_next_8am_est():
    """Calculate seconds until next 8am EST"""
    now_est = datetime.now(EST)
    today_8am = now_est.replace(hour=DAILY_REFRESH_HOUR, minute=0, second=0, microsecond=0)
    
    if now_est >= today_8am:
        next_8am = today_8am + timedelta(days=1)
    else:
        next_8am = today_8am
    
    seconds_until = (next_8am - now_est).total_seconds()
    return int(seconds_until)


def get_last_8am_est():
    """Get the most recent 8am EST timestamp"""
    now_est = datetime.now(EST)
    today_8am = now_est.replace(hour=DAILY_REFRESH_HOUR, minute=0, second=0, microsecond=0)
    
    if now_est >= today_8am:
        return today_8am
    else:
        return today_8am - timedelta(days=1)


def is_crypto(symbol):
    """Check if symbol is a cryptocurrency"""
    symbol_upper = symbol.upper().replace('-USD', '').replace('/USD', '')
    return symbol_upper in CRYPTO_MAP


def get_coingecko_id(symbol):
    """Get CoinGecko ID for a symbol"""
    symbol_upper = symbol.upper().replace('-USD', '').replace('/USD', '')
    return CRYPTO_MAP.get(symbol_upper, symbol.lower())


def map_symbol(symbol):
    """Map display symbol to API symbol"""
    return SYMBOL_MAP.get(symbol.upper(), symbol.upper())


def get_cached_or_fetch(cache_key, fetch_function):
    """Cache implementation with daily 8am expiration"""
    current_time = time.time()
    seconds_until_8am = get_next_8am_est()
    
    if cache_key in cache:
        data, timestamp, expires_at = cache[cache_key]
        if current_time < expires_at:
            hours_left = int((expires_at - current_time) / 3600)
            print(f"Cache hit for {cache_key} (expires in {hours_left}h)")
            return data
    
    # Fetch fresh data
    print(f"Fetching fresh data for {cache_key}")
    data = fetch_function()
    
    # Cache until next 8am EST
    expires_at = current_time + seconds_until_8am
    cache[cache_key] = (data, current_time, expires_at)
    
    return data


def fetch_crypto_data(symbol, ma_period=20):
    """Fetch cryptocurrency data from CoinGecko (unlimited free tier)"""
    coin_id = get_coingecko_id(symbol)
    
    try:
        days = ma_period * 7 + 30
        url = f"{COINGECKO_URL}/coins/{coin_id}/market_chart"
        params = {
            'vs_currency': 'usd',
            'days': days,
            'interval': 'daily'
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'prices' not in data:
            raise ValueError(f"No price data available for {symbol}")
        
        prices = data['prices']
        weekly_prices = []
        
        # Convert daily to weekly
        for i in range(0, len(prices), 7):
            week_data = prices[i:i+7]
            if week_data:
                weekly_prices.append(week_data[-1][1])
        
        print(f"✓ CoinGecko: Fetched {len(weekly_prices)} weeks for {symbol}")
        return weekly_prices
        
    except requests.exceptions.RequestException as e:
        print(f"✗ CoinGecko error for {symbol}: {str(e)}")
        raise ValueError(f"CoinGecko API request failed: {str(e)}")


def fetch_twelve_data(symbol, ma_period=20):
    """Fetch stock/ETF data from Twelve Data (800 calls/day free tier)"""
    mapped_symbol = map_symbol(symbol)
    
    try:
        # Twelve Data time series endpoint
        url = f"{TWELVE_DATA_URL}/time_series"
        params = {
            'symbol': mapped_symbol,
            'interval': '1week',
            'outputsize': ma_period + 10,
            'apikey': TWELVE_DATA_API_KEY
        }
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        # Check for errors
        if 'status' in data and data['status'] == 'error':
            error_msg = data.get('message', 'Unknown error')
            print(f"✗ Twelve Data error for {symbol}: {error_msg}")
            raise ValueError(f"Twelve Data error: {error_msg}")
        
        if 'values' not in data:
            print(f"✗ Twelve Data: No values for {symbol}. Response: {data}")
            raise ValueError(f"No data available for {symbol}")
        
        values = data['values']
        
        if not values or len(values) == 0:
            raise ValueError(f"Empty data for {symbol}")
        
        # Extract closing prices (most recent first)
        closing_prices = [float(item['close']) for item in values]
        
        print(f"✓ Twelve Data: Fetched {len(closing_prices)} weeks for {symbol}")
        
        return closing_prices
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Twelve Data request error for {symbol}: {str(e)}")
        raise ValueError(f"Twelve Data API request failed: {str(e)}")
    except (KeyError, ValueError) as e:
        print(f"✗ Twelve Data parse error for {symbol}: {str(e)}")
        raise ValueError(f"Error processing {symbol}: {str(e)}")


def calculate_sma(prices, period):
    """Calculate Simple Moving Average"""
    if len(prices) < period:
        return None
    return sum(prices[:period]) / period


def get_asset_data(symbol, ma_period=20):
    """Get asset data with SMA calculation"""
    cache_key = f"{symbol}_{ma_period}"
    original_symbol = symbol
    
    def fetch():
        if is_crypto(symbol):
            print(f"→ {symbol} detected as CRYPTO (using CoinGecko)")
            closing_prices = fetch_crypto_data(symbol, ma_period)
            source = "CoinGecko"
        else:
            print(f"→ {symbol} detected as STOCK/ETF (using Twelve Data)")
            closing_prices = fetch_twelve_data(symbol, ma_period)
            source = "Twelve Data"
        
        sma = calculate_sma(closing_prices, ma_period)
        
        if sma is None:
            raise ValueError(f"Insufficient data for {ma_period}-week SMA")
        
        current_price = closing_prices[0]
        is_above_ma = current_price > sma
        percent_from_ma = ((current_price - sma) / sma) * 100
        
        price_change = 0
        if len(closing_prices) > 1:
            price_change = ((closing_prices[0] - closing_prices[1]) / closing_prices[1]) * 100
        
        return {
            'symbol': original_symbol,
            'currentPrice': round(current_price, 2),
            'ma': round(sma, 2),
            'isAboveMA': is_above_ma,
            'percentFromMA': round(percent_from_ma, 2),
            'priceChange': round(price_change, 2),
            'dataPoints': len(closing_prices),
            'source': source,
            'lastUpdated': get_last_8am_est().isoformat()
        }
    
    return get_cached_or_fetch(cache_key, fetch)


def calculate_relative_strength(asset1_data, asset2_data):
    """Calculate relative strength between two assets"""
    ratio = asset1_data['currentPrice'] / asset2_data['currentPrice']
    ma_ratio = asset1_data['ma'] / asset2_data['ma']
    
    is_above_ma = ratio > ma_ratio
    strength = ((ratio - ma_ratio) / ma_ratio) * 100
    
    return {
        'isAboveMA': is_above_ma,
        'strength': round(strength, 2),
        'ratio': round(ratio, 6)
    }


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    now_est = datetime.now(EST)
    last_8am = get_last_8am_est()
    next_8am = last_8am + timedelta(days=1)
    
    return jsonify({
        'status': 'healthy',
        'timestamp': now_est.isoformat(),
        'cache_size': len(cache),
        'last_update': last_8am.strftime('%Y-%m-%d %I:%M %p EST'),
        'next_update': next_8am.strftime('%Y-%m-%d %I:%M %p EST'),
        'seconds_until_refresh': get_next_8am_est(),
        'apis': {
            'twelve_data': 'Configured ✓' if TWELVE_DATA_API_KEY != 'YOUR_API_KEY_HERE' else 'NOT CONFIGURED ✗',
            'coingecko': 'Enabled (no key required)'
        }
    })


@app.route('/api/asset/<symbol>', methods=['GET'])
def get_asset(symbol):
    """Get data for a single asset"""
    try:
        ma_period = int(request.args.get('ma_period', 20))
        data = get_asset_data(symbol, ma_period)
        return jsonify(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'Internal error: {str(e)}'}), 500


@app.route('/api/assets', methods=['POST'])
def get_multiple_assets():
    """Get data for multiple assets"""
    try:
        data = request.get_json()
        symbols = data.get('symbols', [])
        ma_period = data.get('ma_period', 20)
        
        results = {}
        errors = {}
        
        for symbol in symbols:
            try:
                results[symbol] = get_asset_data(symbol, ma_period)
                # Twelve Data free tier: 8 calls/minute
                time.sleep(3.0)
            except Exception as e:
                errors[symbol] = str(e)
        
        last_8am = get_last_8am_est()
        
        response = {
            'data': results,
            'errors': errors if errors else None,
            'lastUpdate': last_8am.strftime('%Y-%m-%d %I:%M %p EST'),
            'nextUpdate': (last_8am + timedelta(days=1)).strftime('%Y-%m-%d %I:%M %p EST'),
            'timestamp': datetime.now(EST).isoformat()
        }
        
        return jsonify(response)
    
    except Exception as e:
        return jsonify({'error': f'Internal error: {str(e)}'}), 500


@app.route('/api/matrix', methods=['POST'])
def get_strength_matrix():
    """Get full relative strength matrix"""
    try:
        data = request.get_json()
        symbols = data.get('symbols', [])
        ma_period = data.get('ma_period', 20)
        
        asset_data = {}
        for symbol in symbols:
            try:
                asset_data[symbol] = get_asset_data(symbol, ma_period)
                time.sleep(3.0)
            except Exception as e:
                print(f"Error fetching {symbol}: {e}")
        
        matrix = {}
        for base_asset in symbols:
            if base_asset not in asset_data:
                continue
            
            matrix[base_asset] = {}
            for quote_asset in symbols:
                if quote_asset not in asset_data or base_asset == quote_asset:
                    continue
                
                strength = calculate_relative_strength(
                    asset_data[base_asset],
                    asset_data[quote_asset]
                )
                matrix[base_asset][quote_asset] = strength
        
        last_8am = get_last_8am_est()
        
        response = {
            'assets': asset_data,
            'matrix': matrix,
            'lastUpdate': last_8am.strftime('%Y-%m-%d %I:%M %p EST'),
            'nextUpdate': (last_8am + timedelta(days=1)).strftime('%Y-%m-%d %I:%M %p EST'),
            'timestamp': datetime.now(EST).isoformat()
        }
        
        return jsonify(response)
    
    except Exception as e:
        return jsonify({'error': f'Internal error: {str(e)}'}), 500


@app.route('/api/clear-cache', methods=['POST'])
def clear_cache():
    """Clear the cache"""
    cache.clear()
    return jsonify({'message': 'Cache cleared', 'timestamp': datetime.now(EST).isoformat()})


if __name__ == '__main__':
    print("=" * 70)
    print("Asset Strength Matrix - Backend API v3.0")
    print("Twelve Data (800 calls/day) + CoinGecko (unlimited)")
    print("Daily Refresh at 8:00 AM EST")
    print("=" * 70)
    print(f"Twelve Data: {'Configured ✓' if TWELVE_DATA_API_KEY != 'YOUR_API_KEY_HERE' else 'NOT CONFIGURED ✗'}")
    print(f"CoinGecko: Enabled (no key required)")
    
    now_est = datetime.now(EST)
    last_8am = get_last_8am_est()
    next_8am = last_8am + timedelta(days=1)
    
    print(f"\nCurrent time: {now_est.strftime('%I:%M %p EST')}")
    print(f"Last update: {last_8am.strftime('%I:%M %p EST')}")
    print(f"Next update: {next_8am.strftime('%I:%M %p EST')}")
    print(f"Cache expires in: {get_next_8am_est()//3600}h {(get_next_8am_est()%3600)//60}m")
    
    print("\nAPI Limits:")
    print("  Twelve Data: 800 calls/day, 8 calls/minute (FREE)")
    print("  CoinGecko: Unlimited (FREE)")
    print("  Rate limiting: 8 second delay between requests")
    
    print("\nEndpoints:")
    print("  GET  /api/health")
    print("  GET  /api/asset/<symbol>?ma_period=20")
    print("  POST /api/assets")
    print("  POST /api/matrix")
    print("  POST /api/clear-cache")
    print("=" * 70)
    print("\n🚀 Starting server...")
    print("📍 Access your API at: http://localhost:5000")
    print("⚠️  Keep this window open while using the dashboard")
    print("\n")
    
    app.run(debug=True, host='0.0.0.0', port=5000)
