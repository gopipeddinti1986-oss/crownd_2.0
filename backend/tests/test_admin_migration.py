import sqlite3
from pathlib import Path
from alembic import command
from alembic.config import Config
from app.core.config import settings


def test_platform_admin_migration_historical_upgrade_and_non_destructive_reupgrade(tmp_path, monkeypatch):
    database = tmp_path / "phase7-admin.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{database}")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "0007_campaign_intelligence")
    conn = sqlite3.connect(database)
    for table in ("admin_dispute_events", "admin_disputes", "admin_audit_events"):
        conn.execute(f'DROP TABLE "{table}"')
    conn.execute("ALTER TABLE creator_profiles DROP COLUMN verification")
    conn.execute("INSERT INTO users(id,name,email,password_hash,role,is_active,email_verified,created_at) VALUES(50,'Existing Creator','existing@example.test','hash','creator',1,1,'2026-01-01T00:00:00+00:00')")
    conn.execute("INSERT INTO creator_profiles(id,user_id,username,niche,location,bio,platform,followers,engagement,availability,crown_score,trust_score) VALUES(50,50,'existing_creator','Lifestyle','India','','Instagram',0,0,1,500,80)")
    conn.commit(); conn.close()
    command.upgrade(config, "head")
    conn = sqlite3.connect(database)
    assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0010_integration_snapshots"
    assert "verification" in {row[1] for row in conn.execute("PRAGMA table_info(creator_profiles)")}
    assert conn.execute("SELECT user_id, username, verification FROM creator_profiles WHERE user_id=50").fetchone() == (50, "existing_creator", "unverified")
    assert {"admin_audit_events", "admin_disputes", "admin_dispute_events"} <= {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in ("audit_logs", "admin_audit_events", "admin_dispute_events"):
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (table,)).fetchone()[0] == 2
    conn.execute("INSERT INTO audit_logs(action,entity_type,entity_id,created_at) VALUES('test','test','1','2026-11-25T00:00:00+00:00')")
    conn.execute("INSERT INTO admin_audit_events(action,entity_type,entity_id,reason,metadata_json,created_at) VALUES('test','test','1','test reason','{}','2026-11-25T00:00:00+00:00')")
    conn.commit()
    for table in ("audit_logs", "admin_audit_events"):
        try:
            conn.execute(f"UPDATE {table} SET entity_id='mutated' WHERE entity_id='1'")
            raise AssertionError(f"{table} accepted an update despite its append-only trigger")
        except sqlite3.IntegrityError:
            conn.rollback()
    conn.close()
    command.downgrade(config, "0007_campaign_intelligence")
    command.upgrade(config, "head")
    conn = sqlite3.connect(database)
    assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "0010_integration_snapshots"
    conn.close()
