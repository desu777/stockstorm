# d10/urls.py
from django.urls import path
from .views import (
    register_token,
    create_bot,
    get_bot_details,
    remove_bot,
    export_d10_trades_csv,
    check_d10_connection,
    get_bot_status
)

urlpatterns = [
    path('register_token/', register_token, name='register_token'),
    path('create_bot/', create_bot, name='create_bot'),
    path('get_bot_details/<int:bot_id>/', get_bot_details, name='get_bot_details'),
    path('remove_bot/<int:bot_id>/', remove_bot, name='remove_bot'),
    path('export_d10_trades_csv/<int:bot_id>/', export_d10_trades_csv, name='export_bot_trades_csv'),
    path('check_d10_connection/<int:bot_id>/', check_d10_connection, name='check_d10_connection'),
    path('get_bot_status/<int:bot_id>/', get_bot_status, name='get_bot_status'),
]
