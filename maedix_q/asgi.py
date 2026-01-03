"""
ASGI config for maedix_q project.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maedix_q.settings')

application = get_asgi_application()
