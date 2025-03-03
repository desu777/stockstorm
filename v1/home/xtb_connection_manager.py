# xtb_connection_manager.py

import threading
import time
from datetime import datetime
from .models import XTBConnection
from cryptography.fernet import Fernet
import websocket
import json

# Szyfrowanie
FERNET_KEY = 'GiLFpoI4-TzsPAheWRYytzPXuOlZVHOz5FrZsjHYZSk='
fernet = Fernet(FERNET_KEY)

class XTBConnectionManager:
    def __init__(self):
        self.connections = {}  # Klucz: user_id, wartość: połączenie

    def connect(self, xtb_connection):
        """Łączy się z API XTB i uzyskuje stream_session_id dla danego użytkownika."""
        user_id = xtb_connection.user.id

        if user_id in self.connections and self.connections[user_id]['is_connected']:
            print(f"🟢 Użytkownik {user_id} jest już połączony z XTB API.")
            return True

        xtb_id = xtb_connection.xtb_id
        try:
            password = fernet.decrypt(xtb_connection.password).decode('utf-8')
        except Exception as e:
            print(f"🔴 Błąd deszyfrowania hasła dla użytkownika {user_id}: {e}")
            return False

        try:
            ws = websocket.create_connection("wss://ws.xtb.com/demo")
            login_request = {
                "command": "login",
                "arguments": {
                    "userId": xtb_id,
                    "password": password
                }
            }
            ws.send(json.dumps(login_request))
            response = json.loads(ws.recv())

            if response.get("status") is True and "streamSessionId" in response:
                stream_session_id = response["streamSessionId"]
                xtb_connection.stream_session_id = stream_session_id
                xtb_connection.is_live = True
                xtb_connection.save()

                self.connections[user_id] = {
                    'ws': ws,
                    'stream_session_id': stream_session_id,
                    'is_connected': True
                }

                print(f"🟢 Połączono użytkownika {user_id} z XTB API. streamSessionId: {stream_session_id}")
                return True
            else:
                print(f"🔴 Nie udało się połączyć użytkownika {user_id} z XTB API: {response}")
                return False
        except Exception as e:
            print(f"🔴 Błąd połączenia użytkownika {user_id} z XTB API: {e}")
            return False

    def disconnect(self, user_id):
        """Rozłącza aktywne połączenie dla danego użytkownika."""
        if user_id in self.connections and self.connections[user_id]['is_connected']:
            ws = self.connections[user_id]['ws']
            ws.close()
            self.connections[user_id]['is_connected'] = False
            print(f"🟡 Rozłączono użytkownika {user_id} z XTB API.")

    def ping(self, user_id):
        """Ping dla utrzymania aktywnej sesji dla danego użytkownika."""
        if user_id not in self.connections or not self.connections[user_id]['is_connected']:
            print(f"🔴 Brak aktywnego połączenia dla użytkownika {user_id} do pingowania.")
            return

        try:
            ping_request = {"command": "ping"}
            ws = self.connections[user_id]['ws']
            ws.send(json.dumps(ping_request))
            self.connections[user_id]['last_ping'] = datetime.now()
            print(f"🟢 Ping wysłany do XTB API dla użytkownika {user_id}.")
        except Exception as e:
            print(f"🔴 Błąd pingowania dla użytkownika {user_id}: {e}")
            self.disconnect(user_id)
            # Opcjonalnie spróbuj ponownie połączyć
            # self.connect(xtb_connection)

    def send_command(self, user_id, command, arguments=None):
        """Wysyła komendę do API XTB dla danego użytkownika."""
        if user_id not in self.connections or not self.connections[user_id]['is_connected']:
            print(f"🔴 Nie ma aktywnego połączenia dla użytkownika {user_id}. Próba ponownego połączenia.")
            xtb_connection = XTBConnection.objects.filter(user_id=user_id, is_live=True).first()
            if not xtb_connection or not self.connect(xtb_connection):
                return None

        try:
            request = {
                "command": command,
                "arguments": arguments or {}
            }
            ws = self.connections[user_id]['ws']
            ws.send(json.dumps(request))
            response_data = ws.recv()
            if not response_data.strip():
                return None
            response = json.loads(response_data)
            return response
        except Exception as e:
            print(f"🔴 Błąd wysyłania komendy {command} dla użytkownika {user_id}: {e}")
            self.disconnect(user_id)
            return None


# Automatyczne pingowanie w tle
def start_ping_thread():
    manager = XTBConnectionManager()
    def ping_loop():
        while True:
            for user_id, conn in manager.connections.items():
                if conn['is_connected']:
                    manager.ping(user_id)
            time.sleep(300)  # Ping co 5 minut

    ping_thread = threading.Thread(target=ping_loop, daemon=True)
    ping_thread.start()
    print("🟡 Ping Thread Started")

# Uruchom automatyczne pingowanie
start_ping_thread()
