# bnbgrid/bnb_manager.py

import time
import math
import decimal
from decimal import Decimal, ROUND_DOWN
from django.utils import timezone

from .models import BnbBot, BnbTrade
from binance.client import Client  # jeśli używamy python-binance
from binance.exceptions import BinanceAPIException

FEE_RATE = Decimal("0.0011")  # 0.11% = 0.0011 w zapisie dziesiętnym


def get_binance_client(bot: BnbBot) -> Client:
    """
    Tworzy klienta Binance używając kluczy zapisanych w obiekcie bota.
    """
    api_key = bot.binance_api_key or ""
    api_secret = bot.get_binance_api_secret() or ""
    return Client(api_key, api_secret)


def fetch_symbol_price(client: Client, symbol: str) -> Decimal:
    """
    Pobiera aktualną cenę z Binance (ticker).
    """
    # W python-binance np.:
    ticker = client.get_symbol_ticker(symbol=symbol)
    current_price = Decimal(ticker["price"])
    return current_price
    #current_price = 7.00
    #return current_price
    #return 5.500
    #return 4.511
    #return 3.90


def place_market_order(client: Client, symbol: str, side: str, quantity: Decimal) -> dict:
    """
    Składa zlecenie rynkowe (BUY lub SELL).
    - BUY: 'quoteOrderQty' (podajemy kwotę w USDT, np. 100.00)
    - SELL: 'quantity' (podajemy liczbę w walucie bazowej, np. 0.0123 BTC)
    
    Dla BUY obcinamy do 2 miejsc po przecinku,
    dla SELL obcinamy do 1 miejsca po przecinku.
    """
    try:
        if side.upper() == "BUY":
            # Market BUY: obcinamy do 2 miejsc po przecinku
            buy_qty = quantity.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            order = client.create_order(
                symbol=symbol,
                side="BUY",
                type="MARKET",
                quoteOrderQty=str(buy_qty)  # ilość w walucie kwotowanej (np. USDT)
            )
        else:
            # Market SELL: obcinamy wolumen do 1 miejsca po przecinku
            sell_qty = quantity.quantize(Decimal("0.1"), rounding=ROUND_DOWN)
            order = client.create_order(
                symbol=symbol,
                side="SELL",
                type="MARKET",
                quantity=str(sell_qty)  # ilość w walucie bazowej (np. BTC)
            )
        return order

    except BinanceAPIException as e:
        print(f"[place_market_order] BinanceAPIException: {e}")
        return {}


def calculate_profit(buy_price: Decimal, sell_price: Decimal, volume: Decimal) -> Decimal:
    """
    Liczy zysk: (sell_price - buy_price) * volume, następnie odejmuje prowizję 0.11%.
    """
    gross = (sell_price - buy_price) * volume
    fee = gross * FEE_RATE
    net = gross - fee
    return net


def run_grid_bot(bot_id: int):
    """
    Funkcja, która może być wywoływana co pewien interwał (cron, Celery, cokolwiek),
    by aktualizować stany i ewentualnie wykonywać transakcje.
    """
    try:
        bot = BnbBot.objects.get(id=bot_id, status="RUNNING")
    except BnbBot.DoesNotExist:
        return  # Bot nie istnieje lub nie jest w statusie RUNNING

    # 1) Pobierz aktualną cenę z Binance
    client = get_binance_client(bot)
    current_price = fetch_symbol_price(client, bot.symbol)

    levels_data = bot.get_levels_data()    # np. {"lv1": 5.655, "lv2": 5.372, ..., "caps": {...}, "sell_levels": {...}}
    runtime_data = bot.get_runtime_data()  # np. {"flags": {"lv1_bought": False, ...}, "buy_price": {"lv1":0}, "buy_volume": {"lv1":0}}

    if not levels_data or not runtime_data:
        return

    # Wyodrębnij listę poziomów (np. lv1, lv2, lv3...)
    level_names = sorted([k for k in levels_data.keys() if k.startswith("lv")],
                         key=lambda x: int(x.replace("lv", "")))

    if "lv1" not in level_names:
        # Jeśli nie ma lv1, nie ma sensu kontynuować
        return

    lv1_price = Decimal(str(levels_data["lv1"]))

    # -----------------------------------------------------
    # SPRAWDZENIE, CZY current_price > lv1
    # Jeśli tak - zamykamy wszystkie pozycje i kończymy bota.
    # -----------------------------------------------------
    if current_price > lv1_price * Decimal("1.1"):
        print(f"[run_grid_bot] Bot {bot.id}: current_price={current_price} > lv1={lv1_price}, closing all and FINISHING.")

        for lv_name in level_names:
            lv_bought = runtime_data["flags"].get(f"{lv_name}_bought", False)
            lv_in_progress = runtime_data["flags"].get(f"{lv_name}_in_progress", False)
            buy_price_stored = Decimal(runtime_data["buy_price"].get(lv_name, "0"))
            buy_volume_stored = Decimal(runtime_data["buy_volume"].get(lv_name, "0"))

            # Jeżeli mamy pozycję kupioną (bought == True) i nie jest w trakcie in_progress -> zamykamy SELL
            if lv_bought and not lv_in_progress and buy_volume_stored > 0:
                runtime_data["flags"][f"{lv_name}_in_progress"] = True

                order_resp = place_market_order(client, bot.symbol, "SELL", buy_volume_stored)
                if not order_resp:
                    # Błąd w składaniu zlecenia – reset flag, przechodzimy dalej
                    runtime_data["flags"][f"{lv_name}_in_progress"] = False
                    continue

                # Oblicz średnią cenę sprzedaży i zysk
                fills = order_resp.get("fills", [])
                executed_qty = Decimal("0")
                fill_cost = Decimal("0")

                for f in fills:
                    fill_price = Decimal(f["price"])
                    fill_qty = Decimal(f["qty"])
                    executed_qty += fill_qty
                    fill_cost += fill_price * fill_qty

                average_price = fill_cost / executed_qty if executed_qty > 0 else Decimal("0")
                profit = calculate_profit(buy_price_stored, average_price, executed_qty)

                # Zapisz transakcję SELL
                BnbTrade.objects.create(
                    bot=bot,
                    level=lv_name,
                    side="SELL",
                    quantity=executed_qty,
                    open_price=buy_price_stored,
                    close_price=average_price,
                    profit=profit,
                    binance_order_id=order_resp.get("orderId", ""),
                    status="FILLED",
                    sell_type="MARKET"
                )

                # Zwiększamy kapitał poziomu o profit (opcjonalnie)
                new_cap = Decimal(levels_data["caps"][lv_name]) + profit
                levels_data["caps"][lv_name] = str(new_cap)

                # Reset flag
                runtime_data["flags"][f"{lv_name}_in_progress"] = False
                runtime_data["flags"][f"{lv_name}_bought"] = False
                runtime_data["buy_price"][lv_name] = "0"
                runtime_data["buy_volume"][lv_name] = "0"

        # Ustawiamy status bota na FINISHED i zapisujemy
        bot.status = "FINISHED"
        bot.save_levels_data(levels_data)
        bot.save_runtime_data(runtime_data)
        bot.save()
        return  # Koniec działania

    # -----------------------------------------------
    # JEŚLI current_price <= lv1_price -> standardowa logika grid
    # -----------------------------------------------

    # 2) Przejrzyj pozostałe poziomy
    for lv_name in level_names:
        level_price = Decimal(levels_data[lv_name])
        capital_for_level = Decimal(levels_data["caps"].get(lv_name, 0))  # kapitał w USDT (zakładam)

        lv_bought = runtime_data["flags"].get(f"{lv_name}_bought", False)
        lv_in_progress = runtime_data["flags"].get(f"{lv_name}_in_progress", False)
        buy_price_stored = Decimal(runtime_data["buy_price"].get(lv_name, "0"))
        buy_volume_stored = Decimal(runtime_data["buy_volume"].get(lv_name, "0"))

        # -----------------------------------------------------
        # A) Logika KUPNA
        # -----------------------------------------------------
        if current_price < level_price and not lv_bought and not lv_in_progress:
            runtime_data["flags"][f"{lv_name}_in_progress"] = True

            order_resp = place_market_order(client, bot.symbol, "BUY", capital_for_level)
            if not order_resp:
                runtime_data["flags"][f"{lv_name}_in_progress"] = False
                continue

            fills = order_resp.get("fills", [])
            executed_qty = Decimal("0")
            fill_cost = Decimal("0")

            for f in fills:
                fill_price = Decimal(f["price"])
                fill_qty = Decimal(f["qty"])
                executed_qty += fill_qty
                fill_cost += fill_price * fill_qty

            average_price = fill_cost / executed_qty if executed_qty > 0 else Decimal("0")

            BnbTrade.objects.create(
                bot=bot,
                level=lv_name,
                side="BUY",
                quantity=executed_qty,
                open_price=average_price,
                close_price=None,
                profit=None,
                binance_order_id=order_resp.get("orderId", ""),
                status="FILLED",
                buy_type="MARKET"
            )

            runtime_data["flags"][f"{lv_name}_in_progress"] = False
            runtime_data["flags"][f"{lv_name}_bought"] = True
            runtime_data["buy_price"][lv_name] = str(average_price)
            runtime_data["buy_volume"][lv_name] = str(executed_qty)

        # -----------------------------------------------------
        # B) Logika SPRZEDAŻY
        # -----------------------------------------------------
        sell_lv_name = levels_data["sell_levels"].get(lv_name) if "sell_levels" in levels_data else None
        if lv_bought and not lv_in_progress and sell_lv_name:
            sell_target_price = Decimal(levels_data[sell_lv_name])

            if current_price >= sell_target_price:
                runtime_data["flags"][f"{lv_name}_in_progress"] = True

                order_resp = place_market_order(client, bot.symbol, "SELL", buy_volume_stored)
                if not order_resp:
                    runtime_data["flags"][f"{lv_name}_in_progress"] = False
                    continue

                fills = order_resp.get("fills", [])
                executed_qty = Decimal("0")
                fill_cost = Decimal("0")

                for f in fills:
                    fill_price = Decimal(f["price"])
                    fill_qty = Decimal(f["qty"])
                    executed_qty += fill_qty
                    fill_cost += fill_price * fill_qty

                average_price = fill_cost / executed_qty if executed_qty > 0 else Decimal("0")
                profit = calculate_profit(buy_price_stored, average_price, executed_qty)

                BnbTrade.objects.create(
                    bot=bot,
                    level=lv_name,
                    side="SELL",
                    quantity=executed_qty,
                    open_price=buy_price_stored,
                    close_price=average_price,
                    profit=profit,
                    binance_order_id=order_resp.get("orderId", ""),
                    status="FILLED",
                    sell_type="MARKET"
                )

                new_cap = Decimal(levels_data["caps"][lv_name]) + profit
                levels_data["caps"][lv_name] = str(new_cap)

                runtime_data["flags"][f"{lv_name}_in_progress"] = False
                runtime_data["flags"][f"{lv_name}_bought"] = False
                runtime_data["buy_price"][lv_name] = "0"
                runtime_data["buy_volume"][lv_name] = "0"

    # 3) Zapisz zmodyfikowane dane w bazie
    bot.save_levels_data(levels_data)
    bot.save_runtime_data(runtime_data)
    bot.save()
