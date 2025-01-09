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
from .forms import CustomUserCreationForm, XTBConnectionForm, BotForm
from .models import XTBConnection, Bot
from .xtb_connection_manager import XTBConnectionManager
from .utils import get_token
from datetime import datetime, timezone, timedelta 

logger = logging.getLogger(__name__)

# Create your views here.

def home(request):
    return render(request, 'home.html')

def login_view(request):
    return render(request, 'login.html')  

def success_view(request):
    return render(request, 'success.html')

def forgot_password_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        new_password = request.POST.get('new_password')

        try:
            # Weryfikacja użytkownika po username i email
            user = User.objects.get(username=username, email=email)
            user.set_password(new_password)  # Ustawienie nowego hasła
            user.save()
            messages.success(request, 'Password successfully changed! Now log in.')
            return redirect('success')  # Przekierowanie na success.html
        except User.DoesNotExist:
            messages.error(request, 'No user found with that username and email.')

    return render(request, 'forgot.html')

@login_required
def profile_view(request):
    xtb_connection = XTBConnection.objects.filter(user=request.user).first()
    session_id = xtb_connection.stream_session_id if xtb_connection else None
    manager = XTBConnectionManager()

    if request.method == 'POST':
        form = XTBConnectionForm(request.POST, instance=xtb_connection)
        if form.is_valid():
            xtb_connection = form.save(commit=False)
            xtb_connection.user = request.user
            xtb_connection.save()  # Zapisz najpierw

            # Spróbuj nawiązać połączenie, przekazując aktualne połączenie
            if manager.connect(xtb_connection=xtb_connection):
                session_id = manager.connections.get(request.user.id, {}).get('stream_session_id')
                messages.success(request, "Pomyślnie połączono z XTB API!")
            else:
                messages.error(request, "Nie udało się połączyć z XTB API!")

            return redirect('profile')
        else:
            messages.error(request, "Błąd w formularzu. Spróbuj ponownie.")
    else:
        form = XTBConnectionForm(instance=xtb_connection)

    return render(request, 'profile.html', {
        'form': form,
        'session_id': session_id,
    })

@login_required
def history_view(request):
    manager = XTBConnectionManager()
    trade_history = []

    xtb_connection = XTBConnection.objects.filter(user=request.user, is_live=True).first()
    if not xtb_connection:
        messages.error(request, "Brak aktywnego połączenia z XTB API. Proszę uzupełnij dane logowania w profilu.")
        return redirect('profile')

    if not manager.connect(xtb_connection=xtb_connection):
        messages.error(request, "Nie udało się połączyć z XTB API. Proszę uzupełnij dane logowania w profilu.")
        return redirect('profile')

    response = manager.send_command(request.user.id, "getTradesHistory", {"start": 0, "end": 100})
    if response and response.get("status"):
        trade_history = response.get("returnData", [])

    return render(request, 'history.html', {
        'history': trade_history,
        'is_live': manager.connections.get(request.user.id, {}).get('is_connected', False)
    })


def register_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            token, created = Token.objects.get_or_create(user=user)
            
            # Wysłanie tokena do mikroserwisu
            try:
                # Dodajemy nagłówek Authorization: Bearer <MICROSERVICE_API_TOKEN2>
                headers = {
                    'Authorization': f'Bearer {settings.MICROSERVICE_API_TOKEN}',
                    'Content-Type': 'application/json',
                }
                
                response = requests.post(
                    f"{settings.MICROSERVICE_URL2}/register_token/",
                    json={
                        'user_id': user.id,
                        'token': token.key
                    },
                    headers=headers,
                    timeout=5
                )

                if response.status_code == 200:
                    messages.success(request, 'Możesz się już zalogować!')
                else:
                    messages.warning(request, 'Rejestracja udana, ale synchronizacja z mikroserwisem nie powiodła się.')
            except Exception as e:
                messages.error(request, f'Błąd synchronizacji z mikroserwisem: {e}')
            
            return redirect('login')
        else:
            messages.error(request, 'Spróbuj jeszcze raz!')
    else:
        form = CustomUserCreationForm()
    return render(request, 'register.html', {'form': form})


@login_required
def dashboard_view(request):
    manager = XTBConnectionManager()
    open_trades = []
    pending_orders = []
    recent_trades = []

    xtb_connection = XTBConnection.objects.filter(user=request.user, is_live=True).first()
    if not xtb_connection:
        messages.error(request, "Brak aktywnego połączenia z XTB API. Proszę uzupełnij dane logowania w profilu.")
        return redirect('profile')

    if not manager.connect(xtb_connection=xtb_connection):
        messages.error(request, "Nie udało się połączyć z XTB API. Proszę uzupełnij dane logowania w profilu.")
        return redirect('profile')

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
    manager = XTBConnectionManager()

    xtb_connection = XTBConnection.objects.filter(user=request.user, is_live=True).first()
    if not xtb_connection:
        return JsonResponse({"error": "No active XTB connection."}, status=400)

    if not manager.connect(xtb_connection=xtb_connection):
        return JsonResponse({"error": "Failed to connect to XTB API."}, status=400)

    response = manager.send_command(request.user.id, "getMarginLevel")
    if response and response.get("status") is True:
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
    manager = XTBConnectionManager()
    symbol = request.GET.get('symbol', '').strip()  # Pobierz symbol z żądania

    # Sprawdź, czy symbol jest podany
    if not symbol:
        return JsonResponse({"error": "Parameter 'symbol' is required."}, status=400)

    xtb_connection = XTBConnection.objects.filter(user=request.user, is_live=True).first()
    if not xtb_connection:
        return JsonResponse({"error": "No active XTB connection."}, status=400)

    if not manager.connect(xtb_connection=xtb_connection):
        return JsonResponse({"error": "Failed to connect to XTB API."}, status=400)

    response = manager.send_command(request.user.id, "getSymbol", {"symbol": symbol})

    # Sprawdź odpowiedź API
    if response and response.get("status"):
        data = response.get("returnData", {})
        return JsonResponse({
            "ask": data.get("ask"),
            "bid": data.get("bid")
        })
    else:
        return JsonResponse({
            "error": "Failed to fetch instrument price.",
            "details": response.get("error") if response else "No response from API"
        }, status=400)

@login_required
def search_instruments(request):
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
                "categoryName": sym_info.get('categoryName')
            })

    return JsonResponse(selected_data, safe=False)

def get_stock_market_status():
    now = datetime.now(timezone.utc)
    day_of_week = now.weekday()  # 0 = Poniedziałek, 6 = Niedziela

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
    print(stock_markets)
    context = {
        'history': [],  # istniejące dane historii
        'documents': [],  # istniejące dane dokumentów
        'stocks': stock_markets,
    }
    return render(request, 'dashboard.html', context)

def api_stock_status(request):
    stock_markets = get_stock_market_status()
    return JsonResponse(stock_markets, safe=False)

@login_required
def get_symbol_details_view(request):
    """
    Pobiera szczegółowe informacje o wybranym symbolu z API XTB.
    """
    symbol = request.GET.get('symbol', 'PKN.PL_4')  # Domyślnie symbol PKN.PL_4 stc
    xtb_connection = XTBConnection.objects.filter(user=request.user, is_live=True).first()

    if not xtb_connection or not xtb_connection.stream_session_id:
        return JsonResponse({"error": "No active XTB connection."}, status=400)

    manager = XTBConnectionManager()
    if not manager.connect(xtb_connection=xtb_connection):
        return JsonResponse({"error": "Failed to connect to XTB API."}, status=400)

    response = manager.send_command(request.user.id, "getSymbol", {"symbol": symbol})

    if response and response.get("status"):
        return JsonResponse(response.get("returnData"), safe=False)
    else:
        return JsonResponse({"error": "Failed to fetch symbol details"}, status=400)

@login_required
def bot_list(request):
    """Pokazuje listę wszystkich botów zalogowanego użytkownika."""
    user_bots = Bot.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'bot_list.html', {'bots': user_bots})

@login_required
def get_stream_session_id(request):
    try:
        xtb_connection = XTBConnection.objects.get(user=request.user, is_live=True)
        if xtb_connection.stream_session_id:
            return JsonResponse({"stream_session_id": xtb_connection.stream_session_id})
        else:
            return JsonResponse({"error": "No active stream session ID found."}, status=400)
    except XTBConnection.DoesNotExist:
        return JsonResponse({"error": "No active XTB connection found."}, status=400)

####################################################### Bot Views

@login_required
def bot_add(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        instrument = request.POST.get('instrument')
        min_price = request.POST.get('min_price')
        max_price = request.POST.get('max_price')
        percent = request.POST.get('percent')
        capital = request.POST.get('capital')
        
        # Nowe pola
        xtb_id = request.POST.get('xtb_id')
        xtb_password = request.POST.get('xtb_password')

        # 1) Zapisz bota w bazie danych
        new_bot = Bot.objects.create(
            user=request.user,
            name=name,
            instrument=instrument,
            min_price=min_price,
            max_price=max_price,
            percent=percent,
            capital=capital,
            status='NEW'
        )
        
        # 2) Pobierz token mikroserwisu zamiast używać ustawień
        microservice_token = get_token(request.user.id)
        if not microservice_token:
            new_bot.status = 'ERROR'
            new_bot.save()
            messages.error(request, 'Brak tokena mikroserwisu. Nie udało się utworzyć bota.')
            return redirect('bot_list')
        
        # 3) Wyślij dane do mikroserwisu
        headers = {'Authorization': f'Token {microservice_token}'}
        payload = {
            'user_id': request.user.id,
            'name': name,
            'instrument': instrument,
            'min_price': min_price,
            'max_price': max_price,
            'percent': percent,
            'capital': capital,

            # Dane do logowania w XTB (mikroserwis sam się zaloguje)
            'xtb_id': xtb_id,
            'xtb_password': xtb_password,
        }

        try:
            resp = requests.post(
                f"{settings.MICROSERVICE_URL2}/create_bot/", 
                json=payload, 
                headers=headers, 
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                # Odbieramy ID bota w mikroserwisie
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

    # GET -> renderujemy formularz
    return render(request, 'bot_add.html')

@login_required
def bot_remove(request, bot_id):
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)

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
    except requests.RequestException as e:
        bot_details = None
        messages.error(request, "Nie udało się pobrać szczegółów bota z mikroserwisu.")
    
    # Przekazanie danych do szablonu
    return render(request, 'bot_detail.html', {
        'bot': bot,
        'bot_details': bot_details,
    })

############### REST API przekazanie session id na endpoint

@api_view(['POST'])
@permission_classes([AllowAny])  # Zezwól na dowolne połączenie
def start_microservice_stream(request):
    """
    Wysyła żądanie do mikroserwisu z użyciem dynamicznie pobranego tokena.
    """
    try:
        user_id = request.data.get('user_id')
        if not user_id:
            return Response({"error": "User ID is required."}, status=400)
        
        xtb_connection = XTBConnection.objects.get(user_id=user_id, is_live=True)
        
        if xtb_connection.stream_session_id:
            # Pobierz token mikroserwisu dla danego user_id
            microservice_token = get_token(user_id)
            if not microservice_token:
                return Response({"error": "Brak tokena mikroserwisu."}, status=400)
            
            response = send_request_to_microservice(user_id, xtb_connection.stream_session_id, token=microservice_token)
            
            if 'error' in response:
                return Response({
                    "error": response['error'],
                    "details": response.get('details')
                }, status=400)
            
            return Response({
                "message": "Stream started successfully",
                "microservice_response": response
            })
        else:
            return Response({
                "error": "No active stream session ID found."
            }, status=400)
    
    except XTBConnection.DoesNotExist:
        return Response({
            "error": "No active XTB connection found."
        }, status=400)
    except Exception as e:
        return Response({
            "error": str(e)
        }, status=400)

####################################################### Proxy Views

@login_required
@require_GET
def get_bot_details_proxy(request, bot_id):
    bot = get_object_or_404(Bot, id=bot_id, user=request.user)
    api_endpoint = f"{settings.MICROSERVICE_URL2}/get_bot_details/{bot.microservice_bot_id}/"
    
    # Pobierz dynamiczny token
    microservice_token = get_token(request.user.id)
    if not microservice_token:
        return JsonResponse({"error": "Brak tokena mikroserwisu."}, status=400)

    headers = {
        'Authorization': f'Token {microservice_token}',
    }
    params = {
        'user_id': request.user.id  # Przekazanie user_id jako parametr GET
    }
    
    try:
        response = requests.get(api_endpoint, headers=headers, params=params, timeout=5)
        response.raise_for_status()
        bot_details = response.json()
        return JsonResponse(bot_details)
    except requests.HTTPError as http_err:
        logger.error(f"HTTP error occurred when fetching bot details for bot_id={bot_id}: {http_err}")
        return JsonResponse({"error": "Błąd HTTP podczas pobierania danych z mikroserwisu."}, status=500)
    except requests.RequestException as req_err:
        logger.error(f"Request exception occurred when fetching bot details for bot_id={bot_id}: {req_err}")
        return JsonResponse({"error": "Nie udało się pobrać danych z mikroserwisu."}, status=500)
    except ValueError as json_err:
        logger.error(f"JSON decode error when fetching bot details for bot_id={bot_id}: {json_err}")
        return JsonResponse({"error": "Błąd dekodowania danych z mikroserwisu."}, status=500)