"""Socket Mode runner for the orchestrator bot (짐).

The orchestrator no longer owns user-facing slash commands — `/psearch`, `/usdtw`,
`/reply` have been transferred to the personal bot runner at
[apps/personal-bot/socket_mode_runner.py](../personal-bot/socket_mode_runner.py).

This runner keeps a Socket Mode connection alive so the orchestrator can react to
channel mentions and (future) orchestration events. Add new handlers here only if
they are orchestration-layer concerns (state fan-out, worker dispatch, status
reporting) — not feature work.
"""

import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from shared.profile import get_persona
from shared.utils import to_slack_format

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv(REPO_ROOT / ".env")

ORCHESTRATOR_PERSONA = get_persona("orchestrator")


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def build_app() -> App:
    bot_token = _required_env("SLACK_BOT_TOKEN")
    signing_secret = _required_env("SLACK_SIGNING_SECRET")

    app = App(token=bot_token, signing_secret=signing_secret)

    @app.event("app_mention")
    def handle_mention(event, say, logger):
        user_id = (event.get("user") or "").strip()
        thread_ts = (event.get("thread_ts") or "").strip()
        redirect = (
            f"<@{user_id}> 짐은 오케스트레이션만 한다곰. "
            "검색·환율·답장 초안은 쥐피티(개인봇)에게 요청하라곰. :king_gom:"
        )
        say(text=to_slack_format(redirect), thread_ts=thread_ts or None)

    return app


def main() -> None:
    app_token = _required_env("SLACK_APP_TOKEN")
    app = build_app()

    logger.info("Starting orchestrator Socket Mode handler")
    SocketModeHandler(app, app_token).start()


if __name__ == "__main__":
    main()
