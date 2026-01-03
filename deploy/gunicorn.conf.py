# Gunicorn configuration file for maedix-q
# https://docs.gunicorn.org/en/stable/settings.html

import multiprocessing

# Server socket
bind = "unix:/home/ubuntu/maedix-q/maedix-q.sock"
backlog = 2048

# Worker processes
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50
timeout = 120  # Increased for video generation
graceful_timeout = 30
keepalive = 5

# Process naming
proc_name = "maedix-q"

# Server mechanics
daemon = False
pidfile = "/home/ubuntu/maedix-q/gunicorn.pid"
user = "ubuntu"
group = "www-data"
tmp_upload_dir = None

# Logging
accesslog = "/home/ubuntu/maedix-q/logs/gunicorn-access.log"
errorlog = "/home/ubuntu/maedix-q/logs/gunicorn-error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Debugging
reload = False
spew = False
check_config = False

# SSL (if not using Nginx)
# keyfile = None
# certfile = None
