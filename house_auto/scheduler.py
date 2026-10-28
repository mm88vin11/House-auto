"""Решает, каким площадкам пора публиковать, чтобы не спамить и не ловить баны."""

from __future__ import annotations

from datetime import datetime, timedelta

from .config import WEEKDAYS, Target
from .state import State

# Небольшой запас: запуск по расписанию «раз в 3 дня» не должен срываться
# из-за того, что прошлый запуск случился на пару минут позже.
SLACK = timedelta(hours=2)


def due_reason(t: Target, state: State, at: datetime) -> str | None:
    """None — публиковать пора; иначе — почему нет."""
    if not t.enabled:
        return "выключено"
    if t.platform == "manual":
        return "ручная площадка"
    if t.days and WEEKDAYS[at.weekday()] not in t.days:
        return "сегодня не разрешённый день (" + ", ".join(t.days) + ")"
    last = state.last_success(t.id)
    if last and at - last < timedelta(days=t.min_interval_days) - SLACK:
        nxt = last + timedelta(days=t.min_interval_days)
        return f"рано, следующий раз после {nxt:%d.%m %H:%M} UTC"
    return None


def plan(targets: list[Target], state: State, at: datetime, limit: int,
         only: set[str] | None = None, force: bool = False) -> tuple[list[Target], list[tuple[Target, str]]]:
    """Возвращает (к публикации, пропущенные с причиной)."""
    due, skipped = [], []
    for t in targets:
        if only and t.id not in only:
            continue
        reason = None if (force and t.enabled and t.platform != "manual") else due_reason(t, state, at)
        if reason:
            skipped.append((t, reason))
        else:
            due.append(t)
    # Дольше всех ждавшие — первыми; остальные уйдут в следующий запуск.
    due.sort(key=lambda t: state.last_success(t.id) or datetime.min.replace(tzinfo=at.tzinfo))
    for t in due[limit:]:
        skipped.append((t, f"лимит {limit} публикаций за запуск — уйдёт в следующий раз"))
    return due[:limit], skipped
