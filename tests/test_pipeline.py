"""End-to-end pipeline behaviour with mocked source, API and SMTP."""

import copy
import datetime as dt
import json
import logging
from unittest.mock import MagicMock, patch

import pipeline
from tests.conftest import make_item
from util import local_now, now_utc

log = logging.getLogger("test")
SECRETS = {"email_address": "me@x.com", "email_app_password": "pw"}


class FakeSMTP:
    sent: list = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, *a):
        pass

    def send_message(self, msg):
        FakeSMTP.sent.append(msg)


def _scoring_client():
    def create(**kwargs):
        body = kwargs["messages"][0]["content"]
        ids = [e["external_id"] for e in json.loads(body[body.find("[") : body.rfind("]") + 1])]
        resp = MagicMock()
        resp.usage.input_tokens, resp.usage.output_tokens = 500, 100
        block = MagicMock()
        block.type = "text"
        block.text = json.dumps([{"external_id": i, "score": 70, "why": "w"} for i in ids])
        resp.content = [block]
        return resp

    client = MagicMock()
    client.messages.create.side_effect = create
    return client


def test_morning_then_evening_delta(cfg, profile, store):
    FakeSMTP.sent = []
    cfg = copy.deepcopy(cfg)

    def fake_fetch(since, scfg):
        return [make_item(f"arxiv:e2e{i}", title=f"Agentic LLM paper {i}") for i in range(3)]

    with patch.dict(pipeline.SOURCE_FETCHERS, {"arxiv": fake_fetch}), \
         patch("anthropic.Anthropic", return_value=_scoring_client()), \
         patch("smtplib.SMTP", FakeSMTP):
        assert pipeline.run_brief("morning", cfg, profile, SECRETS, store, log) == 0
        assert len(FakeSMTP.sent) == 1 and "Scout AM" in FakeSMTP.sent[0]["Subject"]
        # idempotency: no second morning today
        assert pipeline.run_brief("morning", cfg, profile, SECRETS, store, log) == 0
        assert len(FakeSMTP.sent) == 1
        # evening sees nothing new -> quiet one-liner, and no attachments of any kind
        assert pipeline.run_brief("evening", cfg, profile, SECRETS, store, log) == 0
        assert "quiet since this morning" in FakeSMTP.sent[1]["Subject"]
        names = [p.get_filename() for p in FakeSMTP.sent[1].walk() if p.get_filename()]
        assert names == []


def test_failed_send_keeps_items_unseen(cfg, profile, store):
    FakeSMTP.sent = []
    cfg = copy.deepcopy(cfg)

    def fake_fetch(since, scfg):
        return [make_item("arxiv:keep1", title="Agentic LLM paper")]

    class BrokenSMTP(FakeSMTP):
        def send_message(self, msg):
            raise ConnectionError("smtp down")

    with patch.dict(pipeline.SOURCE_FETCHERS, {"arxiv": fake_fetch}), \
         patch("anthropic.Anthropic", return_value=_scoring_client()), \
         patch("smtplib.SMTP", BrokenSMTP), \
         patch("mailer.RETRY_BACKOFF_SECONDS", 0):
        assert pipeline.run_brief("morning", cfg, profile, SECRETS, store, log) == 1
    # item not marked seen -> comes back next run; watermark not advanced
    assert len(store.filter_unseen([make_item("arxiv:keep1")])) == 1
    assert store.last_fetch_time() is None


def test_morning_reminder_flow(cfg, profile, store):
    FakeSMTP.sent = []
    cfg = copy.deepcopy(cfg)
    today = local_now(cfg["timezone"]).date()
    cfg["sources"] = {
        "opportunities": {
            "enabled": True, "feeds": [], "greenhouse_boards": [],
            "manual": [{"title": "Some Hackathon", "url": "https://hack.example",
                        "deadline": (today + dt.timedelta(days=7)).isoformat()}],
        }
    }
    dead = MagicMock()
    dead.messages.create.side_effect = RuntimeError("no api")
    with patch("anthropic.Anthropic", return_value=dead), patch("smtplib.SMTP", FakeSMTP):
        assert pipeline.run_brief("morning", cfg, profile, SECRETS, store, log) == 0
    body = FakeSMTP.sent[0].get_body(("plain",)).get_content()
    assert "DEADLINES" in body and "7 days left" in body


def test_weekly_synthesis_and_fallback(cfg, profile, store):
    FakeSMTP.sent = []
    cfg = copy.deepcopy(cfg)
    items = [make_item(f"w{i}", score=60 + i, why=f"why {i}") for i in range(3)]
    store.mark_seen(items)
    for i in items:
        store.save_score(i.external_id, i.score, i.section, i.why)
    rid = store.start_run("morning")
    store.finish_run(rid, "ok")
    store.record_brief_items(rid, items)

    synth = {"week_read": "Edge heating up.", "threads": ["t"], "momentum": [],
             "top_items": [], "deadline_note": ""}
    resp = MagicMock()
    resp.usage.input_tokens, resp.usage.output_tokens = 900, 250
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(synth)
    resp.content = [block]
    good = MagicMock()
    good.messages.create.return_value = resp

    with patch("anthropic.Anthropic", return_value=good), patch("smtplib.SMTP", FakeSMTP):
        assert pipeline.run_weekly(cfg, profile, SECRETS, store, log) == 0
    assert "the pattern" in FakeSMTP.sent[0]["Subject"]
    assert "Edge heating up." in FakeSMTP.sent[0].get_body(("plain",)).get_content()
    assert good.messages.create.call_args.kwargs["model"] == cfg["ranking"]["weekly_model"]
    # once per week
    with patch("anthropic.Anthropic", return_value=good), patch("smtplib.SMTP", FakeSMTP):
        assert pipeline.run_weekly(cfg, profile, SECRETS, store, log) == 0
    assert len(FakeSMTP.sent) == 1
