from django.db import models

# Create your models here.
from django.db import models
import json

class UserProfile(models.Model):
    user_id = models.IntegerField(unique=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    reserved_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    auth_token = models.CharField(max_length=255, blank=True, null=True)
    def __str__(self):
        return f"UserProfile(user_id={self.user_id}, balance={self.balance}, reserved={self.reserved_balance})"



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
    min_price = models.DecimalField(max_digits=10, decimal_places=2)
    max_price = models.DecimalField(max_digits=10, decimal_places=2)
    percent = models.IntegerField()
    capital = models.DecimalField(max_digits=12, decimal_places=2)
    stream_session_id = models.CharField(max_length=100, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NEW')
    created_at = models.DateTimeField(auto_now_add=True)

    # Pola do logiki poziomów (JSON)
    levels_data = models.TextField(blank=True, null=True)  
    # np. { "lv1": 10.0, "lv2": 9.0, "lv3": 8.1, "flags": {...}, ... }

    def __str__(self):
        return f"MicroserviceBot {self.name} (user={self.user_id}, {self.instrument}, {self.status})"


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