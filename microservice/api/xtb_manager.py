import asyncio
import datetime
import json
import websockets

from asgiref.sync import sync_to_async
from .models import MicroserviceBot

XTB_MAIN_URL = "wss://ws.xtb.com/demo"

# Globalny słownik do przechowywania cen instrumentów
instrument_prices = {}


class _XTBConnection:
    def __init__(self, bot_id: int, login: str, password: str, instrument: str):
        self.bot_id = bot_id
        self.login = login
        self.password = password
        self.instrument = instrument

        self.main_ws = None
        self.is_connected = False
        self._price_update_task = None

    def _timestamp(self):
        return datetime.datetime.utcnow().isoformat()

    async def send_message(self, ws, msg: dict, label: str = ""):
        msg_text = json.dumps(msg)
        await ws.send(msg_text)

    async def receive_message(self, ws, label: str = "") -> dict:
        msg_text = await ws.recv()
        return json.loads(msg_text)

    async def connect(self) -> bool:
        try:
            self.main_ws = await websockets.connect(XTB_MAIN_URL)
            print(f"[{self._timestamp()}] [Bot {self.bot_id}] Connected main ws.")
        except Exception as e:
            print(f"[{self._timestamp()}] [Bot {self.bot_id}] Cannot connect main ws: {e}")
            return False

        login_req = {
            "command": "login",
            "arguments": {"userId": self.login, "password": self.password}
        }
        try:
            await self.send_message(self.main_ws, login_req, "login")
            resp = await self.receive_message(self.main_ws, "login")
            if not resp.get("status"):
                print(f"[{self._timestamp()}] [Bot {self.bot_id}] Login failed: {resp}")
                await self.close()
                return False
        except Exception as e:
            print(f"[{self._timestamp()}] [Bot {self.bot_id}] Error during login: {e}")
            await self.close()
            return False

        print(f"[{self._timestamp()}] [Bot {self.bot_id}] Logged in to XTB.")
        self.is_connected = True
        self._price_update_task = asyncio.create_task(self._update_prices_loop())
        return True

    async def _update_prices_loop(self):
        global instrument_prices
        while self.is_connected:
            try:
                cmd = {"command": "getSymbol", "arguments": {"symbol": self.instrument}}
                await self.send_message(self.main_ws, cmd, "getSymbol")
                resp = await self.receive_message(self.main_ws, "getSymbol")
                if resp.get("status"):
                    data = resp.get("returnData", {})
                    instrument_prices[self.instrument] = {
                        "ask": data.get("ask"),
                        "bid": data.get("bid"),
                        "timestamp": self._timestamp()
                    }
                    print(f"[{self._timestamp()}] [Bot {self.bot_id}] Updated price: {instrument_prices[self.instrument]}")
            except Exception as e:
                print(f"[{self._timestamp()}] [Bot {self.bot_id}] Price update error: {e}")
            await asyncio.sleep(0.5)

    async def trade_transaction(self, symbol, price, volume, cmd):
        trade_data = {
            "command": "tradeTransaction",
            "arguments": {
                "symbol": symbol,
                "price": price,
                "volume": volume,
                "cmd": cmd,
                "orderType": 0
            }
        }
        await self.send_message(self.main_ws, trade_data, "tradeTransaction")
        response = await self.receive_message(self.main_ws, "tradeTransaction")
        print(f"[{self._timestamp()}] [Bot {self.bot_id}] Trade response: {response}")
        return response

    async def close(self):
        self.is_connected = False
        if self._price_update_task:
            self._price_update_task.cancel()
            self._price_update_task = None
        if self.main_ws:
            try:
                await self.main_ws.close()
            except Exception:
                pass
            self.main_ws = None
        print(f"[{self._timestamp()}] [Bot {self.bot_id}] Connection closed.")


class XTBManager:
    def __init__(self):
        self._connections = {}

    def _timestamp(self):
        return datetime.datetime.utcnow().isoformat()

    async def connect_bot(self, bot_id: int) -> bool:
        try:
            bot = await sync_to_async(MicroserviceBot.objects.get)(pk=bot_id)
        except MicroserviceBot.DoesNotExist:
            print(f"[{self._timestamp()}] [connect_bot] Bot {bot_id} not found in DB!")
            return False

        if bot_id in self._connections and self._connections[bot_id].is_connected:
            print(f"[{self._timestamp()}] [connect_bot] Bot {bot_id} is already connected.")
            return True

        conn = _XTBConnection(
            bot_id=bot.id,
            login=bot.xtb_login,
            password=bot.get_xtb_password(),
            instrument=bot.instrument
        )
        ok = await conn.connect()
        if ok:
            self._connections[bot_id] = conn
        return ok

    async def trade_bot(self, bot_id: int, symbol: str, price: float, volume: float, cmd=0):
        if bot_id not in self._connections or not self._connections[bot_id].is_connected:
            print(f"[{self._timestamp()}] [trade_bot] Bot {bot_id} not connected or missing!")
            return None
        return await self._connections[bot_id].trade_transaction(symbol, price, volume, cmd)

    async def disconnect_bot(self, bot_id: int):
        if bot_id in self._connections:
            # Zamknięcie połączenia
            await self._connections[bot_id].close()
            
            # Usunięcie instrumentu z globalnego słownika
            instrument = self._connections[bot_id].instrument
            if instrument in instrument_prices:
                del instrument_prices[instrument]
                print(f"[{self._timestamp()}] [disconnect_bot] Removed instrument {instrument} from instrument_prices.")
            
            # Usunięcie bota z połączeń
            del self._connections[bot_id]


xtb_manager = XTBManager()
