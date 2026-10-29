"""
PIXL 2.0 - Universal Services Launcher (start_all.py)
======================================================
Starts the PIXL 2.0 Digital Signage Core Platform:
 1. Environment & Database Verification
 2. FastAPI Backend Server (API, Media Streaming, Native TV Endpoints)
 3. Browser Screen Simulator (http://localhost:8000/simulator)
 4. Celery Background Worker (if Redis is active)
 5. Clean process supervision with graceful Ctrl+C shutdown.
"""

import os
import sys
import time
import socket
import signal
import shutil
import subprocess
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

ROOT_DIR = Path(__file__).resolve().parent
ENV_FILE = ROOT_DIR / ".env"
ENV_EXAMPLE = ROOT_DIR / ".env.example"


def find_python_executable() -> Path:
    """Finds the virtualenv python interpreter or falls back to sys.executable."""
    if os.name == "nt":
        venv_py = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        venv_py = ROOT_DIR / ".venv" / "bin" / "python"

    if venv_py.exists():
        return venv_py
    return Path(sys.executable)


# Automatic venv delegation: if run with global python, re-exec under .venv
TARGET_PYTHON = find_python_executable()
if TARGET_PYTHON.exists() and Path(sys.executable).resolve() != TARGET_PYTHON.resolve():
    try:
        res = subprocess.call([str(TARGET_PYTHON)] + sys.argv)
        sys.exit(res)
    except Exception as _e:
        pass


def print_banner(text: str):
    print(f"\n\033[1;36m{'=' * 72}\033[0m")
    print(f"\033[1;36m  {text}\033[0m")
    print(f"\033[1;36m{'=' * 72}\033[0m\n")


def log(prefix: str, msg: str, color: str = "\033[1;32m"):
    print(f"{color}[{prefix}]\033[0m {msg}", flush=True)


def get_local_ip() -> str:
    """Detects outbound LAN IP for Android TV device connectivity."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def ensure_environment():
    """Ensures .env exists and pythonpath includes ROOT_DIR."""
    if not ENV_FILE.exists() and ENV_EXAMPLE.exists():
        log("Setup", "Creating .env from .env.example...", "\033[1;33m")
        shutil.copy(ENV_EXAMPLE, ENV_FILE)

    if str(ROOT_DIR) not in sys.path:
        sys.path.insert(0, str(ROOT_DIR))
    os.environ["PYTHONPATH"] = str(ROOT_DIR)


def is_redis_online(redis_url: str = "redis://localhost:6379/0") -> bool:
    """Checks whether local Redis instance is reachable."""
    try:
        import redis
        client = redis.from_url(redis_url, socket_connect_timeout=1.0)
        return bool(client.ping())
    except Exception:
        return False


def wait_for_api_ready(port: int = 8000, timeout_seconds: int = 20) -> bool:
    """Polls the /health endpoint until FastAPI application reports UP."""
    url = f"http://127.0.0.1:{port}/health"
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        try:
            req = Request(url, headers={"User-Agent": "PIXL-Launcher"})
            with urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except (URLError, ConnectionResetError, OSError):
            pass
        time.sleep(0.5)
    return False


def main():
    ensure_environment()

    # Load configuration
    try:
        from pixl.core.config import settings
        host = settings.HOST
        port = settings.PORT
        redis_url = settings.REDIS_URL
    except Exception as e:
        log("Config", f"Could not load pixl.core.config: {e}. Falling back to defaults.", "\033[1;33m")
        host = "0.0.0.0"
        port = 8000
        redis_url = "redis://localhost:6379/0"

    local_ip = get_local_ip()
    processes = []

    def shutdown(signum=None, frame=None):
        print_banner("SHUTTING DOWN ALL PIXL SERVICES")
        for p, name in processes:
            if p.poll() is None:
                log("Stop", f"Stopping {name} (PID: {p.pid})...", "\033[1;33m")
                p.terminate()
                try:
                    p.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    p.kill()
        log("Exit", "All services stopped cleanly.", "\033[1;32m")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, shutdown)

    print_banner("STARTING PIXL 2.0 DIGITAL SIGNAGE PLATFORM")

    # 1. Start Celery Worker (if Redis is running)
    if is_redis_online(redis_url):
        log("Celery", f"Redis detected at {redis_url}. Launching background worker...", "\033[1;34m")
        celery_pool = ["-P", "solo"] if sys.platform.startswith("win") else []
        celery_cmd = [
            str(TARGET_PYTHON), "-m", "celery",
            "-A", "pixl.workers.celery_app",
            "worker",
            "--loglevel=INFO"
        ] + celery_pool
        p_celery = subprocess.Popen(celery_cmd, cwd=str(ROOT_DIR), env=os.environ.copy())
        processes.append((p_celery, "Celery Worker"))
    else:
        log("Celery", "Redis not detected locally. Background worker skipped (API operating standalone).", "\033[1;33m")

    # 2. Launch FastAPI API Server
    log("FastAPI", f"Launching Uvicorn server on http://{host}:{port}...", "\033[1;34m")
    uvicorn_cmd = [
        str(TARGET_PYTHON), "-m", "uvicorn",
        "pixl.main:app",
        "--host", host,
        "--port", str(port),
    ]
    p_uvicorn = subprocess.Popen(uvicorn_cmd, cwd=str(ROOT_DIR), env=os.environ.copy())
    processes.append((p_uvicorn, "FastAPI Backend"))

    # 3. Wait for API readiness
    log("Health", "Verifying application readiness...", "\033[1;35m")
    is_ready = wait_for_api_ready(port=port, timeout_seconds=25)

    if not is_ready:
        log("Error", "Server failed to respond to /health probe within 25 seconds.", "\033[1;31m")
        shutdown()
        return

    # 4. Display Status Dashboard
    print(f"\n\033[1;32m{'=' * 72}\033[0m")
    print(f"\033[1;32m  PIXL 2.0 CORE PLATFORM IS ONLINE AND READY\033[0m")
    print(f"\033[1;32m{'=' * 72}\033[0m")
    print(f"  \033[1m* API Root:\033[0m            http://localhost:{port}")
    print(f"  \033[1m* Interactive Docs:\033[0m    http://localhost:{port}/api/docs")
    print(f"  \033[1m* Screen Simulator:\033[0m    http://localhost:{port}/simulator")
    print(f"  \033[1m* Health Probe:\033[0m        http://localhost:{port}/health")
    print(f"  \033[1m* Native TV URL (LAN):\033[0m http://{local_ip}:{port}")
    print(f"\033[1;32m{'-' * 72}\033[0m")
    print(f"  \033[1m* Android APK:\033[0m         app/app-debug.apk")
    print(f"  \033[1m* Quick TV Setup:\033[0m      In app-debug.apk, set server to: http://{local_ip}:{port}")
    print(f"  \033[1m* To Exit:\033[0m             Press Ctrl+C to stop all services")
    print(f"\033[1;32m{'=' * 72}\033[0m\n")

    # 5. Supervise running processes
    try:
        while True:
            for p, name in processes:
                exit_code = p.poll()
                if exit_code is not None:
                    log("Alert", f"{name} exited unexpectedly with code {exit_code}.", "\033[1;31m")
                    shutdown()
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()

