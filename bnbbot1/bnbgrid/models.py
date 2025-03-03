from django.db import models
from decimal import Decimal
import json
from cryptography.fernet import Fernet

# Przykładowy klucz szyfrujący (możesz zmienić)
FERNET_KEY = "GiLFpoI4-TzsPAheWRYytzPXuOlZVHOz5FrZsjHYZSk="
fernet = Fernet(FERNET_KEY)


class UserProfile(models.Model):
    user_id = models.IntegerField(unique=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reserved_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    auth_token = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"UserProfile(user_id={self.user_id}, balance={self.balance}, reserved={self.reserved_balance})"


class BnbBot(models.Model):
    STATUS_CHOICES = (
        ('RUNNING', 'Running'),
        ('STOPPED', 'Stopped'),
    )

    user_id = models.IntegerField()
    name = models.CharField(max_length=100)
    symbol = models.CharField(max_length=50)  # np. BTCUSDT

    max_price = models.DecimalField(max_digits=12, decimal_places=2)
    percent = models.DecimalField(max_digits=5, decimal_places=2, default=2.0)
    capital = models.DecimalField(max_digits=12, decimal_places=2)

   # Dotychczasowe
    levels_data = models.TextField(default="{}")  # <-- tu zostawiamy tylko konfigurację
    # Nowe pole na "dane dynamiczne" (flagi, buy_volume, buy_price)
    runtime_data = models.TextField(default="{}")

    binance_api_key = models.CharField(max_length=100, blank=True, null=True)
    binance_api_secret_enc = models.BinaryField(blank=True, null=True)

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='STOPPED')

    def __str__(self):
        return f"BnbBot(id={self.id}, user={self.user_id}, symbol={self.symbol}, status={self.status})"

    def get_levels_data(self) -> dict:
        if not self.levels_data:
            return {}
        # jeśli zapisujesz w formie stringa przez str(data), można używać eval
        # jeśli w formie JSON, to json.loads()
        return eval(self.levels_data)

    def save_levels_data(self, data: dict):
        """
        Ustawia atrybut levels_data, ale NIE wywołuje self.save().
        """
        self.levels_data = str(data)
        # UWAGA: USUWAMY self.save()!
        # Poprawność w asynchronicznym kodzie zapewniamy przez await sync_to_async(bot.save)()

    def get_runtime_data(self) -> dict:
        if not self.runtime_data:
            return {}
        return eval(self.runtime_data)  # lub json.loads

    def save_runtime_data(self, data: dict):
        self.runtime_data = str(data)
        # nie wywołujemy self.save() tutaj

    def set_binance_api_secret(self, plain_secret: str):
        self.binance_api_secret_enc = fernet.encrypt(plain_secret.encode("utf-8"))

    def get_binance_api_secret(self) -> str:
        if not self.binance_api_secret_enc:
            return ""
        return fernet.decrypt(self.binance_api_secret_enc).decode("utf-8")


class BnbTrade(models.Model):
    """
    Transakcje zawarte przez BnbBot (kupno/sprzedaż).
    """
    bot = models.ForeignKey(BnbBot, on_delete=models.CASCADE, related_name='trades')
    level = models.CharField(max_length=10)             # np. "lv1"
    side = models.CharField(max_length=4)               # "BUY"/"SELL"
    quantity = models.DecimalField(max_digits=20, decimal_places=8)
    open_price = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    close_price = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    profit = models.DecimalField(max_digits=20, decimal_places=8, null=True)
    binance_order_id = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(max_length=10)  # np. "FILLED", "OPEN", itp.
    buy_type = models.CharField(max_length=10, null=True)
    sell_type = models.CharField(max_length=10, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"BnbTrade(bot_id={self.bot_id}, lv={self.level}, side={self.side}, status={self.status})"

