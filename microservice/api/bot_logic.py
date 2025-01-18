import asyncio
import json
from decimal import Decimal
import datetime

from django.db.models import Q
from asgiref.sync import sync_to_async

from .models import MicroserviceBot
from .xtb_manager import xtb_manager, instrument_prices


def _timestamp():
    """Generuje aktualny timestamp."""
    return datetime.datetime.utcnow().isoformat()


def get_current_price(bot_id: int, symbol: str):
    data = instrument_prices.get((bot_id, symbol), {})  # <-- poprawione
    ask = data.get("ask")
    bid = data.get("bid")
    if ask is not None and bid is not None:
        return (ask + bid)/2
    return None



async def monitor_price(bot_id: int, symbol: str, interval: float = 0.5):
    last_price = None
    while True:
        try:
            current_price = get_current_price(bot_id, symbol)
            if current_price is not None:
                if current_price != last_price:
                    bot = await sync_to_async(MicroserviceBot.objects.get)(pk=bot_id)
                    await _apply_levels_logic(bot, current_price)
                    last_price = current_price
                    print(f"[{_timestamp()}] [Bot {bot_id}] Updated price: {current_price}")
                else:
                    print(f"[{_timestamp()}] [Bot {bot_id}] Price unchanged: {current_price}")

        except Exception as e:
            print(f"[ERROR] [Bot {bot_id}] Error in monitoring price: {e}")
            await asyncio.sleep(5)  # Opóźnienie przed kolejną próbą

        await asyncio.sleep(interval)


import asyncio

async def _apply_levels_logic(bot: MicroserviceBot, current_price: float):
    try:
        if not bot.levels_data:
            return

        data = json.loads(bot.levels_data)
        flags = data.get("flags", {})
        caps = data.get("caps", {})
        buy_price = data.get("buy_price", {})
        buy_volume = data.get("buy_volume", {})

        usdpln_rate = instrument_prices.get((bot.id, "USDPLN"), {}).get("bid", 1)

        # 📉 SPRAWDZENIE PRZEKROCZENIA LV1
        lv1_price = data.get("lv1", 0)
        if current_price > lv1_price:
            print(f"[{_timestamp()}] [Bot {bot.id}] Cena przekroczyła poziom lv1. Bot zakończy działanie po zamknięciu pozycji.")

            # 🛑 SPRZEDAŻ WSZYSTKICH OTWARTYCH POZYCJI
            for lv in sorted([k for k in data.keys() if k.startswith('lv')], key=lambda x: int(x[2:])):
                bf, sf = f"{lv}_bought", f"{lv}_sold"

                # Jeśli pozycja kupiona i jeszcze nie sprzedana
                if flags.get(bf) and not flags.get(sf):
                    volume = buy_volume.get(lv, 0.0)
                    if volume > 0:
                        response = await xtb_manager.trade_bot(bot.id, bot.instrument, volume, cmd=1)  # SELL
                        if response.get('status'):
                            flags[sf] = True  # Aktualizacja flagi sprzedanej pozycji
                            print(f"[SELL] Bot {bot.id}: Sprzedał otwartą pozycję na {lv}, wolumen {volume}")
                        else:
                            print(f"[ERROR] Bot {bot.id}: Nie udało się sprzedać {lv}, wolumen {volume}")

            # 🔒 ZAKOŃCZENIE DZIAŁANIA BOTA
            bot.status = 'FINISHED'
            bot.levels_data = json.dumps(data)
            await sync_to_async(bot.save)()
            print(f"[{_timestamp()}] [Bot {bot.id}] Wszystkie pozycje zamknięte. Status zmieniony na FINISHED.")
            return  # Przerwanie działania bota po sprzedaży wszystkiego

        # 📈 STANDARDOWA LOGIKA HANDLU
        for lv in sorted([k for k in data.keys() if k.startswith('lv')], key=lambda x: int(x[2:])):
            price_lv = data[lv]
            bf, sf = f"{lv}_bought", f"{lv}_sold"
            in_progress = f"{lv}_in_progress"

            lower_bound = price_lv * 0.995
            upper_bound = price_lv * 1.005

            # KUPNO z blokadą
            if not flags.get(bf) and not flags.get(in_progress) and lower_bound <= current_price <= upper_bound:
                flags[in_progress] = True
                portion = caps[lv]
                adjusted_portion = portion / usdpln_rate if bot.account_currency != bot.asset_currency else portion
                volume = round(adjusted_portion / current_price, 3)

                response = await xtb_manager.trade_bot(bot.id, bot.instrument, volume, cmd=0)  # BUY
                if response.get('status'):
                    buy_price[lv] = current_price
                    buy_volume[lv] = volume
                    flags[bf] = True
                    print(f"[BUY] Bot {bot.id}: Kupił na {lv} za {current_price}, wolumen {volume}")
                flags[in_progress] = False

            # SPRZEDAŻ z reinwestycją
            if flags.get(bf) and not flags.get(sf) and buy_price[lv] > 0:
                growth_percent = ((current_price - buy_price[lv]) / buy_price[lv]) * 100.0
                if growth_percent >= float(bot.percent):
                    volume = buy_volume[lv]
                    response = await xtb_manager.trade_bot(bot.id, bot.instrument, volume, cmd=1)  # SELL
                    if response.get('status'):
                        flags[sf] = True
                        profit = (current_price - buy_price[lv]) * volume
                        caps[lv] += profit
                        print(f"[SELL] Bot {bot.id}: Sprzedał na {lv} za {current_price}, zysk: {profit}")

        # Aktualizacja danych w bazie
        data["flags"] = flags
        data["buy_price"] = buy_price
        data["buy_volume"] = buy_volume
        data["caps"] = caps

        bot.levels_data = json.dumps(data)
        await sync_to_async(bot.save)()

    except Exception as e:
        print(f"[ERROR] Bot {bot.id}: Błąd w logice poziomów - {e}")




async def run_main_loop():
    while True:
        bots = await sync_to_async(list)(MicroserviceBot.objects.filter(status='RUNNING'))
        active_bot_ids = {bot.id for bot in bots}

        # Odłącz boty, które są nieaktywne
        for bot_id in list(xtb_manager._connections.keys()):
            if bot_id not in active_bot_ids:
                await xtb_manager.disconnect_bot(bot_id)
                print(f"[{_timestamp()}] [Bot {bot_id}] Disconnected due to inactivity.")

        # Podłącz nowe boty
        for bot in bots:
            if bot.id not in xtb_manager._connections:
                ok = await xtb_manager.connect_bot(bot.id)
                if ok:
                    print(f"[{_timestamp()}] [Bot {bot.id}] XTB connected.")
                    asyncio.create_task(monitor_price(bot.id, bot.instrument))
                else:
                    print(f"[{_timestamp()}] [Bot {bot.id}] Failed to connect.")

        await asyncio.sleep(10)



def start_bots_worker():
    """
    Uruchamia w osobnym wątku asyncio.run(run_main_loop()).
    """
    import threading

    def run_loop():
        asyncio.run(run_main_loop())

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()

