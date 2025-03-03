# d10/apps.py
from django.apps import AppConfig

class D10Config(AppConfig):
    name = 'd510'

    def ready(self):
        # Uruchamiaj w trybie deweloperskim worker w wątku
        # (Uwaga: w produkcji lepiej użyć innego mechanizmu np. Celery)
        from .worker import start_worker
        start_worker()
