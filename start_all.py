"""Development launcher. Never seeds accounts or silently applies migrations.

Production: use the migration/API/worker/Beat services in docker-compose.yml.
"""
import argparse
import asyncio
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT_DIR = Path(__file__).resolve().parent


def find_python_executable():
    path = ROOT_DIR / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return path if path.exists() else Path(sys.executable)


def ensure_database():
    """Verify migration history without changing customer data."""
    from alembic.config import Config
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory
    from pixl.core.database import engine

    async def check():
        try:
            async with engine.connect() as connection:
                return await connection.run_sync(lambda conn: MigrationContext.configure(conn).get_current_heads())
        finally:
            await engine.dispose()

    actual = set(asyncio.run(check()))
    expected = set(ScriptDirectory.from_config(Config(str(ROOT_DIR / "alembic.ini"))).get_heads())
    if actual != expected:
        raise RuntimeError("Database migrations are pending. Back up the database, then run python -m alembic upgrade head.")


def is_redis_online(redis_url):
    import redis
    try:
        with redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2) as client:
            return bool(client.ping())
    except redis.RedisError:
        return False


def wait_for_api_ready(port=8000, timeout_seconds=25):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/api/v1/health/ready", timeout=1) as response:
                if response.status == 200:
                    return True
        except (URLError, OSError):
            pass
        time.sleep(0.5)
    return False


def main():
    python = find_python_executable()
    if Path(sys.executable).resolve() != python.resolve():
        raise SystemExit(subprocess.call([str(python), str(Path(__file__).resolve()), *sys.argv[1:]], cwd=ROOT_DIR))
    os.chdir(ROOT_DIR)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--migrate", action="store_true", help="Explicitly apply pending migrations; back up your database first")
    args = parser.parse_args()
    from pixl.core.config import settings
    if settings.ENVIRONMENT == "production":
        raise SystemExit("Use the production Compose services, not the development launcher.")
    try:
        if args.migrate:
            subprocess.run([str(python), "-m", "alembic", "upgrade", "head"], cwd=ROOT_DIR, check=True)
        ensure_database()
    except Exception:
        print("Database verification failed. Back up and inspect migration history, then run python -m alembic upgrade head.", file=sys.stderr)
        raise SystemExit(1) from None

    broker_ready = is_redis_online(settings.CELERY_BROKER_URL)
    if settings.MEDIA_PROCESSING_MODE == "worker" and not broker_ready:
        raise SystemExit("Worker processing requires a reachable CELERY_BROKER_URL. Start Redis or select inline mode.")
    processes = []

    def shutdown(signum=None, frame=None):
        for process, _ in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process, _ in reversed(processes):
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if signum is not None:
            raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    def launch(name, arguments):
        processes.append((subprocess.Popen([str(python), "-m", *arguments], cwd=ROOT_DIR), name))

    try:
        if broker_ready:
            worker = ["celery", "-A", "pixl.workers.celery_app:celery_app", "worker", "--loglevel=INFO", "--concurrency=2"]
            if os.name == "nt":
                worker += ["--pool=solo"]
            launch("worker", worker)
            launch("scheduler", ["celery", "-A", "pixl.workers.celery_app:celery_app", "beat", "--loglevel=INFO"])
        else:
            print("Redis unavailable: using inline processing; scheduled maintenance is not running.")
        launch("API", ["uvicorn", "pixl.main:app", "--host", settings.HOST, "--port", str(settings.PORT), "--no-access-log"])
        if not wait_for_api_ready(settings.PORT):
            raise RuntimeError("API failed readiness checks")
        print(f"Master: http://localhost:{settings.PORT}/master")
        print(f"Agency: http://localhost:{settings.PORT}/agency")
        print("Use your own account. First account: python -m scripts.create_master")
        print("Press Ctrl+C to stop. Never expose this development server directly to the Internet.")
        while True:
            for process, name in processes:
                if process.poll() is not None:
                    raise RuntimeError(f"{name} exited unexpectedly")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()


if __name__ == "__main__":
    main()
