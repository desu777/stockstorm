# hpcrypto/views.py
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from .models import HPCategory, Position, PriceAlert
from .forms import HPCategoryForm, PositionForm, PriceAlertForm
from home.models import UserProfile
from django.views.decorators.http import require_POST
from .onesignal_utils import send_onesignal_notification

@login_required
def position_list(request):
    """View all positions grouped by HP category"""
    categories = HPCategory.objects.filter(user=request.user).prefetch_related('positions')
    
    # Prepare data for UI
    for category in categories:
        # Calculate totals
        positions = category.positions.all()
        total_investment = sum(position.position_size for position in positions)
        total_pnl_dollar = sum(position.profit_loss_dollar or 0 for position in positions)
        
        category.total_investment = total_investment
        category.total_pnl_dollar = total_pnl_dollar
        category.total_pnl_percent = (total_pnl_dollar / total_investment * 100) if total_investment else 0
    
    return render(request, 'position_list.html', {
        'categories': categories,
    })

@login_required
def add_category(request):
    """Add a new HP category"""
    if request.method == 'POST':
        form = HPCategoryForm(request.POST)
        if form.is_valid():
            category = form.save(commit=False)
            category.user = request.user
            category.save()
            messages.success(request, f"Category '{category.name}' created successfully.")
            return redirect('position_list')
    else:
        form = HPCategoryForm()
    
    return render(request, 'category_form.html', {
        'form': form,
        'title': 'Add New HP Category'
    })

@login_required
def edit_category(request, category_id):
    """Edit an existing HP category"""
    category = get_object_or_404(HPCategory, id=category_id, user=request.user)
    if request.method == 'POST':
        form = HPCategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, f"Category '{category.name}' updated successfully.")
            return redirect('position_list')
    else:
        form = HPCategoryForm(instance=category)
    
    return render(request, 'category_form.html', {
        'form': form,
        'title': f'Edit Category: {category.name}'
    })

@login_required
def delete_category(request, category_id):
    """Delete an HP category and all associated positions"""
    category = get_object_or_404(HPCategory, id=category_id, user=request.user)
    if request.method == 'POST':
        name = category.name
        category.delete()
        messages.success(request, f"Category '{name}' and all its positions have been deleted.")
        return redirect('position_list')
    
    return render(request, 'confirm_delete.html', {
        'object': category,
        'title': f'Delete Category: {category.name}',
        'message': 'This will delete the category and ALL positions within it. This action cannot be undone.'
    })

@login_required
def add_position(request):
    """Add a new position"""
    if request.method == 'POST':
        form = PositionForm(request.POST)
        if form.is_valid():
            position = form.save(commit=False)
            position.user = request.user
            position.save()
            
            # Try to fetch current price
            try:
                from hpcrypto.utils import get_binance_price
                current_price = get_binance_price(request.user, position.ticker)
                if current_price:
                    position.current_price = current_price
                    position.last_price_update = timezone.now()
                    position.save()
            except Exception as e:
                messages.warning(request, f"Position created, but couldn't fetch price: {str(e)}")
            
            messages.success(request, f"Position for {position.ticker} added successfully.")
            return redirect('position_list')
    else:
        # Only show categories for this user
        form = PositionForm()
        form.fields['category'].queryset = HPCategory.objects.filter(user=request.user)
    
    return render(request, 'position_form.html', {
        'form': form,
        'title': 'Add New Position'
    })

@login_required
def edit_position(request, position_id):
    """Edit an existing position"""
    position = get_object_or_404(Position, id=position_id, user=request.user)
    if request.method == 'POST':
        form = PositionForm(request.POST, instance=position)
        if form.is_valid():
            form.save()
            messages.success(request, f"Position for {position.ticker} updated successfully.")
            return redirect('position_list')
    else:
        form = PositionForm(instance=position)
        form.fields['category'].queryset = HPCategory.objects.filter(user=request.user)
    
    return render(request, 'position_form.html', {
        'form': form,
        'title': f'Edit Position: {position.ticker}',
        'position': position
    })

@login_required
def delete_position(request, position_id):
    """Delete a position"""
    position = get_object_or_404(Position, id=position_id, user=request.user)
    if request.method == 'POST':
        ticker = position.ticker
        position.delete()
        messages.success(request, f"Position for {ticker} has been deleted.")
        return redirect('position_list')
    
    return render(request, 'confirm_delete.html', {
        'object': position,
        'title': f'Delete Position: {position.ticker}',
        'message': 'Are you sure you want to delete this position? This action cannot be undone.'
    })

@login_required
def add_alert(request, position_id):
    """Add a price alert for a position"""
    position = get_object_or_404(Position, id=position_id, user=request.user)
    if request.method == 'POST':
        form = PriceAlertForm(request.POST)
        if form.is_valid():
            alert = form.save(commit=False)
            alert.position = position
            alert.save()
            messages.success(request, f"Alert for {position.ticker} created successfully.")
            return redirect('position_detail', position_id=position.id)
    else:
        form = PriceAlertForm()
    
    return render(request, 'alert_form.html', {
        'form': form,
        'position': position,
        'title': f'Add Alert for {position.ticker}'
    })

@login_required
def position_detail(request, position_id):
    """View details for a specific position"""
    position = get_object_or_404(Position, id=position_id, user=request.user)
    alerts = PriceAlert.objects.filter(position=position)
    
    return render(request, 'position_detail.html', {
        'position': position,
        'alerts': alerts
    })

# Updated update_prices view function in hpcrypto/views.py
@login_required
@require_POST
def update_prices(request):
    """Update prices for all positions using Binance API"""
    # Get user's Binance API credentials
    profile = getattr(request.user, 'profile', None)
    if not profile or not profile.binance_api_key or not profile.binance_api_secret_enc:
        return JsonResponse({"success": False, "error": "Binance API credentials not configured"}, status=400)
    
    # Get all positions for this user
    positions = Position.objects.filter(user=request.user)
    updated_count = 0
    errors = []
    positions_data = []
    
    for position in positions:
        try:
            from hpcrypto.utils import get_binance_price
            current_price = get_binance_price(request.user, position.ticker)
            if current_price:
                position.current_price = current_price
                position.last_price_update = timezone.now()
                position.save()
                updated_count += 1
                
                # Append position data for frontend update
                positions_data.append({
                    'id': position.id,
                    'current_price': float(position.current_price),
                    'last_update_timestamp': position.last_price_update.isoformat(),
                    'pnl_dollar': float(position.profit_loss_dollar) if position.profit_loss_dollar is not None else None,
                    'pnl_percent': float(position.profit_loss_percent) if position.profit_loss_percent is not None else None
                })
            else:
                errors.append(f"Couldn't fetch price for {position.ticker}")
        except Exception as e:
            errors.append(f"Error updating {position.ticker}: {str(e)}")
    
    # Check alerts
    alerts_triggered = check_price_alerts()
    
    # Get category summary data
    categories_data = []
    categories = HPCategory.objects.filter(user=request.user).prefetch_related('positions')
    
    for category in categories:
        positions = category.positions.all()
        total_investment = sum(position.position_size for position in positions)
        total_pnl_dollar = sum(position.profit_loss_dollar or 0 for position in positions)
        
        categories_data.append({
            'id': category.id,
            'total_investment': float(total_investment),
            'total_pnl_dollar': float(total_pnl_dollar),
            'total_pnl_percent': float(total_pnl_dollar / total_investment * 100) if total_investment else 0
        })
    
    return JsonResponse({
        "success": True,
        "updated_count": updated_count,
        "errors": errors,
        "alerts_triggered": alerts_triggered,
        "positions_data": positions_data,
        "categories_data": categories_data
    })

from django.utils import timezone
from .twilio_utils import send_sms_notification
import logging



def check_price_alerts():
    """Check all active price alerts and mark triggered ones, send push notifications if configured"""
    alerts = PriceAlert.objects.filter(is_active=True, triggered=False)
    triggered = []
    
    for alert in alerts:
        position = alert.position
        if not position.current_price:
            continue
        
        trigger = False
        if alert.alert_type == 'PRICE_ABOVE' and position.current_price >= alert.threshold_value:
            trigger = True
        elif alert.alert_type == 'PRICE_BELOW' and position.current_price <= alert.threshold_value:
            trigger = True
        elif alert.alert_type == 'PCT_INCREASE':
            pct_change = ((position.current_price - position.entry_price) / position.entry_price) * 100
            if pct_change >= alert.threshold_value:
                trigger = True
        elif alert.alert_type == 'PCT_DECREASE':
            pct_change = ((position.entry_price - position.current_price) / position.entry_price) * 100
            if pct_change >= alert.threshold_value:
                trigger = True
        
        if trigger:
            now = timezone.now()
            alert.triggered = True
            alert.last_triggered = now
            
            # Check if user has push notifications enabled
            user = position.user
            user_profile = getattr(user, 'profile', None)
            
            # Send push notification if user has enabled it
            if (user_profile and 
                user_profile.push_notifications_enabled and 
                not alert.notification_sent):
                
                # Format message based on alert type
                message = alert.format_notification_message()
                title = f"STOCKstorm: {position.ticker} Alert Triggered"
                
                # Additional data for the notification
                data = {
                    "alert_id": alert.id,
                    "position_id": position.id,
                    "ticker": position.ticker,
                    "current_price": float(position.current_price)
                }
                
                # Use OneSignal to send notification to user
                success, result = send_onesignal_notification(
                    user_id=user.id,
                    message=message,
                    title=title,
                    url=f"/hpcrypto/position/{position.id}/",
                    data=data
                )
                
                if success:
                    alert.notification_sent = True
                    alert.last_notification_sent = now
                    # Log success
                    logger.info(f"Push notification sent for {position.ticker} to user {user.id}: {result}")
                else:
                    # Log error
                    logger.error(f"Failed to send push notification for {position.ticker}: {result}")
            
            alert.save()
            
            triggered.append({
                "id": alert.id,
                "position": position.ticker,
                "type": alert.get_alert_type_display(),
                "threshold": float(alert.threshold_value),
                "current_price": float(position.current_price),
                "notification_sent": alert.notification_sent
            })
    
    return triggered