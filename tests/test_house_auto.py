import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from house_auto import publish, texts
from house_auto.config import Target, load_house, load_targets
from house_auto.posters import PosterError
from house_auto.scheduler import due_reason, plan
from house_auto.site import site_html
from house_auto.state import State

MON = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)   # понедельник


def tmp_state() -> State:
    return State(Path(tempfile.mkdtemp()) / "posts.json")


class TextsTest(unittest.TestCase):
    def setUp(self):
        self.h = load_house()

    def test_lengths_fit_platform_limits(self):
        v = texts.render_all(self.h)
        self.assertLessEqual(len(v["medium"]), texts.CAPTION_LIMIT)
        self.assertLessEqual(len(v["short"]), texts.SHORT_LIMIT)
        self.assertLessEqual(len(v["full"]), 4096)

    def test_contacts_and_facts_everywhere(self):
        for name, text in texts.render_all(self.h).items():
            self.assertIn(self.h["contact"]["phone"], text, name)
            self.assertIn("86,5 м²", text, name)
            self.assertIn("Шахтёрск", text, name)

    def test_plain_has_no_emoji_or_hashtags(self):
        plain = texts.render(self.h, "plain")
        self.assertIsNone(texts._EMOJI.search(plain))
        self.assertNotIn("#", plain)

    def test_price_and_site_link(self):
        h = {**self.h, "price": 1450000, "site_url": "https://example.github.io/house"}
        for text in texts.render_all(h).values():
            self.assertIn("1 450 000 ₽", text)
            self.assertIn("https://example.github.io/house", text)
        self.assertIn("в личных сообщениях", texts.render(self.h, "short"))


class SchedulerTest(unittest.TestCase):
    def test_interval_days_and_disabled(self):
        st = tmp_state()
        t = Target(id="a", platform="telegram", chat="@x", min_interval_days=3, days=["mon", "thu"])
        self.assertIsNone(due_reason(t, st, MON))
        self.assertIn("день", due_reason(t, st, MON + timedelta(days=1)))
        st.history.append({"target": "a", "status": "ok", "at": (MON - timedelta(days=1)).isoformat()})
        self.assertIn("рано", due_reason(t, st, MON))
        t.enabled = False
        self.assertEqual(due_reason(t, st, MON), "выключено")

    def test_limit_prefers_longest_waiting(self):
        st = tmp_state()
        ts = [Target(id=i, platform="telegram", chat="@" + i, min_interval_days=1) for i in "abc"]
        st.history.append({"target": "a", "status": "ok", "at": (MON - timedelta(days=5)).isoformat()})
        st.history.append({"target": "b", "status": "ok", "at": (MON - timedelta(days=2)).isoformat()})
        todo, skipped = plan(ts, st, MON, limit=2)
        self.assertEqual([t.id for t in todo], ["c", "a"])
        self.assertIn("лимит", skipped[0][1])

    def test_real_targets_file_is_valid(self):
        targets, settings = load_targets()
        self.assertTrue(targets)
        self.assertIn("delay_seconds", settings)


class FakePoster:
    def __init__(self, platform, fail=None):
        self.platform, self.fail = platform, fail or {}
        self.posted, self.deleted = [], []

    def post(self, t, text, photos):
        if t.id in self.fail:
            raise self.fail[t.id]
        self.posted.append((t.id, text))
        return {"message_ids": [len(self.posted)], "link": f"https://t.me/x/{len(self.posted)}"}

    def delete(self, t, ref):
        self.deleted.append((t.id, ref["message_ids"]))

    def close(self):
        pass


class PublishTest(unittest.TestCase):
    def run_with(self, targets, posters, state):
        with mock.patch.object(publish, "load_targets", return_value=(targets, {"delay_seconds": [0, 0]})):
            return publish.run(state=state, poster_factory=lambda p: posters[p], sleep=lambda s: None)

    def test_posts_then_replaces_previous_post(self):
        st, tg = tmp_state(), FakePoster("telegram")
        ts = [Target(id="a", platform="telegram", chat="@a", min_interval_days=0)]
        r1 = self.run_with(ts, {"telegram": tg}, st)
        self.assertEqual(len(r1.ok), 1)
        self.run_with(ts, {"telegram": tg}, st)
        self.assertEqual(tg.deleted, [("a", [1])])
        self.assertEqual(st.live["a"]["ref"]["message_ids"], [2])
        self.assertTrue(st.path.exists())

    def test_flood_stops_platform_but_not_others(self):
        st = tmp_state()
        tg = FakePoster("telegram", fail={"a": PosterError("flood", stop_platform=True)})
        vk = FakePoster("vk")
        ts = [Target(id="a", platform="telegram", chat="@a"), Target(id="b", platform="telegram", chat="@b"),
              Target(id="c", platform="vk", chat="-1")]
        r = self.run_with(ts, {"telegram": tg, "vk": vk}, st)
        self.assertEqual([t.id for t, _ in r.failed], ["a"])
        self.assertEqual([t.id for t, _ in r.ok], ["c"])
        self.assertIn("остановлена", dict((t.id, w) for t, w in r.skipped)["b"])

    def test_dry_run_sends_nothing(self):
        st = tmp_state()
        ts = [Target(id="a", platform="telegram", chat="@a")]
        with mock.patch.object(publish, "load_targets", return_value=(ts, {})):
            r = publish.run(dry_run=True, state=st, poster_factory=lambda p: self.fail("poster created"))
        self.assertEqual(len(r.ok), 1)
        self.assertFalse(st.path.exists())


class SiteTest(unittest.TestCase):
    def test_site_renders_with_and_without_photos(self):
        h = load_house()
        html = site_html(h, [])
        self.assertIn("tel:+79995857940", html)
        self.assertIn("Фотографии скоро появятся", html)
        html = site_html({**h, "site_url": "https://x.github.io/h/"}, ["01.jpg", "plan.jpg"])
        self.assertIn('og:image" content="https://x.github.io/h/photos/01.jpg"', html)
        self.assertIn("photos/plan.jpg", html)


if __name__ == "__main__":
    unittest.main()
