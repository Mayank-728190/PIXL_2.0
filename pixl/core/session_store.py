"""Session persistence adapters. Redis outages fail closed, never fall back to memory."""
import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache

import redis

from pixl.core.config import settings
from pixl.core.exceptions import PixlException


@lru_cache(maxsize=4)
def redis_client(url):
    return redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2,
                                socket_timeout=2, health_check_interval=30)


def session_key(token):
    return "pixl:session:" + hashlib.sha256(token.encode()).hexdigest()


def user_key(user_id):
    return "pixl:user-sessions:" + user_id


def cache():
    return redis_client(settings.REDIS_URL)


def unavailable(exc):
    raise PixlException(503, "Session service temporarily unavailable", "SESSION_SERVICE_UNAVAILABLE") from exc


def save(token, data):
    payload = {k: v.isoformat() if isinstance(v, datetime) else v
               for k, v in data.items() if k != "session_token"}
    try:
        with cache().pipeline() as pipe:
            pipe.setex(session_key(token), settings.SESSION_MAX_AGE_SECONDS, json.dumps(payload))
            pipe.sadd(user_key(data["user_id"]), session_key(token))
            pipe.expire(user_key(data["user_id"]), settings.SESSION_MAX_AGE_SECONDS)
            pipe.execute()
    except redis.RedisError as exc:
        unavailable(exc)


def get(token):
    try:
        payload = cache().get(session_key(token))
    except redis.RedisError as exc:
        unavailable(exc)
    if not payload:
        return None
    data = json.loads(payload)
    for field in ("created_at", "expires_at"):
        data[field] = datetime.fromisoformat(data[field])
    if data["expires_at"] <= datetime.now(timezone.utc):
        revoke(token)
        return None
    data["session_token"] = token
    return data


def revoke(token):
    data = get_without_expiration(token)
    try:
        with cache().pipeline() as pipe:
            pipe.delete(session_key(token))
            if data:
                pipe.srem(user_key(data["user_id"]), session_key(token))
            result = pipe.execute()
        return bool(result[0])
    except redis.RedisError as exc:
        unavailable(exc)


def get_without_expiration(token):
    try:
        payload = cache().get(session_key(token))
        return json.loads(payload) if payload else None
    except redis.RedisError as exc:
        unavailable(exc)


def revoke_user(user_id):
    # Atomic across API workers; no session tokens are stored in the index.
    script = """
    local sessions = redis.call('SMEMBERS', KEYS[1])
    local count = 0
    for _, key in ipairs(sessions) do count = count + redis.call('DEL', key) end
    redis.call('DEL', KEYS[1])
    return count
    """
    try:
        return int(cache().eval(script, 1, user_key(user_id)))
    except redis.RedisError as exc:
        unavailable(exc)
