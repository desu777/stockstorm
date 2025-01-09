import os
from celery import Celery

# Ustawienia Django dla Celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'stockstorm_project.settings')

app = Celery('stockstorm_project')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
