#!/usr/bin/env bash
# First-time setup: install Python dependencies and download Chromium.
set -e

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Downloading Chromium for Playwright..."
playwright install chromium

if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "Created .env from template. Please edit it now:"
    echo "  nano .env"
    echo ""
    echo "At minimum set: SMTP_USER, SMTP_PASSWORD, NOTIFY_EMAIL"
else
    echo ".env already exists — skipping."
fi

echo ""
echo "Setup complete. Run the monitor with:"
echo "  python monitor.py --once    # test once"
echo "  python monitor.py           # run continuously"
