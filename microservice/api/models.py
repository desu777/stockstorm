from django.db import models
#api/models.py
# Create your models here.
from django.db import models
import json
from cryptography.fernet import Fernet

class UserProfile(models.Model):
    user_id = models.IntegerField(unique=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reserved_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    auth_token = models.CharField(max_length=255, blank=True, null=True)
    def __str__(self):
        return f"UserProfile(user_id={self.user_id}, balance={self.balance}, reserved={self.reserved_balance})"

FERNET_KEY = "GiLFpoI4-TzsPAheWRYytzPXuOlZVHOz5FrZsjHYZSk="  # przykładowy klucz
fernet = Fernet(FERNET_KEY)


class MicroserviceBot(models.Model):
    STATUS_CHOICES = (
        ('NEW', 'New'),
        ('RUNNING', 'Running'),
        ('FINISHED', 'Finished'),
        ('ERROR', 'Error'),
    )

    user_id = models.IntegerField()
    name = models.CharField(max_length=100)
    instrument = models.CharField(max_length=50)
    max_price = models.DecimalField(max_digits=10, decimal_places=2)
    percent = models.IntegerField()
    capital = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NEW')
    created_at = models.DateTimeField(auto_now_add=True)

    # Nowe pola:
    account_currency = models.CharField(max_length=3, choices=[('PLN', 'PLN'), ('USD', 'USD')], default='PLN')
    asset_currency = models.CharField(max_length=3, choices=[('PLN', 'PLN'), ('USD', 'USD'), ('EUR', 'EUR')], default='PLN')

    levels_data = models.TextField(blank=True, null=True)  # Zapis wolumenów dla poziomów
    xtb_login = models.CharField(max_length=50, blank=True, null=True)
    xtb_password_enc = models.BinaryField(blank=True, null=True)
    def __str__(self):
        return f"MicroserviceBot {self.name} (user={self.user_id}, {self.instrument}, {self.status})"


    def set_xtb_password(self, plain_password: str):
        """
        Zaszyfrowanie hasła i zapis w polu xtb_password_enc
        """
        enc = fernet.encrypt(plain_password.encode('utf-8'))
        self.xtb_password_enc = enc

    def get_xtb_password(self):
        """
        Odszyfrowanie hasła z xtb_password_enc
        """
        if not self.xtb_password_enc:
            return None
        return fernet.decrypt(self.xtb_password_enc).decode('utf-8')

    def get_tp_count(self, lv_number):
        """
        Liczy liczbę zrealizowanych sprzedaży (TP) dla danego poziomu.
        """
        return self.trade_set.filter(level=lv_number, status='SOLD').count()

    def get_profit(self, lv_number):
        """
        Oblicza całkowity zysk dla danego poziomu.
        """
        return self.trade_set.filter(level=lv_number, status='SOLD').aggregate(
            total_profit=models.Sum('profit')
        )['total_profit'] or 0.0

class Trade(models.Model):
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('SOLD', 'Sold'),
    ]

    bot = models.ForeignKey(MicroserviceBot, on_delete=models.CASCADE)
    level = models.CharField(max_length=10)  # np. 'lv1', 'lv2', etc.
    open_price = models.DecimalField(max_digits=10, decimal_places=2)
    close_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    profit = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    open_time = models.DateTimeField(auto_now_add=True)
    close_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='OPEN')

    def save(self, *args, **kwargs):
        if self.close_price and not self.profit:
            self.profit = self.close_price - self.open_price  # Przykładowa kalkulacja zysku
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.bot.name} - {self.level} - {self.status}"