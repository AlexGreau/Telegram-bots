import logging
from telegram.ext import Application

from config import Config
from handlers import register_handlers

logging.basicConfig(
    level=Config.LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    app = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()
    register_handlers(app)
    app.run_polling()


if __name__ == "__main__":
    main()