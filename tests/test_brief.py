"""Brief assembly: selection rules, subjects, quiet paths."""

import brief
from tests.conftest import make_item


def _ranked(cfg):
    mk = make_item
    return [
        mk("o1", "opportunity", "Edge AI hackathon", score=91, why="Deadline 20 Aug."),
        mk("f1", "arxiv", "Edge multi-agent planner", score=88, why="New benchmark."),
        mk("d1", "ai_news", "Lab ships agent tooling", score=74, why="Notable release."),
        mk("p1", "uk_politics", "R&D tax credit expansion", score=61, why="w"),
        mk("p2", "uk_politics", "Politics two", score=60, why="w"),
        mk("p3", "uk_politics", "Politics three", score=59, why="w"),
        mk("g1", "arxiv", "Low relevance paper", score=20, why="meh"),
    ]


def test_select_caps_politics_and_floors_score(cfg):
    chosen = brief.select_items(_ranked(cfg), cfg, "morning")
    sections = [i.section for i in chosen]
    cap = cfg["sources"]["uk_politics"]["max_items"]
    assert sections.count("Politics") == min(3, cap)  # fixture has 3 above the floor
    assert all(i.score >= cfg["min_score_to_show"] for i in chosen)
    assert len(chosen) <= cfg["max_items_morning"]


def test_groups_order_opportunities_first(cfg):
    chosen = brief.select_items(_ranked(cfg), cfg, "morning")
    groups = brief.group_items(chosen, cfg)
    assert groups[0][0] == "Opportunities"


def test_morning_subject_and_sections(cfg):
    chosen = brief.select_items(_ranked(cfg), cfg, "morning")
    doc = brief.build_brief(
        "morning", chosen, cfg,
        reminders=[{"title": "DD", "url": "https://dd", "line": "7 days left"}],
        footer_lines=["Filtered 34 items you didn't need to see."],
    )
    assert "Scout AM" in doc["subject"] and "worth your time" in doc["subject"]
    for needle in ("DEADLINES", "DD", "Filtered 34", "PAPERS", "NEWS"):
        assert needle in doc["text"]
    assert "Edge AI hackathon" in doc["html"]


def test_evening_quiet_one_liner(cfg):
    doc = brief.build_brief("evening", [], cfg)
    assert "quiet since this morning" in doc["subject"]
    assert "Nothing meaningful landed" in doc["text"]


def test_weekly_build(cfg):
    data = {
        "week_read": "Edge agents heating up.",
        "threads": ["t1"], "momentum": ["m1"],
        "top_items": [{"section": "Papers", "title": "Paper", "why": "w"}],
        "read_of_week": {"title": "Good Read", "url": "https://r", "why": "worth it"},
        "deadline_note": "DD closes in 10 days.",
    }
    doc = brief.build_weekly(data, "29 Jun", cfg, [])
    assert doc["subject"] == "Scout — Week of 29 Jun — the pattern"
    for needle in ("heating up", "t1", "m1", "BEST OF THE WEEK", "Paper",
                   "ONE GOOD READ", "Good Read", "closes in 10 days"):
        assert needle in doc["text"]
