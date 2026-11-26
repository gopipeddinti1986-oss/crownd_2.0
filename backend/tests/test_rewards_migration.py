import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.core.config import settings


def test_rewards_migration_adds_database_append_only_guards_and_blocks_data_loss(tmp_path, monkeypatch):
    database = tmp_path / "phase5-migration.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{database}")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")

    connection = sqlite3.connect(database)
    connection.execute("INSERT INTO ledger_entries (reference,user_id,entry_type,amount,currency,direction,description,created_at) VALUES ('TEST-ORDER',1,'TEST',1.00,'INR','credit','test','2026-11-25T00:00:00')")
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("UPDATE ledger_entries SET amount=2.00 WHERE reference='TEST-ORDER'")
    connection.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM ledger_entries WHERE reference='TEST-ORDER'")
    connection.rollback()
    connection.execute("INSERT INTO reward_events (reward_id,event_key,event_type,to_status,metadata_json,created_at) VALUES (1,'event-1','reward_created','pending','{}','2026-11-25T00:00:00')")
    connection.commit()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("UPDATE reward_events SET to_status='approved' WHERE event_key='event-1'")
    connection.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM reward_events WHERE event_key='event-1'")
    connection.rollback()
    connection.close()

    with pytest.raises(RuntimeError, match="reward_events contains Phase 5 records"):
        command.downgrade(config, "0005_referral_attribution")
