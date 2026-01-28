# Telegram Bot on Raspberry Pi

A simple Hello World Telegram bot running on Raspberry Pi 4.

## Prerequisites

- Raspberry Pi 4 with Raspberry Pi OS
- WiFi configured and SSH enabled
- Telegram account

## Setup

### 1. Create Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot` and follow prompts
3. Save the API token you receive

### 2. Prepare Raspberry Pi

SSH into your Pi and install dependencies:

```bash
ssh <username>@<pi-ip-address>
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip -y
pip3 install python-telegram-bot --break-system-packages
```

### 3. Deploy Bot

On your laptop, create `hello_bot.py` and add your bot token.

Copy the script to your Pi:

```bash
scp hello_bot.py <username>@<pi-ip>:/home/<username>/
```

### 4. Set Up as System Service

Create `telegram-bot.service` (replace `<username>` with your Pi username):

```ini
[Unit]
Description=Telegram Hello World Bot
After=network.target

[Service]
Type=simple
User=<username>
WorkingDirectory=/home/<username>
ExecStart=/usr/bin/python3 /home/<username>/hello_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Copy and enable the service:

```bash
scp telegram-bot.service <username>@<pi-ip>:/home/<username>/
ssh <username>@<pi-ip>
sudo mv telegram-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable telegram-bot.service
sudo systemctl start telegram-bot.service
```

### 5. Verify

Check service status:

```bash
sudo systemctl status telegram-bot.service
```

Open Telegram, find your bot, and send `/start`

## Useful Commands

```bash
# Check status
sudo systemctl status telegram-bot.service

# View logs
sudo journalctl -u telegram-bot.service -f

# Restart bot
sudo systemctl restart telegram-bot.service

# Stop bot
sudo systemctl stop telegram-bot.service
```

## Features

- `/start` - Get a hello world message
- Send any text - Bot echoes it back

## Roadmap

- [ ] Flashcard dealer functionality
- [ ] File storage via Telegram

## License

MIT
