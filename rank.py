"""The ranking & annotation engine — what makes Scout more than an RSS reader.

For each item surviving the pre-filter, the Anthropic API produces a
score (0-100), a route tag, and a one-line "why this matters to you",
judged against the full profile (spec Section 7).

Cost control: items are batched per call, scores are cached in SQLite so
nothing is ever re-scored, and token usage is tallied for the run log.
Failures degrade to a neutral score — loudly, never silently.
"""

from __future__ import annotations

import json
import logging
import re

from models import ROUTE_TAGS, Item
from store import Store

NEUTRAL_SCORE = 50
FALLBACK_WHY = "(unranked — scoring failed this run, will retry next run)"

SYSTEM_TEMPLATE = """\
You are the ranking engine inside Scout, a private twice-daily intelligence \
brief serving exactly one person. Score each item for how much it matters to \
THIS person's career, given their north star and its routes. Their full \
profile follows.

=== PROFILE ===
{profile_md}
=== END PROFILE ===

Scoring (0-100):
- 0-20 noise; 21-44 marginal; 45-64 worth a skim; 65-84 clearly serves a \
route or lane; 85-100 act on this — rare, real signal.
- Weight by the goal_weights above: an item serving `founder` (weight 10) \
matters far more than one serving `pe_ib` (weight 1).
- Prefer their proven lanes. An item in a lane that ALSO carries an \
opportunity (a hackathon, a job, a fundable wedge) ranks highest of all.
- Give Anthropic-related items a modest boost (their FDE target) — a boost, \
not an automatic top score.
- Politics only scores high when the policy genuinely touches tech, \
startups, funding, defence, talent visas, or AI/data regulation.

route_tag: assign exactly one of {route_tags}.

why: ONE sentence, second person, blunt and direct, no fluff, no hype — \
like a sharp friend who knows their career, never a newsletter. Tie it to \
their actual situation. For opportunities with hard filters (grade cutoffs, \
eligibility, deadlines) state the filter plainly — honesty over \
encouragement; their 57 average means a grade cutoff must never be hidden.

Output: a STRICT JSON array only — no prose, no markdown fences, no extra \
keys. One object per input item, external_id copied verbatim:
[{{"external_id": "...", "score": 0, "route_tag": "...", "why": "..."}}]
"""


def profile_to_markdown(profile: dict) -> str:
    """Render profile.yaml as readable prose/markdown, not raw YAML.

    Generic: survives user edits to the profile structure. Dicts become
    sections, short scalar-only dicts become bullet lists (goal_weights),
    lists become bullets, name/detail entries get bolded names.
    """
    lines: list[str] = []

    def title(key: str) -> str:
        return str(key).replace("_", " ").strip().title()

    def emit(key, value, depth: int) -> None:
        heading = "#" * min(depth + 2, 6)
        if isinstance(value, dict):
            scalars_only = all(not isinstance(v, (dict, list)) for v in value.values())
            short = scalars_only and all(len(str(v)) <= 80 for v in value.values())
            lines.append(f"{heading} {title(key)}")
            if short:
                lines.extend(f"- {title(k)}: {v}" for k, v in value.items())
            else:
                for k, v in value.items():
                    emit(k, v, depth + 1)
        elif isinstance(value, list):
            lines.append(f"{heading} {title(key)}")
            for v in value:
                if isinstance(v, dict):
                    name = v.get("name")
                    detail = str(v.get("detail") or v.get("description") or "").strip()
                    if name:
                        lines.append(f"- **{name}** — {detail}")
                    else:
                        lines.append("- " + "; ".join(f"{k}: {x}" for k, x in v.items()))
                else:
                    lines.append(f"- {str(v).strip()}")
        else:
            lines.append(f"{heading} {title(key)}")
            lines.append(str(value).strip())
        lines.append("")

    for key, value in profile.items():
        emit(key, value, 0)
    return "\n".join(lines).strip()


def build_system_prompt(profile: dict) -> str:
    return SYSTEM_TEMPLATE.format(
        profile_md=profile_to_markdown(profile),
        route_tags=", ".join(ROUTE_TAGS),
    )


def parse_json_array(text: str) -> list:
    """Defensive JSON extraction: tolerate fences and stray prose."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("no JSON array in model output")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("model output is not a JSON array")
    return data


def _validate(entries: list, batch: list[Item]) -> dict[str, tuple[int, str, str]]:
    valid_ids = {i.external_id for i in batch}
    out: dict[str, tuple[int, str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        eid = str(entry.get("external_id", ""))
        if eid not in valid_ids:
            continue
        try:
            score = max(0, min(100, int(entry.get("score", NEUTRAL_SCORE))))
        except (TypeError, ValueError):
            score = NEUTRAL_SCORE
        route = entry.get("route_tag")
        if route not in ROUTE_TAGS:
            route = "General"
        why = str(entry.get("why", "")).strip()
        out[eid] = (score, route, why)
    return out


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _batch_payload(batch: list[Item], max_chars: int) -> str:
    payload = [
        {
            "external_id": i.external_id,
            "source": i.source,
            "title": i.title,
            "summary": i.summary[:max_chars],
            "tags": i.raw_tags[:6],
            "published": i.published.date().isoformat(),
        }
        for i in batch
    ]
    return json.dumps(payload, ensure_ascii=False)


def _rank_batch(
    client, model: str, system_prompt: str, batch: list[Item],
    max_chars: int, stats: dict, logger: logging.Logger,
) -> dict[str, tuple[int, str, str]] | None:
    """One API call for one batch. Retries once on parse/API failure, then
    None — the caller falls back to a neutral score (spec 7.1)."""
    user_content = (
        f"Score these {len(batch)} items against the profile.\n\n"
        + _batch_payload(batch, max_chars)
    )
    for attempt in (1, 2):
        content = user_content
        if attempt == 2:
            content += "\n\nReturn ONLY the strict JSON array. No prose, no fences."
        try:
            response = client.messages.create(
                model=model,
                max_tokens=2048,
                system=system_prompt,
                messages=[{"role": "user", "content": content}],
            )
            stats["api_calls"] += 1
            stats["input_tokens"] += response.usage.input_tokens
            stats["output_tokens"] += response.usage.output_tokens
            text = "".join(b.text for b in response.content if b.type == "text")
            results = _validate(parse_json_array(text), batch)
            if not results:
                raise ValueError("no valid entries in model output")
            return results
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("ranking parse failure (attempt %d/2): %s", attempt, exc)
        except Exception as exc:  # noqa: BLE001 — API/auth/network: degrade, never crash
            logger.warning(
                "ranking API failure (attempt %d/2): %s: %s", attempt, type(exc).__name__, exc
            )
    return None


def rank_items(
    items: list[Item], profile: dict, cfg: dict, store: Store, logger: logging.Logger
) -> dict:
    """Score every item in place. Returns run stats incl. a cost estimate."""
    rcfg = cfg.get("ranking") or {}
    model = rcfg.get("model", "claude-haiku-4-5")
    batch_size = max(1, int(rcfg.get("batch_size", 10)))
    max_chars = int(rcfg.get("max_summary_chars", 1200))
    stats = {
        "api_calls": 0, "input_tokens": 0, "output_tokens": 0,
        "cache_hits": 0, "failed_items": 0, "cost_usd": 0.0,
    }

    to_rank: list[Item] = []
    for item in items:
        cached = store.get_score(item.external_id)
        if cached:
            item.score, item.route_tag, item.why = (
                cached["score"], cached["route_tag"], cached["why"],
            )
            stats["cache_hits"] += 1
        else:
            to_rank.append(item)
    if not to_rank:
        return stats

    client = None
    try:
        import anthropic

        client = anthropic.Anthropic()
    except Exception as exc:  # noqa: BLE001
        logger.error("cannot create Anthropic client (%s) — neutral scores this run", exc)

    system_prompt = build_system_prompt(profile)
    for batch in _chunks(to_rank, batch_size):
        results = None
        if client is not None:
            results = _rank_batch(client, model, system_prompt, batch, max_chars, stats, logger)
        for item in batch:
            scored = results.get(item.external_id) if results else None
            if scored is None:
                # Neutral fallback — deliberately NOT cached, so it gets
                # re-scored on the next run instead of sticking forever.
                item.score, item.route_tag, item.why = NEUTRAL_SCORE, "General", FALLBACK_WHY
                stats["failed_items"] += 1
            else:
                item.score, item.route_tag, item.why = scored
                store.save_score(item.external_id, *scored)

    price_in = float(rcfg.get("price_per_mtok_input", 1.0))
    price_out = float(rcfg.get("price_per_mtok_output", 5.0))
    stats["cost_usd"] = round(
        stats["input_tokens"] / 1e6 * price_in + stats["output_tokens"] / 1e6 * price_out, 4
    )
    return stats
