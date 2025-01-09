# tasks.py
from celery import shared_task
from .models import XTBConnection, XTBApiConnector
from django.contrib.auth.models import User
from .models import XTBConnection
import requests
from django.conf import settings

@shared_task
def ping_xtb():
    # Pobierz wszystkie połączenia aktywne
    print("Ping XTB Task Executed!")
    active_connections = XTBConnection.objects.filter(is_live=True)
    for conn in active_connections:
        # Ponownie łączymy się z API (można to usprawnić trzymając połączenie w pamięci)
        connector = XTBApiConnector(conn.xtb_id, conn.get_password(), conn.stream_session_id)
        if connector.connect():
            # Utrzymujemy sesję aktywną przez ping
            connector.ping()
            connector.disconnect()
        else:
            # Jeśli połączenie się nie powiedzie, ustaw is_live na False
            conn.is_live = False
            conn.stream_session_id = None
            conn.save()

import logging

logger = logging.getLogger(__name__)

@shared_task
def sync_xtb_session_ids():
    logger.info("Sync XTB Session IDs Task Executed!")
    connections = XTBConnection.objects.filter(is_live=True, stream_session_id__isnull=False)
    for conn in connections:
        try:
            payload = {
                'user_id': conn.user.id,
                'stream_session_id': conn.stream_session_id
            }
            headers = {
                'Authorization': f'Token {settings.MICROSERVICE_API_TOKEN2}'
            }
            response = requests.post(
                f"{settings.MICROSERVICE_URL2}/sync_session_id/",
                json=payload,
                headers=headers,
                timeout=5
            )
            if response.status_code == 200:
                logger.info(f"Session ID synchronized for user {conn.user.username}")
            else:
                logger.warning(f"Failed to sync Session ID for user {conn.user.username}: {response.text}")
        except requests.RequestException as e:
            logger.error(f"Request error for user {conn.user.username}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error for user {conn.user.username}: {e}")