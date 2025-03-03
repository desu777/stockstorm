# bnbgrid/views.py

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.http import HttpResponse

from decimal import Decimal
import csv
import json
from io import StringIO

from django.conf import settings

from .models import UserProfile, BnbBot, BnbTrade
from .authentication import CustomAuthentication



# -------------------------------------------------------
# 1) Rejestracja tokena usera (do weryfikacji z DRF)
# -------------------------------------------------------
@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """
    Endpoint do rejestrowania tokena użytkownika w mikroserwisie.
    Oczekuje nagłówka Authorization: Bearer <MICROSERVICE_API_TOKEN>
    """
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        return Response({'error': 'Missing Authorization header'}, status=401)

    expected_value = f"Bearer {settings.MICROSERVICE_API_TOKEN}"
    if auth_header != expected_value:
        return Response({'error': 'Invalid or missing microservice token'}, status=403)

    user_id = request.data.get('user_id')
    token = request.data.get('token')
    if not user_id or not token:
        return Response({'error': 'user_id and token are required'}, status=400)

    user_profile, created = UserProfile.objects.get_or_create(user_id=user_id)
    user_profile.auth_token = token
    user_profile.save()
    return Response({'status': 'Token saved successfully'})


def generate_levels(max_price, pct, capital, min_price=None, decimals=3):
    """
    Generuje SŁOWNIK zawierający TYLKO:
      - lv1, lv2, ... (właściwe ceny)
      - caps
      - sell_levels
    Nie zwraca flag i buy_price/buy_volume!
    """

    data = {
        "caps": {},
        "sell_levels": {}
    }

    max_p = float(max_price)
    pct_f = float(pct)

    levels = []
    i = 1
    while True:
        lv_price = max_p * (1 - (i - 1) * pct_f / 100.0)
        if lv_price <= 0:
            break
        if min_price and lv_price <= float(min_price):
            break
        if i > 50:
            break

        lv_price = round(lv_price, decimals)
        levels.append(lv_price)
        i += 1

    total_lv_count = len(levels)
    if total_lv_count == 0:
        return data

    portion_per_level = float(capital) / total_lv_count

    # Wypełniamy data (tylko część statyczną: lvX, caps, sell_levels)
    for idx, lv_price in enumerate(levels, start=1):
        lv_name = f"lv{idx}"
        data[lv_name] = lv_price
        data["caps"][lv_name] = round(portion_per_level, 2)

    for idx in range(2, total_lv_count + 1):
        buy_lv = f"lv{idx}"
        sell_lv = f"lv{idx - 1}"
        data["sell_levels"][buy_lv] = sell_lv

    return data


def init_runtime_data(level_names):
    """
    Tworzy słownik z `flags`, `buy_price`, `buy_volume` = 0.
    """
    rd = {
        "flags": {},
        "buy_price": {},
        "buy_volume": {}
    }
    for lv_name in level_names:
        rd["flags"][f"{lv_name}_bought"] = False
        rd["flags"][f"{lv_name}_sold"] = False
        rd["flags"][f"{lv_name}_in_progress"] = False
        rd["buy_price"][lv_name] = 0.0
        rd["buy_volume"][lv_name] = 0.0
    return rd



@api_view(['POST'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def create_bot(request):
    user_id = request.data.get("user_id")
    symbol = request.data.get("symbol", "BTCUSDT")
    max_price = float(request.data.get("max_price", 20000))
    percent = float(request.data.get("percent", 2))
    capital = float(request.data.get("capital", 1000))
    decimals = int(request.data.get("decimals", 2))
    binance_key = request.data.get("binance_api_key", "")
    binance_secret = request.data.get("binance_api_secret", "")

    bot = BnbBot.objects.create(
        user_id=user_id,
        name=request.data.get("name", "MyGridBot"),
        symbol=symbol,
        max_price=max_price,
        percent=percent,
        capital=capital,
        status='RUNNING',
        binance_api_key=binance_key
    )
    if binance_secret:
        bot.set_binance_api_secret(binance_secret)
        bot.save()

    # 1) Tylko statyczna konfiguracja:
    data = generate_levels(max_price, percent, capital, decimals=decimals)
    bot.save_levels_data(data)

    # 2) Inicjalizacja runtime:
    #    *level_names* to klucze lv1..lvN wygenerowane przez generate_levels
    level_names = [k for k in data.keys() if k.startswith("lv")]
    runtime = init_runtime_data(level_names)
    bot.save_runtime_data(runtime)

    bot.save()
    return Response({
        "bot_id": bot.id,
        "message": "Bot created successfully"
    })



# -------------------------------------------------------
# 4) Szczegóły bota
# -------------------------------------------------------
@api_view(['GET'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def get_bot_details(request, bot_id):
    bot = get_object_or_404(BnbBot, pk=bot_id, user_id=request.user.id)
    raw_data = bot.get_levels_data()

    # wczytaj FILLED transakcje
    trades = BnbTrade.objects.filter(bot=bot, status='FILLED')

    # Zbuduj obiekt levels
    levels = {}
    for k, v in raw_data.items():
        if k.startswith("lv"):
            levels[k] = {
                "price": float(v),
                "capital": float(raw_data.get("caps", {}).get(k, 0.0)),
                "tp": 0,
                "profit": 0.0,
            }

    total_profit = 0.0
    for lv_key, info in levels.items():
        sells = trades.filter(level=lv_key, side='SELL')
        tp_count = sells.count()
        lv_profit = sum(float(t.profit or 0) for t in sells)

        info["tp"] = tp_count
        info["profit"] = round(lv_profit, 2)
        total_profit += lv_profit

    resp = {
        "bot_id": bot.id,
        "status": bot.status,
        "symbol": bot.symbol,
        "levels": levels,
        "capital": float(bot.capital),
        "total_profit": round(total_profit, 2)
    }
    return Response(resp)


# -------------------------------------------------------
# 5) Usunięcie bota
# -------------------------------------------------------
@api_view(['POST'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def remove_bot(request, bot_id):
    """
    Usuwa bota z bazy – ale najpierw zatrzymuje go i rozłącza z Binance.
    """
    bot = get_object_or_404(BnbBot, pk=bot_id, user_id=request.user.id)

    bot.delete()

    return Response({"message": f"Bot {bot_id} removed."})

# -------------------------------------------------------
# 6) Status bota
# -------------------------------------------------------
@api_view(['GET'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def get_bot_status(request, bot_id):
    bot = get_object_or_404(BnbBot, pk=bot_id, user_id=request.user.id)
    return Response({
        "bot_id": bot.id,
        "status": bot.status,
        "symbol": bot.symbol
    })


# -------------------------------------------------------
# 7) Eksport transakcji do CSV
# -------------------------------------------------------
@api_view(['GET'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def export_bnb_trades_csv(request, bot_id):
    try:
        bot = BnbBot.objects.get(id=bot_id, user_id=request.user.id)
    except BnbBot.DoesNotExist:
        return Response({"error": "Bot not found or not owned by user"}, status=404)

    trades = BnbTrade.objects.filter(bot=bot).order_by('created_at')

    output = StringIO()
    writer = csv.writer(output, delimiter=';')

    # Definicja nagłówka CSV - pomijamy pola związane z id
    header = [
        "Level", 
        "Side",
        "Quantity",
        "Open Price",
        "Close Price",
        "Profit",
        "Binance Order Id",
        "Buy Type",
        "Sell Type",
        "Status",
        "Open Time",
        "Close Time"
    ]
    writer.writerow(header)

    for trade in trades:
        quantity = str(trade.quantity).replace('.', ',') if trade.quantity is not None else ""
        open_price = str(trade.open_price).replace('.', ',') if trade.open_price is not None else ""
        close_price = str(trade.close_price).replace('.', ',') if trade.close_price is not None else ""
        profit = str(trade.profit).replace('.', ',') if trade.profit is not None else ""
        
        binance_order_id = trade.binance_order_id or ""
        buy_type = trade.buy_type or ""
        sell_type = trade.sell_type or ""
        side = trade.side or ""

        open_time = trade.created_at.strftime("%Y-%m-%d %H:%M") if trade.created_at else ""
        # Jeżeli posiadasz pole 'filled_at' (np. jako moment zamknięcia transakcji)
        close_time = ""
        if hasattr(trade, 'filled_at') and trade.filled_at:
            close_time = trade.filled_at.strftime("%Y-%m-%d %H:%M")

        writer.writerow([
            trade.level,
            side,
            quantity,
            open_price,
            close_price,
            profit,
            binance_order_id,
            buy_type,
            sell_type,
            trade.status,
            open_time,
            close_time,
        ])

    response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="bot_{bot_id}_trades.csv"'
    return response

