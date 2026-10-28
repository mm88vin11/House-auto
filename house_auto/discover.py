"""Поиск подходящих чатов и групп по ключевым словам.

Результат — candidates/*.yaml в формате targets.yaml, все записи выключены (enabled: false).
Вы просматриваете список, открываете правила чата и переносите подходящие в targets.yaml.
Ничего никуда не публикуется.
"""

from __future__ import annotations

import os
import re
import time

import yaml

from .config import ROOT, load_targets

DEFAULT_KEYWORDS = [
    "Шахтёрск", "Шахтерск", "Шахтёрск объявления", "Шахтерск барахолка",
    "Торез объявления", "Енакиево объявления", "Харцызск объявления", "Кировское ДНР",
    "Донецк недвижимость", "ДНР недвижимость", "недвижимость ДНР продажа",
    "дома ДНР", "продажа домов Донецк", "Донецк объявления", "ДНР объявления", "Макеевка недвижимость",
]


def _slug(s: str) -> str:
    s = re.sub(r"[^\w]+", "_", s.lower()).strip("_")
    return s[:40] or "chat"


def _known() -> set[str]:
    try:
        targets, _ = load_targets()
    except (OSError, ValueError):
        return set()
    return {str(t.chat).lower().lstrip("@") for t in targets}


def _save(name: str, items: list[dict], header: str) -> str:
    out = ROOT / "candidates" / f"{name}.yaml"
    out.parent.mkdir(exist_ok=True)
    body = yaml.safe_dump(items, allow_unicode=True, sort_keys=False, width=120)
    out.write_text(header + body, encoding="utf-8")
    return str(out.relative_to(ROOT))


def telegram(keywords: list[str]) -> str:
    from telethon.sessions import StringSession
    from telethon.sync import TelegramClient
    from telethon.tl.functions.contacts import SearchRequest
    from telethon.tl.types import Channel

    env = os.environ.get
    if not (env("TG_API_ID") and env("TG_API_HASH") and env("TG_SESSION")):
        raise SystemExit("нет TG_API_ID / TG_API_HASH / TG_SESSION")
    client = TelegramClient(StringSession(env("TG_SESSION", "")), int(env("TG_API_ID", "0")), env("TG_API_HASH", ""))
    client.connect()
    if not client.is_user_authorized():
        raise SystemExit("Сначала выполните: python -m house_auto login")
    known, found = _known(), {}
    try:
        for kw in keywords:
            res = client(SearchRequest(q=kw, limit=100))
            for ch in res.chats:
                if not isinstance(ch, Channel) or not ch.username or ch.username.lower() in known:
                    continue
                found.setdefault(ch.username, (ch, kw))
            time.sleep(2)
    finally:
        client.disconnect()

    groups, channels = [], []
    for username, (ch, kw) in sorted(found.items(), key=lambda kv: -(kv[1][0].participants_count or 0)):
        item = {"id": "tg_" + _slug(username), "platform": "telegram", "chat": "@" + username,
                "name": ch.title, "enabled": False,
                "note": f"участников: {ch.participants_count or '?'}; найдено по «{kw}». "
                        "Прочитайте закреп/правила, при необходимости задайте days и min_interval_days"}
        if ch.megagroup or getattr(ch, "forum", False):
            groups.append(item)
        else:
            # В чужой канал напрямую не написать — только через админа (часто платно, но охват большой).
            channels.append({**item, "platform": "manual", "url": f"https://t.me/{username}",
                             "note": f"КАНАЛ, подписчиков: {ch.participants_count or '?'}. "
                                     "Напишите админу о размещении (контакт обычно в описании)"})
    head = ("# Кандидаты из поиска Telegram. Группы (platform: telegram) — можно постить от вашего аккаунта;\n"
            "# каналы (platform: manual) — размещение через админа. Перенесите нужное в targets.yaml\n"
            "# и поставьте enabled: true.\n\n")
    path = _save("telegram", groups + channels, head)
    return f"Telegram: групп {len(groups)}, каналов {len(channels)} → {path}"


def vk(keywords: list[str]) -> str:
    from .posters.vk import VkPoster

    api = VkPoster(os.environ.get("VK_TOKEN", ""))
    known, ids, hit = _known(), [], {}
    for kw in keywords:
        res = api.call("groups.search", q=kw, count=100)
        for g in res.get("items", []):
            if g["id"] not in hit:
                hit[g["id"]] = kw
                ids.append(g["id"])
        time.sleep(0.4)

    items = []
    for i in range(0, len(ids), 400):
        res = api.call("groups.getById", group_ids=",".join(map(str, ids[i:i + 400])),
                       fields="members_count,can_post,can_suggest,city")
        groups = res.get("groups", res) if isinstance(res, dict) else res
        for g in groups:
            can_post, can_suggest = g.get("can_post"), g.get("can_suggest")
            if not (can_post or can_suggest) or str(-g["id"]) in known or g.get("screen_name", "").lower() in known:
                continue
            items.append((g.get("members_count") or 0, {"id": "vk_" + _slug(g.get("screen_name") or str(g["id"])), "platform": "vk",
                          "chat": str(-g["id"]), "name": g["name"], "enabled": False,
                          "note": f"участников: {g.get('members_count', '?')}; "
                                  f"{'стена открыта' if can_post else 'через «Предложить новость»'}; "
                                  f"найдено по «{hit[g['id']]}»; https://vk.com/{g.get('screen_name', '')}"}))
        time.sleep(0.4)
    items = [it for _, it in sorted(items, key=lambda x: -x[0])]
    head = ("# Кандидаты из поиска ВКонтакте — только группы, куда можно написать или предложить пост.\n"
            "# Перенесите нужное в targets.yaml и поставьте enabled: true.\n\n")
    path = _save("vk", items, head)
    return f"ВКонтакте: групп {len(items)} → {path}"
