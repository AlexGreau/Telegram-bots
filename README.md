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

## Auto-deploy

Two ways to get new code onto the Pi without SSHing in. Both call `deploy.sh`,
which fetches, fast-forwards, reinstalls dependencies **only** if
`requirements.txt` changed, and exits `10` when there was nothing to pull.

### `/update` from Telegram

Send `/update` to the bot. It pulls, replies with the new commit, then exits -
`Restart=always` in the unit brings it straight back on the new code, so no
sudo is involved. Restricted to `UPDATE_ALLOWED_IDS` (defaults to
`ASSIST_ALLOWED_IDS`).

### GitHub webhook (deploy on push)

A second service listens for GitHub push events and restarts the bot.

1. Pick a secret and add it to `.env`:

   ```env
   GITHUB_WEBHOOK_SECRET=<long random string>
   DEPLOY_BRANCH=main
   WEBHOOK_PORT=9000
   WEBHOOK_PATH=/deploy
   ```

2. Let the bot user restart the service without a password:

   ```bash
   sudo visudo -f /etc/sudoers.d/telegram-bot-deploy
   # add this line (check `which systemctl` if the path differs):
   techman ALL=(root) NOPASSWD: /usr/bin/systemctl restart telegram-bot.service
   ```

3. Install and start the listener:

   ```bash
   sudo cp telegram-bot-webhook.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now telegram-bot-webhook.service
   sudo journalctl -u telegram-bot-webhook.service -f
   ```

4. Expose port 9000 to GitHub - either a router port-forward, or a tunnel
   (`cloudflared tunnel --url http://localhost:9000`) if the Pi has no public IP.

5. In the repo: **Settings → Webhooks → Add webhook**
   - Payload URL: `https://<your-host>/deploy`
   - Content type: `application/json`
   - Secret: the same `GITHUB_WEBHOOK_SECRET`
   - Events: *Just the push event*

   GitHub's "Redeliver" button on the ping event is the quickest way to test.

Requests without a valid `X-Hub-Signature-256`, for another branch, or for
another event type are rejected or ignored.

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
