"""GitHub push webhook listener: pulls the latest code and restarts the bot.

Runs as its own systemd service (telegram-bot-webhook.service) so it survives
the bot restart it triggers. Requires GITHUB_WEBHOOK_SECRET in .env and a
sudoers rule allowing `systemctl restart telegram-bot.service` without a
password - see the "Auto-deploy" section of the README.
"""

import hmac
import json
import logging
import os
import subprocess
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("webhook")

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
DEPLOY_SCRIPT = os.path.join(REPO_DIR, "deploy.sh")
SERVICE = os.environ.get("DEPLOY_SERVICE", "telegram-bot.service")
SYSTEMCTL = os.environ.get("SYSTEMCTL_PATH", "/usr/bin/systemctl")
SUDO = os.environ.get("SUDO_PATH", "/usr/bin/sudo")
BRANCH = os.environ.get("DEPLOY_BRANCH", "main")
SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "").encode()
PORT = int(os.environ.get("WEBHOOK_PORT", "9000"))
PATH = os.environ.get("WEBHOOK_PATH", "/deploy")
MAX_BODY = 1_000_000

NOTHING_TO_DO = 10


def signature_ok(body: bytes, header: str) -> bool:
    if not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(SECRET, body, sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def deploy() -> None:
    result = subprocess.run(
        ["bash", DEPLOY_SCRIPT],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=REPO_DIR,
        env={**os.environ, "DEPLOY_BRANCH": BRANCH},
    )
    output = (result.stdout + result.stderr).strip()

    if result.returncode == NOTHING_TO_DO:
        logger.info("%s", output)
        return
    if result.returncode != 0:
        logger.error("Deploy failed (%s): %s", result.returncode, output)
        return

    logger.info("%s", output)
    restart = subprocess.run(
        [SUDO, "-n", SYSTEMCTL, "restart", SERVICE],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if restart.returncode != 0:
        logger.error("Restart failed: %s", (restart.stdout + restart.stderr).strip())
    else:
        logger.info("Restarted %s", SERVICE)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # route access logs through logging
        logger.debug("%s - %s", self.address_string(), fmt % args)

    def reply(self, code: int, message: str) -> None:
        body = message.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != PATH:
            self.reply(404, "not found")
            return

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self.reply(400, "bad body length")
            return
        body = self.rfile.read(length)

        if not signature_ok(body, self.headers.get("X-Hub-Signature-256", "")):
            logger.warning("Rejected request with bad signature from %s", self.address_string())
            self.reply(401, "bad signature")
            return

        event = self.headers.get("X-GitHub-Event", "")
        if event == "ping":
            self.reply(200, "pong")
            return
        if event != "push":
            self.reply(202, f"ignored event: {event}")
            return

        try:
            ref = json.loads(body).get("ref", "")
        except json.JSONDecodeError:
            self.reply(400, "bad json")
            return

        if ref != f"refs/heads/{BRANCH}":
            self.reply(202, f"ignored ref: {ref}")
            return

        # Answer before deploying: the restart kills nothing here, but GitHub
        # times out at 10s and a pip install can take longer.
        self.reply(200, "deploying")
        try:
            deploy()
        except subprocess.TimeoutExpired:
            logger.error("Deploy timed out")


def main():
    if not SECRET:
        raise SystemExit("GITHUB_WEBHOOK_SECRET is not set - refusing to start")
    logger.info("Listening on 0.0.0.0:%s%s for pushes to %s", PORT, PATH, BRANCH)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
