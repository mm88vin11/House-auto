"""Тексты объявления в нескольких форматах — под разные площадки.

full    — полный текст: свой канал, стена ВК, группы без ограничений;
medium  — до 1024 символов: помещается в подпись к фото в Telegram;
short   — до 500 символов: для чатов со строгими правилами по длине;
plain   — полный текст без эмодзи: доски объявлений, Одноклассники, сайты.
"""

from __future__ import annotations

import re

CAPTION_LIMIT = 1024    # подпись к фото в Telegram
SHORT_LIMIT = 500


def fmt_num(x: float) -> str:
    s = f"{x:,.1f}".rstrip("0").rstrip(".")
    return s.replace(",", " ").replace(".", ",")


def price_line(h: dict) -> str:
    if h.get("price"):
        return f"{int(h['price']):,} ₽".replace(",", " ")
    return "цена — в личных сообщениях"


def contact_lines(h: dict) -> list[str]:
    c = h["contact"]
    lines = [f"📷 {h['more_photos']}"] if h.get("more_photos") else []
    if c.get("phone"):
        lines.append(f"📞 {c['phone']}" + (f" — {c['name']}" if c.get("name") else ""))
    if c.get("telegram"):
        lines.append(f"✉️ {c['telegram']}")
    if h.get("site_url"):
        lines.append(f"🌐 Подробнее о доме: {h['site_url']}")
    return lines


def hashtags(h: dict) -> str:
    return " ".join("#" + t for t in h.get("hashtags", []))


def facts_line(h: dict) -> str:
    return (f"{fmt_num(h['area_house'])} м² • участок {fmt_num(h['area_land'])} сот. • "
            f"{h['year_built']} г. ({h['walls']})")


def full(h: dict) -> str:
    extra = " и ".join(h.get("extra_rooms", []))
    parts = [
        f"🏡 Продаётся дом на {h['street'].replace('улица ', '')}, {h['city']} — "
        "крепкий, с хорошей землёй и настоящим потенциалом",
        "",
        f"💰 {cap(price_line(h))}",
        f"📐 {facts_line(h)}",
        f"Планировка: {h['layout']}."
        + (f" Есть {extra} — места хватит с запасом." if extra else ""),
        "",
        f"🎨 {h['condition']}",
        "",
        "Коммуникации:",
        *[f"{u['icon']} {u['name']}: {u['text']}" for u in h.get("utilities", [])],
        "",
        f"📍 Локация: {h['street']}. {h['location']}",
        "",
        "🌳 На участке:",
        "Хозяйство под ключ: " + ", ".join(h.get("outbuildings", [])) + ".",
        "Сад — полноценный: " + ", ".join(h.get("garden", []))
        + ". Урожай каждый год без всяких усилий.",
        h.get("neighbors", ""),
        "",
        "📄 Документы в порядке:"
        + (" дом внесён в российский реестр (ЕГРН)," if h.get("egrn") else "")
        + f" земля — {h['land_category']}, достраиваться и расширяться можно свободно.",
        "",
        "🔥 Дом с реальным потенциалом — не витрина, а хорошая база для тех, кто готов "
        "вложить немного труда и получить взамен просторный участок, сад и крепкие стены.",
        "",
        "Подробности и просмотр — в личные сообщения или по телефону:",
        *contact_lines(h),
        "",
        hashtags(h),
    ]
    return _clean("\n".join(parts))


def medium(h: dict) -> str:
    parts = [
        f"🏡 Продаётся дом, {h['city']}, {h['street']}",
        "",
        f"💰 {cap(price_line(h))}",
        f"📐 {facts_line(h)}",
        f"🏠 {h['layout']}, " + ", ".join(h.get("extra_rooms", [])),
        "🔧 Требует ремонта — отсюда честная цена.",
        f"⚙️ {cap(_utilities_brief(h))}.",
        "🌳 Сад: " + ", ".join(h.get("garden", [])) + ".",
        "🏚 Постройки: " + ", ".join(h.get("outbuildings", [])) + ".",
        f"📄 {'ЕГРН, ' if h.get('egrn') else ''}{h['land_category']}. "
        f"Тихий район, асфальт, рядом школа и магазины.",
        "",
        *contact_lines(h),
        hashtags(h),
    ]
    text = _clean("\n".join(parts))
    if len(text) > CAPTION_LIMIT:   # срезаем наименее важные строки
        text = _clean("\n".join(p for p in parts if not p.startswith(("🏚", "⚙️"))))
    return text


def short(h: dict) -> str:
    parts = [
        f"🏡 Продам дом, {h['city']}, {h['street']}",
        f"{facts_line(h)}",
        f"{h['layout']}. " + cap(_utilities_brief(h))
        + f". Сад, постройки. {'ЕГРН, ' if h.get('egrn') else ''}{h['land_category']}. "
        "Требует ремонта.",
        f"💰 {cap(price_line(h))}",
        *contact_lines(h),
    ]
    return _clean("\n".join(parts))


def plain(h: dict) -> str:
    text = full(h)
    text = _EMOJI.sub("", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    text = re.sub(r"\n#.*$", "", text.strip())   # хэштеги на досках не нужны
    return _clean(text)


VARIANTS = {"full": full, "medium": medium, "short": short, "plain": plain}


def render(h: dict, variant: str) -> str:
    return VARIANTS[variant](h)


def render_all(h: dict) -> dict[str, str]:
    return {name: fn(h) for name, fn in VARIANTS.items()}


_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")


def _utilities_brief(h: dict) -> str:
    return "; ".join(f"{u['name'].lower()} — {u.get('short') or u['text']}"
                     for u in h.get("utilities", []))


def _clean(s: str) -> str:
    s = re.sub(r"[ \t]+\n", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]
