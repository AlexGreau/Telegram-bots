#!/bin/bash
# Pull the latest code and refresh dependencies.
# Does NOT restart the bot - the caller decides how (systemctl, or self-exit).
#
# Exit codes:
#   0  - updated, a restart is needed
#   10 - already up to date, nothing to do
#   *  - failure (message on stderr)
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

BRANCH="${DEPLOY_BRANCH:-main}"
PIP="$(pwd)/venv/bin/pip"

git fetch --quiet origin "$BRANCH"

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "Already up to date at $(git rev-parse --short HEAD)"
    exit 10
fi

DEPS_CHANGED=0
if git diff --name-only "$LOCAL" "$REMOTE" | grep -qx 'requirements.txt'; then
    DEPS_CHANGED=1
fi

echo "Updating $(git rev-parse --short "$LOCAL") -> $(git rev-parse --short "$REMOTE")"
git pull --ff-only --quiet origin "$BRANCH"

if [ "$DEPS_CHANGED" -eq 1 ]; then
    echo "requirements.txt changed, installing dependencies..."
    "$PIP" install --quiet -r requirements.txt
fi

echo "Now at $(git rev-parse --short HEAD): $(git log -1 --pretty=%s)"
