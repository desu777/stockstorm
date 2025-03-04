from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from django.contrib.auth.views import LogoutView
from django.views.generic import TemplateView

urlpatterns = [
    path('login/', views.custom_login_view, name='login'),
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
    path('list/', views.bot_list, name='bot_list'),
    path('add/', views.bot_add, name='bot_add'),
    path('<int:bot_id>/remove/', views.bot_remove, name='bot_remove'),
    path('bot/<int:bot_id>/detail/', views.bot_detail, name='bot_detail'),
    path('proxy/get_bot_details/<int:bot_id>/', views.get_bot_details_proxy, name='get_bot_details_proxy'),
    path('test/', TemplateView.as_view(template_name='index.html')),
    path('bot/<int:bot_id>/status/', views.get_bot_status, name='get_bot_status'),
    path('bnb/create/', views.bnb_create, name='bnb_create'),
    path('bnb/<int:bot_id>/delete/', views.bnb_delete, name='bnb_delete'),
    path('bnb/<int:bot_id>/detail/', views.bnb_detail, name='bnb_detail'),
    path('bnb/<int:bot_id>/status/', views.bnb_status, name='bnb_status'),
    path('listbnb/', views.bnb_list, name='bnb_list'),
    path('bot/<int:bot_id>/export_csv/', views.export_bot_trades, name='export_bot_trades'),
    path('bot/<int:bot_id>/check_connection/', views.check_broker_connection, name='check_broker_connection'),
    path('bot/<int:bot_id>/export_csv_bnb/', views.export_bnb_trades, name='export_bnb_trades'),
    path('d10/', views.d10_list, name='d10_list'),
    path('d10/add/', views.d10_add, name='d10_add'),
    path('d10/<int:bot_id>/', views.d10_detail, name='d10_detail'),
    path('d10/<int:bot_id>/remove/', views.d10_remove, name='d10_remove'),
    path('bot/<int:bot_id>/check_d10_connection/', views.check_d10_connection, name='check_d10_connection'),
    path('bot/<int:bot_id>/export_d10_trades/', views.export_d10_trades, name='export_d10_trades'),

]



