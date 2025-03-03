import json
import datetime
from decimal import Decimal

from asgiref.sync import sync_to_async

from .models import BotD10, TradeD10
from .xtb_manager import xtb_manager, instrument_prices


def generate_levels(bot: BotD10, lv1_price: float) -> dict:
    """
    Generuje lv1..lvN w dół od lv1_price z krokiem step_percent,
    aż do (lv1_price * (1 - band_percent/100)).
    """
    step = float(bot.step_percent) / 100.0
    band = float(bot.band_percent) / 100.0

    lower_bound = lv1_price * (1 - band)
    current = lv1_price
    prices_descending = [lv1_price]

    while True:
        next_p = current * (1 - step)
        if next_p < lower_bound:
            break
        prices_descending.append(next_p)
        current = next_p

    n_levels = len(prices_descending)
    if n_levels < 1:
        n_levels = 1
        prices_descending = [lv1_price]

    # KLUCZOWE: bierzemy globalne pole 'capital' z bazy (które może rosnąć)
    total_cap = float(bot.capital)
    portion = total_cap / n_levels

    data = {}
    for i, price_val in enumerate(prices_descending, start=1):
        lv_name = f"lv{i}"
        data[lv_name] = {
            "price": round(price_val, 4),
            "capital": round(portion, 2),
            "bought": False,
            "volume": 0.0
        }
    return data


async def initial_buy_lv1(bot_id: int, current_price: float):
    """
    Kup lv1 zaraz po wygenerowaniu poziomów.
    (Przykład bez if resp.get("status"), zawsze ustawia bought = True)
    """
    try:
        bot = await sync_to_async(BotD10.objects.get)(pk=bot_id)
    except BotD10.DoesNotExist:
        return

    if not bot.levels_data:
        return

    data = json.loads(bot.levels_data)
    lv1 = data.get("lv1", {})

    if lv1.get("bought", False):
        return  # juź kupione

    cap = float(lv1.get("capital", 0))
    if cap <= 0 or current_price <= 0:
        return

    volume = round(cap / current_price, 3)

    resp = await xtb_manager.trade_bot(bot_id, bot.instrument, volume, cmd=0)
    print(f"[initial_buy_lv1] Bot {bot_id} trade_bot response => {resp}")

    lv1["bought"] = True
    lv1["volume"] = volume

    t = TradeD10(
        bot=bot,
        level_name="lv1",
        open_price=Decimal(str(current_price)),
        status="OPEN"
    )
    await sync_to_async(t.save)()

    data["lv1"] = lv1
    bot.levels_data = json.dumps(data)
    await sync_to_async(bot.save)()


async def reapply_logic_once(bot_id: int, current_price: float):
    """
    Główna logika bota D10:
      - jeśli bot.status=NEW => generuj lv1..lvN, kup lv1, set RUNNING
      - jeśli RUNNING => check SELL/BUY warunki
    """
    try:
        bot = await sync_to_async(BotD10.objects.get)(pk=bot_id)
    except BotD10.DoesNotExist:
        return

    if bot.status == 'NEW':
        # Generujemy poziomy na podstawie bieżącej ceny
        data = generate_levels(bot, current_price)
        bot.levels_data = json.dumps(data)
        await sync_to_async(bot.save)()

        # Kupujemy lv1
        await initial_buy_lv1(bot_id, current_price)
        
        # Zmieniamy status na RUNNING
        bot = await sync_to_async(BotD10.objects.get)(pk=bot_id)
        bot.status = 'RUNNING'
        await sync_to_async(bot.save)()
        print(f"[reapply_logic_once] Bot {bot_id} from NEW -> RUNNING (lv1 bought).")
        return

    if bot.status != 'RUNNING':
        return

    data = json.loads(bot.levels_data or "{}")
    lv1 = data.get("lv1", {})
    lv1_price = float(lv1.get("price", 0))
    lv1_bought = lv1.get("bought", False)
    lv1_volume = float(lv1.get("volume", 0))
    rise_p = float(bot.rise_percent) / 100.0

    # SELL lv1 if current_price >= lv1_price*(1+rise_p)
    if lv1_bought and lv1_volume > 0:
        threshold = lv1_price * (1 + rise_p)
        if current_price >= threshold:
            resp = await xtb_manager.trade_bot(bot_id, bot.instrument, lv1_volume, cmd=1)
            if resp.get("status"):
                raw_profit = (current_price - lv1_price) * lv1_volume
                profit_net = raw_profit * 0.98

                trades = await sync_to_async(list)(
                    TradeD10.objects.filter(bot=bot, level_name="lv1", status='OPEN')
                )
                if trades:
                    t = trades[0]
                    t.close_price = Decimal(str(current_price))
                    t.profit = Decimal(str(profit_net))
                    t.status = "CLOSED"
                    t.closed_at = datetime.datetime.utcnow()
                    await sync_to_async(t.save)()

                # 1) Dopisujemy zysk do globalnego bot.capital
                old_capital = float(bot.capital)
                bot.capital = Decimal(str(old_capital + profit_net))
                await sync_to_async(bot.save)()

                # 2) Zwiększamy local capital lv1 (tak jak w oryginale)
                new_cap = float(lv1["capital"]) + profit_net
                print(f"[reapply_logic_once] SELL lv1 => +{profit_net:.2f} => new lv1 capital={new_cap:.2f}")

                # Odkup lv1 na nowym poziomie
                lv1["price"] = current_price
                lv1["capital"] = new_cap
                lv1["bought"] = False
                lv1["volume"] = 0.0

                re_vol = round(new_cap / current_price, 3)
                resp2 = await xtb_manager.trade_bot(bot_id, bot.instrument, re_vol, cmd=0)
                if resp2.get("status"):
                    lv1["bought"] = True
                    lv1["volume"] = re_vol
                    t2 = TradeD10(
                        bot=bot,
                        level_name="lv1",
                        open_price=Decimal(str(current_price)),
                        status="OPEN"
                    )
                    await sync_to_async(t2.save)()
                    print(f"[reapply_logic_once] re-BUY lv1 at {current_price}, vol={re_vol}")
                else:
                    bot.status = "ERROR"
                    await sync_to_async(bot.save)()
                    print(f"[reapply_logic_once] re-BUY lv1 FAIL => {resp2}")

                # regenerujemy poziomy z uwzględnieniem powiększonego bot.capital
                new_levels = generate_levels(bot, current_price)
                new_levels["lv1"]["bought"] = lv1["bought"]
                new_levels["lv1"]["volume"] = lv1["volume"]
                data = new_levels
            else:
                bot.status = "ERROR"
                await sync_to_async(bot.save)()
                print(f"[reapply_logic_once] SELL lv1 FAIL => {resp}")

    # BUY lv2..lvN => if current_price <= lvX['price']
    for key, val in data.items():
        if key.startswith("lv") and key != "lv1":
            if not val.get("bought", False):
                cap = float(val.get("capital", 0))
                lv_price = float(val.get("price", 0))
                if cap > 0 and current_price <= lv_price:
                    buy_vol = round(cap / current_price, 3)
                    resp = await xtb_manager.trade_bot(bot_id, bot.instrument, buy_vol, cmd=0)
                    if resp.get("status"):
                        val["bought"] = True
                        val["volume"] = buy_vol
                        tr = TradeD10(
                            bot=bot,
                            level_name=key,
                            open_price=Decimal(str(current_price)),
                            status="OPEN"
                        )
                        await sync_to_async(tr.save)()
                        print(f"[reapply_logic_once] Bot {bot_id} BUY {key} at {current_price}, vol={buy_vol}")

    # SELL lv2..lvN => if current_price >= lv1_price
    new_lv1_price = float(data["lv1"]["price"])
    for key, val in data.items():
        if key.startswith("lv") and key != "lv1":
            if val.get("bought", False):
                volume = float(val.get("volume", 0))
                buy_pr = float(val.get("price", 0))
                if volume > 0 and current_price >= new_lv1_price:
                    resp = await xtb_manager.trade_bot(bot_id, bot.instrument, volume, cmd=1)
                    if resp.get("status"):
                        raw_profit = (current_price - buy_pr) * volume
                        profit_net = raw_profit * 0.98
                        qs = await sync_to_async(list)(
                            TradeD10.objects.filter(bot=bot, level_name=key, status='OPEN')
                        )
                        if qs:
                            tt = qs[0]
                            tt.close_price = Decimal(str(current_price))
                            tt.profit = Decimal(str(profit_net))
                            tt.closed_at = datetime.datetime.utcnow()
                            tt.status = "CLOSED"
                            await sync_to_async(tt.save)()

                        # 1) Dopisujemy zysk do globalnego bot.capital
                        old_capital = float(bot.capital)
                        bot.capital = Decimal(str(old_capital + profit_net))
                        await sync_to_async(bot.save)()

                        # 2) Dodajemy go również do local capital (jak w oryginale)
                        new_cap = float(val["capital"]) + profit_net
                        print(f"[reapply_logic_once] SELL {key} => +{profit_net:.2f}, new {key} capital={new_cap:.2f}")

                        val["capital"] = new_cap
                        val["bought"] = False
                        val["volume"] = 0.0
                    else:
                        bot.status = "ERROR"
                        await sync_to_async(bot.save)()
                        print(f"[reapply_logic_once] SELL {key} FAIL => {resp}")

    bot.levels_data = json.dumps(data)
    await sync_to_async(bot.save)()
