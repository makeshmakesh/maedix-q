"""
WSGI config for maedix_q project.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'maedix_q.settings')

application = get_wsgi_application()
