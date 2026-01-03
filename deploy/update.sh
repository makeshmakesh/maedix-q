#!/bin/bash
#
# Update deployment script for maedix-q on AWS EC2
# Usage: ./update.sh [--no-restart] [--migrate] [--static]
#

set -e

# Configuration
APP_NAME="maedix-q"
APP_USER="ubuntu"
APP_DIR="/home/$APP_USER/$APP_NAME"
BRANCH="main"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default options
DO_RESTART=true
DO_MIGRATE=true
DO_STATIC=true
DO_DEPS=true

print_status() {
    echo -e "${GREEN}[*]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_info() {
    echo -e "${BLUE}[i]${NC} $1"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --no-restart)
            DO_RESTART=false
            shift
            ;;
        --no-migrate)
            DO_MIGRATE=false
            shift
            ;;
        --no-static)
            DO_STATIC=false
            shift
            ;;
        --no-deps)
            DO_DEPS=false
            shift
            ;;
        --quick)
            DO_MIGRATE=false
            DO_STATIC=false
            DO_DEPS=false
            shift
            ;;
        --help)
            echo "Usage: $0 [options]"
            echo ""
            echo "Options:"
            echo "  --no-restart  Don't restart the service after update"
            echo "  --no-migrate  Skip database migrations"
            echo "  --no-static   Skip collecting static files"
            echo "  --no-deps     Skip installing dependencies"
            echo "  --quick       Quick update (no migrate, static, or deps)"
            echo "  --help        Show this help message"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "================================================"
echo "  Maedix-Q Update Deployment"
echo "================================================"
echo ""

# Check if running as correct user or root
if [ "$EUID" -ne 0 ] && [ "$USER" != "$APP_USER" ]; then
    print_error "Please run as root (sudo) or as $APP_USER"
    exit 1
fi

# Navigate to app directory
cd $APP_DIR

# Show current version
print_info "Current commit: $(git rev-parse --short HEAD)"

# Pull latest changes
print_status "Pulling latest changes from $BRANCH..."
if [ "$EUID" -eq 0 ]; then
    sudo -u $APP_USER git fetch origin
    sudo -u $APP_USER git reset --hard origin/$BRANCH
else
    git fetch origin
    git reset --hard origin/$BRANCH
fi

# Show new version
print_info "Updated to commit: $(git rev-parse --short HEAD)"

# Install dependencies if requirements changed
if [ "$DO_DEPS" = true ]; then
    print_status "Installing/updating Python dependencies..."
    if [ "$EUID" -eq 0 ]; then
        sudo -u $APP_USER $APP_DIR/venv/bin/pip install -r requirements.txt --quiet
    else
        $APP_DIR/venv/bin/pip install -r requirements.txt --quiet
    fi
fi

# Run migrations
if [ "$DO_MIGRATE" = true ]; then
    print_status "Running database migrations..."
    if [ "$EUID" -eq 0 ]; then
        sudo -u $APP_USER $APP_DIR/venv/bin/python manage.py migrate --noinput
    else
        $APP_DIR/venv/bin/python manage.py migrate --noinput
    fi
fi

# Collect static files
if [ "$DO_STATIC" = true ]; then
    print_status "Collecting static files..."
    if [ "$EUID" -eq 0 ]; then
        sudo -u $APP_USER $APP_DIR/venv/bin/python manage.py collectstatic --noinput --clear
    else
        $APP_DIR/venv/bin/python manage.py collectstatic --noinput --clear
    fi
fi

# Restart service
if [ "$DO_RESTART" = true ]; then
    print_status "Restarting maedix-q service..."
    if [ "$EUID" -eq 0 ]; then
        systemctl restart maedix-q
    else
        sudo systemctl restart maedix-q
    fi

    # Wait and check status
    sleep 2
    if systemctl is-active --quiet maedix-q; then
        print_status "Service restarted successfully!"
    else
        print_error "Service failed to start. Check logs with: journalctl -u maedix-q -n 50"
        exit 1
    fi
fi

echo ""
echo "================================================"
echo -e "${GREEN}  Update Complete!${NC}"
echo "================================================"
echo ""
print_info "Commit: $(git rev-parse --short HEAD)"
print_info "Time: $(date)"
echo ""
echo "Useful commands:"
echo "  - Check status: sudo systemctl status maedix-q"
echo "  - View logs: sudo journalctl -u maedix-q -f"
echo "  - Check app logs: tail -f $APP_DIR/logs/gunicorn-error.log"
echo ""
