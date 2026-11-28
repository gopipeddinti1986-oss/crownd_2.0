import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import settings


def test_notifications_migration_is_additive_and_repeatable(tmp_path, monkeypatch):
    database = tmp_path / "phase8-notifications.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{database}")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "0008_platform_admin")
    conn = sqlite3.connect(database)
    conn.execute("INSERT INTO users(id,name,email,password_hash,role,is_active,email_verified,created_at) VALUES(81,'Existing','existing@example.test','hash','customer',1,1,'2026-01-01T00:00:00+00:00')")
    # The legacy 0001 revision creates current metadata on fresh schemas; remove
    # Phase 8 tables to emulate an actual historical 0008 database before upgrade.
    for table in ("email_deliveries", "notifications", "notification_preferences"):
        conn.execute(f'DROP TABLE "{table}"')
    conn.commit()
    conn.close()
    command.upgrade(config, "head")
    conn = sqlite3.connect(database)
    assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0010_integration_snapshots"
    assert conn.execute("SELECT email FROM users WHERE id=81").fetchone()[0] == "existing@example.test"
    assert "reward_snapshot" in {row[1] for row in conn.execute("PRAGMA table_info(order_items)")}
    assert {"dispute_hold", "dispute_prior_status"} <= {row[1] for row in conn.execute("PRAGMA table_info(rewards)")}
    assert conn.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name='order_items_no_update'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name='order_items_no_delete'").fetchone()[0] == 1
    assert {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")} >= {
        "notification_preferences", "notifications", "email_deliveries"}
    for table in ("notification_preferences", "notifications", "email_deliveries"):
        assert conn.execute(f"SELECT count(*) FROM sqlite_master WHERE type='index' AND tbl_name=?", (table,)).fetchone()[0] >= 1
    conn.close()
    command.downgrade(config, "0008_platform_admin")
    command.upgrade(config, "head")
    conn = sqlite3.connect(database)
    assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0010_integration_snapshots"
    assert conn.execute("SELECT email FROM users WHERE id=81").fetchone()[0] == "existing@example.test"
    conn.close()
