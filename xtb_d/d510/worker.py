# worker.py
import asyncio
import threading
from collections import defaultdict

from asgiref.sync import sync_to_async
from django.utils import timezone

from .models import BotD10
from .xtb_manager import xtb_manager, instrument_prices
from .d10_manager import reapply_logic_once


# Słownik globalny: klucz = bot_id, wartość = asyncio.Lock()
_bot_locks = defaultdict(asyncio.Lock)

# Trzymamy bieżące zadania monitorujące
_monitor_tasks = {}

# Flaga, żeby start_worker() nie uruchamiał się wielokrotnie
_worker_started = False


async def bot_monitor_loop(bot_id: int):
    """
    Co kilka sekund:
      - łączy się z XTB
      - pobiera aktualną cenę (ask, bid)
      - wchodzi w async with _bot_locks[bot_id], wywołuje reapply_logic_once
    """
    print(f"[worker] Start monitoring bot {bot_id}")
    while True:
        try:
            # Łączenie się z XTB
            await xtb_manager.connect_bot(bot_id)

            # Pobranie symbolu i ceny
            bot = await sync_to_async(BotD10.objects.get)(pk=bot_id)
            symbol = bot.instrument

            pinfo = instrument_prices.get((bot_id, symbol), {})
            ask = pinfo.get("ask", 0.0)
            bid = pinfo.get("bid", 0.0)
            if ask > 0 and bid > 0:
                current_price = (ask + bid) / 2
                #current_price = 87799.86
                # Ochrona lockiem
                async with _bot_locks[bot_id]:
                    await reapply_logic_once(bot_id, current_price)

        except asyncio.CancelledError:
            print(f"[worker] Bot {bot_id} monitor cancelled.")
            return
        except Exception as e:
            print(f"[worker] Bot {bot_id} error => {e}")

        await asyncio.sleep(3)


async def main_loop():
    """
    Główna pętla workerów - co 10s sprawdza 
    boty o statusie != FINISHED/ERROR i tworzy/usuwa zadania monitorujące.
    """
    while True:
        running_bots = await sync_to_async(list)(
            BotD10.objects.exclude(status__in=['FINISHED', 'ERROR'])
        )
        running_ids = [b.id for b in running_bots]

        # Dodaj nowy task monitorujący, jeśli nie istnieje
        for b_id in running_ids:
            if b_id not in _monitor_tasks:
                _monitor_tasks[b_id] = asyncio.create_task(bot_monitor_loop(b_id))

        # Anuluj te, które już nie są w trybie "monitor"
        for bot_id in list(_monitor_tasks.keys()):
            if bot_id not in running_ids:
                _monitor_tasks[bot_id].cancel()
                del _monitor_tasks[bot_id]

        await asyncio.sleep(10)


def start_worker():
    """
    Uruchamia main_loop w osobnym wątku (jako daemon) - tylko raz.
    """
    global _worker_started
    if _worker_started:
        print("[worker] Worker already started -> skipping.")
        return
    _worker_started = True

    def run():
        asyncio.run(main_loop())

    t = threading.Thread(target=run, daemon=True)
    t.start()
    print("[worker] Worker thread started.")


def get_bot_lock(bot_id):
    """
    Jeśli chcesz używać locka ręcznie gdzieś indziej,
    możesz importować get_bot_lock i wywołać:
       async with get_bot_lock(bot_id):
           # ...
    """
    return _bot_locks[bot_id]

