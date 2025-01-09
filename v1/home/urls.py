from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from django.contrib.auth.views import LogoutView


urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register_view, name='register'),
    path('dashboard/', views.dashboard_view, name='dashboard'),
    path('forgot/', views.forgot_password_view, name='forgot'),
    path('success/', views.success_view, name='success'),
    path('profile/', views.profile_view, name='profile'),
    path('history/', views.history_view, name='history'), 
    path('logout/', LogoutView.as_view(next_page='home'), name='logout'),
    path('balance_data/', views.get_balance_data, name='balance_data'),
    path('instrument_price/', views.get_instrument_price, name='get_instrument_price'),
    path('search_instruments/', views.search_instruments, name='search_instruments'),
    path('show_symbols/', views.show_symbols_view, name='show_symbols'),
    path('accounts/login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('', views.home, name='home'),
    path('api/stock_status/', views.api_stock_status, name='api_stock_status'),
    path('symbol_details/', views.get_symbol_details_view, name='symbol_details'),
    path('get_stream_session_id/', views.get_stream_session_id, name='get_stream_session_id'),
    path('list/', views.bot_list, name='bot_list'),
    path('add/', views.bot_add, name='bot_add'),
    path('<int:bot_id>/remove/', views.bot_remove, name='bot_remove'),
    path('bot/<int:bot_id>/detail/', views.bot_detail, name='bot_detail'),
    path('proxy/get_bot_details/<int:bot_id>/', views.get_bot_details_proxy, name='get_bot_details_proxy'),
]



