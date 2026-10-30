"""Главный запуск: «одна кнопка» — публикует везде, где пора, и пишет отчёт."""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field

from . import texts
from .config import ROOT, Target, list_photos, load_house, load_targets
from .posters import PosterError
from .scheduler import plan
from .state import State, now


def make_poster(platform: str):
    env = os.environ.get
    if platform == "telegram":
        from .posters.telegram_user import TelegramUserPoster
        return TelegramUserPoster(env("TG_API_ID", ""), env("TG_API_HASH", ""), env("TG_SESSION", ""))
    if platform == "telegram_bot":
        from .posters.telegram_bot import TelegramBotPoster
        return TelegramBotPoster(env("TG_BOT_TOKEN", ""))
    if platform == "vk":
        from .posters.vk import VkPoster
        return VkPoster(env("VK_TOKEN", ""))
    raise ValueError(platform)


@dataclass
class Report:
    dry_run: bool
    ok: list[tuple[Target, str]] = field(default_factory=list)
    failed: list[tuple[Target, str]] = field(default_factory=list)
    skipped: list[tuple[Target, str]] = field(default_factory=list)
    manual: list[Target] = field(default_factory=list)

    def text(self) -> str:
        quiet = ("выключено", "ручная площадка")
        waiting = [(t, why) for t, why in self.skipped if why not in quiet]
        off = sum(1 for _, why in self.skipped if why == "выключено")
        head = "🧪 Пробный запуск (ничего не отправлено)" if self.dry_run else "🏡 Отчёт о публикации"
        lines = [head, f"✅ {'к отправке' if self.dry_run else 'опубликовано'}: {len(self.ok)}   "
                       f"❌ ошибок: {len(self.failed)}   ⏭ ждут своей очереди: {len(waiting)}"]
        if self.ok or self.failed:
            lines.append("")
        lines += [f"✅ {t.name or t.id}: {link or 'ok'}" for t, link in self.ok]
        lines += [f"❌ {t.name or t.id}: {err}" for t, err in self.failed]
        if waiting:
            lines += ["", "Ждут:"] + [f"⏭ {t.name or t.id}: {why}" for t, why in waiting]
        if off:
            lines += ["", f"Выключенных площадок: {off} (enabled: false в targets.yaml)"]
        if self.manual:
            lines += ["", f"✋ Ручные площадки ({len(self.manual)}) — тексты в out/kit.html:"]
            lines += [f"• {t.name or t.id} {t.url}".rstrip() for t in self.manual]
        return "\n".join(lines)


def run(*, dry_run: bool = False, only: set[str] | None = None, force: bool = False,
        state: State | None = None, poster_factory=make_poster, sleep=time.sleep,
        progress=lambda line: None) -> Report:
    house = load_house()
    targets, settings = load_targets()
    state = state or State()
    photos = list_photos(house)
    limit = int(settings.get("max_posts_per_run", 20))
    delay = settings.get("delay_seconds", [45, 120])

    todo, skipped = plan(targets, state, now(), limit, only=only, force=force)
    report = Report(dry_run=dry_run, skipped=skipped,
                    manual=[t for t in targets if t.platform == "manual" and t.enabled])
    posters: dict[str, object] = {}
    stopped: dict[str, str] = {}
    last_sent: dict[str, float] = {}

    try:
        for t in todo:
            if t.platform in stopped:
                report.skipped.append((t, f"платформа остановлена: {stopped[t.platform]}"))
                continue
            text = texts.render(house, t.variant)
            pics = photos[:t.photos] if t.photos else []
            if dry_run:
                report.ok.append((t, f"[{t.variant}, {len(text)} симв., фото: {len(pics)}]"))
                continue
            try:
                if t.platform not in posters:
                    posters[t.platform] = poster_factory(t.platform)
                poster = posters[t.platform]
                # Пауза между постами на одной платформе — как у живого человека, а не бота.
                if t.platform in last_sent:
                    wait = random.uniform(*delay) - (time.monotonic() - last_sent[t.platform])
                    if wait > 0:
                        progress(f"⏳ пауза {wait:.0f} с перед «{t.name or t.id}»")
                        sleep(wait)
                prev = state.live.get(t.id)
                if prev and t.delete_previous:
                    try:
                        poster.delete(t, prev["ref"])
                        state.record(t.id, "ok", ref=prev["ref"], action="delete")
                    except PosterError as e:   # старый пост мог удалить админ — это не мешает новому
                        state.record(t.id, "error", ref=prev["ref"], error=str(e), action="delete")
                        state.live.pop(t.id, None)
                ref = {**poster.post(t, text, pics), "platform": t.platform}
                last_sent[t.platform] = time.monotonic()
                state.record(t.id, "ok", ref=ref)
                report.ok.append((t, ref.get("link", "")))
                progress(f"✅ {t.name or t.id}: {ref.get('link') or 'ok'}")
            except PosterError as e:
                last_sent[t.platform] = time.monotonic()
                state.record(t.id, "error", error=str(e))
                report.failed.append((t, str(e)))
                progress(f"❌ {t.name or t.id}: {e}")
                if e.stop_platform:
                    stopped[t.platform] = str(e)
            finally:
                if not dry_run:
                    state.save()   # сохраняем после каждого поста — на случай обрыва
    finally:
        for p in posters.values():
            p.close()
    return report


def remove_all(*, only: set[str] | None = None, poster_factory=make_poster) -> Report:
    """Снять все живые объявления (дом продан или меняется цена)."""
    targets, _ = load_targets()
    by_id = {t.id: t for t in targets}
    state = State()
    report = Report(dry_run=False)
    posters: dict[str, object] = {}
    try:
        for target_id, rec in list(state.live.items()):
            if only and target_id not in only:
                continue
            t = by_id.get(target_id) or Target(id=target_id, platform=rec["ref"].get("platform", ""), chat="")
            try:
                if t.platform not in posters:
                    posters[t.platform] = poster_factory(t.platform)
                posters[t.platform].delete(t, rec["ref"])
                state.record(target_id, "ok", ref=rec["ref"], action="delete")
                report.ok.append((t, "удалено"))
            except (PosterError, ValueError) as e:
                state.record(target_id, "error", ref=rec["ref"], error=str(e), action="delete")
                report.failed.append((t, str(e)))
            state.save()
    finally:
        for p in posters.values():
            p.close()
    return report


def notify_owner(report: Report) -> None:
    token, chat = os.environ.get("TG_BOT_TOKEN"), os.environ.get("TG_OWNER_CHAT_ID")
    if not (token and chat):
        return
    from .posters.telegram_bot import TelegramBotPoster
    try:
        TelegramBotPoster(token).notify(chat, report.text())
    except PosterError as e:
        print(f"Не удалось отправить отчёт в Telegram: {e}")


def write_summary(report: Report) -> None:
    (ROOT / "state").mkdir(exist_ok=True)
    (ROOT / "state" / "last_run.txt").write_text(report.text(), encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("```\n" + report.text() + "\n```\n")
