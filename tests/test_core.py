"""util, store and prefilter behaviour."""

import datetime as dt

import prefilter
from tests.conftest import make_item
from util import clean_text, keyword_match, now_utc


def test_keyword_match_word_boundaries():
    kws = ["RL", "tool use", "on-device", "LLM"]
    assert keyword_match("Deep RL for robots", kws)
    assert keyword_match("A study of tool use in agents", kws)
    assert keyword_match("On-device inference", kws)
    assert not keyword_match("A world model approach", kws)  # 'RL' inside 'world'
    assert not keyword_match("", kws)


def test_clean_text_strips_html():
    assert clean_text("<p>Big &amp; <b>bold</b></p>\n launch") == "Big & bold launch"


def test_store_dedupe_and_watermark(store):
    item = make_item()
    assert len(store.filter_unseen([item, item])) == 1  # in-batch dupe dropped
    store.mark_seen([item])
    assert store.filter_unseen([item]) == []
    assert store.last_fetch_time() is None  # no ok run yet
    run_id = store.start_run("morning")
    store.finish_run(run_id, "ok")
    assert store.last_fetch_time() is not None
    # dry runs never advance the watermark
    before = store.last_fetch_time()
    rid2 = store.start_run("evening")
    store.finish_run(rid2, "dry-run")
    assert store.last_fetch_time() == before


def test_store_deadlines(store):
    store.upsert_deadline("d1", "Hack", "https://h", dt.date(2030, 1, 10))
    assert len(store.unexpired_deadlines(dt.date(2030, 1, 1))) == 1
    store.drop_expired_deadlines(dt.date(2030, 1, 11))
    assert store.unexpired_deadlines(dt.date(2030, 1, 1)) == []


def test_prefilter_rules(cfg):
    items = [
        make_item("a1", "arxiv", "Multi-agent LLM planning", summary=""),
        make_item("a2", "arxiv", "Topological quantum sheaves", summary=""),
        make_item("a3", "arxiv", "A world model", summary=""),  # RL must not fire inside 'world'
        make_item("p1", "uk_politics", "PM reshuffles cabinet", summary=""),
        make_item("p2", "uk_politics", "Budget boosts R&D tax credit for startups", summary=""),
        make_item("n1", "ai_news", "Some product release", summary=""),
    ]
    kept, dropped = prefilter.apply(items, cfg)
    assert sorted(i.external_id for i in kept) == ["a1", "n1", "p2"]
    assert dropped == 3


def test_prefilter_arxiv_cap(cfg):
    many = [make_item(f"a{i}", "arxiv", f"LLM paper {i}",
                      published=now_utc() - dt.timedelta(minutes=i)) for i in range(60)]
    kept, dropped = prefilter.apply(many, cfg)
    cap = cfg["sources"]["arxiv"]["daily_cap"]
    assert len(kept) == cap and dropped == 60 - cap
    # most recent survive
    assert kept[0].external_id == "a0"
