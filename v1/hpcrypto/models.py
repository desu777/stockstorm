# hpcrypto/models.py
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class HPCategory(models.Model):
    """Model for grouping positions (e.g., HP1, HP2)"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=50)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} ({self.user.username})"
    
    class Meta:
        verbose_name_plural = "HP Categories"
        ordering = ['name']

class Position(models.Model):
    """Model for individual trading positions"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    category = models.ForeignKey(HPCategory, on_delete=models.CASCADE, related_name='positions')
    ticker = models.CharField(max_length=20)
    quantity = models.DecimalField(max_digits=18, decimal_places=8)
    entry_price = models.DecimalField(max_digits=18, decimal_places=8)
    exit_price = models.DecimalField(max_digits=18, decimal_places=8, blank=True, null=True)
    current_price = models.DecimalField(max_digits=18, decimal_places=8, blank=True, null=True)
    last_price_update = models.DateTimeField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.ticker} - {self.quantity} @ {self.entry_price}"
    
    @property
    def position_size(self):
        """Calculate total position size in dollars"""
        return self.quantity * self.entry_price
    
    @property
    def profit_loss_dollar(self):
        """Calculate profit/loss in dollars"""
        if not self.current_price:
            return None
        return (self.current_price - self.entry_price) * self.quantity
    
    @property
    def profit_loss_percent(self):
        """Calculate profit/loss in percentage"""
        if not self.current_price or self.entry_price == 0:
            return None
        return ((self.current_price - self.entry_price) / self.entry_price) * 100
    
    class Meta:
        ordering = ['-created_at']

class PriceAlert(models.Model):
    """Model for price alerts on positions"""
    ALERT_TYPES = (
        ('PRICE_ABOVE', 'Price Above'),
        ('PRICE_BELOW', 'Price Below'),
        ('PCT_INCREASE', '% Increase'),
        ('PCT_DECREASE', '% Decrease'),
    )
    
    position = models.ForeignKey(Position, on_delete=models.CASCADE, related_name='alerts')
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES)
    threshold_value = models.DecimalField(max_digits=18, decimal_places=8)
    is_active = models.BooleanField(default=True)
    triggered = models.BooleanField(default=False)
    last_triggered = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.get_alert_type_display()} @ {self.threshold_value} for {self.position.ticker}"