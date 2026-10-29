"""Fixed-window abuse protection; shared Redis counters in production."""
import hashlib
import time
from threading import Lock

import redis
from fastapi import Request
from starlette.concurrency import run_in_threadpool

from pixl.core.config import settings
from pixl.core.exceptions import PixlException
from pixl.core import session_store

_attempts = {}
_lock = Lock()


def check_rate(key: str, limit: int = 30, window: int = 60):
    key = "pixl:rate:" + hashlib.sha256(key.encode()).hexdigest()
    if settings.SESSION_BACKEND == "redis":
        try:
            count = session_store.cache().eval("""
                local count = redis.call('INCR', KEYS[1])
                if count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
                return count
            """, 1, key, window)
        except redis.RedisError as exc:
            session_store.unavailable(exc)
    else:
        with _lock:
            now = time.monotonic()
            for stale_key, (_, expiry) in list(_attempts.items()):
                if expiry <= now:
                    del _attempts[stale_key]
            count, expiry = _attempts.get(key, (0, now + window))
            count += 1
            _attempts[key] = (count, expiry)
    if count > limit:
        raise PixlException(429, "Too many requests; please retry later", "RATE_LIMITED",
                            headers={"Retry-After": str(window)})


async def authentication_rate_limit(request: Request):
    # Never trust arbitrary X-Forwarded-For headers. Configure trusted proxies in Uvicorn.
    host = request.client.host if request.client else "unknown"
    await run_in_threadpool(check_rate, f"authentication:{host}")


async def enrollment_rate_limit(request: Request):
    host = request.client.host if request.client else "unknown"
    await run_in_threadpool(check_rate, f"enrollment:{host}", 30, 60)
