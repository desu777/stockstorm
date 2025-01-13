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


def get_current_price(symbol: str):
    """
    Zwraca aktualną cenę instrumentu pobraną z instrument_prices.
    """
    data = instrument_prices.get(symbol, {})
    ask = data.get("ask")
    bid = data.get("bid")
    if ask is not None and bid is not None:
        return (ask + bid) / 2
    return None


async def monitor_price(bot_id: int, symbol: str, interval: float = 0.5):
    """
    Monitoruje cenę instrumentu co `interval` sekund i aktualizuje dane tylko, gdy cena się zmienia.
    """
    last_price = None

    while True:
        current_price = get_current_price(symbol)
        if current_price is not None:
            # Sprawdzamy, czy cena się zmieniła
            if current_price != last_price:
                bot = await sync_to_async(MicroserviceBot.objects.get)(pk=bot_id)
                await _apply_levels_logic(bot, current_price)
                last_price = current_price  # Aktualizujemy ostatnią zapisaną cenę
                print(f"[{_timestamp()}] [Bot {bot_id}] Updated price: {current_price}")
            else:
                print(f"[{_timestamp()}] [Bot {bot_id}] Price unchanged: {current_price}")
        else:
            print(f"[{_timestamp()}] [Bot {bot_id}] Brak aktualnej ceny dla {symbol}")

        await asyncio.sleep(interval)  # Sprawdzaj co 0.5 sekundy


async def _apply_levels_logic(bot: MicroserviceBot, current_price: float):
    """
    Sprawdza, czy trzeba kupić/sprzedać według 'levels_data'.
    Jeśli tak, wywołuje trade_bot(...) w xtb_manager.
    """
    if not bot.levels_data:
        return

    data = json.loads(bot.levels_data)
    flags = data.get("flags", {})
    caps = data.get("caps", {})
    buy_price = data.get("buy_price", {})

    levels_keys = [k for k in data.keys() if k.startswith('lv')]
    levels_keys.sort(key=lambda x: int(x[2:]))

    if not levels_keys:
        return

    target_profit_percent = float(bot.percent)

    for lv in levels_keys:
        price_lv = data[lv]
        bf = f"{lv}_bought"
        sf = f"{lv}_sold"

        if lv not in caps:
            caps[lv] = 0
        if lv not in buy_price:
            buy_price[lv] = 0

        # ###### KUPNO ######
        if current_price <= price_lv and not flags.get(bf):
            if caps[lv] == 0:
                total_lv_count = len(levels_keys)
                portion = float(bot.capital) / total_lv_count
                caps[lv] = round(portion, 2)

            buy_vol = round(caps[lv] / current_price, 3)
            # Kupno w XTB
            await xtb_manager.trade_bot(
                bot_id=bot.id,
                symbol=bot.instrument,
                price=current_price,
                volume=buy_vol,
                cmd=0  # BUY
            )
            buy_price[lv] = current_price
            flags[bf] = True
            print(f"[{_timestamp()}] [Bot {bot.id}] BUY at {lv} price={current_price} vol={buy_vol}")

        # ###### SPRZEDAŻ ######
        if flags.get(bf) and not flags.get(sf) and buy_price[lv] > 0:
            growth_percent = ((current_price - buy_price[lv]) / buy_price[lv]) * 100.0
            if growth_percent >= target_profit_percent:
                profit = caps[lv] * (growth_percent / 100.0)
                caps[lv] += round(profit, 2)  # reinwestycja

                sell_vol = round(caps[lv] / current_price, 3)
                await xtb_manager.trade_bot(
                    bot_id=bot.id,
                    symbol=bot.instrument,
                    price=current_price,
                    volume=sell_vol,
                    cmd=1  # SELL
                )
                flags[sf] = True
                print(
                    f"[{_timestamp()}] [Bot {bot.id}] SELL at {lv} price={current_price}, "
                    f"growth={growth_percent:.2f}%, profit={profit:.2f}, caps={caps[lv]:.2f}"
                )

    data["flags"] = flags
    data["caps"] = caps
    data["buy_price"] = buy_price

    # Gdy cena >= max_price => FINISHED
    if current_price >= float(bot.max_price):
        bot.status = 'FINISHED'
        print(f"[{_timestamp()}] [Bot {bot.id}] Bot finished - price >= max_price")

    bot.levels_data = json.dumps(data)
    await sync_to_async(bot.save)()


async def run_main_loop():
    """
    Główna korutyna:
    - Co pewien czas szuka botów w statusie RUNNING
    - Próbuje je łączyć z XTB i uruchamia monitorowanie ceny.
    """
    while True:
        bots = await sync_to_async(list)(MicroserviceBot.objects.filter(status='RUNNING'))
        for bot in bots:
            ok = await xtb_manager.connect_bot(bot.id)
            if ok:
                print(f"[{_timestamp()}] [Bot {bot.id}] XTB connected.")
                asyncio.create_task(monitor_price(bot.id, bot.instrument))
            else:
                print(f"[{_timestamp()}] [Bot {bot.id}] connect failed or already connected.")
        await asyncio.sleep(60)  # Sprawdzaj co 60 sekund


def start_bots_worker():
    """
    Uruchamia w osobnym wątku asyncio.run(run_main_loop()).
    """
    import threading

    def run_loop():
        asyncio.run(run_main_loop())

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()

