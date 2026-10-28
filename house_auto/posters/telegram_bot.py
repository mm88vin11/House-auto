"""Публикация в ваш собственный Telegram-канал через бота (Bot API).

Бот должен быть администратором канала с правом публикации. Токен — TG_BOT_TOKEN от @BotFather.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path

import requests

from ..config import Target
from ..texts import CAPTION_LIMIT
from . import PosterError

API = "https://api.telegram.org/bot{token}/{method}"


class TelegramBotPoster:
    platform = "telegram_bot"

    def __init__(self, token: str):
        if not token:
            raise PosterError("нет TG_BOT_TOKEN — см. README, раздел «Свой канал»", stop_platform=True)
        self.token = token

    def close(self) -> None:
        pass

    def _call(self, method: str, data: dict, files: dict | None = None) -> dict | list:
        try:
            r = requests.post(API.format(token=self.token, method=method), data=data, files=files, timeout=120)
            body = r.json()
        except (requests.RequestException, ValueError) as e:
            raise PosterError(f"Bot API недоступен: {e}")
        if not body.get("ok"):
            desc = body.get("description", "")
            code = body.get("error_code")
            raise PosterError(f"Bot API {method}: {code} {desc}", stop_platform=code in (401, 429))
        return body["result"]

    def post(self, t: Target, text: str, photos: list[Path]) -> dict:
        base = {"chat_id": t.chat}
        if t.topic_id:
            base["message_thread_id"] = t.topic_id
        ids = []
        photos = photos[:10]
        caption = text if len(text) <= CAPTION_LIMIT else None
        if len(photos) == 1:
            with open(photos[0], "rb") as f:
                msg = self._call("sendPhoto", {**base, **({"caption": caption} if caption else {})},
                                 files={"photo": f})
            ids.append(msg["message_id"])
        elif photos:
            media = [{"type": "photo", "media": f"attach://p{i}"} for i in range(len(photos))]
            if caption:
                media[0]["caption"] = caption
            with ExitStack() as stack:
                files = {f"p{i}": stack.enter_context(open(p, "rb")) for i, p in enumerate(photos)}
                msgs = self._call("sendMediaGroup", {**base, "media": json.dumps(media, ensure_ascii=False)},
                                  files=files)
            ids += [m["message_id"] for m in msgs]
        if not photos or not caption:
            msg = self._call("sendMessage", {**base, "text": text,
                                             "link_preview_options": json.dumps({"is_disabled": True})})
            ids.append(msg["message_id"])
        chat = str(t.chat)
        link = f"https://t.me/{chat.lstrip('@')}/{ids[0]}" if chat.startswith("@") else ""
        return {"chat": chat, "message_ids": ids, "link": link}

    def delete(self, t: Target, ref: dict) -> None:
        self._call("deleteMessages", {"chat_id": ref.get("chat") or t.chat,
                                      "message_ids": json.dumps(ref["message_ids"])})

    def notify(self, chat_id: str, text: str) -> None:
        """Отчёт владельцу в личку (длинный текст режем по лимиту Telegram)."""
        for i in range(0, len(text), 4000):
            self._call("sendMessage", {"chat_id": chat_id, "text": text[i:i + 4000],
                                       "link_preview_options": json.dumps({"is_disabled": True})})
