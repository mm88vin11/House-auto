"""Журнал публикаций: что, куда и когда отправлено. Хранится в state/posts.json."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT

STATE_FILE = ROOT / "state" / "posts.json"


def now() -> datetime:
    return datetime.now(timezone.utc)


class State:
    def __init__(self, path: Path = STATE_FILE):
        self.path = path
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        else:
            data = {}
        self.live: dict[str, dict] = data.get("live", {})      # target_id -> последний живой пост
        self.history: list[dict] = data.get("history", [])

    def last_success(self, target_id: str) -> datetime | None:
        for rec in reversed(self.history):
            if rec["target"] == target_id and rec["status"] == "ok":
                return datetime.fromisoformat(rec["at"])
        return None

    def record(self, target_id: str, status: str, *, ref: dict | None = None,
               error: str = "", action: str = "post") -> None:
        rec = {"target": target_id, "action": action, "status": status,
               "at": now().isoformat(timespec="seconds")}
        if ref:
            rec["ref"] = ref
        if error:
            rec["error"] = error[:500]
        self.history.append(rec)
        if action == "post" and status == "ok" and ref:
            self.live[target_id] = rec
        if action == "delete" and status == "ok":
            self.live.pop(target_id, None)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"live": self.live, "history": self.history[-2000:]}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
