# Maedix-Q

A Django-based quiz platform with video export functionality for social media (Instagram Reels format).

## Features

- User authentication (login, register, password reset)
- Quiz creation and management
- Quiz attempts with scoring
- Video export (9:16 vertical format for Instagram Reels)
- Subscription plans with usage limits
- Razorpay payment integration

## Tech Stack

- **Backend:** Django 6.0, Django REST Framework
- **Database:** PostgreSQL
- **Video Generation:** MoviePy, FFmpeg, Pillow
- **Payments:** Razorpay
- **Deployment:** AWS EC2, Nginx, Gunicorn

---

## Local Development Setup

### Prerequisites

- Python 3.12+
- PostgreSQL
- FFmpeg

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/maedix-q.git
cd maedix-q

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create .env file
cp deploy/.env.example .env
# Edit .env with your values

# Run migrations
python manage.py migrate

# Create superuser
python manage.py createsuperuser

# Run development server
python manage.py runserver
```

---

## Production Deployment (AWS EC2)

### Recommended Instance

| Usage | Instance Type | RAM |
|-------|---------------|-----|
| Without video gen | t3.micro | 1GB |
| With video gen | t3.small+ | 2GB+ |

### Step-by-Step Deployment

#### 1. System Setup

```bash
sudo apt update && sudo apt upgrade -y

sudo apt install -y python3 python3-pip python3-venv python3-dev \
    postgresql postgresql-contrib libpq-dev \
    nginx git curl ffmpeg certbot python3-certbot-nginx
```

#### 2. PostgreSQL Setup

```bash
sudo -u postgres psql
```

```sql
CREATE USER maedix_q WITH PASSWORD 'your-secure-password';
CREATE DATABASE maedix_q OWNER maedix_q;
GRANT ALL PRIVILEGES ON DATABASE maedix_q TO maedix_q;
\q
```

#### 3. Application Setup

```bash
cd ~
git clone https://github.com/yourusername/maedix-q.git
cd maedix-q

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn

# Create directories
mkdir -p logs media cache

# Setup environment
nano .env  # Add your configuration

# Run migrations
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
```

#### 4. Gunicorn Service

```bash
sudo nano /etc/systemd/system/maedix-q.service
```

```ini
[Unit]
Description=Maedix-Q Gunicorn Daemon
After=network.target

[Service]
User=ubuntu
Group=www-data
WorkingDirectory=/home/ubuntu/maedix-q
Environment="PATH=/home/ubuntu/maedix-q/venv/bin"
ExecStart=/home/ubuntu/maedix-q/venv/bin/gunicorn \
    --workers 3 \
    --bind unix:/home/ubuntu/maedix-q/maedix-q.sock \
    --access-logfile /home/ubuntu/maedix-q/logs/gunicorn-access.log \
    --error-logfile /home/ubuntu/maedix-q/logs/gunicorn-error.log \
    --timeout 120 \
    maedix_q.wsgi:application

Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable maedix-q
sudo systemctl start maedix-q
```

#### 5. Nginx Setup

```bash
sudo nano /etc/nginx/sites-available/maedix-q
```

```nginx
server {
    listen 80;
    server_name your-domain.com www.your-domain.com;

    client_max_body_size 50M;

    location /static/ {
        alias /home/ubuntu/maedix-q/staticfiles/;
    }

    location /media/ {
        alias /home/ubuntu/maedix-q/media/;
    }

    location / {
        proxy_pass http://unix:/home/ubuntu/maedix-q/maedix-q.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/maedix-q /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx
```

#### 6. SSL Certificate

```bash
sudo certbot --nginx -d your-domain.com
```

#### 7. Firewall

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
```

---

## Common Commands

### Restart Services

```bash
sudo systemctl restart maedix-q
sudo systemctl restart nginx
```

### View Logs

```bash
# Gunicorn logs
sudo journalctl -u maedix-q -f
tail -f ~/maedix-q/logs/gunicorn-error.log

# Nginx logs
tail -f /var/log/nginx/error.log
```

### Update Deployment

```bash
cd ~/maedix-q
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart maedix-q
```

---

## Environment Variables

Create `.env` file with:

```env
DEBUG=False
SECRET_KEY=your-secret-key
ALLOWED_HOSTS=your-domain.com,www.your-domain.com

DB_NAME=maedix_q
DB_USER=maedix_q
DB_PASSWORD=your-db-password
DB_HOST=localhost
DB_PORT=5432

EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-app-password
DEFAULT_FROM_EMAIL=noreply@your-domain.com

RAZORPAY_KEY_ID=rzp_live_xxx
RAZORPAY_KEY_SECRET=your-secret
```

---

## Subscription Features

### Usage-based Features (with limits)

| Feature Code | Description | Used In |
|--------------|-------------|---------|
| `quiz_attempt` | Quiz attempts per month | quiz/views.py:122, 128 |
| `video_gen` | Video generation from quiz | quiz/views.py:808, 834, 839 |
| `quiz_create` | Create custom quizzes | quiz/views.py:968, 986, 994 |

### Boolean Features (no limits)

| Feature Code | Description |
|--------------|-------------|
| `custom_handle_name_in_video_export` | Custom handle name in video export |
| `analytics` | Advanced analytics |
| `certificates` | Completion certificates |

### Feature JSON Structure

```json
// With limit (usage-based)
{"code": "video_gen", "limit": 5, "description": "Video generation from quiz"}

// Without limit (boolean feature)
{"code": "custom_handle_name_in_video_export", "description": "Custom handle name"}
```

### Free Plan Features

```json
[
    {"code": "quiz_attempt", "description": "Quiz attempts per month", "limit": 50},
    {"code": "video_gen", "description": "Video generation from quiz", "limit": 3},
    {"code": "quiz_create", "description": "Create custom quizzes", "limit": 5}
]
```

### Pro Plan Features

```json
[
    {"code": "quiz_attempt", "description": "Quiz attempts per month", "limit": 500},
    {"code": "video_gen", "description": "Video generation from quiz", "limit": 50},
    {"code": "quiz_create", "description": "Create custom quizzes", "limit": 100},
    {"code": "custom_handle_name_in_video_export", "description": "Custom handle name in video export"},
    {"code": "analytics", "description": "Advanced analytics"},
    {"code": "certificates", "description": "Completion certificates"}
]
```

---

## Razorpay Test Cards

### Indian Payments

| Card Network | Card Number |
|--------------|-------------|
| Mastercard | 2305 3242 5784 8228 |
| Visa | 4386 2894 0766 0153 |

### International Payments

| Card Network | Card Number |
|--------------|-------------|
| Mastercard | 5421 1393 0609 0628 |
| Mastercard | 5105 1051 0510 5100 |
| Visa | 4012 8888 8888 1881 |
| Visa | 5104 0600 0000 0008 |

**Test Card Details:** Any future expiry date, any 3-digit CVV

---

## Troubleshooting

### 502 Bad Gateway

```bash
# Check if Gunicorn is running
sudo systemctl status maedix-q

# Check logs
sudo journalctl -u maedix-q -n 50

# Check socket exists
ls -la ~/maedix-q/maedix-q.sock

# Fix permissions
sudo chmod 755 /home/ubuntu
sudo systemctl restart maedix-q
```

### Video Generation Stuck

- **Cause:** Low memory (needs 2GB+ RAM for video encoding)
- **Solution:** Upgrade to t3.small or add swap:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Task Not Found Error

- **Cause:** Cache not shared between workers
- **Solution:** File-based cache is configured in settings.py. Ensure cache directory exists:

```bash
mkdir -p ~/maedix-q/cache
chmod 755 ~/maedix-q/cache
sudo systemctl restart maedix-q
```

---

## Project Structure

```
maedix-q/
├── maedix_q/           # Django project settings
├── core/               # Core app (plans, subscriptions)
├── users/              # User authentication
├── quiz/               # Quiz app (main functionality)
├── templates/          # HTML templates
├── static/             # Static files (CSS, JS)
├── deploy/             # Deployment configurations
├── requirements.txt    # Python dependencies
└── manage.py
```

---

## License

Private - All rights reserved


sudo systemctl daemon-reload
sudo systemctl restart maedix-q
sudo systemctl restart nginx


live log

sudo journalctl -u maedix-q -f