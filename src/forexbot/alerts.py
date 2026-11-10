"""Optional paper-session notifications."""

from collections.abc import Mapping
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class Alerter:
    def send(self, event: str, details: Mapping[str, object]) -> None:
        raise NotImplementedError


class NullAlerter(Alerter):
    def send(self, event: str, details: Mapping[str, object]) -> None:
        return


class TelegramAlerter(Alerter):
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 5.0) -> None:
        if not bot_token or not chat_id:
            raise ValueError("Telegram bot token and chat ID are required")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout = timeout

    def send(self, event: str, details: Mapping[str, object]) -> None:
        message = "ForexBot paper: " + event.replace("_", " ")
        if details:
            message += "\n" + "\n".join(f"{key}: {value}" for key, value in details.items())
        request = Request(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            data=urlencode({"chat_id": self.chat_id, "text": message}).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read())
        if not payload.get("ok"):
            raise RuntimeError("Telegram rejected the notification")


def create_alerter(environment: Mapping[str, str] | None = None) -> Alerter:
    values = environment if environment is not None else os.environ
    bot_token = values.get("FOREXBOT_TELEGRAM_BOT_TOKEN", "")
    chat_id = values.get("FOREXBOT_TELEGRAM_CHAT_ID", "")
    if not bot_token and not chat_id:
        return NullAlerter()
    if not bot_token or not chat_id:
        raise ValueError("Set both FOREXBOT_TELEGRAM_BOT_TOKEN and FOREXBOT_TELEGRAM_CHAT_ID")
    return TelegramAlerter(bot_token, chat_id)
