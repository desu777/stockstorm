# api/xtb_ws.py

import asyncio
import json
import logging
from websockets import connect

logger = logging.getLogger(__name__)

XTB_MAIN_URL = "wss://ws.xtb.com/demo"       # wysyłanie komend
XTB_STREAM_URL = "wss://ws.xtb.com/demoStream" # odbiór ticków

class XTBWebSocketClient:
    """
    Używa istniejącego 'streamSessionId' (bez logowania hasłem).
    Komunikaty do main: tradeTransaction
    Komunikaty do stream: getTickPrices
    """

    def __init__(self, stream_session_id):
        self.stream_session_id = stream_session_id
        self.main_ws = None
        self.stream_ws = None

    async def connect_main(self):
        """ Połączenie z wss://ws.xtb.com/demo """
        self.main_ws = await connect(XTB_MAIN_URL)
        logger.info("Connected to XTB main (demo).")

    async def connect_stream(self):
        """ Połączenie z wss://ws.xtb.com/demoStream """
        self.stream_ws = await connect(XTB_STREAM_URL)
        logger.info("Connected to XTB stream (demoStream).")

    async def subscribe_tick_prices(self, symbol, minArrivalTime=100, maxLevel=0):
        """
        Wysyłamy subskrypcję do stream:
        {
          "command": "getTickPrices",
          "streamSessionId": "...",
          "symbol": "EURUSD"
        }
        """
        if not self.stream_ws:
            raise Exception("Stream WebSocket not connected!")
        cmd = {
            "command": "getTickPrices",
            "streamSessionId": self.stream_session_id,
            "symbol": symbol,
            "minArrivalTime": minArrivalTime,
            "maxLevel": maxLevel
        }
        await self.stream_ws.send(json.dumps(cmd))
        logger.info(f"Subscribed tickPrices for {symbol} with session {self.stream_session_id}")

    async def listen_stream(self, on_tick_callback):
        """
        W pętli odbiera dane z stream_ws.
        Kiedy przyjdzie "tickPrices", wywołuje on_tick_callback(data).
        """
        while True:
            try:
                msg = await self.stream_ws.recv()
                data = json.loads(msg)
                cmd = data.get("command")
                if cmd == "tickPrices":
                    tick_info = data.get("data")
                    on_tick_callback(tick_info)
                else:
                    logger.debug(f"Other stream message: {data}")
            except Exception as e:
                logger.error(f"Error in stream listening: {e}")
                await asyncio.sleep(1)  # minimalny retry

    async def trade_transaction(self, symbol, price, volume, cmd=0):
        """
        Wysyła zlecenie do main_ws:
        {
          "command": "tradeTransaction",
          "arguments": {
            "tradeTransInfo": {...},
            "streamSessionId": "...", (jeśli wymagane)
          }
        }
        """
        if not self.main_ws:
            raise Exception("Main WebSocket not connected!")
        trade_info = {
            "cmd": cmd,  # 0 = BUY, 1 = SELL
            "customComment": "bot_order",
            "expiration": 0,
            "offset": 0,
            "order": 0,
            "price": price,  
            "sl": 0.0,
            "symbol": symbol,
            "tp": 0.0,
            "type": 0,  # 0=OPEN
            "volume": volume
        }
        req_data = {
            "command": "tradeTransaction",
            "arguments": {
                "tradeTransInfo": trade_info
                # "streamSessionId": self.stream_session_id  # w razie potrzeby
            }
        }
        await self.main_ws.send(json.dumps(req_data))
        resp_text = await self.main_ws.recv()
        return json.loads(resp_text)

    async def close(self):
        if self.stream_ws:
            await self.stream_ws.close()
        if self.main_ws:
            await self.main_ws.close()
