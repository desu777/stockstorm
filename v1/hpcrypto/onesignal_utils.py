# v1/hpcrypto/onesignal_utils.py
import requests
import json
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

def send_onesignal_notification(user_id, message, title="STOCKstorm Alert", url=None, data=None):
    """
    Send a push notification using OneSignal API
    
    Args:
        user_id (int): User ID to target (will be converted to external_user_id)
        message (str): Notification message
        title (str): Notification title
        url (str, optional): URL to open when notification is clicked
        data (dict, optional): Additional data to include with the notification
        
    Returns:
        bool: True if successful, False otherwise
        dict: Response data if successful, error message otherwise
    """
    if not hasattr(settings, 'ONESIGNAL_APP_ID') or not hasattr(settings, 'ONESIGNAL_REST_API_KEY'):
        return False, "OneSignal configuration is incomplete"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {settings.ONESIGNAL_REST_API_KEY}"
    }
    
    payload = {
        "app_id": settings.ONESIGNAL_APP_ID,
        "contents": {"en": message},
        "headings": {"en": title},
        "include_external_user_ids": [str(user_id)],
    }
    
    # Add optional parameters if provided
    if url:
        payload["url"] = url
    
    if data:
        payload["data"] = data
    
    try:
        response = requests.post(
            "https://onesignal.com/api/v1/notifications",
            headers=headers,
            data=json.dumps(payload)
        )
        
        response_data = response.json()
        
        if response.status_code == 200 and response_data.get("id"):
            logger.info(f"OneSignal notification sent: {response_data['id']}")
            return True, response_data
        else:
            error_msg = f"OneSignal API error: {response_data.get('errors', 'Unknown error')}"
            logger.error(error_msg)
            return False, error_msg
            
    except Exception as e:
        error_msg = f"Error sending OneSignal notification: {str(e)}"
        logger.error(error_msg)
        return False, error_msg