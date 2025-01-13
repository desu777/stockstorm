# apps.py
import sys
from django.apps import AppConfig

class ApiConfig(AppConfig):
    name = 'api'

    def ready(self):
        # Aby nie uruchamiać bota w trakcie migrate:
        if 'makemigrations' in sys.argv or 'migrate' in sys.argv:
            return

        from .bot_logic import start_bots_worker
        start_bots_worker()
