import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maedix_q.settings')

app = Celery('maedix_q')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
