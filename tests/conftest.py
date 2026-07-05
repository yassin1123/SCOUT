import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import load_config, load_profile  # noqa: E402
from models import Item, section_for  # noqa: E402
from store import Store  # noqa: E402
from util import now_utc  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    s = Store(tmp_path / "scout.db")
    yield s
    s.close()


@pytest.fixture(scope="session")
def cfg():
    return load_config()


@pytest.fixture(scope="session")
def profile():
    return load_profile()


def make_item(external_id="x1", source="arxiv", title="Multi-agent LLM planning",
              summary="edge inference", score=0, section=None, why="", **kw):
    return Item(
        source=source, external_id=external_id, title=title, summary=summary,
        url=f"https://example.org/{external_id}", published=kw.pop("published", now_utc()),
        score=score, section=section if section is not None else section_for(source),
        why=why, **kw,
    )
