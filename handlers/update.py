import asyncio
import logging
import os
import subprocess

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from config import Config

logger = logging.getLogger(__name__)

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY_SCRIPT = os.path.join(REPO_DIR, "deploy.sh")

NOTHING_TO_DO = 10

BASH = "/bin/bash"
SYSTEM_PATH = "/usr/local/bin:/usr/bin:/bin"

DEPLOY_ENV = {
    # The systemd unit narrows PATH to the venv, which hides git from deploy.sh.
    "PATH": os.pathsep.join(p for p in (os.environ.get("PATH"), SYSTEM_PATH) if p),
    # git must never sit waiting on a prompt it cannot receive - fail fast instead.
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
    "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new",
}


async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in Config.UPDATE_ALLOWED_IDS:
        await update.message.reply_text("Sorry, you are not authorized to use this command.")
        return

    await update.message.reply_text("⏳ Pulling latest code...")

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [BASH, DEPLOY_SCRIPT],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=REPO_DIR,
            stdin=subprocess.DEVNULL,
            env={**os.environ, **DEPLOY_ENV},
        )
    except subprocess.TimeoutExpired:
        await update.message.reply_text("❌ Update timed out after 5 minutes.")
        return
    except Exception as exc:
        # Never leave the user staring at "Pulling latest code..." forever.
        logger.exception("Update crashed")
        await update.message.reply_text(f"❌ Update crashed: {type(exc).__name__}: {exc}")
        return

    output = (result.stdout + result.stderr).strip() or "(no output)"

    if result.returncode == NOTHING_TO_DO:
        await update.message.reply_text(f"✅ {output}")
        return

    if result.returncode != 0:
        logger.error("Update failed (%s): %s", result.returncode, output)
        await update.message.reply_text(f"❌ Update failed:\n{output}")
        return

    await update.message.reply_text(f"{output}\n\n♻️ Restarting, back in a few seconds...")
    logger.info("Update applied, exiting so systemd restarts on the new code")
    # Restart=always in the systemd unit brings the bot back on the new code.
    # os._exit skips cleanup on purpose: it is the only exit that reliably
    # escapes the polling loop from inside a handler.
    asyncio.get_running_loop().call_later(1.0, lambda: os._exit(0))


def register(app):
    app.add_handler(CommandHandler("update", update_command))
