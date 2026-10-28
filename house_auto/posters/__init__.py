"""Отправщики постов. У каждого: post(target, text, photos) -> ref и delete(target, ref)."""

from __future__ import annotations


class PosterError(Exception):
    """Ошибка публикации. stop_platform=True — дальше на этой платформе в этом запуске не постим
    (флуд-контроль, капча, слетела авторизация), чтобы не усугублять и не получить бан."""

    def __init__(self, message: str, stop_platform: bool = False):
        super().__init__(message)
        self.stop_platform = stop_platform
