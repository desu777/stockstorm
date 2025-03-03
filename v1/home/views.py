# views.py

import logging
import requests
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import login
from django.contrib import messages 
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.views.decorators.http import require_GET
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from .forms import CustomUserCreationForm, XTBConnectionForm, BotForm, BinanceApiForm
from .models import XTBConnection, Bot
from .xtb_connection_manager import XTBConnectionManager
from .utils import get_token
from datetime import datetime, timezone, timedelta
from django.http import HttpResponse
import csv
from io import StringIO
from .models import UserProfile

logger = logging.getLogger(__name__)


def home(request):
    return render(request, 'home.html')


def login_view(request):
    return render(request, 'login.html')


def success_view(request):
    return render(request, 'success.html')


def forgot_password_view(request):
    """
    Obsługa odzyskiwania hasła (przykładowe).
    """
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        new_password = request.POST.get('new_password')

        try:
            user = User.objects.get(username=username, email=email)
            user.set_password(new_password)
            user.save()
            messages.success(request, 'Password successfully changed! Now log in.')
            return redirect('success')
        except User.DoesNotExist:
            messages.error(request, 'No user found with that username and email.')

    return render(request, 'forgot.html')


@login_required
def profile_view(request):
    # Get or create the user's profile
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    
    # Initialize forms
    xtb_form = XTBConnectionForm(instance=getattr(request.user, 'xtb_connection', None))
    binance_form = BinanceApiForm(instance=profile)
    
    binance_status = None  # Will store connection test result
    sms_test_result = None
    sms_test_success = False
    
    if request.method == 'POST':
        form_type = request.POST.get('form_type')
        
        if form_type == 'xtb_connection':
            # Handle the existing XTB connection form
            xtb_form = XTBConnectionForm(request.POST, instance=getattr(request.user, 'xtb_connection', None))
            if xtb_form.is_valid():
                connection = xtb_form.save(commit=False)
                connection.user = request.user
                connection.save()
                
                # Test XTB connection
                if connection.connect_to_xtb():
                    messages.success(request, "Successfully connected to XTB!")
                else:
                    messages.error(request, "Failed to connect to XTB. Check your credentials.")
                    
                return redirect('profile')
                
        elif form_type == 'binance_api':
            # Handle the Binance API form
            binance_form = BinanceApiForm(request.POST, instance=profile)
            if binance_form.is_valid():
                test_connection = request.POST.get('test_connection') == 'on'
                
                if test_connection:
                    # Test the Binance connection
                    api_key = binance_form.cleaned_data['binance_api_key']
                    api_secret = request.POST.get('binance_api_secret')
                    
                    # If no new secret provided but we have one stored, use the stored one
                    if not api_secret and profile.binance_api_secret_enc:
                        api_secret = profile.get_binance_api_secret()
                    
                    # Only test if we have both key and secret
                    if api_key and api_secret:
                        binance_status = test_binance_connection(api_key, api_secret)
                        
                        if "Success" not in binance_status:
                            # Show error but don't save invalid credentials
                            messages.error(request, f"Binance connection failed: {binance_status}")
                            return render(request, 'profile.html', {
                                'xtb_form': xtb_form,
                                'binance_form': binance_form,
                                'binance_status': binance_status,
                                'session_id': getattr(getattr(request.user, 'xtb_connection', None), 'stream_session_id', None)
                            })
                
                # Save the form (only saves key, secret is handled separately)
                profile = binance_form.save()
                messages.success(request, "Binance API settings saved successfully!")
                return redirect('profile')
                
        elif form_type == 'sms_settings':
            # Handle SMS settings form
            binance_form = BinanceApiForm(request.POST, instance=profile)
            if binance_form.is_valid():
                profile = binance_form.save()
                messages.success(request, "SMS notification settings saved successfully!")
                return redirect('profile')
                
        elif form_type == 'test_sms':
            # Send a test SMS
            from hpcrypto.twilio_utils import send_sms_notification
            if profile.phone_number and profile.sms_alerts_enabled:
                success, result = send_sms_notification(
                    profile.phone_number,
                    "This is a test message from STOCKstorm. Your SMS alerts are configured correctly!"
                )
                sms_test_success = success
                if success:
                    sms_test_result = "Test SMS sent successfully!"
                else:
                    sms_test_result = f"Failed to send test SMS: {result}"
            else:
                sms_test_result = "SMS alerts are not properly configured. Please save your phone number and enable SMS alerts."
                sms_test_success = False
    
    # Get XTB session_id for display
    session_id = getattr(getattr(request.user, 'xtb_connection', None), 'stream_session_id', None)
    
    return render(request, 'profile.html', {
        'xtb_form': xtb_form,
        'binance_form': binance_form,
        'binance_status': binance_status,
        'session_id': session_id,
        'sms_test_result': sms_test_result,
        'sms_test_success': sms_test_success
    })


@login_required
def history_view(request):
    """
    Przykładowa historia transakcji XTB.
    """
    manager = XTBConnectionManager()
    trade_history = []

    xtb_connection = XTBConnection.objects.filter(user=request.user, is_live=True).first()
    if not xtb_connection:
        messages.error(request, "Brak aktywnego połączenia z XTB API.")
        return redirect('profile')

    if not manager.connect(xtb_connection=xtb_connection):
        messages.error(request, "Nie udało się połączyć z XTB API.")
        return redirect('profile')

    response = manager.send_command(request.user.id, "getTradesHistory", {"start": 0, "end": 100})
    if response and response.get("status"):
        trade_history = response.get("returnData", [])

    return render(request, 'history.html', {
        'history': trade_history,
        'is_live': manager.connections.get(request.user.id, {}).get('is_connected', False)
    })


def register_view(request):
    """
    Rejestracja użytkownika w głównym serwisie,
    wysyłanie tokenów do mikroserwisów XTB i BNB.
    """
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)

        # Sprawdzenie REGISTER_KEY
        register_key = request.POST.get('register_key')
        if register_key != settings.REGISTER_KEY:
            messages.error(request, 'Niepoprawny klucz rejestracyjny.')
            return render(request, 'register.html', {'form': form})

        if form.is_valid():
            # 1) Tworzymy użytkownika
            user = form.save()

            # 2) Generujemy token
            token, created = Token.objects.get_or_create(user=user)

            # 3) Wysyłanie tokena do mikroserwisów
            microservices = [
                {
                    'name': 'XTB',
                    'url': f"{settings.MICROSERVICE_URL2}/register_token/",
                    'headers': {
                        'Authorization': f'Bearer {settings.MICROSERVICE_API_TOKEN}',
                        'Content-Type': 'application/json',
                    },
                },
                {
                    'name': 'BNB',
                    'url': f"{settings.BNB_MICROSERVICE_URL}/register_token/",
                    'headers': {
                        'Authorization': f'Bearer {settings.MICROSERVICE_API_TOKEN}',
                        'Content-Type': 'application/json',
                    },
                },
                {
                    'name': 'D510',
                    'url': f"{settings.XTB_D}/register_token/",
                    'headers': {
                        'Authorization': f'Bearer {settings.MICROSERVICE_API_TOKEN}',
                        'Content-Type': 'application/json',
                    },
                }
            ]

            for service in microservices:
                try:
                    payload = {
                        'user_id': user.id,
                        'token': token.key
                    }
                    response = requests.post(
                        service['url'],
                        json=payload,
                        headers=service['headers'],
                        timeout=5
                    )
                    if response.status_code == 200:
                        messages.success(request, f"Token wysłany do mikroserwisu {service['name']}.")
                    else:
                        messages.warning(
                            request,
                            f"Rejestracja OK, ale mikroserwis {service['name']} zwrócił "
                            f"{response.status_code}: {response.text}"
                        )
                except Exception as e:
                    messages.error(request, f"Błąd łączenia z mikroserwisem {service['name']}: {e}")

            # 4) Sukces
            messages.success(request, 'Możesz się już zalogować!')
            return redirect('login')
        else:
            messages.error(request, 'Spróbuj jeszcze raz! Formularz niepoprawny.')
    else:
        form = CustomUserCreationForm()

    return render(request, 'register.html', {'form': form})


@login_required
def dashboard_view(request):
    """
    Prosty widok 'dashboard' np. do XTB (otwarte pozycje, pending orders itd.)
    """
    manager = XTBConnectionManager()
    open_trades = []
    pending_orders = []
    recent_trades = []

    xtb_connection = XTBConnection.objects.filter(user=request.user, is_live=True).first()
 

    response = manager.send_command(request.user.id, "getTrades", {"openedOnly": True})
    if response and response.get("status"):
        trades = response.get("returnData", [])
        for trade in trades:
            if trade['cmd'] in [0, 1]:
                open_trades.append(trade)
            elif trade['cmd'] in [2, 3, 4, 5]:
                pending_orders.append(trade)

    closed_response = manager.send_command(request.user.id, "getTradesHistory", {"start": 0, "end": 3})
    if closed_response and closed_response.get("status"):
        recent_trades = closed_response.get("returnData", [])

    return render(request, 'dashboard.html', {
        'is_live': manager.connections.get(request.user.id, {}).get('is_connected', False),
        'open_trades': open_trades,
        'pending_orders': pending_orders,
        'recent_trades': recent_trades,
    })


@login_required
def get_balance_data(request):
    """
    Przykład pobrania stanu konta XTB (marginLevel).
    """
    manager = XTBConnectionManager()
    xtb_connection = XTBConnection.objects.filter(user=request.user, is_live=True).first()
    if not xtb_connection:
        return JsonResponse({"error": "No active XTB connection."}, status=400)

    if not manager.connect(xtb_connection=xtb_connection):
        return JsonResponse({"error": "Failed to connect to XTB API."}, status=400)

    response = manager.send_command(request.user.id, "getMarginLevel")
    if response and response.get("status"):
        returnData = response.get("returnData", {})
        return JsonResponse({
            "balance": returnData.get("balance"),
            "equity": returnData.get("equity"),
            "margin": returnData.get("margin"),
            "margin_free": returnData.get("margin_free"),
            "margin_level": returnData.get("margin_level"),
            "currency": returnData.get("currency"),
        })
    else:
        return JsonResponse({"error": "Failed to get margin level."}, status=400)


@login_required
@require_GET
def get_instrument_price(request):
    """
    Przykład pobierania ceny z XTB (getSymbol).
    """
    manager = XTBConnectionManager()
    symbol = request.GET.get('symbol', '').strip()
    if not symbol:
        return JsonResponse({"error": "Parameter 'symbol' is required."}, status=400)

    xtb_connection = XTBConnection.objects.filter(user=request.user, is_live=True).first()
    if not xtb_connection:
        return JsonResponse({"error": "No active XTB connection."}, status=400)

    if not manager.connect(xtb_connection=xtb_connection):
        return JsonResponse({"error": "Failed to connect to XTB API."}, status=400)

    response = manager.send_command(request.user.id, "getSymbol", {"symbol": symbol})
    if response and response.get("status"):
        data = response.get("returnData", {})
        return JsonResponse({"ask": data.get("ask"), "bid": data.get("bid")})
    else:
        return JsonResponse({"error": "Failed to fetch instrument price."}, status=400)


@login_required
def search_instruments(request):
    """
    Przykład wyszukiwania instrumentów w XTB (getAllSymbols).
    """
    manager = XTBConnectionManager()
    query = request.GET.get('q', '').upper()
    matches = []

    xtb_connection = XTBConnection.objects.filter(user=request.user, is_live=True).first()
    if not xtb_connection:
        return JsonResponse({"error": "No active XTB connection."}, status=400)

    if not manager.connect(xtb_connection=xtb_connection):
        return JsonResponse({"error": "Failed to connect to XTB API."}, status=400)

    response = manager.send_command(request.user.id, "getAllSymbols")
    if response and response.get("status"):
        all_symbols = response.get("returnData", [])
        matches = [s for s in all_symbols if query in s.get('symbol', '').upper()]

    return JsonResponse(matches[:10], safe=False)


@login_required
def show_symbols_view(request):
    """
    Przykład wypisania wszystkich symboli z XTB (getAllSymbols).
    """
    manager = XTBConnectionManager()
    selected_data = []

    xtb_connection = XTBConnection.objects.filter(user=request.user, is_live=True).first()
    if not xtb_connection:
        return JsonResponse({"error": "No active XTB connection."}, status=400)

    if not manager.connect(xtb_connection=xtb_connection):
        return JsonResponse({"error": "Failed to connect to XTB API."}, status=400)

    response = manager.send_command(request.user.id, "getAllSymbols")
    if response and response.get("status"):
        all_symbols = response.get("returnData", [])
        for sym_info in all_symbols:
            selected_data.append({
                "symbol": sym_info.get('symbol'),
                "currency": sym_info.get('currency'),
                "categoryName": sym_info.get('categoryName'),
                "description": sym_info.get('description'),
                "leverage": sym_info.get('leverage'),
            })

    return JsonResponse(selected_data, safe=False)


def get_stock_market_status():
    """
    Przykład statusu giełdowego (otwarte/zamknięte).
    """
    now = datetime.now(timezone.utc)
    day_of_week = now.weekday()

    stock_markets = [
        {
            'name': 'NASDAQ',
            'open_time': now.replace(hour=14, minute=30, second=0, microsecond=0),
            'close_time': now.replace(hour=21, minute=0, second=0, microsecond=0),
        },
        {
            'name': 'GPW',
            'open_time': now.replace(hour=7, minute=30, second=0, microsecond=0),
            'close_time': now.replace(hour=15, minute=30, second=0, microsecond=0),
        },
        {
            'name': 'NYSE',
            'open_time': now.replace(hour=14, minute=30, second=0, microsecond=0),
            'close_time': now.replace(hour=21, minute=0, second=0, microsecond=0),
        },
        {
            'name': 'LSE',
            'open_time': now.replace(hour=8, minute=0, second=0, microsecond=0),
            'close_time': now.replace(hour=16, minute=30, second=0, microsecond=0),
        },
        {
            'name': 'JPX',
            'open_time': now.replace(hour=0, minute=0, second=0, microsecond=0),
            'close_time': now.replace(hour=6, minute=0, second=0, microsecond=0),
        }
    ]

    for market in stock_markets:
        if day_of_week in [5, 6]:  
            days_until_monday = (7 - day_of_week) % 7
            monday_open_time = (now + timedelta(days=days_until_monday)).replace(
                hour=market['open_time'].hour,
                minute=market['open_time'].minute,
                second=0,
                microsecond=0
            )
            delta = monday_open_time - now
            market['status'] = 'CLOSED (Weekend)'
            market['css_class'] = 'status-weekend'
            market['time_to_open'] = str(delta).split(".")[0]
        elif market['open_time'] <= now <= market['close_time']:
            market['status'] = 'LIVE'
            market['css_class'] = 'status-live'
            market['time_to_open'] = '-'
        else:
            if now < market['open_time']:
                delta = market['open_time'] - now
            else:
                delta = (market['open_time'] + timedelta(days=1)) - now
            market['status'] = 'Closed'
            market['css_class'] = 'status-closed'
            market['time_to_open'] = str(delta).split(".")[0]

    return stock_markets


@login_required
def dashboard(request):
    stock_markets = get_stock_market_status()
    # Przykładowo pobierz 3 aktywne boty użytkownika (dowolnego typu)
    active_bots = Bot.objects.filter(user=request.user, status='RUNNING')[:3]
    
    context = {
        'history': [],
        'documents': [],
        'stocks': stock_markets,
        'active_bots': active_bots,
    }
    return render(request, 'dashboard.html', context)


def api_stock_status(request):
    stock_markets = get_stock_market_status()
    return JsonResponse(stock_markets, safe=False)


#######################################################################
#                          GŁÓWNY WIDOK LISTY BOTÓW                  #
#######################################################################
@login_required
def bot_list(request):
    """
    Pokazuje listę wszystkich botów zalogowanego użytkownika, które są BNB.
    """
    user_bots = Bot.objects.filter(user=request.user, broker_type='XTB').order_by('-created_at')
    return render(request, 'bot_list.html', {'bots': user_bots})

#######################################################################
#              PODSTAWOWE WIDOKI do OBSŁUGI XTB (EXAMPLE)             #
#######################################################################
@login_required
def bot_add(request):
    """
    Tworzenie bota XTB (przykładowo).
    Ustaw broker_type='XTB'.
    """
    if request.method == 'POST':
        name = request.POST.get('name')
        instrument = request.POST.get('instrument')
        max_price = request.POST.get('max_price')
        percent = request.POST.get('percent')
        capital = request.POST.get('capital')
        account_currency = request.POST.get('account_currency')  # nowa linijka
        asset_currency = request.POST.get('asset_currency')      # nowa linijka
        xtb_id = request.POST.get('xtb_id')
        xtb_password = request.POST.get('xtb_password')

        new_bot = Bot.objects.create(
            user=request.user,
            broker_type='XTB',  # WAŻNE: oznaczamy jako XTB
            name=name,
            instrument=instrument,
            max_price=max_price,
            percent=percent,
            capital=capital,
            status='NEW'
        )
        microservice_token = get_token(request.user.id)
        if not microservice_token:
            new_bot.status = 'ERROR'
            new_bot.save()
            messages.error(request, 'Brak tokena mikroserwisu. Nie udało się utworzyć bota.')
            return redirect('bot_list')

        headers = {'Authorization': f'Token {microservice_token}'}
        payload = {
            'user_id': request.user.id,
            'name': name,
            'instrument': instrument,
            'max_price': max_price,
            'percent': percent,
            'capital': capital,
            'account_currency': account_currency,
            'asset_currency': asset_currency,
            'xtb_id': xtb_id,
            'xtb_password': xtb_password,
        }

        try:
            resp = requests.post(f"{settings.MICROSERVICE_URL2}/create_bot/", json=payload, headers=headers, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                new_bot.microservice_bot_id = data.get("bot_id")
                new_bot.status = 'RUNNING'
                new_bot.save()
                messages.success(request, "Bot został utworzony i uruchomiony w mikroserwisie!")
            else:
                new_bot.status = 'ERROR'
                new_bot.save()
                messages.error(request, f"Błąd mikroserwisu: {resp.text}")
        except Exception as e:
            new_bot.status = 'ERROR'
            new_bot.save()
            messages.error(request, f"Błąd: {str(e)}")

        return redirect('bot_list')

    return render(request, 'bot_add.html')


@login_required
def bot_detail(request, bot_id):
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)
    
    # Endpoint mikroserwisu do pobierania danych bota
    api_endpoint = f"{settings.MICROSERVICE_URL2}/get_bot_details/{bot.microservice_bot_id}/"
    
    # Pobierz dynamiczny token
    microservice_token = get_token(request.user.id)
    if not microservice_token:
        messages.error(request, "Brak tokena mikroserwisu. Nie udało się pobrać szczegółów bota.")
        return redirect('bot_list')

    headers = {
        'Authorization': f'Token {microservice_token}',
    }
    
    try:
        response = requests.get(api_endpoint, headers=headers, timeout=5)
        response.raise_for_status()
        bot_details = response.json()
        
        # Aktualizacja lokalnego statusu bota na podstawie mikroserwisu
        microservice_status = bot_details.get('status')
        if microservice_status and bot.status != microservice_status:
            bot.status = microservice_status
            bot.save()
            print(f"[UPDATE] Bot {bot.id} status updated to {microservice_status}")
    except requests.RequestException as e:
        bot_details = None
        messages.error(request, "Nie udało się pobrać szczegółów bota z mikroserwisu.")
    
    # Przekazanie danych do szablonu
    return render(request, 'bot_detail.html', {
        'bot': bot,
        'bot_details': bot_details,
    })


@login_required
def bot_remove(request, bot_id):
    """
    Usunięcie bota XTB w mikroserwisie XTB.
    """
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)
    if bot.broker_type != 'XTB':
        messages.error(request, "Ten widok dotyczy bota XTB, a bot jest BNB.")
        return redirect('bot_list')
    if request.method == 'POST':
        # Sprawdź, czy `bot.microservice_bot_id` jest ustawione poprawnie
        if not bot.microservice_bot_id or bot.microservice_bot_id == 'None':
            # Jeśli microservice_bot_id jest puste lub None, usuwamy lokalnie
            bot.delete()
            messages.success(request, "Bot usunięty lokalnie (brak identyfikatora w mikroserwisie).")
            return redirect('bot_list')

        microservice_remove_url = f"{settings.MICROSERVICE_URL2}/remove_bot/{bot.microservice_bot_id}/"

        # Pobierz dynamiczny token zamiast używać ustawień
        microservice_token = get_token(request.user.id)
        if not microservice_token:
            # Jeśli brak tokena, usuwamy lokalnie
            bot.delete()
            messages.warning(request, "Bot usunięty lokalnie. Brak tokena mikroserwisu.")
            return redirect('bot_list')

        headers = {
            'Authorization': f'Token {microservice_token}',
            'Content-Type': 'application/json'
        }
        payload = {
            'user_id': request.user.id,
        }

        try:
            resp = requests.post(microservice_remove_url, json=payload, headers=headers, timeout=5)
            if resp.status_code == 200:
                # Mikroserwis potwierdził usunięcie -> usuwamy bota lokalnie
                bot.delete()
                messages.success(request, "Bot usunięty w mikroserwisie i lokalnie.")
            else:
                # Jeśli mikroserwis zwróci błąd, usuwamy lokalnie
                bot.delete()
                messages.warning(request, f"Bot usunięty lokalnie. Błąd mikroserwisu: {resp.status_code} {resp.text}")
        except Exception as e:
            # Obsługa wyjątków (np. mikroserwis niedostępny)
            bot.delete()
            messages.warning(request, f"Bot usunięty lokalnie z powodu błędu mikroserwisu: {str(e)}")

        return redirect('bot_list')

    return render(request, 'bot_confirm_delete.html', {'bot': bot})



#######################################################################
#           NOWE WIDOKI BNB: bnb_create, bnb_detail, bnb_delete       #
#######################################################################
@login_required
def bnb_create(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        symbol = request.POST.get('symbol')
        max_price = request.POST.get('max_price')
        percent = request.POST.get('percent')
        capital = request.POST.get('capital')

        # Parametr decimals
        decimals = request.POST.get('decimals', '2')

        # Pola do Binance
        binance_api_key = request.POST.get('binance_api_key', '')
        binance_api_secret = request.POST.get('binance_api_secret', '')

        local_bot = Bot.objects.create(
            user=request.user,
            broker_type='BNB',
            name=name,
            instrument=symbol,
            max_price=max_price,
            percent=percent,
            capital=capital,
            status='NEW'
        )

        microservice_token = get_token(request.user.id)
        if not microservice_token:
            local_bot.status = 'ERROR'
            local_bot.save()
            messages.error(request, "Brak tokena mikroserwisu BNB.")
            return redirect('bot_list')

        headers = {
            'Authorization': f'Token {microservice_token}',
            'Content-Type': 'application/json'
        }

        # Upewnij się, że wszystkie klucze w payload mają takie nazwy,
        # jakie czyta mikroserwis w create_bot
        payload = {
            'user_id': request.user.id,
            'name': name,
            'symbol': symbol,
            'max_price': max_price,
            'percent': percent,
            'capital': capital,
            'decimals': decimals,                # <-- pass 'decimals'
            'binance_api_key': binance_api_key,
            'binance_api_secret': binance_api_secret,  # <-- ZMIANA: używamy 'binance_api_secret' zamiast 'binance_api_secret_enc'
        }

        try:
            resp = requests.post(
                f"{settings.BNB_MICROSERVICE_URL}/create_bot/",
                json=payload,
                headers=headers,
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                local_bot.microservice_bot_id = data.get("bot_id")
                local_bot.status = "RUNNING"
                local_bot.save()
                messages.success(request, "Bot utworzony w bnbbot1 i uruchomiony!")
            else:
                local_bot.status = "ERROR"
                local_bot.save()
                messages.error(request, f"Błąd bnbbot1: {resp.status_code} {resp.text}")
        except Exception as e:
            local_bot.status = "ERROR"
            local_bot.save()
            messages.error(request, f"Wyjątek przy łączeniu z bnbbot1: {str(e)}")

        return redirect('bnb_list')

    return render(request, 'bnb_create.html')


@login_required
def bnb_detail(request, bot_id):
    """
    Szczegóły bota BNB – łączymy się z bnbbot1 (broker_type='BNB').
    """
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)
    if bot.broker_type != 'BNB':
        messages.error(request, "Ten widok dotyczy bota BNB, a bot jest XTB.")
        return redirect('bot_list')

    if not bot.microservice_bot_id:
        messages.error(request, "Ten bot nie ma przypisanego ID w bnbbot1.")
        return redirect('bot_list')

    microservice_token = get_token(request.user.id)
    if not microservice_token:
        messages.error(request, "Brak tokena mikroserwisu do pobrania detali bota BNB.")
        return redirect('bot_list')

    headers = {'Authorization': f'Token {microservice_token}'}
    url = f"{settings.BNB_MICROSERVICE_URL}/get_bot_details/{bot.microservice_bot_id}/"

    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            bot_details = resp.json()
            ms_status = bot_details.get("status")
            if ms_status and bot.status != ms_status:
                bot.status = ms_status
                bot.save()
        else:
            bot_details = None
            messages.error(request, f"Błąd bnbbot1: {resp.status_code} {resp.text}")
    except Exception as e:
        bot_details = None
        messages.error(request, f"Wyjątek przy łączeniu z bnbbot1: {str(e)}")

    return render(request, 'bnb_detail.html', {
        'bot': bot,
        'bot_details': bot_details,
    })


@login_required
def bnb_delete(request, bot_id):
    """
    Usuwa bota w bnbbot1 i lokalnie (jeśli microservice_bot_id jest ustawione).
    """
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)
    if bot.broker_type != 'BNB':
        messages.error(request, "Ten widok dotyczy bota BNB, a bot jest XTB.")
        return redirect('bnb_list')

    if request.method == 'POST':
        if not bot.microservice_bot_id:
            bot.delete()
            messages.success(request, "Bot (BNB) usunięty lokalnie (bez microservice_bot_id).")
            return redirect('bnb_list')

        microservice_token = get_token(request.user.id)
        if not microservice_token:
            bot.delete()
            messages.warning(request, "Brak tokena do bnbbot1 – usunięty lokalnie.")
            return redirect('bnb_list')

        headers = {
            'Authorization': f'Token {microservice_token}',
            'Content-Type': 'application/json'
        }
        payload = {"user_id": request.user.id}
        try:
            url = f"{settings.BNB_MICROSERVICE_URL}/remove_bot/{bot.microservice_bot_id}/"
            resp = requests.post(url, json=payload, headers=headers, timeout=5)
            if resp.status_code == 200:
                bot.delete()
                messages.success(request, "Bot usunięty w bnbbot1 i lokalnie.")
            else:
                bot.delete()
                messages.warning(request, f"Błąd bnbbot1: {resp.status_code} {resp.text}, bot usunięty lokalnie.")
        except Exception as e:
            bot.delete()
            messages.warning(request, f"Wyjątek usuwania w bnbbot1: {str(e)} – bot usunięty lokalnie.")

        return redirect('bnb_list')

    return render(request, 'bnb_delete_confirm.html', {'bot': bot})


@login_required
def bnb_status(request, bot_id):
    """
    Pobieranie statusu bota (BNB) w JSON, aktualizacja w modelu.
    """
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)
    if bot.broker_type != 'BNB':
        return JsonResponse({"error": "Bot is not BNB type."}, status=400)

    if not bot.microservice_bot_id:
        return JsonResponse({"error": "Bot has no bnb microservice ID"}, status=400)

    microservice_token = get_token(request.user.id)
    if not microservice_token:
        return JsonResponse({"error": "No microservice token available."}, status=400)

    headers = {'Authorization': f'Token {microservice_token}'}
    url = f"{settings.BNB_MICROSERVICE_URL}/get_bot_details/{bot.microservice_bot_id}/"

    try:
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        ms_status = data.get("status", "UNKNOWN")
        if ms_status and bot.status != ms_status:
            bot.status = ms_status
            bot.save()
        return JsonResponse({"status": bot.status})
    except requests.RequestException as e:
        logger.error(f"Błąd podczas pobierania statusu bnb bot {bot_id}: {e}")
        return JsonResponse({"error": f"Request error: {e}"}, status=500)


@login_required
def bnb_list(request):
    """
    Pokazuje listę wszystkich botów zalogowanego użytkownika, które są BNB.
    """
    user_bots = Bot.objects.filter(user=request.user, broker_type='BNB').order_by('-created_at')
    return render(request, 'bnb_list.html', {'bots': user_bots})

@login_required
def export_bnb_trades(request, bot_id):
    """
    Proxy do pobrania CSV z transakcjami bota z mikroserwisu
    i przesłania go użytkownikowi.
    """
    # Szukamy bota w głównym serwisie:
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)

    # Musimy mieć ID bota w mikroserwisie:
    if not bot.microservice_bot_id:
        messages.error(request, "Bot nie ma przypisanego ID w mikroserwisie – brak możliwości eksportu.")
        return redirect('bnb_detail', bot_id=bot_id)

    # Pobranie tokena z bazy:
    microservice_token = get_token(request.user.id)  # Twoja funkcja, która zwraca token
    if not microservice_token:
        messages.error(request, "Brak tokena mikroserwisu – nie można pobrać CSV.")
        return redirect('bnb_detail', bot_id=bot_id)

    # Budujemy URL do mikroserwisu:
    url = f"{settings.BNB_MICROSERVICE_URL}/export_bnb_trades_csv/{bot.microservice_bot_id}/"

    # Ustawiamy nagłówek autoryzacji:
    headers = {
        "Authorization": f"Token {microservice_token}"
    }

    try:
        # Odpytujemy mikroserwis, używając stream=True, by pobierać dane kawałkami
        r = requests.get(url, headers=headers, stream=True, timeout=10)

        if r.status_code == 200:
            # Przygotowujemy własną odpowiedź HTTP
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="bot_{bot_id}_trades.csv"'

            # Przepuszczamy strumień do odpowiedzi
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    response.write(chunk)
            return response
        else:
            # Mikroserwis nie zwrócił 200 => błąd
            messages.error(request, f"Błąd mikroserwisu podczas generowania CSV: {r.status_code} {r.text}")
            return redirect('bnb_detail', bot_id=bot_id)
    except requests.RequestException as e:
        messages.error(request, f"Nie można pobrać CSV z mikroserwisu: {str(e)}")
        return redirect('bnb_detail', bot_id=bot_id)




########################################################################
#           PRZYKŁAD UŻYCIA PROXY get_bot_details_proxy itp.           #
########################################################################


@login_required
def get_bot_status(request, bot_id):
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)

    if bot.broker_type == 'XTB':
        base_url = settings.MICROSERVICE_URL2
    elif bot.broker_type == 'BNB':
        base_url = settings.BNB_MICROSERVICE_URL
    elif bot.broker_type == 'D10':
        base_url = settings.XTB_D
    else:
        return JsonResponse({"error": "Unknown broker type."}, status=400)

    if not bot.microservice_bot_id:
        return JsonResponse({"error": "Bot has no microservice ID."}, status=400)

    microservice_token = get_token(request.user.id)
    if not microservice_token:
        return JsonResponse({"error": "No microservice token."}, status=400)

    headers = {'Authorization': f'Token {microservice_token}'}
    url = f"{base_url}/get_bot_details/{bot.microservice_bot_id}/"

    try:
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        details = resp.json()
        ms_status = details.get("status")
        if ms_status and bot.status != ms_status:
            bot.status = ms_status
            bot.save()
        return JsonResponse({"status": bot.status})
    except requests.RequestException as e:
        logger.error(f"Błąd pobierania statusu bota {bot_id}: {e}")
        return JsonResponse({"error": "Nie udało się pobrać statusu."}, status=500)

###################################################
#### Pobieranie trejdów botów xtb do csv####

@login_required
def export_bot_trades(request, bot_id):
    """
    Proxy do pobrania CSV z transakcjami bota z mikroserwisu
    i przesłania go użytkownikowi.
    """
    # Szukamy bota w głównym serwisie:
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)

    # Musimy mieć ID bota w mikroserwisie:
    if not bot.microservice_bot_id:
        messages.error(request, "Bot nie ma przypisanego ID w mikroserwisie – brak możliwości eksportu.")
        return redirect('bot_detail', bot_id=bot_id)

    # Pobranie tokena z bazy:
    microservice_token = get_token(request.user.id)  # Twoja funkcja, która zwraca token
    if not microservice_token:
        messages.error(request, "Brak tokena mikroserwisu – nie można pobrać CSV.")
        return redirect('bot_detail', bot_id=bot_id)

    # Budujemy URL do mikroserwisu:
    url = f"{settings.MICROSERVICE_URL2}/export_bot_trades_csv/{bot.microservice_bot_id}/"

    # Ustawiamy nagłówek autoryzacji:
    headers = {
        "Authorization": f"Token {microservice_token}"
    }

    try:
        # Odpytujemy mikroserwis, używając stream=True, by pobierać dane kawałkami
        r = requests.get(url, headers=headers, stream=True, timeout=10)

        if r.status_code == 200:
            # Przygotowujemy własną odpowiedź HTTP
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="bot_{bot_id}_trades.csv"'

            # Przepuszczamy strumień do odpowiedzi
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    response.write(chunk)
            return response
        else:
            # Mikroserwis nie zwrócił 200 => błąd
            messages.error(request, f"Błąd mikroserwisu podczas generowania CSV: {r.status_code} {r.text}")
            return redirect('bot_detail', bot_id=bot_id)
    except requests.RequestException as e:
        messages.error(request, f"Nie można pobrać CSV z mikroserwisu: {str(e)}")
        return redirect('bot_detail', bot_id=bot_id)



##################################################
#### sprawdzenie połączenia bota xtb z klientem xtb ####

@login_required
def check_broker_connection(request, bot_id):
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)

    if not bot.microservice_bot_id:
        return JsonResponse({
            "ok": False,
            "message": "Bot nie ma ID w mikroserwisie."
        }, status=400)

    microservice_token = get_token(request.user.id)
    if not microservice_token:
        return JsonResponse({
            "ok": False,
            "message": "Brak tokena mikroserwisu."
        }, status=400)

    # Wołanie mikroserwisu:
    url = f"{settings.MICROSERVICE_URL2}/check_xtb_connection/{bot.microservice_bot_id}/"
    headers = {
        "Authorization": f"Token {microservice_token}"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        resp_json = resp.json()
        if resp.status_code == 200:
            return JsonResponse({"ok": True, "message": resp_json.get("message")}, status=200)
        else:
            return JsonResponse({"ok": False, "message": resp_json.get("message")}, status=400)
    except Exception as e:
        return JsonResponse({"ok": False, "message": str(e)}, status=400)


#######################################################################
#                          GŁÓWNY WIDOK D510              #
#######################################################################
@login_required
def d10_list(request):
    """
    Pokazuje listę wszystkich botów zalogowanego użytkownika, które są BNB.
    """
    user_bots = Bot.objects.filter(user=request.user, broker_type='D10').order_by('-created_at')
    return render(request, 'd10_list.html', {'bots': user_bots})

#######################################################################
#              PODSTAWOWE WIDOKI do OBSŁUGI D510            #
#######################################################################
@login_required
def d10_add(request):
    """
    Tworzenie bota D10.
    W formularzu pobieramy band_percent, step_percent, rise_percent.
    """
    if request.method == 'POST':
        # 1) Odczyt pól z formularza
        print("[DEBUG d10_add] POST DATA =>", request.POST.dict())
        
        name = request.POST.get('name')
        instrument = request.POST.get('instrument')

        band_percent = request.POST.get('band_percent')
        step_percent = request.POST.get('step_percent')
        rise_percent = request.POST.get('rise_percent')

        capital = request.POST.get('capital')
        account_currency = request.POST.get('account_currency')
        asset_currency = request.POST.get('asset_currency')

        xtb_id = request.POST.get('xtb_id')
        xtb_password = request.POST.get('xtb_password')

        # 2) Tworzymy lokalnie
        new_bot = Bot.objects.create(
            user=request.user,
            broker_type='D10',
            name=name,
            instrument=instrument,
            max_price=band_percent,  # ewentualnie zmień w modelu
            percent=step_percent,
            capital=capital,
            status='NEW'
        )
        print(f"[DEBUG d10_add] Lokalny Bot utworzony => ID={new_bot.id}")

        # 3) Pobieramy token
        microservice_token = get_token(request.user.id)
        if not microservice_token:
            new_bot.status = 'ERROR'
            new_bot.save()
            messages.error(request, 'Brak tokena mikroserwisu.')
            return redirect('d10_list')

        headers = {'Authorization': f'Token {microservice_token}'}
        payload = {
            'user_id': request.user.id,
            'name': name,
            'instrument': instrument,
            'band_percent': band_percent,
            'step_percent': step_percent,
            'rise_percent': rise_percent,
            'capital': capital,
            'account_currency': account_currency,
            'asset_currency': asset_currency,
            'xtb_id': xtb_id,
            'xtb_password': xtb_password,
        }
        print("[DEBUG d10_add] Payload do mikroserwisu =>", payload)

        try:
            resp = requests.post(
                f"{settings.XTB_D}/create_bot/",
                json=payload,
                headers=headers,
                timeout=10
            )
            print(f"[DEBUG d10_add] Odpowiedź mikroserwisu => status={resp.status_code}, text={resp.text}")

            if resp.status_code == 200:
                data = resp.json()
                new_bot.microservice_bot_id = data.get("bot_id")
                new_bot.status = 'RUNNING'
                new_bot.save()
                messages.success(request, "Bot został utworzony i uruchomiony w mikroserwisie!")
            else:
                new_bot.status = 'ERROR'
                new_bot.save()
                messages.error(request, f"Błąd mikroserwisu: {resp.text}")
        except Exception as e:
            new_bot.status = 'ERROR'
            new_bot.save()
            print("[DEBUG d10_add] Exception =>", e)
            messages.error(request, f"Błąd: {str(e)}")

        return redirect('d10_list')

    return render(request, 'd10_add.html')




@login_required
def d10_detail(request, bot_id):
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)
    
    api_endpoint = f"{settings.XTB_D}/get_bot_details/{bot.microservice_bot_id}/"
    
    microservice_token = get_token(request.user.id)
    if not microservice_token:
        messages.error(request, "Brak tokena mikroserwisu. Nie udało się pobrać szczegółów bota.")
        return redirect('d10_list')

    headers = {'Authorization': f"Token {microservice_token}"}
    try:
        response = requests.get(api_endpoint, headers=headers, timeout=5)
        response.raise_for_status()
        bot_details = response.json()

        # Ustaw lokalny status na podstawie mikroserwisu
        microservice_status = bot_details.get('status')
        if microservice_status and bot.status != microservice_status:
            bot.status = microservice_status
            bot.save()
    except requests.RequestException:
        bot_details = None
        messages.error(request, "Nie udało się pobrać szczegółów bota z mikroserwisu.")
    
    return render(request, 'd10_detail.html', {
        'bot': bot,
        'd10_details': bot_details,
    })



@login_required
def d10_remove(request, bot_id):
    """
    Usunięcie bota D10 w mikroserwisie.
    """
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)
    if bot.broker_type != 'D10':
        messages.error(request, "Ten widok dotyczy bota D10, a bot jest innego typu.")
        return redirect('d10_list')

    if request.method == 'POST':
        if not bot.microservice_bot_id:
            bot.delete()
            messages.success(request, "Bot usunięty lokalnie (brak microservice_bot_id).")
            return redirect('d10_list')

        microservice_remove_url = f"{settings.XTB_D}/remove_bot/{bot.microservice_bot_id}/"
        microservice_token = get_token(request.user.id)
        if not microservice_token:
            bot.delete()
            messages.warning(request, "Bot usunięty lokalnie. Brak tokena mikroserwisu.")
            return redirect('d10_list')

        headers = {
            'Authorization': f"Token {microservice_token}",
            'Content-Type': 'application/json'
        }
        payload = {'user_id': request.user.id}

        try:
            resp = requests.post(microservice_remove_url, json=payload, headers=headers, timeout=5)
            if resp.status_code == 200:
                bot.delete()
                messages.success(request, "Bot usunięty w mikroserwisie i lokalnie.")
            else:
                bot.delete()
                messages.warning(request, f"Bot usunięty lokalnie. Mikroserwis: {resp.status_code} {resp.text}")
        except Exception as e:
            bot.delete()
            messages.warning(request, f"Bot usunięty lokalnie z powodu błędu mikroserwisu: {str(e)}")

        return redirect('d10_list')

    return render(request, 'd10_confirm_delete.html', {'bot': bot})

@login_required
def export_d10_trades(request, bot_id):
    """
    Proxy do pobrania CSV z transakcjami bota z mikroserwisu D10.
    """
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)

    if not bot.microservice_bot_id:
        messages.error(request, "Bot nie ma microservice_bot_id – nie można eksportować CSV.")
        return redirect('d10_detail', bot_id=bot_id)

    microservice_token = get_token(request.user.id)
    if not microservice_token:
        messages.error(request, "Brak tokena mikroserwisu – nie można pobrać CSV.")
        return redirect('d10_detail', bot_id=bot_id)

    url = f"{settings.XTB_D}/export_d10_trades_csv/{bot.microservice_bot_id}/"
    headers = {"Authorization": f"Token {microservice_token}"}

    try:
        r = requests.get(url, headers=headers, stream=True, timeout=10)
        if r.status_code == 200:
            response = HttpResponse(content_type='text/csv; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="bot_{bot_id}_trades.csv"'
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    response.write(chunk)
            return response
        else:
            messages.error(
                request,
                f"Błąd mikroserwisu przy generowaniu CSV: {r.status_code} {r.text}"
            )
            return redirect('d10_detail', bot_id=bot_id)
    except requests.RequestException as e:
        messages.error(request, f"Nie można pobrać CSV: {str(e)}")
        return redirect('d10_detail', bot_id=bot_id)

@login_required
def check_d10_connection(request, bot_id):
    """
    Sprawdza w mikroserwisie, czy bot D10 ma aktywne połączenie z XTB.
    """
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)

    if not bot.microservice_bot_id:
        return JsonResponse({
            "ok": False,
            "message": "Bot nie ma ID w mikroserwisie."
        }, status=400)

    microservice_token = get_token(request.user.id)
    if not microservice_token:
        return JsonResponse({
            "ok": False,
            "message": "Brak tokena mikroserwisu."
        }, status=400)

    url = f"{settings.XTB_D}/check_d10_connection/{bot.microservice_bot_id}/"
    headers = {"Authorization": f"Token {microservice_token}"}

    try:
        resp = requests.get(url, headers=headers, timeout=5)
        data = resp.json()
        if resp.status_code == 200:
            return JsonResponse({"ok": True, "message": data.get("message")}, status=200)
        else:
            return JsonResponse({"ok": False, "message": data.get("message")}, status=400)
    except Exception as e:
        return JsonResponse({"ok": False, "message": str(e)}, status=400)




#################################
####### PROXY ###########
@login_required
@require_GET
def get_bot_details_proxy(request, bot_id):
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)

    if bot.broker_type == 'XTB':
        base_url = settings.MICROSERVICE_URL2
    elif bot.broker_type == 'BNB':
        base_url = settings.BNB_MICROSERVICE_URL
    elif bot.broker_type == 'D10':
        base_url = settings.XTB_D  # <-- TUTAJ! Musi wskazywać na mikroserwis D10
    else:
        return JsonResponse({"error": "Broker type unknown"}, status=400)

    if not bot.microservice_bot_id:
        return JsonResponse({"error": "Bot has no microservice_bot_id."}, status=400)

    microservice_token = get_token(request.user.id)
    if not microservice_token:
        return JsonResponse({"error": "No microservice token."}, status=400)

    headers = {'Authorization': f'Token {microservice_token}'}
    url = f"{base_url}/get_bot_details/{bot.microservice_bot_id}/"

    try:
        resp = requests.get(url, headers=headers, timeout=5)
        resp.raise_for_status()
        bot_details = resp.json()
        return JsonResponse(bot_details)
    except requests.HTTPError as http_err:
        logger.error(f"HTTP error for bot_id={bot_id}: {http_err}")
        return JsonResponse({"error": "Błąd HTTP przy pobieraniu detali z mikroserwisu."}, status=500)
    except requests.RequestException as req_err:
        logger.error(f"Request exception for bot_id={bot_id}: {req_err}")
        return JsonResponse({"error": "Nie udało się pobrać danych z mikroserwisu."}, status=500)
    except ValueError as json_err:
        logger.error(f"JSON decode error for bot_id={bot_id}: {json_err}")
        return JsonResponse({"error": "Błąd dekodowania danych z mikroserwisu."}, status=500)
