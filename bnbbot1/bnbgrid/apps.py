from django.apps import AppConfig

class BnbgridConfig(AppConfig):
    name = 'bnbgrid'

    def ready(self):
        from .bnb_logic import start_bnb_worker
        start_bnb_worker()

