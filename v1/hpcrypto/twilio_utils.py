# Create a new file: v1/hpcrypto/twilio_utils.py
from django.conf import settings
from twilio.rest import Client
import logging

logger = logging.getLogger(__name__)

def send_sms_notification(phone_number, message):
    """
    Send SMS notification using Twilio
    
    Args:
        phone_number (str): The recipient's phone number with country code (e.g., +1234567890)
        message (str): The SMS message text
        
    Returns:
        bool: True if successful, False otherwise
        str: Message SID if successful, error message otherwise
    """
    # Check if SMS notifications are enabled globally
    if not getattr(settings, 'SMS_NOTIFICATIONS_ENABLED', False):
        return False, "SMS notifications are disabled globally"
    
    # Check for required Twilio settings
    if not all([
        hasattr(settings, 'TWILIO_ACCOUNT_SID'),
        hasattr(settings, 'TWILIO_AUTH_TOKEN'),
        hasattr(settings, 'TWILIO_PHONE_NUMBER')
    ]):
        return False, "Twilio settings are incomplete"
    
    # Validate phone number (basic check)
    if not phone_number or not phone_number.startswith('+'):
        return False, "Invalid phone number format. Must include country code (e.g., +1234567890)"
    
    # Initialize Twilio client
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        # Limit message length to 160 characters (standard SMS limit)
        if len(message) > 160:
            message = message[:157] + '...'
        
        # Send SMS
        sms = client.messages.create(
            body=message,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=phone_number
        )
        
        logger.info(f"SMS sent successfully: {sms.sid}")
        return True, sms.sid
        
    except Exception as e:
        error_msg = f"Error sending SMS: {str(e)}"
        logger.error(error_msg)
        return False, error_msg