# d10/models.py

from django.db import models
from django.conf import settings
from cryptography.fernet import Fernet
from django.db.models import Count, Sum

FERNET_KEY = getattr(settings, 'FERNET_KEY', 'GiLFpoI4-TzsPAheWRYytzPXuOlZVHOz5FrZsjHYZSk=')
fernet = Fernet(FERNET_KEY)

class UserProfile(models.Model):
    user_id = models.IntegerField(unique=True)
    auth_token = models.CharField(max_length=128, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"UserProfile(user_id={self.user_id}, token={self.auth_token})"


class BotD10(models.Model):
    STATUS_CHOICES = (
        ('NEW', 'New'),
        ('RUNNING', 'Running'),
        ('FINISHED', 'Finished'),
        ('ERROR', 'Error'),
    )

    user_id = models.IntegerField()
    name = models.CharField(max_length=100)
    instrument = models.CharField(max_length=50)

    band_percent = models.DecimalField(max_digits=5, decimal_places=2, default=30)
    step_percent = models.DecimalField(max_digits=5, decimal_places=2, default=5)
    rise_percent = models.DecimalField(max_digits=5, decimal_places=2, default=10)

    capital = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    account_currency = models.CharField(max_length=10, blank=True, null=True)
    asset_currency = models.CharField(max_length=10, blank=True, null=True)

    xtb_id = models.CharField(max_length=50, blank=True, null=True)
    xtb_password = models.CharField(max_length=128, blank=True, null=True)

    levels_data = models.TextField(blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NEW')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"[D10 Bot] {self.name} (user_id={self.user_id}, status={self.status})"

    def get_level_stats(self):
        """
        Zwraca słownik, w którym kluczem jest nazwa poziomu (np. 'lv1'),
        a wartością słownik z liczbą transakcji (tp) oraz łącznym zyskiem (total_profit).
        Tylko transakcje zamknięte (status='CLOSED') są brane pod uwagę.
        """
        qs = self.trades.filter(status='CLOSED').values('level_name').annotate(
            tp=Count('id'),
            total_profit=Sum('profit')
        )
        stats = {
            item['level_name']: {
                'tp': item['tp'],
                'profit': float(item['total_profit'] or 0)
            }
            for item in qs
        }
        return stats


class TradeD10(models.Model):
    STATUS_CHOICES = (
        ('OPEN', 'Open'),
        ('CLOSED', 'Closed'),
    )

    bot = models.ForeignKey(BotD10, on_delete=models.CASCADE, related_name='trades')
    level_name = models.CharField(max_length=10)  
    open_price = models.DecimalField(max_digits=12, decimal_places=4)
    close_price = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    profit = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='OPEN')
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"TradeD10(bot_id={self.bot.id}, {self.level_name}, {self.status})"
