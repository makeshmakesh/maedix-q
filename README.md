# Maedix-Q

An Instagram automation platform built with Django — automate DMs, build conversation flows, collect leads, and engage your audience at scale.

## Features

### Instagram Automation
- **DM Flow Builder** — Visual workflow editor for automated Direct Messages
- **Trigger Types** — Respond to comment keywords or any comments on posts/reels
- **Flow Nodes** — Conditional logic, delays, AI-powered responses, quick replies
- **Lead Collection** — Automatically capture and store user information from conversations
- **Session Tracking** — Track conversation state and user progression through flows
- **Rate Limit Handling** — Respects Instagram API limits (500 calls/hour) with automatic queuing
- **Queue Processing** — Messages are queued when rate-limited and auto-processed when slots open

### Beta Features
- Quiz creation and management
- Video export (9:16 vertical format for Instagram Reels)
- Voice roleplay with AI
- Interactive games

---

## Tech Stack

- **Backend:** Django 6.0, Django REST Framework, Channels
- **Database:** PostgreSQL, pgvector
- **AI:** OpenAI API (for AI-powered flow responses)
- **Payments:** Razorpay
- **Cloud:** AWS EC2, Lambda, S3, DynamoDB
- **Deployment:** Nginx, Gunicorn, AWS SAM

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
| Standard | t3.micro | 1GB |
| With video gen (beta) | t3.small+ | 2GB+ |

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

## Lambda Functions

Two Lambda functions handle background processing:

- **Queue Processor** — Processes queued Instagram DM messages when rate limits allow
- **Subscription Enforcer** — Enforces subscription limits and auto-downgrades

Deploy using AWS SAM:

```bash
cd aws
sam build
sam deploy --guided
```

See each Lambda's own README for details:
- `lambda/queue_processor/README.md`
- `lambda/subscription_enforcer/README.md`

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

## Subscription Plans

### Usage-based Features

| Feature | Free | Pro |
|---------|------|-----|
| Instagram API calls/hour | 500 | 500 |
| Quiz attempts/month | 50 | 500 |
| Video generation/month | 3 | 50 |
| Custom quiz creation/month | 5 | 100 |

### Pro-only Features

- Custom handle name in video export
- Advanced analytics
- Completion certificates
- Queue triggers (manually trigger queued messages)
- Smart queue processing (auto-process every 5 min)

### Feature JSON Structure

```json
// Usage-based
{"code": "video_gen", "limit": 5, "description": "Video generation from quiz"}

// Boolean
{"code": "analytics", "description": "Advanced analytics"}
```

---

## Project Structure

```
maedix-q/
├── maedix_q/           # Django project settings
├── core/               # Subscriptions, plans, config
├── users/              # Authentication & profiles
├── instagram/          # Instagram automation & DM flows
├── quiz/               # Quiz system (beta)
├── roleplay/           # Voice roleplay (beta)
├── games/              # Interactive games (beta)
├── youtube/            # YouTube integration (beta)
├── blog/               # Blog & content
├── templates/          # HTML templates
├── static/             # CSS, JS, images
├── lambda/             # AWS Lambda functions
├── aws/                # SAM deployment configs
├── deploy/             # Deployment scripts
├── requirements.txt
└── manage.py
```

---

## Troubleshooting

### 502 Bad Gateway

```bash
sudo systemctl status maedix-q
sudo journalctl -u maedix-q -n 50
ls -la ~/maedix-q/maedix-q.sock
sudo chmod 755 /home/ubuntu
sudo systemctl restart maedix-q
```

### Video Generation Stuck (Beta)

Needs 2GB+ RAM. Add swap if needed:

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Task Not Found Error

Ensure cache directory exists:

```bash
mkdir -p ~/maedix-q/cache
chmod 755 ~/maedix-q/cache
sudo systemctl restart maedix-q
```

---

## License

Private - All rights reserved


##################
python manage.py migrate core 0009 --fake