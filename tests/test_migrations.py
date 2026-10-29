"""Validate migration history independently of SQLAlchemy create_all."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from pixl.core.security import hash_device_token


def test_migrations_preserve_data_hash_tokens_and_match_models(tmp_path):
    root = Path(__file__).resolve().parents[1]
    db_path = tmp_path / "migrations.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}", "DEBUG": "false"}

    def alembic(*args):
        result = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=root, env=env,
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        return result

    alembic("upgrade", "585b4edb4711")
    with sqlite3.connect(db_path) as db:
        db.execute("""INSERT INTO screens (id, name, status, orientation, resolution,
                   current_manifest_version, created_at, updated_at)
                   VALUES ('existing-screen', 'Existing', 'READY', 'LANDSCAPE', '1920x1080',
                           1, '2026-01-01', '2026-01-01')""")
        db.execute("""INSERT INTO device_credentials
                   (screen_id, key_id, public_key_pem, token_hash, created_at, updated_at)
                   VALUES ('existing-screen', 'key', 'pem', 'original-device-token',
                           '2026-01-01', '2026-01-01')""")
    alembic("upgrade", "head")
    alembic("check")
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT name, screen_number FROM screens").fetchone() == ("Existing", 1001)
        assert db.execute("SELECT token_hash FROM device_credentials").fetchone()[0] == hash_device_token("original-device-token")
        assert db.execute("SELECT value FROM number_sequences WHERE name='screens'").fetchone()[0] == 1001
    alembic("upgrade", "head")  # No token double hashing or renumbering on repeat.
    alembic("downgrade", "base")
    alembic("upgrade", "head")
    alembic("check")
