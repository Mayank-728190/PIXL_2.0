"""Local quarantine storage and bounded media inspection.

Only published files are exposed by the media router. Quarantine is never public.
External object storage is deliberately rejected until a provider is implemented.
"""
import hashlib
import hmac
import json
import os
import subprocess
import time
from urllib.parse import urlencode
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from pixl.core.config import settings
from pixl.core.exceptions import ConflictError, UnprocessableError

MIME_EXTENSIONS = {
    "video/mp4": "mp4", "video/webm": "webm", "image/png": "png",
    "image/jpeg": "jpg", "image/webp": "webp",
}


def _comparison_path(path: Path) -> Path:
    """Normalize Windows namespace spelling only after resolving symlinks.

    Windows realpath may retain the extended prefix when a parent is created
    concurrently. It must not make the same canonical directory look unrelated.
    Keep the original resolved path for I/O (including long-path support).
    """
    value = str(path)
    if os.name == "nt":
        if value.startswith("\\\\?\\UNC\\"):
            return Path("\\\\" + value[8:])
        if value.startswith("\\\\?\\"):
            return Path(value[4:])
    return path


def storage_path(key: str) -> Path:
    if settings.STORAGE_PROVIDER != "local":
        raise ConflictError("This installation supports local storage only")
    root = Path(settings.LOCAL_STORAGE_PATH).resolve()
    path = (root / key).resolve()
    comparison_root, comparison_path = _comparison_path(root), _comparison_path(path)
    if not comparison_path.is_relative_to(comparison_root) or comparison_path == comparison_root:
        raise UnprocessableError("Invalid storage path")
    return path


def upload_signature(ticket_id: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"upload:{ticket_id}".encode(), hashlib.sha256).hexdigest()


def media_signature(key: str, expires: int) -> str:
    message = f"media:{key}:{expires}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def valid_media_signature(key: str, expires: int, signature: str) -> bool:
    now = int(time.time())
    return (now <= expires <= now + 259260 and len(signature) == 64 and signature.isascii()
            and hmac.compare_digest(signature, media_signature(key, expires)))


def public_media_url(key: str, base_url: str | None = None) -> str:
    expires = int(time.time()) + 259200  # Match the 72-hour offline manifest window.
    query = urlencode({"expires": expires, "signature": media_signature(key, expires)})
    base = settings.MEDIA_PUBLIC_BASE_URL if base_url is None else base_url
    return f"{base.rstrip(chr(47))}/media/{key}?{query}"


def inspect_media(path: Path, declared_mime: str) -> dict:
    """Inspect actual content; never infer dimensions/duration from client input."""
    with path.open("rb") as content:
        digest = hashlib.file_digest(content, "sha256").hexdigest()
    if declared_mime.startswith("image/"):
        try:
            with Image.open(path) as image:
                actual_mime = Image.MIME.get(image.format)
                if actual_mime != declared_mime:
                    raise UnprocessableError("Image content does not match declared MIME type")
                if image.width * image.height > 40_000_000 or getattr(image, "n_frames", 1) > 1:
                    raise UnprocessableError("Image is too large or animated")
                image.verify()
            with Image.open(path) as image:
                image.load()  # verify also that the pixel data can be decoded
                return dict(sha256=digest, width=image.width, height=image.height, duration_ms=0)
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
            raise UnprocessableError("Invalid or unsupported image content") from exc
    try:
        result = subprocess.run([
            settings.FFPROBE_BINARY, "-v", "error", "-protocol_whitelist", "file,pipe",
            "-show_streams", "-show_format", "-of", "json", str(path),
        ], capture_output=True, timeout=30, check=True)
        data = json.loads(result.stdout)
        stream = next(s for s in data["streams"] if s.get("codec_type") == "video")
        formats = data["format"]["format_name"].split(",")
        expected_format = "mp4" if declared_mime == "video/mp4" else "webm"
        duration = float(data["format"]["duration"])
        width, height = int(stream["width"]), int(stream["height"])
        if expected_format not in formats or not 0 < duration <= 86400 or not 0 < width * height <= 40_000_000:
            raise ValueError("Invalid video metadata")
        return dict(sha256=digest, width=width, height=height, duration_ms=round(duration * 1000))
    except FileNotFoundError as exc:
        raise ConflictError("ffprobe is required for video processing") from exc
    except (subprocess.SubprocessError, KeyError, StopIteration, ValueError, TypeError) as exc:
        raise UnprocessableError("Invalid or unsupported video content") from exc


def generate_thumbnail(source: Path, destination: Path, mime: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if mime.startswith("image/"):
        with Image.open(source) as image:
            image.thumbnail((480, 480))
            image.convert("RGB").save(destination, "WEBP")
        return
    try:
        subprocess.run([
            settings.FFMPEG_BINARY, "-v", "error", "-nostdin", "-y",
            "-protocol_whitelist", "file,pipe", "-i", str(source),
            "-frames:v", "1", "-vf", "scale=480:-2", str(destination),
        ], capture_output=True, timeout=60, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        destination.unlink(missing_ok=True)
        raise ConflictError("Unable to decode video or generate thumbnail; check ffmpeg installation") from exc
