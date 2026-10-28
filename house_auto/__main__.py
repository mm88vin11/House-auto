"""Команды:

  python -m house_auto texts               показать все варианты текста
  python -m house_auto site                собрать сайт дома (_site/) и пульт (out/kit.html)
  python -m house_auto publish --dry-run   пробный запуск: что и куда уйдёт, без отправки
  python -m house_auto publish             ОДНА КНОПКА: опубликовать везде, где пора
  python -m house_auto publish --force     опубликовать сейчас, не дожидаясь интервалов
  python -m house_auto status              где висят объявления и когда следующая публикация
  python -m house_auto remove              снять все объявления (дом продан)
  python -m house_auto discover            найти новые чаты и группы → candidates/
  python -m house_auto login               один раз: получить строку сессии Telegram
"""

from __future__ import annotations

import argparse
import os
import sys

from . import texts
from .config import load_house, load_targets
from .scheduler import due_reason
from .state import State, now


def cmd_texts(_):
    for name, text in texts.render_all(load_house()).items():
        print(f"\n===== {name} ({len(text)} символов) =====\n{text}")


def cmd_site(_):
    from .site import build_kit, build_site
    print("Сайт:", build_site())
    print("Пульт:", build_kit())


def cmd_publish(a):
    from .publish import notify_owner, run, write_summary
    report = run(dry_run=a.dry_run, only=set(a.only) if a.only else None, force=a.force)
    print(report.text())
    write_summary(report)
    if not a.dry_run:
        notify_owner(report)
    if report.failed and not report.ok:
        sys.exit(1)


def cmd_remove(a):
    from .publish import notify_owner, remove_all, write_summary
    report = remove_all(only=set(a.only) if a.only else None)
    print(report.text())
    write_summary(report)
    notify_owner(report)


def cmd_status(_):
    targets, _ = load_targets()
    state, at = State(), now()
    for t in targets:
        live = state.live.get(t.id)
        link = live["ref"].get("link", "") if live else ""
        reason = due_reason(t, state, at)
        print(f"{'🟢' if live else '⚪'} {t.id:28} {(t.name or '')[:30]:30} "
              f"{'пора публиковать' if reason is None else reason}  {link}")


def cmd_discover(a):
    from . import discover
    _, settings = load_targets()
    keywords = a.keywords or settings.get("discover_keywords") or discover.DEFAULT_KEYWORDS
    for name, fn in (("telegram", discover.telegram), ("vk", discover.vk)):
        if a.platform not in ("all", name):
            continue
        try:
            print(fn(keywords))
        except (SystemExit, Exception) as e:   # одна платформа не настроена — другая всё равно ищется
            print(f"{name}: поиск не выполнен — {e}")


def cmd_login(_):
    from telethon.sessions import StringSession
    from telethon.sync import TelegramClient

    api_id = os.environ.get("TG_API_ID") or input("api_id (с my.telegram.org): ").strip()
    api_hash = os.environ.get("TG_API_HASH") or input("api_hash: ").strip()
    with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        me = client.get_me()
        print(f"\nВход выполнен: {me.first_name} (@{me.username or '—'})")
        print("\nСкопируйте строку ниже целиком в секрет TG_SESSION (никому её не показывайте!):\n")
        print(client.session.save())


def main(argv=None):
    p = argparse.ArgumentParser(prog="house_auto", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("texts").set_defaults(fn=cmd_texts)
    sub.add_parser("site").set_defaults(fn=cmd_site)
    sp = sub.add_parser("publish")
    sp.add_argument("--dry-run", action="store_true", help="ничего не отправлять, только показать план")
    sp.add_argument("--force", action="store_true", help="игнорировать интервалы и дни недели")
    sp.add_argument("--only", nargs="*", help="только эти id из targets.yaml")
    sp.set_defaults(fn=cmd_publish)
    sr = sub.add_parser("remove")
    sr.add_argument("--only", nargs="*")
    sr.set_defaults(fn=cmd_remove)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    sd = sub.add_parser("discover")
    sd.add_argument("--platform", choices=["all", "telegram", "vk"], default="all")
    sd.add_argument("--keywords", nargs="*")
    sd.set_defaults(fn=cmd_discover)
    sub.add_parser("login").set_defaults(fn=cmd_login)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
