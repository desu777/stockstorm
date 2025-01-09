# api/bot_logic.py
import asyncio
import json
import logging
from decimal import Decimal
from django.db.models import Q
from .models import MicroserviceBot
from .xtb_ws import XTBWebSocketClient

logger = logging.getLogger(__name__)

GLOBAL_CLIENT = None  # jeden globalny klient do XTB WebSocket (przykład)


def on_tick_received(tick_data):
    """
    tick_data np.:
    {
      'symbol': 'EURUSD',
      'bid': 1.2345,
      'ask': 1.2347,
      'high': ...,
      ...
    }
    """
    symbol = tick_data.get("symbol")
    bid = tick_data.get("bid")
    ask = tick_data.get("ask")

    if not symbol or bid is None or ask is None:
        return

    current_price = (bid + ask) / 2.0  # uproszczona średnia
    # Szukamy MicroserviceBot w status=RUNNING i danym instrumencie
    bots = MicroserviceBot.objects.filter(
        status='RUNNING',
        instrument=symbol
    )
    for bot in bots:
        _apply_levels_logic(bot, current_price)


def _apply_levels_logic(bot, current_price):
    """
    Sprawdza, czy trzeba kupić/sprzedać według 'levels_data',
    z reinwestycją kapitału i realizacją zysku wg bot.percent.
    """
    if not bot.levels_data:
        return

    data = json.loads(bot.levels_data)
    # Struktura data np.:
    # {
    #   "lv1": 10.0, "lv2": 9.0, ...,
    #   "flags": { "lv1_bought": false, ... },
    #   "caps":  { "lv1":0, "lv2":0, ... },
    #   "buy_price": { "lv1":0, "lv2":0, ... }
    # }

    flags = data.get("flags", {})
    caps = data.get("caps", {})
    buy_price = data.get("buy_price", {})

    levels_keys = [k for k in data.keys() if k.startswith('lv')]
    levels_keys.sort(key=lambda k: int(k[2:]))

    # Ile poziomów?
    total_lv_count = len(levels_keys)
    if total_lv_count == 0:
        return

    # Procent zysku, przy którym sprzedajemy (bot.percent = np. 10 => 10%)
    target_profit_percent = float(bot.percent)  # np. 10 => 10%

    for lv in levels_keys:
        price_lv = data[lv]
        bf = f"{lv}_bought"  # np. lv3_bought
        sf = f"{lv}_sold"    # np. lv3_sold

        if lv not in caps:
            caps[lv] = 0
        if lv not in buy_price:
            buy_price[lv] = 0

        # ###### KUPNO ######
        # Warunek: current_price <= lv i !bought
        if current_price <= price_lv and not flags.get(bf):
            # Jeśli jeszcze nic nie mamy w caps[lv], 
            # to zainicjujmy kwotą = capital / liczba_poziomów (prosty podział)
            if caps[lv] == 0:
                portion = float(bot.capital) / total_lv_count
                caps[lv] = round(portion, 2)

            buy_vol = round(caps[lv] / float(current_price), 3)
            asyncio.create_task(_place_buy_order(bot, current_price, buy_vol))

            buy_price[lv] = current_price
            flags[bf] = True
            logger.info(f"[Bot {bot.id}] BUY at {lv} price={current_price} volume={buy_vol}")

        # ###### SPRZEDAŻ ######
        # real zysk percent = ((current_price - buy_price[lv]) / buy_price[lv]) * 100
        # sprawdzamy, czy >= target_profit_percent (np. >= 10%)
        if flags.get(bf) and not flags.get(sf) and buy_price[lv] > 0:
            # wylicz faktyczny wzrost od momentu kupna
            growth_percent = ((current_price - buy_price[lv]) / buy_price[lv]) * 100.0

            if growth_percent >= target_profit_percent:
                # zysk
                profit = caps[lv] * (growth_percent / 100.0)
                caps[lv] += round(profit, 2)  # reinwestycja

                sell_vol = round(caps[lv] / float(current_price), 3)
                asyncio.create_task(_place_sell_order(bot, current_price, sell_vol))

                flags[sf] = True
                logger.info(
                    f"[Bot {bot.id}] SELL at {lv} price={current_price},"
                    f" growth={growth_percent:.2f}%, profit={profit:.2f}, caps={caps[lv]:.2f}"
                )

    # Zapisujemy w data
    data["flags"] = flags
    data["caps"] = caps
    data["buy_price"] = buy_price

    # Gdy cena >= max_price => FINISHED
    if Decimal(str(current_price)) >= bot.max_price:
        bot.status = 'FINISHED'
        logger.info(f"[Bot {bot.id}] Bot finished - price >= max_price")

    bot.levels_data = json.dumps(data)
    bot.save()


async def _place_buy_order(bot, price, volume):
    """
    Wysyłamy zlecenie BUY do XTB (cmd=0).
    """
    if not GLOBAL_CLIENT:
        logger.error("No GLOBAL_CLIENT to place buy order.")
        return
    resp = await GLOBAL_CLIENT.trade_transaction(bot.instrument, price, volume, cmd=0)
    logger.info(f"BUY order response: {resp}")


async def _place_sell_order(bot, price, volume):
    """
    Wysyłamy zlecenie SELL do XTB (cmd=1).
    """
    if not GLOBAL_CLIENT:
        logger.error("No GLOBAL_CLIENT to place sell order.")
        return
    resp = await GLOBAL_CLIENT.trade_transaction(bot.instrument, price, volume, cmd=1)
    logger.info(f"SELL order response: {resp}")


async def run_ws_main():
    """
    Główna korutyna:
      1. Pobiera bota RUNNING z stream_session_id (pierwszego z brzegu),
      2. Łączy się do XTB,
      3. Subskrybuje tickPrices,
      4. Słucha i przy każdym ticku on_tick_received(tick_data).
    """
    global GLOBAL_CLIENT
    any_bot = MicroserviceBot.objects.filter(status='RUNNING', stream_session_id__isnull=False).first()
    if not any_bot:
        logger.warning("No bot with valid stream_session_id to connect.")
        return

    session_id = any_bot.stream_session_id
    GLOBAL_CLIENT = XTBWebSocketClient(session_id)
    await GLOBAL_CLIENT.connect_main()
    await GLOBAL_CLIENT.connect_stream()

    instruments = MicroserviceBot.objects.filter(
        status='RUNNING',
        stream_session_id=session_id
    ).values_list('instrument', flat=True).distinct()

    for instr in instruments:
        await GLOBAL_CLIENT.subscribe_tick_prices(instr)

    await GLOBAL_CLIENT.listen_stream(on_tick_received)


def start_bots_worker():
    """
    Uruchamia w osobnym wątku asynchroniczny event loop (asyncio),
    który wykonuje run_ws_main().
    """
    import threading

    def run_loop():
        asyncio.run(run_ws_main())

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
