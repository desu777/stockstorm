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
        self._recv_lock = asyncio.Lock()

    def _timestamp(self):
        return datetime.datetime.utcnow().isoformat()

    async def send_message(self, ws, msg: dict, label: str = ""):
        msg_text = json.dumps(msg)
        await ws.send(msg_text)

    async def receive_message(self, ws, label: str = "") -> dict:
        async with self._recv_lock:
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
        """
        W pętli pobieramy:
         1) Główny instrument (self.instrument),
         2) Dodatkowo USDPLN (jeśli bot potrzebuje przeliczeń PLN->USD).
        """
        global instrument_prices
        while self.is_connected:
            try:
                # 1) Pobierz dane głównego instrumentu (np. RIOT.US)
                cmd_main = {
                    "command": "getSymbol",
                    "arguments": {"symbol": self.instrument}
                }
                await self.send_message(self.main_ws, cmd_main, "getSymbol")
                resp_main = await self.receive_message(self.main_ws, "getSymbol")
                if resp_main.get("status"):
                    rd_main = resp_main.get("returnData", {})
                    instrument_prices[(self.bot_id, self.instrument)] = {
                        "ask": rd_main.get("ask"),
                        "bid": rd_main.get("bid"),
                        "timestamp": self._timestamp()
                    }
                    print(f"[{self._timestamp()}] [Bot {self.bot_id}] Updated price for {self.instrument}: {instrument_prices[(self.bot_id, self.instrument)]}")
                else:
                    print(f"[{self._timestamp()}] [Bot {self.bot_id}] Error in getSymbol response (main): {resp_main}")

                # 2) Pobierz kurs USDPLN, by móc liczyć wolumen dla PLN -> USD
                cmd_usdpln = {
                    "command": "getSymbol",
                    "arguments": {"symbol": "USDPLN"}
                }
                await self.send_message(self.main_ws, cmd_usdpln, "getSymbol")
                resp_usdpln = await self.receive_message(self.main_ws, "getSymbol")
                if resp_usdpln.get("status"):
                    rd_usdpln = resp_usdpln.get("returnData", {})
                    instrument_prices[(self.bot_id, "USDPLN")] = {
                        "ask": rd_usdpln.get("ask"),
                        "bid": rd_usdpln.get("bid"),
                        "timestamp": self._timestamp()
                    }
                    print(f"[{self._timestamp()}] [Bot {self.bot_id}] Updated price for USDPLN: {instrument_prices[(self.bot_id, 'USDPLN')]}")
                else:
                    print(f"[{self._timestamp()}] [Bot {self.bot_id}] Error in getSymbol response (USDPLN): {resp_usdpln}")

            except Exception as e:
                print(f"[{self._timestamp()}] [Bot {self.bot_id}] Price update error: {e}")
                await asyncio.sleep(5)  # Poczekaj przed próbą reconnect
                await self.reconnect()

            await asyncio.sleep(1)

    async def reconnect(self):
        print(f"[{self._timestamp()}] [Bot {self.bot_id}] Reconnecting...")
        await self.close()
        await self.connect()

    async def trade_transaction(self, symbol, volume, cmd):
        # Ustawienie ceny: ASK dla BUY, BID dla SELL
        current_price = instrument_prices.get((self.bot_id, symbol), {}).get("ask" if cmd == 0 else "bid", 0)

        if current_price == 0:
            #print(f"[{self._timestamp()}] [Bot {self.bot_id}] Błąd: Brak aktualnej ceny dla {symbol}.")
            return {"status": False, "errorCode": "NO_PRICE", "errorDescr": "Brak aktualnej ceny."}

        trade_data = {
            "command": "tradeTransaction",
            "arguments": {
                "tradeTransInfo": {
                    "symbol": symbol,
                    "volume": volume,
                    "price": current_price,
                    "cmd": cmd,
                    "type": 0,
                    "sl": 0.0,
                    "tp": 0.0,
                    "customComment": "Market order"
                }
            }
        }

        print(f"[{self._timestamp()}] [Bot {self.bot_id}] Wysyłanie zlecenia: {trade_data}")

        try:
            await self.send_message(self.main_ws, trade_data, "tradeTransaction")
            response = await self.receive_message(self.main_ws, "tradeTransaction")
            print(f"[{self._timestamp()}] [Bot {self.bot_id}] Odpowiedź XTB: {response}")
            return response
        except Exception as e:
            print(f"[{self._timestamp()}] [Bot {self.bot_id}] Błąd transakcji: {e}")
            return {"status": False, "errorCode": "CONNECTION_ERROR", "errorDescr": str(e)}

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

        conn = _XTBConnection(bot_id=bot.id, login=bot.xtb_login, password=bot.get_xtb_password(), instrument=bot.instrument)
        ok = await conn.connect()
        if ok:
            self._connections[bot_id] = conn
        return ok

    async def trade_bot(self, bot_id: int, symbol: str, volume: float, cmd=0):
        max_retries = 5
        attempt = 0

        # Sprawdzenie połączenia
        if bot_id not in self._connections or not self._connections[bot_id].is_connected:
            print(f"[{self._timestamp()}] [trade_bot] Bot {bot_id} not connected or missing!")
            return {"status": False, "errorCode": "NOT_CONNECTED"}

        # (Jeśli usunąłeś logikę salda user_profile to jej tu nie ma)

        # Pobranie aktualnej ceny instrumentu
        current_price = instrument_prices.get((bot_id, symbol), {}).get("ask" if cmd == 0 else "bid", 0)
        if current_price == 0:
            print(f"[{self._timestamp()}] [Bot {bot_id}] Brak aktualnej ceny dla {symbol}.")
            return {"status": False, "errorCode": "NO_PRICE"}

        while attempt < max_retries:
            try:
                print(f"[{self._timestamp()}] [Bot {bot_id}] attempt={attempt+1}, trade_transaction({symbol}, vol={volume}, cmd={cmd})")
                response = await self._connections[bot_id].trade_transaction(symbol, volume, cmd)

                # TU KLUCZOWY PRINT:
                print(f"[DEBUG] [trade_bot] XTB raw response: {response}")

                if response.get("status"):
                    print(f"[{self._timestamp()}] [Bot {bot_id}] Trade successful: {response}")
                    return response
                else:
                    # Tu zobaczysz kod błędu i opis
                    print(f"[{self._timestamp()}] [Bot {bot_id}] Trade failed -> errorCode={response.get('errorCode')}, descr={response.get('errorDescr')}")
                    print(f"[{self._timestamp()}] [Bot {bot_id}] Trade failed, retrying in 5 minutes... Attempt {attempt + 1}")
                    attempt += 1
                    await asyncio.sleep(300)  # 5 minut
            except Exception as e:
                print(f"[{self._timestamp()}] [Bot {bot_id}] Trade error: {e}")
                attempt += 1
                await asyncio.sleep(300)

        # Po 5 nieudanych próbach zmień status bota na ERROR
        bot = await sync_to_async(MicroserviceBot.objects.get)(pk=bot_id)
        bot.status = 'ERROR'
        await sync_to_async(bot.save)()
        print(f"[{self._timestamp()}] [Bot {bot_id}] Too many failed attempts. Status set to ERROR.")
        return {"status": False, "errorCode": "MAX_RETRIES_EXCEEDED"}

    async def disconnect_bot(self, bot_id: int):
        if bot_id in self._connections:
            await self._connections[bot_id].close()
            instrument = self._connections[bot_id].instrument
            key = (bot_id, instrument)
            if key in instrument_prices:
                del instrument_prices[key]
                print(f"[{self._timestamp()}] [disconnect_bot] Removed instrument {key} from instrument_prices.")
            del self._connections[bot_id]



xtb_manager = XTBManager()

