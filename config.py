import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_BOT_TOKEN:
        token_path = os.path.join(os.path.dirname(__file__), "token.txt")
        if os.path.exists(token_path):
            with open(token_path, "r", encoding="utf8") as f:
                TELEGRAM_BOT_TOKEN = f.read().strip()

    if not TELEGRAM_BOT_TOKEN:
        raise SystemExit("Bot token not found. Set TELEGRAM_BOT_TOKEN or create token.txt")

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
    DEBUG = os.environ.get("DEBUG", "False").lower() == "true"
