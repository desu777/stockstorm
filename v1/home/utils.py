import requests
from django.conf import settings

# utils.py

from django.contrib.auth.models import User
from rest_framework.authtoken.models import Token

def get_token(user_id):
    """
    Pobiera token mikroserwisu dla danego user_id.

    Args:
        user_id (int): ID użytkownika.

    Returns:
        str or None: Klucz tokena, jeśli istnieje, w przeciwnym razie None.
    """
    try:
        token = Token.objects.get(user_id=user_id)
        return token.key
    except Token.DoesNotExist:
        print(f"🔴 Token dla użytkownika z id={user_id} nie istnieje.")
        return None

# home/utils.py
from binance.client import Client
from binance.exceptions import BinanceAPIException

def test_binance_connection(api_key, api_secret):
    """Test Binance API connection with the provided credentials"""
    try:
        client = Client(api_key, api_secret)
        
        # Try a basic, non-intrusive API call
        status = client.get_system_status()
        if status['status'] == 0:
            # Also get account info to verify API key permissions
            try:
                account = client.get_account()
                return "Success! API connected and authenticated properly."
            except BinanceAPIException as e:
                if e.code == -2015:  # This code is for invalid API key/signature
                    return "API connected, but account access failed. Check API permissions."
                return f"API connected, but account access error: {e}"
        else:
            return f"Binance system is currently unavailable: {status['msg']}"
            
    except BinanceAPIException as e:
        return f"Binance API error (code {e.code}): {e.message}"
    except Exception as e:
        return f"Connection error: {str(e)}"