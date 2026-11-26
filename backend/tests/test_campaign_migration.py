import sqlite3
from pathlib import Path
from alembic import command
from alembic.config import Config
from app.core.config import settings


def test_phase6_migration_fresh_upgrade_downgrade_reupgrade_is_additive(tmp_path,monkeypatch):
    database=tmp_path/"phase6-campaigns.db"
    monkeypatch.setattr(settings,"database_url",f"sqlite:///{database}")
    config=Config(str(Path(__file__).resolve().parents[1]/"alembic.ini"))
    command.upgrade(config,"head")
    connection=sqlite3.connect(database)
    columns={row[1] for row in connection.execute("PRAGMA table_info(campaigns)")}
    assert {"objectives","target_audience","creator_requirements","visibility","performance_goals"}<=columns
    assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]=="0009_notifications"
    connection.close()
    command.downgrade(config,"0006_rewards_ledger")
    command.upgrade(config,"head")
    connection=sqlite3.connect(database)
    columns={row[1] for row in connection.execute("PRAGMA table_info(campaigns)")}
    assert {"objectives","target_audience","creator_requirements","visibility","performance_goals"}<=columns
    assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]=="0009_notifications"
    connection.close()


def test_phase6_migration_adds_missing_fields_to_historical_phase5_schema(tmp_path,monkeypatch):
    database=tmp_path/"historical-phase5.db"
    monkeypatch.setattr(settings,"database_url",f"sqlite:///{database}")
    config=Config(str(Path(__file__).resolve().parents[1]/"alembic.ini"))
    command.upgrade(config,"0006_rewards_ledger")
    connection=sqlite3.connect(database)
    for column in ("objectives","target_audience","creator_requirements","visibility","performance_goals"):
        connection.execute(f"ALTER TABLE campaigns DROP COLUMN {column}")
    connection.commit();connection.close()
    command.upgrade(config,"head")
    connection=sqlite3.connect(database)
    columns={row[1] for row in connection.execute("PRAGMA table_info(campaigns)")}
    assert {"objectives","target_audience","creator_requirements","visibility","performance_goals"}<=columns
    constraint_rows=connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='campaigns'").fetchone()[0]
    assert "ck_campaign_visibility" in constraint_rows
    connection.close()
