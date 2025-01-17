from django.urls import path
from . import views

urlpatterns = [
    path('create_bot/', views.create_bot, name='create_bot'),
    path('bot_status/<int:bot_id>/', views.debug_bot_status, name='debug_bot_status'),
    path('remove_bot/<int:bot_id>/', views.remove_bot, name='remove_bot'),
    path('sync_session_id/', views.sync_session_id, name='sync_session_id'),
    path('get_bot_details/<int:bot_id>/', views.get_bot_details, name='get_bot_details'), 
    path('register_token/', views.register, name='register_token'),
]
