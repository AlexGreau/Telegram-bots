# Telegram Bot

A modular Telegram bot designed to run on Raspberry Pi with systemd integration.

## Features

- `/start` - Start command
- Echo any text message back
- Auto-discovery handler system
- Environment-based configuration
- Systemd service integration

## Quick Start

### 1. Create Bot Token

Open Telegram and message `@BotFather`:
- Send `/newbot`
- Follow the prompts
- Save your bot token

### 2. Clone & Setup

```bash
git clone https://github.com/AlexGreau/Telegram-bots.git
cd Telegram-bots

# Automated setup
chmod +x setup.sh
./setup.sh

# Configure bot token
nano .env
# Add your TELEGRAM_BOT_TOKEN
```

### 3. Test Locally

```bash
source venv/bin/activate
python bot.py
```

Send `/start` to your bot in Telegram. If it responds, you're good!

### 4. Deploy as Service

```bash
sudo cp telegram-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot.service
sudo systemctl start telegram-bot.service

# Verify
sudo systemctl status telegram-bot.service
```

## Project Structure

```
.
├── bot.py                 # Main entry point
├── config.py              # Configuration management
├── requirements.txt       # Python dependencies
├── .env.example           # Environment template
├── setup.sh               # Automated setup script
├── telegram-bot.service   # Systemd service file
└── handlers/              # Handler modules
    ├── __init__.py        # Auto-discovery
    └── hello.py           # Example handlers
```

## Commands

### Service Management

```bash
# Check status
sudo systemctl status telegram-bot.service

# View live logs
sudo journalctl -u telegram-bot.service -f

# Restart bot
sudo systemctl restart telegram-bot.service

# Stop bot
sudo systemctl stop telegram-bot.service
```

### Development

```bash
# Activate environment
source venv/bin/activate

# Install/update dependencies
pip install -r requirements.txt

# Run bot manually
python bot.py
```

## Configuration

Edit `.env` to customize:

```env
TELEGRAM_BOT_TOKEN=your_token_here
LOG_LEVEL=INFO
DEBUG=False
```

## Updating Code

1. Make changes locally
2. Commit and push
3. On Pi: `git pull`
4. Restart service: `sudo systemctl restart telegram-bot.service`

**Note:** You only need to restart the service. No need to recreate the venv or reinstall dependencies.

## Adding Handlers

1. Create a new file in `handlers/` (e.g., `handlers/myhandler.py`)
2. Implement a `register(app)` function
3. The handler auto-discovers and registers on startup

Example:

```python
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

async def my_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("My response")

def register(app):
    app.add_handler(CommandHandler("mycommand", my_command))
```

## Troubleshooting

### Bot stops after restart

Check logs:
```bash
sudo journalctl -u telegram-bot.service -n 50
```

### Multiple instances running

```bash
# Kill all bot processes
pkill -f "python bot.py"

# Restart service
sudo systemctl restart telegram-bot.service
```

### Token not found

Ensure `.env` is in the project directory with `TELEGRAM_BOT_TOKEN` set.

## License

MIT
