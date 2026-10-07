"""Upgrade the actual previous schema without losing records or calling legacy hits verified."""
from pathlib import Path
import sqlite3
from codeneuro.storage import Storage


def test_legacy_upgrade_quarantines_samples_and_preserves_history(tmp_path):
    path=str(tmp_path/'old.db')
    conn=sqlite3.connect(path)
    conn.executescript((Path(__file__).parent/'fixtures/legacy_schema.sql').read_text())
    conn.execute("INSERT INTO projects VALUES('p','legacy','', '[]','2026-01-01')")
    conn.execute("INSERT INTO rules(id,project_id,scope_patterns,priority,lifecycle,title,content_points,created_by,status,hit_count,created_at,updated_at) VALUES('r','p','[\"**\"]','P0','long_term','rule','[\"content\"]','human','active',212,'2026-01-01','2026-01-01')")
    conn.execute("INSERT INTO findings VALUES('find_live_4_123','p',NULL,NULL,'src/a.py','invented zero jitter','P2','pending_review','2026-01-01')")
    conn.execute("INSERT INTO findings VALUES('observed','p',NULL,NULL,'src/a.py','actual observation','P1','pending_review','2026-01-01')")
    conn.commit();conn.close()
    store=Storage(path)
    assert store.get_rule('r').legacy_hit_count==212
    assert store.get_rule('r').hit_count==0
    assert [f.id for f in store.list_findings('p')]==['observed']
    assert store.conn.execute("SELECT source FROM findings WHERE id='find_live_4_123'").fetchone()[0]=='demo'
    store.increment_rule_hits(['r']);store.close()
    reopened=Storage(path)
    assert reopened.get_rule('r').hit_count==1
    assert reopened.get_rule('r').legacy_hit_count==212
    assert reopened.conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert list(reopened.conn.execute('PRAGMA foreign_key_check'))==[]
    reopened.close()
