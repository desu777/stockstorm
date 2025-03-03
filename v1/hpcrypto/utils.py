# hpcrypto/utils.py
from binance.client import Client
from binance.exceptions import BinanceAPIException
from django.core.cache import cache

def get_binance_price(user, ticker):
    """
    Fetch price from Binance for a given ticker.
    
    Args:
        user: The user object (to get API credentials)
        ticker: The ticker symbol (e.g., "BTC", "ETH")
        
    Returns:
        float: Current price or None if error
    """
    # Format ticker for Binance if needed
    if not ticker.endswith('USDT'):
        binance_ticker = f"{ticker}USDT"
    else:
        binance_ticker = ticker
    
    # Check cache first (5 second validity)
    cache_key = f"binance_price_{binance_ticker}"
    cached_price = cache.get(cache_key)
    if cached_price:
        return cached_price
    
    try:
        # Get user's Binance credentials
        profile = getattr(user, 'profile', None)
        if not profile or not profile.binance_api_key or not profile.binance_api_secret_enc:
            return None
        
        api_key = profile.binance_api_key
        api_secret = profile.get_binance_api_secret()
        
        # Create client and fetch price
        client = Client(api_key, api_secret)
        ticker_data = client.get_symbol_ticker(symbol=binance_ticker)
        price = float(ticker_data['price'])
        
        # Cache for 5 seconds to avoid rate limits
        cache.set(cache_key, price, 5)
        
        return price
        
    except BinanceAPIException as e:
        print(f"Binance API error for {ticker}: {e}")
        return None
    except Exception as e:
        print(f"Error fetching Binance price for {ticker}: {e}")
        return None