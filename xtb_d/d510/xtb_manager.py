# xtb_manager.py
import asyncio
import json
import datetime
from decimal import Decimal
import websockets

from asgiref.sync import sync_to_async
from django.conf import settings

from .models import BotD10

# Tu przechowujemy aktualne ceny instrumentów:
# klucz: (bot_id, symbol) -> {"ask": float, "bid": float, "timestamp": "ISO8601"}
instrument_prices = {}

XTB_MAIN_URL = "wss://ws.xtb.com/demo"


class _XTBConnection:
    def __init__(self, bot_id, login, password, instrument):
        self.bot_id = bot_id
        self.login = login
        self.password = password
        self.instrument = instrument

        self.ws = None
        self.is_connected = False
        self._recv_lock = asyncio.Lock()
        self._price_task = None

    def _ts(self):
        return datetime.datetime.utcnow().isoformat()

    async def connect(self) -> bool:
        try:
            self.ws = await websockets.connect(XTB_MAIN_URL)
            print(f"[XTB] Bot {self.bot_id} connected to ws.")
        except Exception as e:
            print(f"[XTB] Bot {self.bot_id} cannot connect: {e}")
            return False

        # login
        req = {
            "command": "login",
            "arguments": {
                "userId": self.login,
                "password": self.password
            }
        }
        await self.send_message(req)
        resp = await self.receive_message()
        if not resp.get("status"):
            print(f"[XTB] Bot {self.bot_id} login fail: {resp}")
            await self.close()
            return False

        print(f"[XTB] Bot {self.bot_id} logged in.")
        self.is_connected = True
        self._price_task = asyncio.create_task(self._fetch_prices_loop())
        return True

    async def close(self):
        self.is_connected = False
        if self._price_task:
            self._price_task.cancel()
        if self.ws:
            await self.ws.close()
        print(f"[XTB] Bot {self.bot_id} connection closed.")

    async def send_message(self, msg: dict):
        txt = json.dumps(msg)
        await self.ws.send(txt)

    async def receive_message(self):
        async with self._recv_lock:
            txt = await self.ws.recv()
        return json.loads(txt)

    async def _fetch_prices_loop(self):
        """
        Co 1s pobieramy bieżącą cenę instrumentu (np. BITCOIN) 
        i opcjonalnie np. USDPLN – wstawiamy do instrument_prices.
        """
        while self.is_connected:
            try:
                # główny instrument
                await self.fetch_symbol(self.instrument)
            except Exception as e:
                print(f"[XTB] Bot {self.bot_id} fetch price error: {e}")
                await asyncio.sleep(2)
                await self.reconnect()

            await asyncio.sleep(1)

    async def fetch_symbol(self, symbol):
        req = {
            "command": "getSymbol",
            "arguments": {"symbol": symbol}
        }
        await self.send_message(req)
        resp = await self.receive_message()

        if resp.get("status"):
            rd = resp["returnData"]
            instrument_prices[(self.bot_id, symbol)] = {
                "ask": rd.get("ask", 0.0),
                "bid": rd.get("bid", 0.0),
                "timestamp": self._ts()
            }
        else:
            print(f"[XTB] Bot {self.bot_id} error for symbol={symbol}: {resp}")


    async def reconnect(self):
        print(f"[XTB] Bot {self.bot_id} reconnecting...")
        await self.close()
        await self.connect()

    async def trade_transaction(self, symbol, volume, cmd):
        """
        cmd=0 -> BUY, cmd=1 -> SELL
        Korzystamy z last-known price (ask/bid).
        """
        p = instrument_prices.get((self.bot_id, symbol), {})
        px = p.get("ask" if cmd == 0 else "bid", 0)
        if px == 0:
            return {"status": False, "errorCode": "NO_PRICE", "errorDescr": "Brak ceny"}

        req = {
            "command": "tradeTransaction",
            "arguments": {
                "tradeTransInfo": {
                    "symbol": symbol,
                    "volume": volume,
                    "price": px,
                    "cmd": cmd,
                    "type": 0,
                    "sl": 0.0,
                    "tp": 0.0,
                    "customComment": "D10"
                }
            }
        }
        await self.send_message(req)
        resp = await self.receive_message()
        return resp


class XTBManager:
    def __init__(self):
        self._connections = {}

    async def connect_bot(self, bot_id: int) -> bool:
        try:
            bot = await sync_to_async(BotD10.objects.get)(pk=bot_id)
        except BotD10.DoesNotExist:
            return False

        # Jeśli już mamy istniejące połączenie:
        if bot_id in self._connections:
            conn = self._connections[bot_id]
            if conn.is_connected:
                return True
            else:
                await conn.close()
                del self._connections[bot_id]

        login = bot.xtb_id or ""
        password = bot.xtb_password or ""
        if not login or not password:
            print(f"[XTBManager] Bot {bot_id} missing XTB credentials.")
            return False

        conn = _XTBConnection(bot_id, login, password, bot.instrument)
        ok = await conn.connect()
        if ok:
            self._connections[bot_id] = conn
        return ok

    async def disconnect_bot(self, bot_id: int):
        if bot_id in self._connections:
            await self._connections[bot_id].close()
            del self._connections[bot_id]
            # usuń też z instrument_prices
            keys_to_remove = [(b, s) for (b, s) in instrument_prices.keys() if b == bot_id]
            for k in keys_to_remove:
                del instrument_prices[k]

    async def trade_bot(self, bot_id: int, symbol: str, volume: float, cmd: int):
        """
        Wykonuje transakcję BUY/SELL z kilkoma retry.
        cmd=0: BUY, cmd=1: SELL
        """
        if bot_id not in self._connections or not self._connections[bot_id].is_connected:
            print(f"[XTBManager] Bot {bot_id} not connected.")
            return {"status": False, "errorCode": "NOT_CONNECTED"}

        conn = self._connections[bot_id]
        max_retries = 3
        for i in range(max_retries):
            try:
                resp = await conn.trade_transaction(symbol, volume, cmd)
                if resp.get("status"):
                    return resp
                else:
                    print(f"[XTBManager] trade fail attempt={i+1}: {resp}")
            except Exception as e:
                print(f"[XTBManager] trade error bot {bot_id}: {e}")

            await asyncio.sleep(1)

        # Po 3 nieudanych próbach
        bot = await sync_to_async(BotD10.objects.get)(pk=bot_id)
        bot.status = 'ERROR'
        await sync_to_async(bot.save)()
        return {"status": False, "errorCode": "MAX_RETRIES_EXCEEDED"}


# Singleton:
xtb_manager = XTBManager()
