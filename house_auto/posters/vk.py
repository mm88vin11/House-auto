"""Публикация на стены сообществ ВКонтакте от вашего аккаунта (VK API).

Если стена группы открыта — пост появится сразу; если «предложить новость» —
уйдёт администраторам в предложку. Токен пользователя — VK_TOKEN (права wall, photos, groups, offline).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import requests

from ..config import Target
from . import PosterError

API = "https://api.vk.com/method/"
VERSION = "5.199"
STOP_CODES = {5, 9, 14, 17, 29}   # авторизация, флуд-контроль, капча, валидация, лимит


class VkPoster:
    platform = "vk"

    def __init__(self, token: str):
        if not token:
            raise PosterError("нет VK_TOKEN — см. README, раздел ВКонтакте", stop_platform=True)
        self.token = token
        self._uploaded: dict[tuple, list[str]] = {}   # одни и те же фото грузим один раз за запуск

    def close(self) -> None:
        pass

    def call(self, method: str, **params) -> dict | list:
        params.update(access_token=self.token, v=VERSION)
        for attempt in range(3):
            try:
                body = requests.post(API + method, data=params, timeout=60).json()
            except (requests.RequestException, ValueError) as e:
                raise PosterError(f"VK API недоступен: {e}")
            err = body.get("error")
            if not err:
                return body["response"]
            if err.get("error_code") == 6 and attempt < 2:   # слишком много запросов в секунду
                time.sleep(1.5)
                continue
            code = err.get("error_code")
            raise PosterError(f"VK {method}: {code} {err.get('error_msg')}", stop_platform=code in STOP_CODES)
        raise AssertionError("unreachable")

    def owner_id(self, chat: str) -> int:
        chat = str(chat).strip()
        if re.fullmatch(r"-?\d+", chat):
            return int(chat)
        name = re.sub(r"^(https?://)?(m\.)?vk\.(com|ru)/", "", chat).strip("/")
        m = re.fullmatch(r"(?:club|public|event)(\d+)", name)
        if m:
            return -int(m.group(1))
        res = self.call("utils.resolveScreenName", screen_name=name)
        if not res:
            raise PosterError(f"VK: не найдено сообщество «{chat}»")
        oid = int(res["object_id"])
        return -oid if res["type"] in ("group", "page", "event") else oid

    def _attachments(self, photos: list[Path]) -> list[str]:
        key = tuple(photos)
        if key in self._uploaded:
            return self._uploaded[key]
        result = []
        for p in photos:
            server = self.call("photos.getWallUploadServer")
            with open(p, "rb") as f:
                up = requests.post(server["upload_url"], files={"photo": f}, timeout=120).json()
            saved = self.call("photos.saveWallPhoto", server=up["server"], photo=up["photo"], hash=up["hash"])
            result.append(f"photo{saved[0]['owner_id']}_{saved[0]['id']}")
            time.sleep(0.4)
        self._uploaded[key] = result
        return result

    def post(self, t: Target, text: str, photos: list[Path]) -> dict:
        owner = self.owner_id(t.chat)
        attachments = self._attachments(photos[:10])
        res = self.call("wall.post", owner_id=owner, message=text, attachments=",".join(attachments))
        post_id = res["post_id"]
        return {"owner_id": owner, "post_id": post_id, "link": f"https://vk.com/wall{owner}_{post_id}"}

    def delete(self, t: Target, ref: dict) -> None:
        self.call("wall.delete", owner_id=ref["owner_id"], post_id=ref["post_id"])
