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
        """Calculate profit/loss in dollars - use exit_price if available, otherwise use current_price"""
        if self.exit_price is not None:
            return (self.exit_price - self.entry_price) * self.quantity
        elif self.current_price is not None:
            return (self.current_price - self.entry_price) * self.quantity
        return None
    
    @property
    def profit_loss_percent(self):
        """Calculate profit/loss in percentage - use exit_price if available, otherwise use current_price"""
        if self.exit_price is not None and self.entry_price != 0:
            return ((self.exit_price - self.entry_price) / self.entry_price) * 100
        elif self.current_price is not None and self.entry_price != 0:
            return ((self.current_price - self.entry_price) / self.entry_price) * 100
        return None
    
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
    
    # Fields for OneSignal notifications
    notification_sent = models.BooleanField(default=False)
    last_notification_sent = models.DateTimeField(blank=True, null=True)
    
    def __str__(self):
        return f"{self.get_alert_type_display()} @ {self.threshold_value} for {self.position.ticker}"
    
    def format_notification_message(self):
        """Format notification message based on alert type and threshold"""
        position = self.position
        ticker = position.ticker
        current_price = position.current_price
        
        if self.alert_type == 'PRICE_ABOVE':
            return f"{ticker} price is now ${current_price:.4f}, above your ${self.threshold_value:.4f} threshold."
        elif self.alert_type == 'PRICE_BELOW':
            return f"{ticker} price is now ${current_price:.4f}, below your ${self.threshold_value:.4f} threshold."
        elif self.alert_type == 'PCT_INCREASE':
            pct_change = ((current_price - position.entry_price) / position.entry_price) * 100
            return f"{ticker} increased by {pct_change:.2f}%, above your {self.threshold_value:.2f}% threshold. Current price: ${current_price:.4f}"
        elif self.alert_type == 'PCT_DECREASE':
            pct_change = ((position.entry_price - current_price) / position.entry_price) * 100
            return f"{ticker} decreased by {pct_change:.2f}%, above your {self.threshold_value:.2f}% threshold. Current price: ${current_price:.4f}"
        
        return f"{ticker} price alert triggered. Current price: ${current_price:.4f}"