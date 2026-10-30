"""Загрузка карточки дома и списка площадок."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Папка с данными (house.yaml, targets.yaml, photos/, state/). Приложение задаёт её через
# HOUSE_AUTO_HOME до импорта остальных модулей; по умолчанию — корень репозитория.
ROOT = Path(os.environ.get("HOUSE_AUTO_HOME") or Path(__file__).resolve().parent.parent)
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
PLATFORMS = {"telegram", "telegram_bot", "vk", "manual"}
VARIANTS = {"full", "medium", "short", "plain"}


def load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_house(path: Path | None = None) -> dict:
    house = load_yaml(path or ROOT / "house.yaml")
    for key in ("title", "city", "area_house", "area_land", "contact"):
        if not house.get(key):
            raise ValueError(f"house.yaml: не заполнено поле «{key}»")
    if not house["contact"].get("phone") and not house["contact"].get("telegram"):
        raise ValueError("house.yaml: укажите телефон или telegram в contact")
    return house


def list_photos(house: dict, root: Path = ROOT) -> list[Path]:
    """Фото по порядку имён; plan.* (планировка) всегда последним."""
    folder = root / house.get("photos_dir", "photos")
    if not folder.is_dir():
        return []
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in PHOTO_EXT)
    plans = [p for p in files if p.stem.lower() == "plan"]
    return [p for p in files if p not in plans] + plans


@dataclass
class Target:
    id: str
    platform: str
    chat: str = ""              # @username / ссылка / числовой id; для vk — owner_id группы (-123)
    name: str = ""
    url: str = ""
    variant: str = "medium"
    photos: int = 5             # сколько фото прикладывать (0 — без фото)
    min_interval_days: float = 3
    days: list[str] = field(default_factory=list)   # пусто — любой день
    topic_id: int | None = None                     # тема в Telegram-форуме
    delete_previous: bool = True                    # удалять прошлый пост перед новым
    enabled: bool = True
    note: str = ""


def load_targets(path: Path | None = None) -> tuple[list[Target], dict]:
    data = load_yaml(path or ROOT / "targets.yaml")
    settings = data.get("settings", {}) or {}
    defaults = data.get("defaults", {}) or {}
    targets, seen = [], set()
    for raw in data.get("targets", []) or []:
        merged = {**defaults, **raw}
        t = Target(**merged)
        if t.id in seen:
            raise ValueError(f"targets.yaml: повторяется id «{t.id}»")
        seen.add(t.id)
        if t.platform not in PLATFORMS:
            raise ValueError(f"targets.yaml [{t.id}]: неизвестная платформа «{t.platform}»")
        if t.variant not in VARIANTS:
            raise ValueError(f"targets.yaml [{t.id}]: неизвестный вариант текста «{t.variant}»")
        bad = [d for d in t.days if d not in WEEKDAYS]
        if bad:
            raise ValueError(f"targets.yaml [{t.id}]: неверные дни {bad}, нужно {WEEKDAYS}")
        if t.platform != "manual" and not t.chat:
            raise ValueError(f"targets.yaml [{t.id}]: не указан chat")
        targets.append(t)
    return targets, settings
