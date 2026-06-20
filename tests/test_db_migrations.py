import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'app'))

from sqlalchemy import text
from sqlmodel import create_engine


def _columns(engine, table):
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).all()
    return {r[1] for r in rows}


def test_add_missing_columns_adds_only_absent_ones():
    from database import add_missing_columns

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE companysettings (id INTEGER PRIMARY KEY, legal_name TEXT)"))

    added = add_missing_columns(engine, "companysettings", {
        "legal_name": "TEXT",        # already present
        "ollama_url": "TEXT",
        "ollama_model": "TEXT",
    })

    assert set(added) == {"ollama_url", "ollama_model"}
    cols = _columns(engine, "companysettings")
    assert {"legal_name", "ollama_url", "ollama_model"} <= cols


def test_add_missing_columns_is_idempotent():
    from database import add_missing_columns

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE companysettings (id INTEGER PRIMARY KEY)"))

    first = add_missing_columns(engine, "companysettings", {"ollama_url": "TEXT"})
    second = add_missing_columns(engine, "companysettings", {"ollama_url": "TEXT"})

    assert first == ["ollama_url"]
    assert second == []
