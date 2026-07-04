"""Brief assembly: selection rules, subjects, quiet paths."""

import brief
from tests.conftest import make_item


def _ranked(cfg):
    mk = make_item
    return [
        mk("o1", "opportunity", "Defence AI hackathon", score=91, route_tag="Opportunity",
           why="Your winning lane."),
        mk("f1", "arxiv", "Edge multi-agent planner", score=88, route_tag="Founder",
           why="Maps onto Argus."),
        mk("d1", "ai_news", "Anthropic ships agent tooling", score=74, route_tag="FDE",
           why="Know this cold."),
        mk("p1", "uk_politics", "R&D tax credit expansion", score=61, route_tag="Politics", why="w"),
        mk("p2", "uk_politics", "Politics two", score=60, route_tag="Politics", why="w"),
        mk("p3", "uk_politics", "Politics three", score=59, route_tag="Politics", why="w"),
        mk("g1", "arxiv", "Low relevance paper", score=20, route_tag="General", why="meh"),
    ]


def test_select_caps_politics_and_floors_score(cfg):
    chosen = brief.select_items(_ranked(cfg), cfg, "morning")
    tags = [i.route_tag for i in chosen]
    assert tags.count("Politics") == 2
    assert all(i.score >= cfg["min_score_to_show"] for i in chosen)
    assert len(chosen) <= cfg["max_items_morning"]


def test_groups_order_opportunity_first(cfg):
    chosen = brief.select_items(_ranked(cfg), cfg, "morning")
    groups = brief.group_items(chosen, cfg)
    assert groups[0][0] == "Opportunity"


def test_morning_subject_and_sections(cfg):
    chosen = brief.select_items(_ranked(cfg), cfg, "morning")
    doc = brief.build_brief(
        "morning", chosen, cfg,
        reminders=[{"title": "DD", "url": "https://dd", "line": "7 days left"}],
        quiet_lines=["Nothing on the Startup front for 4 days now."],
        footer_lines=["Filtered 34 items you didn't need to see."],
    )
    assert "Scout AM" in doc["subject"] and "worth your time" in doc["subject"]
    for needle in ("DEADLINES", "DD", "Startup front", "Filtered 34"):
        assert needle in doc["text"]
    assert "Defence AI hackathon" in doc["html"]


def test_evening_quiet_one_liner(cfg):
    doc = brief.build_brief("evening", [], cfg)
    assert "quiet since this morning" in doc["subject"]
    assert "Nothing meaningful landed" in doc["text"]


def test_weekly_build(cfg):
    data = {
        "week_read": "Edge agents heating up.",
        "threads": ["t1"], "momentum": ["m1"],
        "top_per_route": [{"route": "Founder", "title": "Paper", "why": "w"}],
        "route_state": ["Founder: strong."], "deadline_note": "DD closes in 10 days.",
    }
    doc = brief.build_weekly(data, "29 Jun", cfg, [])
    assert doc["subject"] == "Scout — Week of 29 Jun — the pattern"
    for needle in ("heating up", "t1", "m1", "Paper", "strong", "closes in 10 days"):
        assert needle in doc["text"]
