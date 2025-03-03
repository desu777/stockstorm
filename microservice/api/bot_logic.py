# api/bot_logic.py

import asyncio
import json
import datetime
from decimal import Decimal
from collections import defaultdict

from django.db.models import Q
from asgiref.sync import sync_to_async

from .models import MicroserviceBot, Trade
from .xtb_manager import xtb_manager, instrument_prices

# Słownik: bot_id -> asyncio.Lock (aby uniknąć kolizji w obsłudze jednego bota)
_bot_locks = defaultdict(asyncio.Lock)

def _timestamp():
    """Generuje aktualny timestamp (UTC)."""
    return datetime.datetime.utcnow().isoformat()

def get_current_price(bot_id: int, symbol: str):
    """
    Pobiera bieżącą cenę instrumentu z globalnego słownika `instrument_prices`.
    Możesz zwracać np. (ask + bid)/2 lub cokolwiek innego.
    """
    data = instrument_prices.get((bot_id, symbol), {})
    ask = data.get("ask")
    bid = data.get("bid")
    if ask is not None and bid is not None:
        return (ask + bid) / 2
        #return 17.96
        #return 15.96
        #return 12.48
        #return 10.92
        #return 9.36
        #return 7.80
        #return 6.24


    return None


async def monitor_price(bot_id: int, symbol: str, interval: float = 0.5):
    """
    Task monitorujący cenę. Gdy cena się zmieni, wywołuje logikę handlu (_apply_levels_logic).
    """
    last_price = None
    while True:
        try:
            current_price = get_current_price(bot_id, symbol)
            if current_price is not None:
                if current_price != last_price:
                    # Blokada per-bot, by nie wchodzić w kolizje
                    async with _bot_locks[bot_id]:
                        # Pobieramy bota z bazy
                        bot = await sync_to_async(MicroserviceBot.objects.get)(pk=bot_id)
                        await _apply_levels_logic(bot, current_price)
                    last_price = current_price
                    print(f"[{_timestamp()}] [Bot {bot_id}] Updated price: {current_price}")
                else:
                    print(f"[{_timestamp()}] [Bot {bot_id}] Price unchanged: {current_price}")
        except Exception as e:
            print(f"[ERROR] [Bot {bot_id}] Error in monitoring price: {e}")
            await asyncio.sleep(5)  # Poczekaj chwilę i spróbuj ponownie

        await asyncio.sleep(interval)


async def _apply_levels_logic(bot: MicroserviceBot, current_price: float):
    """
    Główna logika *grid*:
    - Mamy listę poziomów lv1..lvN i mapę sell_levels: np. lv3 -> lv2.
    - W PASMIE SPRZEDAŻY (top->down) sprawdzamy, czy cena jest na tyle wysoka, by sprzedać otwarty poziom.
    - W PASMIE KUPNA (down->top) sprawdzamy, czy cena jest na tyle niska, by otworzyć (kupić) dany poziom.
    - Dodatkowo, jeśli cena przekroczy lv1, zamykamy wszystkie otwarte pozycje i kończymy bota (FINISHED).
    """

    # 1. Jeśli bot nie ma levels_data albo nie jest RUNNING, nic nie robimy
    if bot.status != "RUNNING":
        return
    if not bot.levels_data:
        return

    data = json.loads(bot.levels_data)
    flags = data.get("flags", {})
    caps = data.get("caps", {})
    buy_price = data.get("buy_price", {})
    buy_volume = data.get("buy_volume", {})
    sell_levels = data.get("sell_levels", {})

    # 2. Odczyt kursu USDPLN (dla ewentualnej konwersji)
    usdpln_rate = instrument_prices.get((bot.id, "USDPLN"), {}).get("bid", 1.0)
    if bot.account_currency != bot.asset_currency and abs(usdpln_rate - 1.0) < 1e-9:
        # Brak poprawnego kursu => pomijamy logikę
        return

    # 3. Zbierz poziomy lvX -> cena
    lv_prices = {}
    for k, v in data.items():
        if k.startswith("lv") and isinstance(v, (int, float)):
            lv_prices[k] = float(v)

    # == SELL PASS (od najwyższej ceny do najniższej) ==
    sorted_lv_desc = sorted(lv_prices.items(), key=lambda x: x[1], reverse=True)
    for lv_buy, lv_buy_price in sorted_lv_desc:
        if lv_buy not in sell_levels:
            continue
        lv_sell = sell_levels[lv_buy]  # np. lv4 -> lv3
        lv_sell_price = lv_prices.get(lv_sell, 0.0)

        if flags.get(f"{lv_buy}_bought") and not flags.get(f"{lv_buy}_in_progress"):
            if current_price >= lv_sell_price:
                flags[f"{lv_buy}_in_progress"] = True
                bot.levels_data = json.dumps(data)
                await sync_to_async(bot.save)()

                await sell_level(bot, lv_buy, current_price, data, usdpln_rate)

                flags[f"{lv_buy}_in_progress"] = False
                bot.levels_data = json.dumps(data)
                await sync_to_async(bot.save)()

    # == BUY PASS (od najniższej ceny do najwyższej) ==
    sorted_lv_asc = sorted(lv_prices.items(), key=lambda x: x[1])
    for lv_buy, lv_buy_price in sorted_lv_asc:
        if not flags.get(f"{lv_buy}_bought") and not flags.get(f"{lv_buy}_in_progress"):
            if current_price <= lv_buy_price:
                flags[f"{lv_buy}_in_progress"] = True
                bot.levels_data = json.dumps(data)
                await sync_to_async(bot.save)()

                await buy_level(bot, lv_buy, current_price, data, usdpln_rate)

                flags[f"{lv_buy}_in_progress"] = False
                bot.levels_data = json.dumps(data)
                await sync_to_async(bot.save)()

    # 4. Zapisujemy dotychczasowe zmiany (bo w kolejnym kroku możemy coś modyfikować)
    bot.levels_data = json.dumps(data)
    await sync_to_async(bot.save)()

    # 5. Dodatkowa logika: jeśli current_price > lv1 => zamykamy wszystkie otwarte pozycje i kończymy bota
    lv1_price = lv_prices.get("lv1")
    if lv1_price and current_price > lv1_price:
        # Znajdź wszystkie poziomy, które są otwarte
        for lv_buy, lv_buy_price in lv_prices.items():
            if flags.get(f"{lv_buy}_bought") and not flags.get(f"{lv_buy}_in_progress"):
                # Oznacz poziom jako "w trakcie" zamykania, aby uniknąć kolizji
                flags[f"{lv_buy}_in_progress"] = True
                bot.levels_data = json.dumps(data)
                await sync_to_async(bot.save)()

                # Sprzedaj
                await sell_level(bot, lv_buy, current_price, data, usdpln_rate)

                flags[f"{lv_buy}_in_progress"] = False
                bot.levels_data = json.dumps(data)
                await sync_to_async(bot.save)()

        # Po zamknięciu wszystkich pozycji ustawiamy status bota na FINISHED
        bot.status = 'FINISHED'
        bot.levels_data = json.dumps(data)
        await sync_to_async(bot.save)()


async def sell_level(bot: MicroserviceBot, lv_buy: str, current_price: float, data: dict, usdpln_rate: float):
    """
    Pomocnicza funkcja do sprzedawania poziomu lv_buy (cmd=1).
    """
    flags = data["flags"]
    caps = data["caps"]
    buy_price = data["buy_price"]
    buy_volume = data["buy_volume"]

    vol = float(buy_volume.get(lv_buy, 0.0))
    if vol <= 1e-9:
        # Nic do sprzedania
        flags[f"{lv_buy}_bought"] = False
        flags[f"{lv_buy}_sold"] = True
        return

    resp = await xtb_manager.trade_bot(bot.id, bot.instrument, vol, cmd=1)  # SELL
    if resp.get("status"):
        open_p = float(buy_price.get(lv_buy, 0.0))
        profit_asset = (current_price - open_p) * vol
        profit_acc = profit_asset
        if bot.account_currency != bot.asset_currency:
            profit_acc = profit_asset * usdpln_rate

        # Odejmij 2% od zysku jako zabezpieczenie przed spreadem i innymi kosztami
        profit_acc_with_fee = profit_acc * 0.98  # 2% odjęte od zysku

        # Dołóż zysk (po odjęciu 2%) do puli lv_buy
        caps[lv_buy] = float(caps.get(lv_buy, 0.0)) + profit_acc_with_fee

        # Oznacz, że już nie mamy pozycji
        flags[f"{lv_buy}_bought"] = False
        flags[f"{lv_buy}_sold"] = True

        # Znajdź w DB transakcję OPEN i zamknij
        trade_qs = await sync_to_async(Trade.objects.filter)(bot=bot, level=lv_buy, status='OPEN')
        if await sync_to_async(trade_qs.exists)():
            t = await sync_to_async(trade_qs.first)()
            t.close_price = Decimal(str(current_price))
            t.profit = Decimal(str(profit_acc_with_fee))  # Zapisujemy zysk po odjęciu 2%
            t.close_time = datetime.datetime.utcnow()
            t.status = 'SOLD'
            await sync_to_async(t.save)()
        else:
            # Na wypadek gdyby nie było w bazie
            await sync_to_async(Trade.objects.create)(
                bot=bot,
                level=lv_buy,
                open_price=Decimal(str(open_p)),
                close_price=Decimal(str(current_price)),
                profit=Decimal(str(profit_acc_with_fee)),  # Zapisujemy zysk po odjęciu 2%
                status='SOLD'
            )
        print(f"[{_timestamp()}] [Bot {bot.id}] SELL {lv_buy}, volume={vol}, profit={profit_acc_with_fee:.2f} (after 2% fee)")
    else:
        print(f"[{_timestamp()}] [Bot {bot.id}] SELL {lv_buy} failed => {resp}")

async def buy_level(bot: MicroserviceBot, lv_buy: str, current_price: float, data: dict, usdpln_rate: float):
    """
    Pomocnicza funkcja do kupowania poziomu lv_buy (cmd=0).
    """
    flags = data["flags"]
    caps = data["caps"]
    buy_price = data["buy_price"]
    buy_volume = data["buy_volume"]

    portion_acc = float(caps.get(lv_buy, 0.0))  # kapitał w walucie konta
    if portion_acc <= 1e-9:
        # Brak środków? nic nie kupujemy
        return

    portion_asset = portion_acc
    if bot.account_currency != bot.asset_currency:
        portion_asset = portion_acc / usdpln_rate

    vol = round(portion_asset / current_price, 4)
    if vol <= 1e-9:
        return

    resp = await xtb_manager.trade_bot(bot.id, bot.instrument, vol, cmd=0)  # BUY
    if resp.get("status"):
        buy_price[lv_buy] = float(current_price)
        buy_volume[lv_buy] = float(vol)
        flags[f"{lv_buy}_bought"] = True
        flags[f"{lv_buy}_sold"] = False

        # Dodaj wpis w modelu Trade
        await sync_to_async(Trade.objects.create)(
            bot=bot,
            level=lv_buy,
            open_price=Decimal(str(current_price)),
            status='OPEN'
        )
        print(f"[{_timestamp()}] [Bot {bot.id}] BUY {lv_buy}, volume={vol}")
    else:
        print(f"[{_timestamp()}] [Bot {bot.id}] BUY {lv_buy} failed => {resp}")


async def run_main_loop():
    """
    Główna pętla:
      - co jakiś czas sprawdzamy, które boty są RUNNING,
      - rozłączamy te, które już nie są RUNNING,
      - podłączamy nowe i uruchamiamy monitorowanie ich cen.
    """
    while True:
        # Pobierz listę botów w statusie RUNNING
        bots = await sync_to_async(list)(MicroserviceBot.objects.filter(status='RUNNING'))
        active_bot_ids = {bot.id for bot in bots}

        # Odłącz boty, które nie są już RUNNING
        for bot_id in list(xtb_manager._connections.keys()):
            if bot_id not in active_bot_ids:
                await xtb_manager.disconnect_bot(bot_id)
                print(f"[{_timestamp()}] [Bot {bot_id}] Disconnected due to inactivity.")

        # Podłącz nowe boty (jeszcze nieposiadające połączenia w xtb_manager)
        for bot in bots:
            if bot.id not in xtb_manager._connections:
                ok = await xtb_manager.connect_bot(bot.id)
                if ok:
                    print(f"[{_timestamp()}] [Bot {bot.id}] XTB connected.")
                    # Uruchamiamy task monitor_price, by nasłuchiwał zmian ceny
                    asyncio.create_task(monitor_price(bot.id, bot.instrument))
                else:
                    print(f"[{_timestamp()}] [Bot {bot.id}] Failed to connect.")

        await asyncio.sleep(10)


def start_bots_worker():
    """
    Uruchamia w osobnym wątku asyncio.run(run_main_loop()).
    Dzięki temu Django nie blokuje się na pętli asynchronicznej.
    """
    import threading

    def run_loop():
        asyncio.run(run_main_loop())

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()

