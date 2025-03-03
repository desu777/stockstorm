from django.urls import path
from . import views

urlpatterns = [
    path('create_bot/', views.create_bot, name='bnb_create_bot'),
    path('get_bot_details/<int:bot_id>/', views.get_bot_details, name='bnb_get_bot'),
    path('remove_bot/<int:bot_id>/', views.remove_bot, name='bnb_remove_bot'),
    path('get_bot_status/<int:bot_id>/', views.get_bot_status, name='bnb_bot_status'),
    path('register_token/', views.register, name='register_token'),
    path('export_bnb_trades_csv/<int:bot_id>/', views.export_bnb_trades_csv, name='export_bnb_trades_csv'),
]