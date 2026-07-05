"""Ranking engine: parsing, validation, caching, degradation."""

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from rank import (FALLBACK_WHY, NEUTRAL_SCORE, _validate, build_system_prompt,
                  parse_json_array, parse_json_object, rank_items)
from tests.conftest import make_item

log = logging.getLogger("test")


def test_parse_json_array_defensive():
    assert parse_json_array('[{"a": 1}]') == [{"a": 1}]
    assert parse_json_array('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert parse_json_array('Sure: [{"a": 1}] done') == [{"a": 1}]
    with pytest.raises(ValueError):
        parse_json_array("nope")


def test_parse_json_object_defensive():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json_object("[1, 2]")


def test_validate_clamps_and_coerces():
    batch = [make_item("arxiv:1")]
    out = _validate(
        [
            {"external_id": "arxiv:1", "score": 250, "why": " w "},
            {"external_id": "unknown", "score": 10, "why": "x"},
        ],
        batch,
    )
    assert out == {"arxiv:1": (100, "w")}


def test_system_prompt_is_interests_only(profile):
    prompt = build_system_prompt(profile)
    assert "INTERESTS" in prompt
    assert "never address" in prompt
    # nothing personal may appear in what goes to the API
    for forbidden in ("Accenture", "Southampton", "57", "founder", "FDE"):
        assert forbidden not in prompt, forbidden


def _fake_client(score=88):
    def create(**kwargs):
        body = kwargs["messages"][0]["content"]
        ids = [e["external_id"] for e in json.loads(body[body.find("[") : body.rfind("]") + 1])]
        resp = MagicMock()
        resp.usage.input_tokens, resp.usage.output_tokens = 500, 100
        block = MagicMock()
        block.type = "text"
        block.text = json.dumps(
            [{"external_id": i, "score": score, "why": "w"} for i in ids]
        )
        resp.content = [block]
        return resp

    client = MagicMock()
    client.messages.create.side_effect = create
    return client


def test_rank_items_scores_and_caches(cfg, profile, store):
    with patch("anthropic.Anthropic", return_value=_fake_client()):
        items = [make_item("arxiv:2")]
        stats = rank_items(items, profile, cfg, store, log)
        assert items[0].score == 88 and stats["api_calls"] == 1
        assert stats["cost_usd"] > 0
        again = [make_item("arxiv:2")]
        stats2 = rank_items(again, profile, cfg, store, log)
        assert stats2["cache_hits"] == 1 and stats2["api_calls"] == 0
        assert again[0].score == 88


def test_rank_items_degrades_without_caching_failures(cfg, profile, store):
    dead = MagicMock()
    dead.messages.create.side_effect = RuntimeError("api down")
    with patch("anthropic.Anthropic", return_value=dead):
        items = [make_item("arxiv:3")]
        stats = rank_items(items, profile, cfg, store, log)
    assert items[0].score == NEUTRAL_SCORE and items[0].why == FALLBACK_WHY
    assert stats["failed_items"] == 1
    assert store.get_score("arxiv:3") is None  # retried next run
