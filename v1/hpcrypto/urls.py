# hpcrypto/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.position_list, name='position_list'),
    path('category/add/', views.add_category, name='add_category'),
    path('category/<int:category_id>/edit/', views.edit_category, name='edit_category'),
    path('category/<int:category_id>/delete/', views.delete_category, name='delete_category'),
    path('position/add/', views.add_position, name='add_position'),
    path('position/<int:position_id>/', views.position_detail, name='position_detail'),
    path('position/<int:position_id>/edit/', views.edit_position, name='edit_position'),
    path('position/<int:position_id>/delete/', views.delete_position, name='delete_position'),
    path('position/<int:position_id>/add-alert/', views.add_alert, name='add_alert'),
    path('update-prices/', views.update_prices, name='update_prices'),
]