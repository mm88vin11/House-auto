"""Приложение «Продажа дома»: окно в браузере с кнопками, всё хранится на вашем компьютере.

Запуск: двойной клик по HouseAuto (собранная программа) или `python run_app.py`.
Данные лежат в папке HouseAuto-data рядом с программой: house.yaml, targets.yaml, photos/,
settings.json (ключи доступа — только на этом компьютере), state/ (журнал публикаций).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import threading
import time
import traceback
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

SECRET_KEYS = ["TG_API_ID", "TG_API_HASH", "TG_SESSION", "VK_TOKEN", "TG_BOT_TOKEN", "TG_OWNER_CHAT_ID"]
AUTOPILOT_EVERY = 2 * 3600          # как часто автопилот проверяет, кому пора публиковать
AUTOPILOT_HOURS = range(9, 21)      # только днём — ночные посты раздражают и хуже читаются


def prepare_home() -> Path:
    """Папка данных. У собранной программы — HouseAuto-data рядом с ней (заполняется при первом запуске)."""
    if getattr(sys, "frozen", False):
        home = Path(sys.executable).resolve().parent / "HouseAuto-data"
        bundle = Path(sys._MEIPASS) / "defaults"
        home.mkdir(exist_ok=True)
        for name in ("house.yaml", "targets.yaml", "photos"):
            src, dst = bundle / name, home / name
            if src.exists() and not dst.exists():
                shutil.copytree(src, dst) if src.is_dir() else shutil.copy2(src, dst)
    else:
        home = Path(__file__).resolve().parent.parent
    os.environ["HOUSE_AUTO_HOME"] = str(home)
    return home


class Settings:
    def __init__(self, home: Path):
        self.path = home / "settings.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}
        self.apply()

    def update(self, **kv) -> None:
        for k, v in kv.items():
            if v is None:
                self.data.pop(k, None)
                os.environ.pop(k, None)
            else:
                self.data[k] = v
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        self.apply()

    def apply(self) -> None:
        for k in SECRET_KEYS:
            if self.data.get(k):
                os.environ[k] = str(self.data[k])


class Worker:
    """Один фоновый поток на всё (Telegram-клиенту нужен один и тот же цикл событий)."""

    def __init__(self):
        self.pool = ThreadPoolExecutor(1, initializer=lambda: asyncio.set_event_loop(asyncio.new_event_loop()))
        self.job: dict | None = None
        self.lock = threading.Lock()

    def busy(self) -> bool:
        return bool(self.job and not self.job["done"])

    def start(self, title: str, fn) -> bool:
        with self.lock:
            if self.busy():
                return False
            job = self.job = {"title": title, "lines": [], "done": False}

        def log(line: str) -> None:
            for part in str(line).splitlines() or [""]:
                job["lines"].append(f"{datetime.now():%H:%M:%S}  {part}")

        def runner():
            try:
                fn(log)
            except Exception as e:   # показываем любую ошибку в окне, а не роняем приложение
                log(f"❌ Ошибка: {e}")
                traceback.print_exc()
            finally:
                log("— готово —")
                job["done"] = True

        self.pool.submit(runner)
        return True

    def call(self, fn, timeout: float = 120):
        return self.pool.submit(fn).result(timeout)


class TgLogin:
    client = None
    phone = ""
    code_hash = ""


def tg_send_code(api_id: str, api_hash: str, phone: str) -> None:
    from telethon.sessions import StringSession
    from telethon.sync import TelegramClient

    if TgLogin.client:
        TgLogin.client.disconnect()
    client = TelegramClient(StringSession(), int(api_id), api_hash,
                            timeout=15, connection_retries=2, request_retries=2)
    client.connect()
    sent = client.send_code_request(phone)
    TgLogin.client, TgLogin.phone, TgLogin.code_hash = client, phone, sent.phone_code_hash


def tg_sign_in(code: str = "", password: str = "") -> dict:
    from telethon.errors import SessionPasswordNeededError

    client = TgLogin.client
    if not client:
        raise ValueError("сначала запросите код")
    try:
        if password:
            client.sign_in(password=password)
        else:
            client.sign_in(TgLogin.phone, code, phone_code_hash=TgLogin.code_hash)
    except SessionPasswordNeededError:
        return {"need_password": True}
    me = client.get_me()
    session = client.session.save()
    client.disconnect()
    TgLogin.client = None
    return {"session": session, "me": f"{me.first_name or ''} @{me.username or ''}".strip()}


def toggle_target(path: Path, target_id: str, enabled: bool) -> None:
    """Меняет enabled у площадки в targets.yaml, не трогая комментарии и порядок."""
    lines = path.read_text(encoding="utf-8").splitlines()
    start = next((i for i, l in enumerate(lines) if re.fullmatch(rf"\s*- id:\s*{re.escape(target_id)}\s*", l)), None)
    if start is None:
        raise ValueError(f"нет площадки {target_id}")
    indent = re.match(r"(\s*)-", lines[start]).group(1) + "  "
    end = start + 1
    while end < len(lines) and (lines[end].startswith(indent) or not lines[end].strip()) \
            and not re.match(r"\s*- id:", lines[end]):
        end += 1
    value = f"{indent}enabled: {'true' if enabled else 'false'}"
    for i in range(start + 1, end):
        if re.match(rf"{indent}enabled:", lines[i]):
            lines[i] = value
            break
    else:
        lines.insert(start + 1, value)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_price(path: Path, price: int | None) -> None:
    text = path.read_text(encoding="utf-8")
    new = re.sub(r"(?m)^price:.*$", f"price: {price if price else 'null'}", text, count=1)
    path.write_text(new, encoding="utf-8")


class App:
    def __init__(self, home: Path):
        self.home = home
        self.settings = Settings(home)
        self.worker = Worker()
        self.last_autopilot = 0.0

    # ───── состояние для окна ─────
    def state(self) -> dict:
        from .config import load_house, load_targets
        from .scheduler import due_reason
        from .state import State, now

        s = self.settings.data
        out = {
            "tg": {"ok": bool(s.get("TG_SESSION")), "me": s.get("TG_ME", ""),
                   "api_id": s.get("TG_API_ID", ""), "has_hash": bool(s.get("TG_API_HASH"))},
            "vk": {"ok": bool(s.get("VK_TOKEN")), "me": s.get("VK_ME", "")},
            "bot": {"ok": bool(s.get("TG_BOT_TOKEN") and s.get("TG_OWNER_CHAT_ID"))},
            "autopilot": bool(s.get("autopilot")),
            "job": self.worker.job, "busy": self.worker.busy(), "targets": [], "error": "",
        }
        try:
            house = load_house()
            targets, _ = load_targets()
            st, at = State(), now()
            out["price"] = house.get("price")
            for t in targets:
                live = st.live.get(t.id)
                last = st.last_success(t.id)
                out["targets"].append({
                    "id": t.id, "name": t.name or t.id, "platform": t.platform, "enabled": t.enabled,
                    "url": t.url, "link": (live or {}).get("ref", {}).get("link", ""),
                    "last": f"{last.astimezone():%d.%m %H:%M}" if last else "",
                    "reason": due_reason(t, st, at) or "пора публиковать"})
        except Exception as e:
            out["error"] = f"Ошибка в house.yaml / targets.yaml: {e}"
        return out

    # ───── действия ─────
    def run(self, mode: str) -> bool:
        from . import discover, publish

        def job(log):
            if mode == "remove":
                rep = publish.remove_all()
            elif mode == "discover":
                from .config import load_targets
                kws = load_targets()[1].get("discover_keywords") or discover.DEFAULT_KEYWORDS
                for fn in (discover.telegram, discover.vk):
                    try:
                        log(fn(kws))
                    except (SystemExit, Exception) as e:
                        log(f"пропуск: {e}")
                log(f"Списки — в папке {self.home / 'candidates'}. Включайте подходящие в targets.yaml.")
                return
            else:
                rep = publish.run(dry_run=mode == "dry", force=mode == "force", progress=log)
            log("")
            log(rep.text())
            publish.write_summary(rep)
            if mode != "dry":
                publish.notify_owner(rep)

        titles = {"dry": "Пробный запуск", "publish": "Публикация (где пора)", "force": "Публикация везде",
                  "remove": "Снятие объявлений", "discover": "Поиск чатов и групп"}
        return self.worker.start(titles[mode], job)

    def autopilot_loop(self) -> None:
        while True:
            time.sleep(60)
            if (self.settings.data.get("autopilot") and datetime.now().hour in AUTOPILOT_HOURS
                    and time.time() - self.last_autopilot > AUTOPILOT_EVERY and not self.worker.busy()):
                self.last_autopilot = time.time()
                self.run("publish")

    def handle_post(self, path: str, body: dict) -> dict:
        s = self.settings
        if path == "/api/run":
            if not self.run(body["mode"]):
                return {"error": "Уже выполняется другая задача — дождитесь окончания"}
            return {"ok": True}
        if path == "/api/autopilot":
            s.update(autopilot=bool(body.get("on")))
            self.last_autopilot = 0
            return {"ok": True}
        if path == "/api/tg/code":
            api_id, api_hash = body.get("api_id", "").strip(), body.get("api_hash", "").strip()
            api_id = api_id or s.data.get("TG_API_ID", "")
            api_hash = api_hash or s.data.get("TG_API_HASH", "")
            if not re.fullmatch(r"\d{3,12}", api_id) or not re.fullmatch(r"[0-9a-f]{32}", api_hash):
                return {"error": "api_id — это число, api_hash — 32 символа из 0-9 и a-f. Возьмите их на my.telegram.org"}
            phone = re.sub(r"[^\d+]", "", body.get("phone", ""))
            if self.worker.busy():
                return {"error": "Идёт публикация — дождитесь окончания"}
            self.worker.call(lambda: tg_send_code(api_id, api_hash, phone))
            s.update(TG_API_ID=api_id, TG_API_HASH=api_hash)
            return {"ok": True}
        if path == "/api/tg/signin":
            res = self.worker.call(lambda: tg_sign_in(body.get("code", "").strip(), body.get("password", "")))
            if res.get("need_password"):
                return {"need_password": True}
            s.update(TG_SESSION=res["session"], TG_ME=res["me"])
            return {"ok": True}
        if path == "/api/tg/logout":
            s.update(TG_SESSION=None, TG_ME=None)
            return {"ok": True}
        if path == "/api/vk":
            raw = body.get("token", "").strip()
            m = re.search(r"access_token=([^&\s]+)", raw)
            token = m.group(1) if m else raw
            from .posters.vk import VkPoster
            me = VkPoster(token).call("users.get")[0]
            s.update(VK_TOKEN=token, VK_ME=f"{me['first_name']} {me['last_name']}")
            return {"ok": True}
        if path == "/api/bot":
            token, owner = body.get("token", "").strip(), body.get("owner", "").strip()
            from .posters.telegram_bot import TelegramBotPoster
            TelegramBotPoster(token).notify(owner, "✅ Отчёты о публикации дома будут приходить сюда.")
            s.update(TG_BOT_TOKEN=token, TG_OWNER_CHAT_ID=owner)
            return {"ok": True}
        if path == "/api/target":
            toggle_target(self.home / "targets.yaml", body["id"], bool(body["enabled"]))
            return {"ok": True}
        if path == "/api/price":
            digits = re.sub(r"\D", "", str(body.get("price", "")))
            set_price(self.home / "house.yaml", int(digits) if digits else None)
            return {"ok": True}
        if path == "/api/open":
            folder = self.home if body.get("what") == "data" else self.home / "photos"
            _open_folder(folder)
            return {"ok": True}
        return {"error": "неизвестная команда"}


def _open_folder(path: Path) -> None:
    path.mkdir(exist_ok=True)
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606 — открыть папку в Проводнике
    elif sys.platform == "darwin":
        os.system(f'open "{path}"')
    else:
        os.system(f'xdg-open "{path}" >/dev/null 2>&1 &')


def make_handler(app: App, port: int):
    from .site import build_kit, build_site
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: dict, code: int = 200) -> None:
            self._send(code, json.dumps(data, ensure_ascii=False, default=str).encode(), "application/json")

        def _file(self, path: Path) -> None:
            types = {".html": "text/html; charset=utf-8", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                     ".png": "image/png", ".webp": "image/webp"}
            if not path.is_file():
                return self._send(404, b"not found", "text/plain")
            self._send(200, path.read_bytes(), types.get(path.suffix.lower(), "application/octet-stream"))

        def do_GET(self):
            if self.headers.get("Host") not in allowed_hosts:
                return self._send(403, b"forbidden", "text/plain")
            p = unquote(urlparse(self.path).path)
            if p == "/":
                return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            if p == "/api/state":
                return self._json(app.state())
            if p == "/kit":
                return self._file(build_kit())
            if p == "/site/":
                return self._file(build_site())
            if p.startswith("/site/photos/"):
                return self._file(app.home / "_site" / "photos" / Path(p).name)
            self._send(404, b"not found", "text/plain")

        def do_POST(self):
            # Защита: принимаем команды только со своей же страницы.
            origin = self.headers.get("Origin", "")
            if self.headers.get("Host") not in allowed_hosts or (origin and urlparse(origin).netloc not in allowed_hosts):
                return self._send(403, b"forbidden", "text/plain")
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                self._json(app.handle_post(self.path, body))
            except Exception as e:
                self._json({"error": _human_error(e)})

    return Handler


def _human_error(e: Exception) -> str:
    name = type(e).__name__
    hints = {
        "PhoneNumberInvalidError": "неверный номер телефона — в формате +7XXXXXXXXXX",
        "PhoneCodeInvalidError": "неверный код — проверьте и введите ещё раз",
        "PhoneCodeExpiredError": "код устарел — запросите новый",
        "ApiIdInvalidError": "неверные api_id / api_hash — перепроверьте на my.telegram.org",
        "PasswordHashInvalidError": "неверный пароль двухэтапной проверки",
        "FloodWaitError": "Telegram просит подождать перед новой попыткой",
    }
    if name == "TimeoutError":
        return "нет ответа от Telegram — проверьте интернет и перезапустите приложение"
    return hints.get(name) or f"{e}"


def main() -> None:
    home = prepare_home()
    app = App(home)
    threading.Thread(target=app.autopilot_loop, daemon=True).start()
    server = None
    for port in range(8765, 8785):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port))
            break
        except OSError:
            continue
    if not server:
        raise SystemExit("Не удалось занять порт 8765–8784")
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Продажа дома — приложение запущено: {url}\nДанные: {home}\nНе закрывайте это окно, пока работает автопилот.")
    if not os.environ.get("HOUSE_AUTO_NO_BROWSER"):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


PAGE = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Продажа дома</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>🏡</text></svg>">
<style>
:root{--bg:#f7f3ec;--card:#fffdf9;--ink:#2b2620;--muted:#6f655a;--accent:#2f6b3a;--accent-ink:#fff;--line:#e6dccd;--bad:#b3261e;--warn:#b5651d}
@media (prefers-color-scheme:dark){:root{--bg:#1b1916;--card:#25221e;--ink:#efe8de;--muted:#b3a899;--accent:#6fbf7d;--accent-ink:#10200f;--line:#3a352e;--bad:#ff8a80;--warn:#e0a060}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:20px 16px 60px}h1{font-size:28px;margin:4px 0}h2{font-size:20px;margin:28px 0 12px}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px}
.ok{color:var(--accent);font-weight:600}.no{color:var(--warn);font-weight:600}
button,.btn{font:inherit;border:0;border-radius:10px;padding:10px 16px;background:var(--accent);color:var(--accent-ink);cursor:pointer;font-weight:600;text-decoration:none;display:inline-block}
button.sec,.btn.sec{background:transparent;color:var(--ink);border:1px solid var(--line)}button.danger{background:var(--bad);color:#fff}
button:disabled{opacity:.5;cursor:default}
input{font:inherit;padding:9px 12px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--ink);width:100%;margin:4px 0 8px}
.actions{display:flex;flex-wrap:wrap;gap:10px}.big{font-size:18px;padding:14px 22px}
#log{background:#14120f;color:#e9e3d8;border-radius:12px;padding:14px;font:13px/1.5 ui-monospace,Menlo,Consolas,monospace;white-space:pre-wrap;max-height:420px;overflow:auto;min-height:80px}
table{width:100%;border-collapse:collapse}td,th{padding:8px 6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:14px}
th{color:var(--muted);font-weight:500}.tag{font-size:12px;border:1px solid var(--line);border-radius:99px;padding:1px 8px;white-space:nowrap}
.switch{display:inline-flex;align-items:center;gap:8px;cursor:pointer}.switch input{width:20px;height:20px;margin:0}
.hide{display:none}.err{color:var(--bad)}.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
details summary{cursor:pointer;color:var(--muted)}ol{padding-left:20px;margin:6px 0}
.tablewrap{overflow-x:auto}
</style></head><body><div class="wrap">
<div class="row" style="justify-content:space-between"><div><h1>🏡 Продажа дома</h1>
<div class="muted">Шахтёрск, ул. Капустина — публикация во все подключённые площадки</div></div>
<label class="switch card" style="padding:10px 14px"><input type="checkbox" id="auto" onchange="autopilot(this.checked)">
<span><b>Автопилот</b><br><span class="muted" style="font-size:13px">сам публикует, где пора, с 9 до 21</span></span></label></div>
<div id="err" class="err"></div>

<h2>1. Подключения</h2>
<div class="grid">
<div class="card"><b>Telegram</b> — <span id="tgst"></span>
 <div id="tgform">
  <details id="tghelp"><summary>Где взять api_id и api_hash (2 минуты)</summary><ol>
   <li>Откройте <a href="https://my.telegram.org" target="_blank">my.telegram.org</a>, войдите по своему номеру.</li>
   <li>«API development tools» → заполните название (любое, например HouseAuto) → Create.</li>
   <li>Скопируйте <b>App api_id</b> и <b>App api_hash</b> сюда.</li></ol></details>
  <input id="api_id" placeholder="api_id (число)"><input id="api_hash" placeholder="api_hash (32 символа)">
  <input id="phone" placeholder="Номер телефона, +7...">
  <button onclick="tgCode()">Получить код</button>
  <div id="codebox" class="hide"><input id="code" placeholder="Код из Telegram"><button onclick="tgSign()">Войти</button></div>
  <div id="pwbox" class="hide"><input id="pw" type="password" placeholder="Пароль двухэтапной проверки"><button onclick="tgSign(true)">Войти</button></div>
 </div>
 <div id="tgout" class="hide" style="margin-top:8px"><button class="sec" onclick="post('/api/tg/logout',{}).then(load)">Выйти</button></div>
</div>
<div class="card"><b>ВКонтакте</b> — <span id="vkst"></span>
 <details><summary>Как получить ключ</summary><ol>
  <li><a href="https://dev.vk.com/ru/admin/apps-list" target="_blank">dev.vk.com</a> → создать приложение → скопировать его ID.</li>
  <li>Подставить ID в ссылку и открыть:<br><input id="vkapp" placeholder="ID приложения" oninput="vkLink()"><a id="vklink" class="btn sec" target="_blank">Открыть вход ВК</a></li>
  <li>Разрешить доступ и вставить сюда адрес страницы, куда вас перекинуло.</li></ol></details>
 <input id="vktoken" placeholder="Адрес с access_token=... или сам ключ"><button onclick="saveVk()">Сохранить</button>
</div>
<div class="card"><b>Отчёты в Telegram</b> — <span id="botst"></span>
 <details><summary>Как настроить (по желанию)</summary><ol>
  <li><a href="https://t.me/BotFather" target="_blank">@BotFather</a> → /newbot → скопируйте токен.</li>
  <li>Напишите своему боту /start.</li>
  <li>Свой id узнайте у <a href="https://t.me/userinfobot" target="_blank">@userinfobot</a>.</li></ol></details>
 <input id="bottoken" placeholder="Токен бота"><input id="botowner" placeholder="Ваш id (число)">
 <button onclick="saveBot()">Проверить и сохранить</button>
</div>
</div>

<h2>2. Публикация</h2>
<div class="card">
<div class="actions">
 <button class="big" onclick="run('force')">🚀 Опубликовать везде сейчас</button>
 <button class="sec" onclick="run('publish')">▶️ Только где пора</button>
 <button class="sec" onclick="run('dry')">🧪 Пробный запуск</button>
 <button class="sec" onclick="run('discover')">🔎 Найти новые чаты</button>
 <button class="danger" onclick="if(confirm('Удалить все опубликованные объявления?'))run('remove')">🧹 Дом продан — снять всё</button>
</div>
<p class="muted" id="jobtitle" style="margin:14px 0 6px"></p><div id="log">Здесь будет ход публикации.</div>
</div>

<h2>3. Дом</h2>
<div class="card row">
 <span>Цена, ₽:</span><input id="price" style="width:180px" placeholder="не указана"><button class="sec" onclick="savePrice()">Сохранить</button>
 <a class="btn sec" href="/site/" target="_blank">🌐 Сайт дома</a>
 <a class="btn sec" href="/kit" target="_blank">📋 Тексты и ручные площадки</a>
 <button class="sec" onclick="post('/api/open',{what:'photos'})">📁 Фото</button>
 <button class="sec" onclick="post('/api/open',{what:'data'})">📁 Все данные</button>
</div>

<h2>4. Площадки</h2>
<div class="card tablewrap"><table><thead><tr><th>Вкл</th><th>Площадка</th><th>Тип</th><th>Последний пост</th><th>Статус</th></tr></thead><tbody id="tb"></tbody></table></div>
</div>
<script>
const $=id=>document.getElementById(id);let busy=false,timer=null;
async function post(u,b){const r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});const j=await r.json();
 if(j.error){alert(j.error)}return j}
const P={telegram:'Telegram',telegram_bot:'Мой канал',vk:'ВКонтакте',manual:'Вручную'};
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function load(){let s;try{s=await (await fetch('/api/state')).json()}catch(e){$('err').textContent='Приложение закрыто — запустите его снова.';return}
 $('err').textContent=s.error||'';
 $('tgst').innerHTML=s.tg.ok?`<span class="ok">подключён ${esc(s.tg.me)}</span>`:'<span class="no">не подключён</span>';
 $('tgform').classList.toggle('hide',s.tg.ok);$('tgout').classList.toggle('hide',!s.tg.ok);
 if(s.tg.api_id&&!$('api_id').value)$('api_id').value=s.tg.api_id;if(s.tg.has_hash)$('api_hash').placeholder='api_hash сохранён';
 $('vkst').innerHTML=s.vk.ok?`<span class="ok">подключён ${esc(s.vk.me)}</span>`:'<span class="no">не подключён</span>';
 $('botst').innerHTML=s.bot.ok?'<span class="ok">включены</span>':'<span class="muted">выключены</span>';
 $('auto').checked=s.autopilot;if(document.activeElement!==$('price'))$('price').value=s.price||'';
 busy=s.busy;document.querySelectorAll('.actions button').forEach(b=>b.disabled=busy);
 if(s.job){$('jobtitle').textContent=(busy?'⏳ Выполняется: ':'Последняя задача: ')+s.job.title;
  const lg=$('log'),atEnd=lg.scrollTop+lg.clientHeight>=lg.scrollHeight-20;lg.textContent=s.job.lines.join('\n');if(atEnd)lg.scrollTop=lg.scrollHeight}
 $('tb').innerHTML=s.targets.map(t=>`<tr><td><input type="checkbox" ${t.enabled?'checked':''} onchange="post('/api/target',{id:'${esc(t.id)}',enabled:this.checked}).then(load)"></td>
 <td>${t.url?`<a href="${esc(t.url)}" target="_blank">${esc(t.name)}</a>`:esc(t.name)}</td><td><span class="tag">${P[t.platform]||t.platform}</span></td>
 <td>${t.link&&t.link.startsWith('http')?`<a href="${esc(t.link)}" target="_blank">${esc(t.last)}</a>`:esc(t.last||'—')}</td><td class="muted">${esc(t.reason)}</td></tr>`).join('');
 clearTimeout(timer);timer=setTimeout(load,busy?1500:8000)}
async function run(m){const j=await post('/api/run',{mode:m});load()}
async function autopilot(on){await post('/api/autopilot',{on});load()}
async function tgCode(){const j=await post('/api/tg/code',{api_id:$('api_id').value,api_hash:$('api_hash').value,phone:$('phone').value});
 if(j.ok){$('codebox').classList.remove('hide');$('code').focus()}}
async function tgSign(pw){const j=await post('/api/tg/signin',pw?{password:$('pw').value}:{code:$('code').value});
 if(j.need_password){$('pwbox').classList.remove('hide');$('pw').focus()}if(j.ok){$('codebox').classList.add('hide');$('pwbox').classList.add('hide');load()}}
function vkLink(){$('vklink').href=`https://oauth.vk.com/authorize?client_id=${encodeURIComponent($('vkapp').value)}&scope=wall,photos,groups,offline&response_type=token&redirect_uri=https://oauth.vk.com/blank.html&v=5.199`}
async function saveVk(){const j=await post('/api/vk',{token:$('vktoken').value});if(j.ok){$('vktoken').value='';load()}}
async function saveBot(){const j=await post('/api/bot',{token:$('bottoken').value,owner:$('botowner').value});if(j.ok){$('bottoken').value='';load()}}
async function savePrice(){const j=await post('/api/price',{price:$('price').value});if(j.ok){$('price').blur();load()}}
load();
</script></body></html>"""
