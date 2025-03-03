# models.py
from django.db import models
from django.contrib.auth.models import User
from cryptography.fernet import Fernet
import websocket
import json

FERNET_KEY = 'GiLFpoI4-TzsPAheWRYytzPXuOlZVHOz5FrZsjHYZSk='  # Klucz do szyfrowania/dekryptacji
fernet = Fernet(FERNET_KEY)

class XTBApiConnector:
    def __init__(self, xtb_id, password, stream_session_id=None):
        self.xtb_id = xtb_id
        self.password = password
        self.ws = None
        self.stream_session_id = stream_session_id

    def connect(self):
        try:
            self.ws = websocket.create_connection("wss://ws.xtb.com/demo")
            login_request = {
                "command": "login",
                "arguments": {
                    "userId": self.xtb_id,
                    "password": self.password
                }
            }
            self.ws.send(json.dumps(login_request))
            response = json.loads(self.ws.recv())
            if response.get("status") is True and "streamSessionId" in response:
                self.stream_session_id = response["streamSessionId"]
                print("Saving stream_session_id:", self.stream_session_id)
                return True
            return False
        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def send_command(self, command, arguments=None):
        if not self.ws:
            raise ConnectionError("Not connected to XTB API.")
        try:
            request = {
                "command": command,
                "arguments": arguments or {}
            }
            self.ws.send(json.dumps(request))
            response_data = self.ws.recv()
            if not response_data.strip():
                return None
            response = json.loads(response_data)
            return response
        except Exception as e:
            print(f"Command error: {e}")
            return None

    def ping(self):
        if not self.ws:
            raise ConnectionError("Not connected to XTB API.")
        # Komenda ping nie zwraca danych, jest to keep alive
        ping_request = {
            "command": "ping"
        }
        self.ws.send(json.dumps(ping_request))
        # Brak odpowiedzi - ping nie zwraca danych, służy tylko utrzymaniu sesji

    def disconnect(self):
        if self.ws:
            self.ws.close()
            self.ws = None
            
###############################################
class XTBConnection(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='xtb_connection')
    xtb_id = models.CharField(max_length=50, verbose_name="XTB ID")
    password = models.BinaryField(verbose_name="Encrypted Password")
    is_live = models.BooleanField(default=False, verbose_name="Live Status")
    stream_session_id = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} - {'LIVE' if self.is_live else 'NOT LIVE'}"

    def set_password(self, raw_password):
        self.password = fernet.encrypt(raw_password.encode('utf-8'))

    def get_password(self):
        return fernet.decrypt(self.password).decode('utf-8')

    def connect_to_xtb(self):
        connector = XTBApiConnector(self.xtb_id, self.get_password())
        if connector.connect():
            self.is_live = True
            self.stream_session_id = connector.stream_session_id
            self.save()
            connector.disconnect()  # rozłącz po logowaniu, jeśli nie potrzebujesz stale połączone
            return True
        else:
            self.is_live = False
            self.stream_session_id = None
            self.save()
            return False

def get_symbol_from_xtb(user, symbol):
    # Pobierz XTBConnection dla danego użytkownika
    xtb_connection = getattr(user, 'xtb_connection', None)
    if not xtb_connection or not xtb_connection.is_live:
        # Brak aktywnej sesji
        return {"ask": None, "bid": None, "error": "No active XTB session."}

    xtb_id = xtb_connection.xtb_id
    xtb_password = xtb_connection.get_password()
    stream_session_id = xtb_connection.stream_session_id

    connector = XTBApiConnector(xtb_id, xtb_password, stream_session_id)

    if connector.connect():
        response = connector.send_command("getSymbol", {"symbol": symbol})
        connector.disconnect()
        if response and response.get("status"):
            data = response.get("returnData", {})
            ask = data.get("ask")
            bid = data.get("bid")
            return {"ask": ask, "bid": bid}
        else:
            return {"ask": None, "bid": None, "error": "Failed to get symbol data."}
    else:
        return {"ask": None, "bid": None, "error": "Failed to connect to XTB."}
def get_all_symbols_from_xtb(user):
    xtb_connection = getattr(user, 'xtb_connection', None)
    if not xtb_connection or not xtb_connection.is_live:
        return []
    
    xtb_id = xtb_connection.xtb_id
    xtb_password = xtb_connection.get_password()
    stream_session_id = xtb_connection.stream_session_id

    connector = XTBApiConnector(xtb_id, xtb_password, stream_session_id)
    if connector.connect():
        response = connector.send_command("getAllSymbols")
        connector.disconnect()
        if response and response.get("status"):
            # Zwraca listę SYMBOL_RECORD
            symbols_data = response.get("returnData", [])
            # Zmapuj je do formatu {symbol: 'XYZ', description: '...'}
            result = []
            for s in symbols_data:
                symbol_name = s.get('symbol')
                description = s.get('description', '')
                # Możesz opcjonalnie odfiltrować, aby zwracać tylko ważne dane
                result.append({
                    "symbol": symbol_name,
                    "description": description
                })
            return result
        
        else:
            return []
    else:
        return []
    

##########################################

class Bot(models.Model):
    STATUS_CHOICES = (
        ('NEW', 'New'),
        ('RUNNING', 'Running'),
        ('FINISHED', 'Finished'),
        ('ERROR', 'Error'),
    )

    BROKER_CHOICES = (
    ('XTB', 'XTB Broker'),
    ('BNB', 'Binance'),
    ('D10', 'D510XTB'),
    )
    broker_type = models.CharField(
        max_length=3,
        choices=BROKER_CHOICES,
        default='XTB'
    )


    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    instrument = models.CharField(max_length=50)
    max_price = models.DecimalField(max_digits=10, decimal_places=2)
    percent = models.IntegerField()
    capital = models.DecimalField(max_digits=12, decimal_places=2)
    stream_session_id = models.CharField(max_length=200, blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NEW')
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)  # Zaktualizowane pole
    # id bota w mikroserwisie
    microservice_bot_id = models.IntegerField(blank=True, null=True)

    def __str__(self):
        return f"Bot {self.name} (user={self.user}, {self.instrument}, {self.status})"


