"""Публикация в Telegram-чаты от вашего личного аккаунта (через Telethon).

Бот в чужие чаты писать не может — поэтому для чатов нужен именно ваш аккаунт.
Авторизация — строкой сессии (TG_SESSION), её один раз получает команда `login`.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from ..config import Target
from ..texts import CAPTION_LIMIT
from . import PosterError

MAX_FLOOD_WAIT = 120    # если Telegram просит подождать дольше — останавливаемся


def parse_chat(chat: str) -> str | int:
    chat = chat.strip()
    if re.fullmatch(r"-?\d+", chat):
        return int(chat)
    m = re.match(r"(?:https?://)?t\.me/(?!\+|joinchat/)([\w\d_]+)", chat)
    if m:
        return m.group(1)
    return chat  # @username или ссылка-приглашение t.me/+...


class TelegramUserPoster:
    platform = "telegram"

    def __init__(self, api_id: str, api_hash: str, session: str):
        from telethon.sessions import StringSession
        from telethon.sync import TelegramClient

        if not (api_id and api_hash and session):
            raise PosterError("нет TG_API_ID / TG_API_HASH / TG_SESSION — см. README, раздел Telegram",
                              stop_platform=True)
        self.client = TelegramClient(StringSession(session), int(api_id), api_hash,
                                     timeout=15, connection_retries=2, request_retries=2)
        self.client.connect()
        if not self.client.is_user_authorized():
            raise PosterError("сессия Telegram недействительна — заново выполните login", stop_platform=True)
        self._dialogs_loaded = False

    def close(self) -> None:
        self.client.disconnect()

    def _entity(self, chat: str):
        from telethon.tl.functions.channels import JoinChannelRequest
        from telethon.errors import UserAlreadyParticipantError
        from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest
        from telethon.tl.types import Channel

        ref = parse_chat(chat)
        invite = re.search(r"t\.me/(?:\+|joinchat/)([\w-]+)", str(ref))
        if invite:
            try:
                upd = self.client(ImportChatInviteRequest(invite.group(1)))
                return upd.chats[0]
            except UserAlreadyParticipantError:
                return self.client(CheckChatInviteRequest(invite.group(1))).chat
        try:
            entity = self.client.get_entity(ref)
        except ValueError:
            # числовой id: нужен кэш диалогов — подгружаем один раз
            if self._dialogs_loaded:
                raise
            self.client.get_dialogs()
            self._dialogs_loaded = True
            entity = self.client.get_entity(ref)
        if isinstance(entity, Channel) and getattr(entity, "left", False):
            self.client(JoinChannelRequest(entity))   # публичная группа — вступаем перед постом
            time.sleep(3)
        return entity

    def post(self, t: Target, text: str, photos: list[Path]) -> dict:
        from telethon import errors

        for attempt in (1, 2):
            try:
                entity = self._entity(t.chat)
                is_bot = getattr(entity, "bot", False)
                if is_bot:   # бот-«предложка» канала: сначала /start, затем само объявление
                    self.client.send_message(entity, "/start")
                    time.sleep(3)
                files = [str(p) for p in photos[:10]]
                msgs = []
                if files and len(text) <= CAPTION_LIMIT:
                    msgs += _as_list(self.client.send_file(entity, files, caption=text, reply_to=t.topic_id,
                                                              parse_mode=None))
                else:
                    if files:
                        msgs += _as_list(self.client.send_file(entity, files, reply_to=t.topic_id))
                    msgs.append(self.client.send_message(entity, text, reply_to=t.topic_id,
                                                         link_preview=False, parse_mode=None))
                username = getattr(entity, "username", None)
                last = msgs[0].id
                return {"chat": t.chat, "message_ids": [m.id for m in msgs],
                        "link": f"https://t.me/{username}/{last}" if username and not is_bot
                                else "отправлено админам на модерацию" if is_bot else ""}
            except errors.FloodWaitError as e:
                if attempt == 1 and e.seconds <= MAX_FLOOD_WAIT:
                    time.sleep(e.seconds + 2)
                    continue
                raise PosterError(f"Telegram просит паузу {e.seconds} с — останавливаемся", stop_platform=True)
            except errors.SlowModeWaitError as e:
                raise PosterError(f"в чате медленный режим, ждать {e.seconds} с — пропуск")
            except (errors.ChatWriteForbiddenError, errors.UserBannedInChannelError,
                    errors.ChatAdminRequiredError, errors.ChannelPrivateError) as e:
                raise PosterError(f"нет права писать в чат ({type(e).__name__}) — проверьте правила/доступ")
            except errors.PeerFloodError:
                raise PosterError("Telegram ограничил аккаунт за частые сообщения (PeerFlood) — "
                                  "сделайте перерыв на сутки", stop_platform=True)
            except errors.AuthKeyError as e:
                raise PosterError(f"проблема авторизации: {e}", stop_platform=True)
            except (errors.RPCError, ValueError) as e:
                raise PosterError(f"{type(e).__name__}: {e}")
        raise AssertionError("unreachable")

    def delete(self, t: Target, ref: dict) -> None:
        from telethon import errors

        try:
            entity = self._entity(ref.get("chat") or t.chat)
            self.client.delete_messages(entity, ref["message_ids"])
        except (errors.RPCError, ValueError) as e:
            raise PosterError(f"не удалось удалить: {type(e).__name__}: {e}")


def _as_list(x) -> list:
    return x if isinstance(x, list) else [x]
