# d10/views.py

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.authentication import BaseAuthentication
from rest_framework.response import Response
from rest_framework.exceptions import AuthenticationFailed
from django.contrib.auth.models import AnonymousUser, User
from rest_framework.authentication import get_authorization_header
from django.http import HttpResponse, JsonResponse  # Dodaj JsonResponse
import json
import csv
from io import StringIO
from asgiref.sync import async_to_sync

from .models import UserProfile, BotD10, TradeD10
from .xtb_manager import xtb_manager, instrument_prices
from .d10_manager import (
    generate_levels,
    initial_buy_lv1,
    reapply_logic_once
)


class CustomAuthentication(BaseAuthentication):
    keyword = b"token"

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth:
            return None
        if auth[0].lower() != self.keyword:
            return None
        if len(auth) == 1:
            raise AuthenticationFailed("Invalid token header. No credentials provided.")
        elif len(auth) > 2:
            raise AuthenticationFailed("Invalid token header. Token string should not contain spaces.")

        try:
            token_key = auth[1].decode()
        except UnicodeError:
            raise AuthenticationFailed("Invalid token header. Token must be ASCII.")

        return self.authenticate_credentials(token_key)

    def authenticate_credentials(self, key):
        try:
            user_profile = UserProfile.objects.get(auth_token=key)
        except UserProfile.DoesNotExist:
            raise AuthenticationFailed("Invalid token")

        user_mock = User(
            id=user_profile.user_id,
            username=f"micro_{user_profile.user_id}",
            is_active=True,
            is_staff=True,
            is_superuser=True
        )
        user_mock.set_unusable_password()
        return (user_mock, None)


@api_view(['POST'])
@permission_classes([AllowAny])
def register_token(request):
    auth_header = request.headers.get('Authorization', '')
    if not auth_header:
        return Response({'error': 'Missing Authorization header'}, status=401)

    expected = f"Bearer {settings.MICROSERVICE_API_TOKEN}"
    if auth_header != expected:
        return Response({'error': 'Invalid or missing microservice token'}, status=403)

    user_id = request.data.get('user_id')
    token = request.data.get('token')
    if not user_id or not token:
        return Response({'error': 'user_id and token are required'}, status=400)

    user_profile, created = UserProfile.objects.get_or_create(user_id=user_id)
    user_profile.auth_token = token
    user_profile.save()

    return Response({'status': 'Token saved successfully'})


@api_view(['POST'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def create_bot(request):
    """
    Tworzy bota D10 w statusie NEW.
    Worker dopiero kupi lv1, gdy będzie cena.
    """
    data = request.data
    print("[DEBUG create_bot] request.data =>", data)

    if data.get('user_id') != request.user.id:
        return Response({"error": "user_id mismatch"}, status=403)

    bot = BotD10.objects.create(
        user_id=data['user_id'],
        name=data.get('name', 'NoName'),
        instrument=data.get('instrument', ''),
        band_percent=data.get('band_percent', 30),
        step_percent=data.get('step_percent', 5),
        rise_percent=data.get('rise_percent', 10),
        capital=data.get('capital', 0),
        account_currency=data.get('account_currency', 'USD'),
        asset_currency=data.get('asset_currency', 'USD'),
        xtb_id=data.get('xtb_id', ''),
        xtb_password=data.get('xtb_password', ''),
        status='NEW'
    )

    return Response({"bot_id": bot.id, "status": bot.status}, status=200)

from django.db.models import Sum

@api_view(['GET'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def get_bot_details(request, bot_id):
    try:
        bot = BotD10.objects.get(id=bot_id, user_id=request.user.id)
    except BotD10.DoesNotExist:
        return Response({"error": "Bot not found"}, status=404)
    
    # Parsowanie levels_data
    try:
        levels_data = json.loads(bot.levels_data)
    except (json.JSONDecodeError, TypeError):
        levels_data = {}
    
    levels = {}
    total_profit = 0.0
    lv_keys = [k for k in levels_data.keys() if k.startswith("lv")]
    number_of_levels = len(lv_keys)

    if number_of_levels == 0:
        return Response({
            "error": "No levels found for this bot.",
            "flags": levels_data.get("flags", {}),
            "levels": levels,
            "capital": float(bot.capital),
            "percent": bot.rise_percent,
            "total_profit": total_profit,
        }, status=400)
    
    for key in lv_keys:
        lv_number = key
        try:
            price = float(levels_data.get(key, {}).get("price", 0.0))
        except (ValueError, TypeError):
            price = 0.0
        
        flags = levels_data.get("flags", {})
        bought = flags.get(f"{lv_number}_bought", False)
        sold = flags.get(f"{lv_number}_sold", False)
        
        tp = bot.trades.filter(level_name=lv_number, status='CLOSED').count()
        profit_sum = bot.trades.filter(level_name=lv_number, status='CLOSED').aggregate(total=Sum('profit'))['total'] or 0.0
        profit_sum = float(profit_sum) 
        
        try:
            capital = float(levels_data.get("caps", {}).get(lv_number, levels_data.get(key, {}).get("capital", 0.0)))
        except (ValueError, TypeError):
            capital = 0.0
        
        levels[lv_number] = {
            "price": price,
            "capital": capital,
            "tp": tp,
            "profit": profit_sum,
            "bought": bought,
            "sold": sold
        }
        total_profit += profit_sum

    return Response({
        "flags": levels_data.get("flags", {}),
        "levels": levels,
        "capital": float(bot.capital),
        "percent": bot.rise_percent,
        "total_profit": total_profit,
    })





@api_view(['POST'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def remove_bot(request, bot_id):
    bot = get_object_or_404(BotD10, id=bot_id)
    if bot.user_id != request.user.id:
        return Response({"error": "No access"}, status=403)
    bot.delete()
    return Response({"status": "Bot removed"})


@api_view(['GET'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def export_d10_trades_csv(request, bot_id):
    bot = get_object_or_404(BotD10, id=bot_id)
    if bot.user_id != request.user.id:
        return Response({"error": "No access"}, status=403)

    trades = bot.trades.all().order_by('created_at')
    output = StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["Level", "OpenPrice", "ClosePrice", "Profit", "Status", "CreatedAt", "ClosedAt"])
    for t in trades:
        writer.writerow([
            t.level_name,
            str(t.open_price).replace('.', ','),
            str(t.close_price or '').replace('.', ','),
            str(t.profit or '').replace('.', ','),
            t.status,
            t.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            t.closed_at.strftime("%Y-%m-%d %H:%M:%S") if t.closed_at else ''
        ])
    response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="bot_{bot_id}_trades.csv"'
    return response


@api_view(['GET'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def check_d10_connection(request, bot_id):
    bot = get_object_or_404(BotD10, id=bot_id)
    if bot.user_id != request.user.id:
        return Response({"ok": False, "message": "No access"}, status=403)

    ok = async_to_sync(xtb_manager.connect_bot)(bot_id)
    if ok:
        return Response({"ok": True, "message": "Bot is connected with XTB"})
    else:
        return Response({"ok": False, "message": "Failed to connect to XTB"}, status=400)


@api_view(['GET'])
@authentication_classes([CustomAuthentication])
@permission_classes([IsAuthenticated])
def get_bot_status(request, bot_id):
    """
    Endpoint zwracający status bota D10
    (zamiana MicroserviceBot -> BotD10).
    """
    try:
        bot = get_object_or_404(BotD10, id=bot_id)
        print(f"[DEBUG get_bot_status] Bot znaleziony: {bot}")
        response_data = {
            "bot_id": bot.id,
            "status": bot.status,
            "name": bot.name,
            "instrument": bot.instrument,
        }
        print(f"[DEBUG get_bot_status] Odpowiedź JSON => {response_data}")
        return JsonResponse(response_data, status=200)
    except Exception as e:
        print(f"[DEBUG get_bot_status] Błąd => {str(e)}")
        return JsonResponse({"error": "Failed to retrieve bot status", "details": str(e)}, status=500)


