# api/views.py
from django.shortcuts import render
from rest_framework.decorators import api_view
from rest_framework.response import Response
from decimal import Decimal
import json
from django.db import transaction
from .models import MicroserviceBot
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import *
import json
from rest_framework.authtoken.models import Token
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import UserProfile
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth.models import AnonymousUser
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth.models import User
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth.models import AnonymousUser
from asgiref.sync import async_to_sync
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from api.models import MicroserviceBot

class CustomAuthentication(BaseAuthentication):
    """
    Ręcznie parsuje nagłówek:
        Authorization: Token <token_z_UserProfile>
    Tworzy 'tymczasowego' użytkownika typu django.contrib.auth.models.User.
    """

    keyword = b"token"  # Oczekujemy "Token <xxx>" (bez względu na wielkość liter)

    def authenticate(self, request):
        # Pobranie nagłówka Authorization
        auth = get_authorization_header(request).split()
        print(f"[AUTH] Otrzymany nagłówek Authorization: {auth}")

        # Sprawdzenie obecności nagłówka
        if not auth:
            print("[AUTH] Brak nagłówka Authorization.")
            return None  # brak nagłówka => brak autentykacji

        # Sprawdzenie prefixu "Token"
        if auth[0].lower() != self.keyword:
            print(f"[AUTH] Niepoprawny prefix. Oczekiwano: {self.keyword}, Otrzymano: {auth[0]}")
            return None  # prefix nie to "Token" => pomijamy

        # Sprawdzenie poprawności długości nagłówka
        if len(auth) == 1:
            print("[AUTH] Nie podano tokena. Nagłówek zawiera tylko prefix.")
            raise AuthenticationFailed("Invalid token header. No credentials provided.")
        elif len(auth) > 2:
            print("[AUTH] Token zawiera spacje. Nieprawidłowy format.")
            raise AuthenticationFailed("Invalid token header. Token string should not contain spaces.")

        try:
            token_key = auth[1].decode()
            print(f"[AUTH] Otrzymany token: {token_key}")
        except UnicodeError:
            print("[AUTH] Token zawiera niedozwolone znaki (nie ASCII).")
            raise AuthenticationFailed("Invalid token header. Token must be ASCII.")

        return self.authenticate_credentials(token_key)

    def authenticate_credentials(self, key):
        from .models import UserProfile  # Import lokalny, aby uniknąć błędów cyklicznych

        print(f"[AUTH] Sprawdzanie tokena w bazie danych: {key}")
        
        try:
            # Szukamy tokenu w UserProfile
            user_profile = UserProfile.objects.get(auth_token=key)
            print(f"[AUTH] Znaleziono użytkownika z user_id={user_profile.user_id}")
        except UserProfile.DoesNotExist:
            print("[AUTH] Nie znaleziono użytkownika z podanym tokenem.")
            raise AuthenticationFailed("Invalid token")

        # Tworzymy tymczasowy obiekt User z biblioteki Django
        user_mock = User(
            id=user_profile.user_id,
            username=f"micro_{user_profile.user_id}",
            is_active=True,
            is_staff=True,
            is_superuser=True
        )
        user_mock.set_unusable_password()

        print(f"[AUTH] Tymczasowy użytkownik: {user_mock.username}, ID: {user_mock.id}")

        return (user_mock, None)

class MicroserviceUser(AnonymousUser):
    """
    Dziedziczymy po AnonymousUser, ale nadpisujemy property
    tak, by faktycznie był traktowany przez DRF jako zalogowany.
    """

    def __init__(self, user_id):
        super().__init__()
        self.pk = user_id
        self.id = user_id
        # Dodatkowo ustawiamy flags – w niektórych przypadkach DRF
        # może sprawdzać is_active, is_staff itp.
        self.is_active = True
        self.is_staff = True
        self.is_superuser = True

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False




@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """
    Endpoint do rejestrowania tokena użytkownika w mikroserwisie.
    Oczekuje nagłówka Authorization: Bearer <MICROSERVICE_API_TOKEN>
    """
    # 1. Pobierz nagłówek Authorization
    auth_header = request.headers.get('Authorization')

    print("\n--- [register] START ---")
    print("[register] Received POST to /register")
    print("[register] Request HEADERS =>", dict(request.headers))
    print("[register] Request DATA =>", request.data)

    if not auth_header:
        print("[register] -> Brak nagłówka Authorization => 401\n")
        return Response({'error': 'Missing Authorization header'}, status=401)

    # 2. Sprawdź, czy nagłówek jest w formie "Bearer <token>"
    expected_value = f"Bearer {settings.MICROSERVICE_API_TOKEN}"
    print(f"[register] Auth header = {auth_header}")
    print(f"[register] Expected    = {expected_value}")

    if auth_header != expected_value:
        print("[register] -> Niepoprawny token => 403\n")
        return Response({'error': 'Invalid or missing microservice token'}, status=403)

    # 3. Gdy autoryzacja OK, przechodzimy do logiki rejestrującej
    user_id = request.data.get('user_id')
    token = request.data.get('token')

    if not user_id or not token:
        print("[register] -> user_id lub token nieobecny => 400\n")
        return Response({'error': 'user_id and token are required'}, status=400)

    user_profile, created = UserProfile.objects.get_or_create(user_id=user_id)
    user_profile.auth_token = token
    user_profile.save()

    print("[register] -> UserProfile", "utworzony" if created else "zaktualizowany", f"dla user_id={user_id}")
    print("[register] Zapisany token =", token)
    print("--- [register] KONIEC ---\n")

    return Response({'status': 'Token saved successfully'})

@api_view(['POST'])
@authentication_classes([CustomAuthentication])
def create_bot(request):
    user_id = request.data.get('user_id')
    name = request.data.get('name')
    instrument = request.data.get('instrument')
    min_price = request.data.get('min_price')
    max_price = request.data.get('max_price')
    percent = request.data.get('percent')
    capital = request.data.get('capital')
    account_currency = request.data.get('account_currency')
    asset_currency = request.data.get('asset_currency')

    xtb_id = request.data.get('xtb_id')
    xtb_password = request.data.get('xtb_password')

    levels = generate_levels(max_price, percent, capital)

    bot = MicroserviceBot.objects.create(
        user_id=user_id,
        name=name,
        instrument=instrument,
        max_price=max_price,
        percent=percent,
        capital=capital,
        account_currency=account_currency,
        asset_currency=asset_currency,
        status='RUNNING',
        levels_data=json.dumps(levels),
        xtb_login=xtb_id,
    )
    if xtb_password:
        bot.set_xtb_password(xtb_password)
        bot.save()

    return Response({
        "message": "Bot created successfully in microservice",
        "bot_id": bot.id,
        "levels": levels
    }, status=200)


# api/xtb_manager.py

def generate_levels(max_price, pct, capital):
    """
    Generates trading levels at fixed percentage intervals from the max_price,
    oraz przypisuje poziomy sprzedaży dla każdego poziomu zakupu.
    
    Args:
        max_price (float): The starting price for level 1 (highest price).
        pct (float): The fixed percentage decrease for each subsequent level.
        capital (float): The total capital allocated across all levels.
    
    Returns:
        dict: A dictionary containing flags, caps, buy_price, buy_volume, sell_levels, and level prices.
    """
    max_p = float(max_price)
    pct_f = float(pct)
    data = {
        "flags": {},
        "caps": {},
        "buy_price": {},
        "buy_volume": {},
        "sell_levels": {}
    }
    total_lv_count = 0
    i = 1

    # Calculate total number of levels until price approaches zero
    while True:
        lv_price = max_p * (1 - (i - 1) * pct_f / 100.0)
        if lv_price <= 0:
            break
        total_lv_count += 1
        i += 1

    # Generate levels in descending order (lv1 highest price, lv10 lowest)
    for level_num in range(1, total_lv_count + 1):
        lv_price = max_p * (1 - (level_num - 1) * pct_f / 100.0)
        lv_name = f"lv{level_num}"
        data[lv_name] = round(lv_price, 3)
        data["flags"][f"{lv_name}_bought"] = False
        data["flags"][f"{lv_name}_sold"] = False
        data["flags"][f"{lv_name}_in_progress"] = False
        data["caps"][lv_name] = round(float(capital) / total_lv_count, 2)
        data["buy_price"][lv_name] = 0.0
        data["buy_volume"][lv_name] = 0.0

    # Assign sell_levels: lv2 -> lv1, lv3 -> lv2, ..., lv10 -> lv9
    for level_num in range(2, total_lv_count + 1):
        lv_buy = f"lv{level_num}"
        lv_sell = f"lv{level_num - 1}"
        data["sell_levels"][lv_buy] = lv_sell
        print(f"[generate_levels] Created level {lv_buy} at price {data[lv_buy]}, sell_level={lv_sell}")

    return data



@api_view(['POST'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def remove_bot(request, bot_id):
    """
    Usuwa MicroserviceBot z bazy.
    (Bez zwalniania salda – to robisz w głównym projekcie, o ile chcesz.)
    """
    try:
        bot = MicroserviceBot.objects.get(id=bot_id)
    except MicroserviceBot.DoesNotExist:
        return Response({"error": "Bot not found"}, status=404)

    bot.delete()

    return Response({
        "message": f"Bot {bot_id} removed."
    }, status=200)

@api_view(['GET'])
def debug_bot_status(request, bot_id):
    """
    Przykładowy widok zwracający informacje o bocie
    """
    try:
        bot = MicroserviceBot.objects.get(id=bot_id)
    except MicroserviceBot.DoesNotExist:
        return Response({"error": "Bot not found"}, status=404)

    return Response({
        "bot_id": bot.id,
        "status": bot.status,
        "instrument": bot.instrument,
        # ewentualnie cokolwiek innego
    }, status=200)


###########
#aktualizacja session id po zmianie 
@api_view(['POST'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def sync_session_id(request):
    user_id = request.data.get('user_id')
    stream_session_id = request.data.get('stream_session_id')
    
    if not user_id or not stream_session_id:
        return Response({"error": "Missing user_id or stream_session_id"}, status=400)
    
    try:
        bot = MicroserviceBot.objects.get(user_id=user_id)
        if bot.stream_session_id != stream_session_id:
            bot.stream_session_id = stream_session_id
            bot.save()
            return Response({"message": "Session ID updated successfully"})
        return Response({"message": "Session ID already up-to-date"})
    except MicroserviceBot.DoesNotExist:
        return Response({"error": "Bot configuration not found for the user"}, status=404)



######################### POBIERANIE DANYCH BOTA
@api_view(['GET'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def get_bot_details(request, bot_id):
    try:
        bot = MicroserviceBot.objects.get(id=bot_id, user_id=request.user.id)
    except MicroserviceBot.DoesNotExist:
        return Response({"error": "Bot not found"}, status=404)
    
    try:
        levels_data = json.loads(bot.levels_data)
    except (json.JSONDecodeError, TypeError):
        levels_data = {}
    
    levels = {}
    total_profit = 0
    lv_keys = [k for k in levels_data.keys() if k.startswith("lv")]
    number_of_levels = len(lv_keys)

    if number_of_levels == 0:
        return Response({
            "error": "No levels found for this bot.",
            "flags": levels_data.get("flags", {}),
            "levels": levels,
            "capital": float(bot.capital),
            "percent": bot.percent,
            "total_profit": total_profit,
        }, status=400)
    
    for key in lv_keys:
        lv_number = key  # np. 'lv1'
        try:
            price = float(levels_data.get(key, 0.0))
        except (ValueError, TypeError):
            price = 0.0
        
        flags = levels_data.get("flags", {})
        bought = flags.get(f"{lv_number}_bought", False)
        sold = flags.get(f"{lv_number}_sold", False)
        
        try:
            tp = bot.get_tp_count(lv_number)
        except Exception as e:
            tp = 0
            print(f"Error in get_tp_count for bot_id={bot_id}, lv_number={lv_number}: {e}")
        
        try:
            profit = float(bot.get_profit(lv_number))
        except Exception as e:
            profit = 0.0
            print(f"Error in get_profit for bot_id={bot_id}, lv_number={lv_number}: {e}")
        
        capital = float(levels_data.get("caps", {}).get(lv_number, 0.0))  # Poprawne odwołanie do `caps`
        
        levels[lv_number] = {
            "price": price,
            "capital": capital,
            "tp": tp,
            "profit": profit,
            "bought": bought,
            "sold": sold
        }
        total_profit += profit

    return Response({
        "flags": levels_data.get("flags", {}),
        "levels": levels,
        "capital": float(bot.capital),
        "percent": bot.percent,
        "total_profit": total_profit,
    })


@api_view(['GET'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def get_bot_status(request, bot_id):
    """
    Endpoint zwracający status bota.
    """
    try:
        # Pobierz bota o podanym ID
        bot = get_object_or_404(MicroserviceBot, id=bot_id)
        print(f"[DEBUG] Bot znaleziony: {bot}")  # Debug
        print(f"[DEBUG] Status bota: {bot.status}")  # Debug
        response_data = {
            "bot_id": bot.id,
            "status": bot.status,  # Zwracamy status bota
            "name": bot.name,
            "instrument": bot.instrument,
        }
        print(f"[DEBUG] Odpowiedź JSON: {response_data}")  # Debug
        return JsonResponse(response_data, status=200)
    except Exception as e:
        print(f"[DEBUG] Wystąpił błąd: {str(e)}")  # Debug
        return JsonResponse({
            "error": "Failed to retrieve bot status",
            "details": str(e),
        }, status=500)



#################################
# Download trades in csv#
# api/views.py (Mikroserwis)
from django.http import HttpResponse
import csv
from io import StringIO

@api_view(['GET'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def export_bot_trades_csv(request, bot_id):
    """
    Zwraca transakcje (Trade) danego bota w formacie CSV,
    zastępując kropkę przecinkiem w cenach.
    """
    try:
        bot = MicroserviceBot.objects.get(id=bot_id, user_id=request.user.id)
    except MicroserviceBot.DoesNotExist:
        return Response({"error": "Bot not found or not owned by user"}, status=404)

    # Pobieramy transakcje
    trades = Trade.objects.filter(bot=bot).order_by('open_time')

    # Generujemy CSV w pamięci
    output = StringIO()
    writer = csv.writer(output, delimiter=';')  # np. średnik, by Excel łatwiej to łyknął

    # NAGŁÓWEK CSV
    writer.writerow([
        "Level", 
        "Open Price", 
        "Close Price", 
        "Profit", 
        "Open Time", 
        "Close Time", 
        "Status"
    ])

    for t in trades:
        # Zamiana kropki na przecinek w stringach:
        open_str = str(t.open_price).replace('.', ',') if t.open_price else ""
        close_str = str(t.close_price).replace('.', ',') if t.close_price else ""
        profit_str = str(t.profit).replace('.', ',') if t.profit else ""

        # Formatowanie dat
        open_time_str = t.open_time.strftime("%Y-%m-%d %H:%M") if t.open_time else ""
        close_time_str = t.close_time.strftime("%Y-%m-%d %H:%M") if t.close_time else ""

        writer.writerow([
            t.level,
            open_str,
            close_str,
            profit_str,
            open_time_str,
            close_time_str,
            t.status
        ])

    response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="bot_{bot_id}_trades.csv"'
    return response

###########################################################
#### Sprawdzenie połączenia z klientem xtb ###########
from .xtb_manager import xtb_manager  # <-- import managera

@api_view(['GET'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def check_xtb_connection(request, bot_id):
    """
    Sprawdza, czy bot ma aktualne połączenie (is_connected=True)
    w xtb_manager._connections. Jeśli nie, próbuje się połączyć,
    a w razie niepowodzenia zwraca błąd 400 i komunikat o 
    możliwości niepoprawnych danych logowania.
    """
    try:
        bot = MicroserviceBot.objects.get(id=bot_id, user_id=request.user.id)
    except MicroserviceBot.DoesNotExist:
        return Response({
            "ok": False, 
            "message": "Bot nie istnieje lub nie należy do usera."
        }, status=404)

    # Jeśli jeszcze nie ma obiektu w słowniku albo is_connected=False,
    # próbujemy go połączyć
    if bot_id not in xtb_manager._connections or not xtb_manager._connections[bot_id].is_connected:
        ok = async_to_sync(xtb_manager.connect_bot)(bot_id)
        if not ok:
            return Response({
                "ok": False,
                "message": "Nie udało się nawiązać połączenia z XTB. (Możliwe złe dane logowania)."
            }, status=400)

    # Skoro tu doszliśmy, to bot ma już is_connected == True
    return Response({
        "ok": True,
        "message": "Bot ma aktywne połączenie z XTB (is_connected)."
    }, status=200)