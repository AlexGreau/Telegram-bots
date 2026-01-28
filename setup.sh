#!/bin/bash
set -e

echo "Setting up Telegram Bot..."

# Create virtual environment
echo "Creating virtual environment..."
python3 -m venv venv

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install requirements
echo "Installing dependencies..."
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file..."
    cp .env.example .env
    echo "⚠️  Please edit .env and add your TELEGRAM_BOT_TOKEN"
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env and add your bot token:"
echo "   nano .env"
echo ""
echo "2. Test the bot:"
echo "   source venv/bin/activate"
echo "   python bot.py"
echo ""
echo "3. Deploy as service:"
echo "   sudo cp telegram-bot.service /etc/systemd/system/"
echo "   sudo systemctl daemon-reload"
echo "   sudo systemctl enable telegram-bot.service"
echo "   sudo systemctl start telegram-bot.service"
