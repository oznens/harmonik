"""Telegram Bot API üzerine ince httpx sarmalayıcı.

Sadece bizim ihtiyaçlarımız: getMe, getUpdates, sendMessage, sendPhoto.
python-telegram-bot kullanmıyoruz — bağımlılık ve karmaşıklığa gerek yok.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from terminal.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger(__name__)

BASE_URL = "https://api.telegram.org"


class TelegramError(Exception):
    """Telegram API başarısız çağrı."""


class TelegramClient:
    """Tek bot için sync REST istemcisi."""

    def __init__(self, token: str | None = None, default_chat_id: str | None = None, timeout: float = 15.0) -> None:
        self.token = (token or TELEGRAM_BOT_TOKEN).strip()
        self.default_chat_id = (default_chat_id or TELEGRAM_CHAT_ID).strip()
        if not self.token:
            raise TelegramError("TELEGRAM_BOT_TOKEN yok (.env veya parametre).")
        self._client = httpx.Client(base_url=f"{BASE_URL}/bot{self.token}", timeout=timeout)

    def _call(self, method: str, **params: Any) -> Any:
        try:
            r = self._client.post(f"/{method}", data=params)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise TelegramError(f"{method} başarısız: {e}") from e
        body = r.json()
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description', body)}")
        return body["result"]

    def _call_with_file(self, method: str, file_field: str, file_bytes: bytes, **params: Any) -> Any:
        try:
            r = self._client.post(
                f"/{method}",
                data=params,
                files={file_field: ("chart.png", file_bytes, "image/png")},
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise TelegramError(f"{method} başarısız: {e}") from e
        body = r.json()
        if not body.get("ok"):
            raise TelegramError(f"{method}: {body.get('description', body)}")
        return body["result"]

    def get_me(self) -> dict:
        return self._call("getMe")

    def get_updates(self, offset: int | None = None, timeout: int = 5) -> list[dict]:
        params: dict[str, Any] = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        return self._call("getUpdates", **params)

    def send_message(self, text: str, chat_id: str | None = None, parse_mode: str = "Markdown") -> dict:
        cid = chat_id or self.default_chat_id
        if not cid:
            raise TelegramError("chat_id yok (parametre veya TELEGRAM_CHAT_ID gerekli).")
        return self._call(
            "sendMessage",
            chat_id=cid,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview="true",
        )

    def send_photo(
        self,
        photo: bytes,
        caption: str | None = None,
        chat_id: str | None = None,
        parse_mode: str = "Markdown",
    ) -> dict:
        cid = chat_id or self.default_chat_id
        if not cid:
            raise TelegramError("chat_id yok.")
        params: dict[str, Any] = {"chat_id": cid, "parse_mode": parse_mode}
        if caption:
            params["caption"] = caption
        return self._call_with_file("sendPhoto", "photo", photo, **params)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TelegramClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
