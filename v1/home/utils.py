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