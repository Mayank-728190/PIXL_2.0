"""Build and verify an isolated production-mode Docker stack, then remove it.

Run: python -m scripts.check_docker [--skip-build] [--skip-browser]
Requires Docker Compose, dev/browser extras, and local Chrome/Edge for the browser.
Never loads the repository .env or connects to existing database containers.
All generated credentials, certificates, configuration and volumes are disposable.
"""
import argparse
import asyncio
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import pyotp
import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "pixl-verification:local"


class DockerCheck:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.project = "pixl-check-" + secrets.token_hex(5)
        self.password = secrets.token_urlsafe(32)
        self.secret = secrets.token_urlsafe(48)
        self.master_password = secrets.token_urlsafe(24)
        self.master_totp = pyotp.random_base32()
        self.ops_totp = pyotp.random_base32()
        self.private_values = [self.password, self.secret, self.master_password, self.master_totp, self.ops_totp]
        self.config = self.directory / "compose.json"
        self.env_file = self.directory / "runtime.env"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base_url = f"https://localhost:{self.port}"
        self.prepare()

    def redact(self, output):
        for value in self.private_values:
            output = output.replace(value, "[REDACTED]")
        return output

    def run(self, args, *, env=None, timeout=180, check=True, input=None):
        result = subprocess.run(args, cwd=ROOT, env={**os.environ, **(env or {})}, input=input,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if check and result.returncode:
            print(self.redact((result.stdout + result.stderr)[-24000:]), flush=True)
            raise RuntimeError(f"Docker verification command failed (exit {result.returncode})")
        return result

    def compose(self, *args, **kwargs):
        return self.run(["docker", "compose", "--project-name", self.project,
                         "--project-directory", str(self.directory), "--env-file", str(self.env_file),
                         "-f", str(self.config), *args], **kwargs)

    def prepare(self):
        from pixl.core.security import generate_ed25519_keypair
        private, public = generate_ed25519_keypair()
        self.private_values.extend([private, public])
        values = {"POSTGRES_PASSWORD": self.password, "SECRET_KEY": self.secret,
                  "MASTER_ORIGIN": self.base_url, "AGENCY_ORIGIN": self.base_url,
                  "ADVERTISER_ORIGIN": self.base_url, "MEDIA_PUBLIC_BASE_URL": self.base_url,
                  "MANIFEST_SIGNING_PRIVATE_KEY_B64": private, "MANIFEST_SIGNING_PUBLIC_KEY_B64": public}
        self.env_file.write_text("\n".join(f"{k}={v}" for k, v in values.items()) + "\n", encoding="utf-8")
        self.env_file.chmod(0o600)
        config = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
        config.pop("x-backend", None)
        for name in ("api", "migrate", "worker", "beat"):
            service = copy.deepcopy(config["services"][name])
            service.pop("build", None)
            service["image"] = IMAGE
            service["env_file"] = [str(self.env_file)]
            config["services"][name] = service
        config["services"]["api"]["ports"] = []
        tests = copy.deepcopy(config["services"]["api"])
        tests.pop("ports", None)
        tests.pop("healthcheck", None)
        tests.pop("volumes", None)
        tests["profiles"] = ["verification"]
        tests["user"] = "root"
        tests["restart"] = "no"
        test_db = f"postgresql+asyncpg://pixl_user:{self.password}@postgres:5432/pixl_test"
        tests["environment"].update({"ENVIRONMENT": "development", "SESSION_BACKEND": "memory",
                                    "SESSION_COOKIE_SECURE": "false", "MEDIA_PROCESSING_MODE": "inline",
                                    "DATABASE_URL": test_db, "PIXL_TEST_DATABASE_URL": test_db,
                                    "PIXL_TEST_REDIS_URL": "redis://redis:6379/13"})
        tests["command"] = ["sh", "-c", "python -m pip install --quiet --disable-pip-version-check '.[dev]' && python -m pytest --tb=short -v"]
        config["services"]["tests"] = tests
        self.certificate()
        nginx = """events {}
http {
  access_log off;
  server {
    listen 8443 ssl;
    server_name localhost;
    ssl_certificate /etc/nginx/test-cert.pem;
    ssl_certificate_key /etc/nginx/test-key.pem;
    client_max_body_size 250m;
    location / {
      proxy_pass http://api:8000;
      proxy_set_header Host $http_host;
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header X-Forwarded-For $remote_addr;
      proxy_read_timeout 180s;
    }
  }
}
"""
        (self.directory / "nginx.conf").write_text(nginx, encoding="utf-8")
        config["services"]["proxy"] = {
            "image": "nginx:stable-alpine", "ports": [f"127.0.0.1:{self.port}:8443"],
            "depends_on": {"api": {"condition": "service_healthy"}},
            "volumes": [f"{(self.directory / name).as_posix()}:/etc/nginx/{target}:ro"
                        for name, target in (("nginx.conf", "nginx.conf"), ("cert.pem", "test-cert.pem"), ("key.pem", "test-key.pem"))],
        }
        self.config.write_text(json.dumps(config), encoding="utf-8")
        self.config.chmod(0o600)

    def certificate(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "PIXL isolated Docker check")])
        now = datetime.now(timezone.utc)
        certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                       .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
                       .not_valid_after(now + timedelta(days=1)).add_extension(x509.SubjectAlternativeName([
                           x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
                       .sign(key, hashes.SHA256()))
        (self.directory / "cert.pem").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        path = self.directory / "key.pem"
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
        path.chmod(0o600)

    def bootstrap(self, email, totp):
        env = {"MASTER_BOOTSTRAP_EMAIL": email, "MASTER_BOOTSTRAP_PASSWORD": self.master_password,
               "MASTER_BOOTSTRAP_TOTP_SECRET": totp}
        self.compose("exec", "-T", *[arg for name in env for arg in ("-e", name)], "api",
                     "python", "-m", "scripts.create_master", env=env)

    def wait_ready(self, expected=200, seconds=45):
        with httpx.Client(base_url=self.base_url, verify=str(self.directory / "cert.pem"), timeout=5, trust_env=False) as client:
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                try:
                    if client.get("/api/v1/health/ready").status_code == expected:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(1)
        raise AssertionError(f"Readiness did not become HTTP {expected}")

    def start(self):
        self.compose("up", "-d", "--no-build", "--wait", "--wait-timeout", "120", timeout=240)
        self.wait_ready()
        self.compose("exec", "-T", "api", "python", "-m", "alembic", "check")
        self.compose("exec", "-T", "api", "python", "-m", "pip", "check")
        uid = self.compose("exec", "-T", "api", "id", "-u").stdout.strip()
        assert uid != "0", "Production API must run non-root"
        self.compose("exec", "-T", "api", "python", "-c",
                     "from pathlib import Path; assert not Path('/app/.env').exists(); assert not Path('/app/.evn').exists()")
        print("PASS: image, production startup, migrations/schema, non-root permissions and HTTPS readiness", flush=True)

    def migration_cycle(self):
        self.compose("exec", "-T", "postgres", "psql", "-U", "pixl_user", "-d", "pixl_production",
                     "-c", "CREATE DATABASE pixl_migrations_test")
        env = {"DATABASE_URL": f"postgresql+asyncpg://pixl_user:{self.password}@postgres:5432/pixl_migrations_test"}

        def alembic(*arguments):
            self.compose("exec", "-T", "-e", "DATABASE_URL", "api", "python", "-m", "alembic", *arguments, env=env)

        alembic("upgrade", "585b4edb4711")
        sql = """INSERT INTO screens (id,name,status,orientation,resolution,current_manifest_version,created_at,updated_at)
VALUES ('existing-screen','Existing','READY','LANDSCAPE','1920x1080',1,'2026-01-01','2026-01-01');
INSERT INTO device_credentials (screen_id,key_id,public_key_pem,token_hash,created_at,updated_at)
VALUES ('existing-screen','fixture-key','pem','migration-fixture-token','2026-01-01','2026-01-01');"""
        self.compose("exec", "-T", "postgres", "psql", "-U", "pixl_user", "-d", "pixl_migrations_test",
                     "-v", "ON_ERROR_STOP=1", "-c", sql)
        alembic("upgrade", "head")
        alembic("check")
        verify = """import asyncio,hashlib
from sqlalchemy import text
from pixl.workers.tasks import with_database
async def check(db):
 assert await db.scalar(text("SELECT screen_number FROM screens WHERE id='existing-screen'"))==1001
 assert await db.scalar(text("SELECT token_hash FROM device_credentials WHERE screen_id='existing-screen'"))=='sha256:'+hashlib.sha256(b'migration-fixture-token').hexdigest()
asyncio.run(with_database(check))
"""
        self.compose("exec", "-T", "-e", "DATABASE_URL", "api", "python", "-c", verify, env=env)
        alembic("upgrade", "head")
        alembic("downgrade", "base")
        alembic("upgrade", "head")
        alembic("check")
        print("PASS: PostgreSQL existing-data numbering/token backfill, repeat upgrade, full downgrade/re-upgrade and schema parity", flush=True)

    def suite(self):
        self.compose("exec", "-T", "postgres", "psql", "-U", "pixl_user", "-d", "pixl_production",
                     "-c", "CREATE DATABASE pixl_test")
        result = self.compose("run", "--rm", "--no-deps", "tests", timeout=300)
        print(self.redact(result.stdout[-16000:]), flush=True)
        assert "::test_real_worker_and_beat_process_queued_media PASSED" in result.stdout, "The real worker/Beat integration test must execute"
        print("PASS: complete Linux/PostgreSQL suite with real Redis worker/Beat integration", flush=True)

    def request(self, client, method, path, expected=200, **kwargs):
        response = client.request(method, path, **kwargs)
        assert response.status_code == expected, f"{method} {urlsplit(path).path}: HTTP {response.status_code}, expected {expected}"
        return response

    def upload(self, client, content, mime="image/png", filename="docker.png", *, wait=True):
        ticket = self.request(client, "POST", "/api/v1/agency/media/upload-ticket", json={
            "filename": filename, "size_bytes": len(content), "declared_mime": mime}).json()
        self.request(client, "PUT", ticket["presigned_upload_url"], content=content)
        self.request(client, "POST", "/api/v1/agency/media/process", expected=202,
                     json={"ticket_id": ticket["ticket_id"], "expected_sha256": hashlib.sha256(content).hexdigest()})
        if wait:
            return ticket, self.wait_job(client, ticket)
        return ticket, None

    def wait_job(self, client, ticket, expected="FINALIZED", seconds=60):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            status = self.request(client, "GET", f'/api/v1/agency/media/uploads/{ticket["ticket_id"]}').json()
            if status["status"] == expected:
                return status
            assert status["status"] != "FAILED", "Worker processing failed"
            time.sleep(1)
        raise AssertionError(f"Media job did not reach {expected}")

    def api_workflow(self):
        tls = str(self.directory / "cert.pem")
        with httpx.Client(base_url=self.base_url, verify=tls, timeout=30, trust_env=False, headers={"Origin": self.base_url}) as master, \
                httpx.Client(base_url=self.base_url, verify=tls, timeout=30, trust_env=False, headers={"Origin": self.base_url}) as agency, \
                httpx.Client(base_url=self.base_url, verify=tls, timeout=30, trust_env=False) as device:
            login = self.request(master, "POST", "/api/v1/auth/master/login", json={
                "email": "ops@example.com", "password": self.master_password, "totp_code": pyotp.TOTP(self.ops_totp).now()})
            self.private_values.append(login.json()["session_token"])
            cookie = login.headers["set-cookie"]
            assert "__Host-PIXL-Master-Session" in cookie and "Secure" in cookie and "HttpOnly" in cookie
            for path in ("/api/docs", "/api/openapi.json", "/simulator"):
                self.request(master, "GET", path, expected=404)
            self.request(master, "POST", "/api/tv/register", expected=410, json={})
            provision = self.request(master, "POST", "/api/v1/master/agencies", json={
                "name": "Docker agency", "slug": "docker-check", "admin_email": "docker@example.com"}).json()
            token = parse_qs(urlsplit(provision["invitation_link"]).query)["token"][0]
            self.private_values.append(token)
            self.request(agency, "POST", "/api/v1/auth/invitation/accept", json={"invitation_token": token, "password": self.master_password})
            auth = self.request(agency, "POST", "/api/v1/auth/agency/login", json={"email": "docker@example.com", "password": self.master_password}).json()
            self.private_values.append(auth["session_token"])
            org_id = provision["agency"]["id"]
            screen = self.request(master, "POST", "/api/v1/master/screens", json={"name": "Docker screen", "organization_id": org_id}).json()
            challenge = self.request(device, "POST", "/api/v1/device/enroll/challenge", json={"hardware_fingerprint": "docker-check-hardware"}).json()
            self.request(agency, "POST", "/api/v1/agency/screens/claim", json={"pin": challenge["pin"], "screen_id": screen["id"]})
            device_key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
            exchange = self.request(device, "POST", "/api/v1/device/enroll/exchange", json={"challenge_id": challenge["challenge_id"], "public_key_pem": device_key}).json()
            self.private_values.append(exchange["device_token"])
            device.headers["X-Device-Token"] = exchange["device_token"]
            output = io.BytesIO()
            Image.new("RGB", (64, 32), "green").save(output, "PNG")
            image = output.getvalue()
            ticket, status = self.upload(agency, image)
            asset = self.request(agency, "GET", f'/api/v1/agency/media/{status["media_id"]}').json()
            assert self.request(agency, "GET", asset["thumbnail_url"]).headers["content-type"] == "image/webp"
            # Real video probing and thumbnail generation happen in the Linux worker.
            self.upload(agency, (ROOT / "tests/fixtures/sample.mp4").read_bytes(), "video/mp4", "docker.mp4")
            bad, _ = self.upload(agency, b"invalid-image-content", filename="invalid.png", wait=False)
            self.wait_job(agency, bad, expected="FAILED")
            playlist = self.request(agency, "POST", "/api/v1/agency/playlists", json={"name": "Docker playlist", "items": [
                {"media_id": asset["id"], "sort_order": 0, "duration_mode": "IMAGE_DEFAULT", "configured_duration_ms": 10000}]}).json()
            now = datetime.now(timezone.utc)
            campaign = self.request(agency, "POST", "/api/v1/agency/campaigns", json={
                "name": "Docker campaign", "playlist_id": playlist["id"], "screen_ids": [screen["id"]],
                "start_time": (now - timedelta(minutes=1)).isoformat(), "end_time": (now + timedelta(hours=1)).isoformat()}).json()
            publish = f'/api/v1/agency/campaigns/{campaign["id"]}/publish'
            self.request(agency, "POST", publish, json={})
            first = self.request(device, "GET", "/api/v1/device/manifest")
            from pixl.core.security import verify_manifest_signature
            manifest = first.json()
            assert verify_manifest_signature(manifest["payload"], manifest["signature"], exchange["server_public_key_pem"])
            assert self.request(device, "GET", manifest["payload"]["assets"][0]["download_url"]).content == image
            self.request(device, "GET", "/api/v1/device/manifest", expected=304, headers={"If-None-Match": first.headers["etag"]})
            self.request(agency, "POST", publish, json={})
            assert self.request(device, "GET", "/api/v1/device/manifest").json()["payload"]["version"] == manifest["payload"]["version"]
            self.request(device, "POST", "/api/v1/device/heartbeat", json={"device_id": screen["id"], "epoch": exchange["epoch"], "playback_state": "PLAYING"})
            batch = {"device_id": screen["id"], "epoch": exchange["epoch"], "batch": [{"local_sequence": 1,
                     "media_id": asset["id"], "campaign_id": campaign["id"], "started_at": now.isoformat(),
                     "duration_ms": 10000, "outcome": "COMPLETED"}]}
            self.request(device, "POST", "/api/v1/device/playback/batch", json=batch)
            duplicate = self.request(device, "POST", "/api/v1/device/playback/batch", json=batch).json()
            assert duplicate["dispositions"][0]["status"] == "DUPLICATE_ACKNOWLEDGED"
            print("PASS: HTTPS cookies/auth, enrollment, image/video worker processing, rejection, manifests/ETag and receipts", flush=True)
            self.security_checks(master, agency, device, asset, screen)
            self.concurrent_checks(agency, device, publish)
            self.resilience(agency, device, ticket, asset)
            self.maintenance(agency, device, bad, campaign, asset)
            self.restore_backup(agency, device, asset, exchange["server_public_key_pem"])

    def security_checks(self, master, agency, device, asset, screen):
        self.request(agency, "GET", "/api/v1/master/agencies", expected=403)
        self.request(agency, "POST", "/api/v1/agency/playlists", expected=403,
                     headers={"Origin": "https://untrusted.invalid"}, json={"name": "Rejected", "items": []})
        other = self.request(master, "POST", "/api/v1/master/agencies", json={
            "name": "Other Docker agency", "slug": "other-docker", "admin_email": "other-docker@example.com"}).json()
        token = parse_qs(urlsplit(other["invitation_link"]).query)["token"][0]
        self.private_values.append(token)
        with httpx.Client(base_url=self.base_url, verify=str(self.directory / "cert.pem"), timeout=30,
                          trust_env=False, headers={"Origin": self.base_url}) as client:
            self.request(client, "POST", "/api/v1/auth/invitation/accept", json={"invitation_token": token, "password": self.master_password})
            login = self.request(client, "POST", "/api/v1/auth/agency/login", json={"email": "other-docker@example.com", "password": self.master_password}).json()
            self.private_values.append(login["session_token"])
            self.request(client, "GET", f'/api/v1/agency/media/{asset["id"]}', expected=404)
            self.request(client, "GET", f'/api/v1/agency/screens/{screen["id"]}', expected=404)
        self.request(device, "GET", "/api/v1/device/manifest", expected=401, headers={"X-Device-Token": "invalid-test-token"})
        # Published bytes are capabilities, not publicly enumerable static files.
        self.request(agency, "GET", f'/media/{asset["storage_key"]}', expected=404)
        approved = self.request(agency, "GET", "/api/v1/agency/screens")
        assert approved.headers["access-control-allow-origin"] == self.base_url
        unapproved = self.request(agency, "GET", "/api/v1/agency/screens", headers={"Origin": "https://untrusted.invalid"})
        assert "access-control-allow-origin" not in unapproved.headers
        print("PASS: production role/tenant isolation, CSRF/CORS, invalid device tokens and unsigned media denial", flush=True)

    def concurrent_checks(self, agency, device, publish):
        before = self.request(device, "GET", "/api/v1/device/manifest").json()["payload"]["version"]

        async def exercise():
            durations = []
            semaphore = asyncio.Semaphore(8)
            async with httpx.AsyncClient(base_url=self.base_url, verify=str(self.directory / "cert.pem"),
                                         cookies=agency.cookies, headers={"Origin": self.base_url},
                                         timeout=15, trust_env=False) as client:
                async def send(index):
                    async with semaphore:
                        started = time.monotonic()
                        path = "/api/v1/agency/media" if index % 2 else "/api/v1/agency/screens"
                        response = await client.get(path) if index < 40 else await client.post(publish, json={})
                        assert response.status_code == 200, f"Concurrent request failed with HTTP {response.status_code}"
                        durations.append(time.monotonic() - started)
                await asyncio.gather(*(send(index) for index in range(50)))
            return sorted(durations)[int(len(durations) * 0.95) - 1]

        p95 = asyncio.run(exercise())
        assert self.request(device, "GET", "/api/v1/device/manifest").json()["payload"]["version"] == before
        print(f"PASS: 50 concurrent-flow requests (8 in flight), no errors or duplicate publish invalidations; observed p95 {p95:.3f}s (not a load/soak certification)", flush=True)

    def resilience(self, agency, device, original_ticket, asset):
        self.compose("restart", "api", timeout=60)
        self.wait_ready()
        self.request(agency, "GET", "/api/v1/agency/screens")
        self.request(device, "GET", "/api/v1/device/manifest")
        self.request(agency, "GET", asset["thumbnail_url"])
        print("PASS: Redis sessions, device credentials, signing key and media survive API restart", flush=True)
        self.compose("stop", "-t", "5", "worker")
        output = io.BytesIO()
        Image.new("RGB", (48, 24), "blue").save(output, "PNG")
        ticket, _ = self.upload(agency, output.getvalue(), filename="restart.png", wait=False)
        status = self.request(agency, "GET", f'/api/v1/agency/media/uploads/{ticket["ticket_id"]}').json()
        assert status["status"] == "QUEUED"
        # Simulate persisted state left by a hard-killed worker. Reclaim is tested
        # through real dispatch/worker processes, not an eager/local task call.
        code = """import asyncio,sys
from datetime import datetime,timedelta,timezone
from sqlalchemy import update
from pixl.modules.media.models import UploadTicket
from pixl.workers.tasks import with_database
async def expire(db):
 await db.execute(update(UploadTicket).where(UploadTicket.id==sys.argv[1]).values(status='PROCESSING',processing_attempts=1,lease_token='killed-worker',lease_expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)))
 await db.commit()
asyncio.run(with_database(expire))
"""
        self.compose("exec", "-T", "api", "python", "-c", code, ticket["ticket_id"])
        self.compose("start", "worker")
        assert self.wait_job(agency, ticket)["attempts"] == 2
        print("PASS: queued work survives worker downtime; expired crash lease is reclaimed exactly once", flush=True)
        self.hard_kill_worker(agency)
        self.compose("stop", "-t", "5", "redis")
        self.wait_ready(expected=503)
        self.request(agency, "GET", "/api/v1/health/live")
        self.request(agency, "GET", "/api/v1/agency/screens", expected=503)
        self.compose("start", "redis")
        self.wait_ready()
        self.request(agency, "GET", "/api/v1/agency/screens")
        self.compose("stop", "-t", "5", "postgres")
        self.wait_ready(expected=503)
        self.request(agency, "GET", "/api/v1/health/live")
        self.compose("start", "postgres")
        self.wait_ready(seconds=60)
        self.request(agency, "GET", "/api/v1/agency/screens")
        self.request(agency, "GET", f'/api/v1/agency/media/{asset["id"]}')
        self.upload(agency, output.getvalue(), filename="after-outages.png")
        print("PASS: Redis/PostgreSQL outage fails closed, liveness stays up, persisted state recovers", flush=True)

    def hard_kill_worker(self, agency):
        # Deterministic fault injection confined to this disposable worker: let
        # real ffprobe start slowly so SIGKILL definitely interrupts PROCESSING.
        wrapper = "/app/local_storage/docker-check-ffprobe.sh"
        script = "from pathlib import Path; p=Path(__import__('sys').argv[1]); p.write_text('#!/bin/sh\\nsleep 60\\nexec /usr/bin/ffprobe \\\"$@\\\"\\n'); p.chmod(0o755)"
        self.compose("exec", "-T", "api", "python", "-c", script, wrapper)
        config = json.loads(self.config.read_text(encoding="utf-8"))
        config["services"]["worker"]["environment"]["FFPROBE_BINARY"] = wrapper
        self.config.write_text(json.dumps(config), encoding="utf-8")
        self.compose("up", "-d", "--no-deps", "--force-recreate", "worker", timeout=60)
        ticket, _ = self.upload(agency, (ROOT / "tests/fixtures/sample.mp4").read_bytes(),
                                "video/mp4", "hard-kill.mp4", wait=False)
        assert self.wait_job(agency, ticket, expected="PROCESSING")["attempts"] == 1
        self.compose("kill", "--signal", "SIGKILL", "worker")
        self.compose("stop", "-t", "2", "worker")
        # Advance the persisted lease deadline rather than waiting 15 minutes.
        code = """import asyncio,sys
from datetime import datetime,timedelta,timezone
from sqlalchemy import update
from pixl.modules.media.models import UploadTicket
from pixl.workers.tasks import with_database
async def expire(db):
 ticket=await db.get(UploadTicket,sys.argv[1])
 assert ticket.status=='PROCESSING' and ticket.processing_attempts==1
 ticket.lease_expires_at=datetime.now(timezone.utc)-timedelta(seconds=1)
 await db.commit()
asyncio.run(with_database(expire))
"""
        self.compose("exec", "-T", "api", "python", "-c", code, ticket["ticket_id"])
        config["services"]["worker"]["environment"].pop("FFPROBE_BINARY")
        self.config.write_text(json.dumps(config), encoding="utf-8")
        self.compose("up", "-d", "--no-deps", "--force-recreate", "worker", timeout=60)
        result = self.wait_job(agency, ticket)
        assert result["attempts"] == 2
        library = self.request(agency, "GET", "/api/v1/agency/media").json()
        assert sum(asset["id"] == result["media_id"] for asset in library) == 1
        self.compose("exec", "-T", "api", "python", "-c", "from pathlib import Path; Path(__import__('sys').argv[1]).unlink()", wrapper)
        print("PASS: real SIGKILL during video processing recovers after lease expiry without duplicate media", flush=True)

    def maintenance(self, agency, device, bad, campaign, asset):
        before = self.request(device, "GET", "/api/v1/device/manifest").json()["payload"]["version"]
        code = """import asyncio,sys
from datetime import datetime,timedelta,timezone
from pixl.modules.media.models import UploadTicket
from pixl.modules.campaigns.models import Campaign
from pixl.workers.tasks import with_database,maintenance
async def age(db):
 ticket=await db.get(UploadTicket,sys.argv[1]); ticket.updated_at=datetime.now(timezone.utc)-timedelta(hours=2)
 campaign=await db.get(Campaign,sys.argv[2]); campaign.end_time=datetime.now(timezone.utc)-timedelta(hours=1)
 await db.commit()
asyncio.run(with_database(age))
maintenance.delay()
"""
        self.compose("exec", "-T", "api", "python", "-c", code, bad["ticket_id"], campaign["id"])
        verify = """import asyncio,sys
from pixl.modules.media.models import UploadTicket,MediaAsset
from pixl.core.storage import storage_path
from pixl.workers.tasks import with_database
async def check(db):
 ticket=await db.get(UploadTicket,sys.argv[1]); asset=await db.get(MediaAsset,sys.argv[2])
 assert ticket.quarantine_cleaned_at is not None and not storage_path(ticket.storage_key).exists()
 assert storage_path(asset.storage_key).is_file()
asyncio.run(with_database(check))
"""
        for _ in range(20):
            result = self.compose("exec", "-T", "api", "python", "-c", verify, bad["ticket_id"], asset["id"], check=False)
            if result.returncode == 0:
                break
            time.sleep(1)
        else:
            raise AssertionError("Real maintenance task did not reconcile failed bytes")
        campaigns = self.request(agency, "GET", "/api/v1/agency/campaigns").json()
        assert next(row for row in campaigns if row["id"] == campaign["id"])["status"] == "ARCHIVED"
        manifest = self.request(device, "GET", "/api/v1/device/manifest").json()["payload"]
        assert manifest["version"] == before + 1 and not manifest["schedule"]
        print("PASS: real Celery maintenance archives expired campaign, invalidates manifest and cleans failed bytes without deleting library media", flush=True)

    def restore_backup(self, agency, device, asset, public_key):
        from pixl.core.security import verify_manifest_signature
        before = self.request(agency, "GET", "/api/v1/agency/media").json()
        self.compose("stop", "-t", "10", "worker", "beat")
        self.compose("exec", "-T", "postgres", "pg_dump", "-U", "pixl_user", "-d", "pixl_production",
                     "--format=custom", "--file=/tmp/pixl-check.dump")
        self.compose("exec", "-T", "api", "tar", "-czf", "/tmp/pixl-media.tar.gz", "-C", "/app/local_storage", ".")
        container = self.compose("ps", "-q", "api").stdout.strip()
        archive = self.directory / "media-backup.tar.gz"
        self.run(["docker", "cp", f"{container}:/tmp/pixl-media.tar.gz", str(archive)])
        archive.chmod(0o600)
        self.compose("exec", "-T", "postgres", "psql", "-U", "pixl_user", "-d", "pixl_production",
                     "-c", "CREATE DATABASE pixl_restore_test")
        self.compose("exec", "-T", "postgres", "pg_restore", "--exit-on-error", "--no-owner", "-U", "pixl_user",
                     "-d", "pixl_restore_test", "/tmp/pixl-check.dump")
        config = json.loads(self.config.read_text(encoding="utf-8"))
        config["volumes"]["restore_media"] = {}
        config["services"]["restore-files"] = {
            "image": IMAGE, "user": "root", "profiles": ["verification"], "restart": "no",
            "volumes": ["restore_media:/restore", f"{archive.as_posix()}:/tmp/media-backup.tar.gz:ro"],
            "command": ["sh", "-c", "tar -xzf /tmp/media-backup.tar.gz -C /restore && chown -R pixl:pixl /restore"],
        }
        self.config.write_text(json.dumps(config), encoding="utf-8")
        self.compose("run", "--rm", "--no-deps", "restore-files")
        restored = f"postgresql+asyncpg://pixl_user:{self.password}@postgres:5432/pixl_restore_test"
        for name in ("api", "worker", "beat", "migrate"):
            config["services"][name]["environment"]["DATABASE_URL"] = restored
            config["services"][name]["volumes"] = ["restore_media:/app/local_storage"]
        self.config.write_text(json.dumps(config), encoding="utf-8")
        self.compose("up", "-d", "--no-deps", "--force-recreate", "api", "worker", "beat", timeout=90)
        self.compose("restart", "proxy", timeout=30)
        self.wait_ready(seconds=60)
        self.compose("exec", "-T", "api", "python", "-m", "alembic", "check")
        verify_db = """import asyncio
from sqlalchemy import text
from pixl.workers.tasks import with_database
async def check(db):
 assert await db.scalar(text('SELECT current_database()'))=='pixl_restore_test'
asyncio.run(with_database(check))
"""
        self.compose("exec", "-T", "api", "python", "-c", verify_db)
        current = self.request(agency, "GET", "/api/v1/agency/media").json()
        assert {row["id"] for row in before} == {row["id"] for row in current}
        self.request(agency, "GET", asset["thumbnail_url"])
        restored_manifest = self.request(device, "GET", "/api/v1/device/manifest").json()
        assert verify_manifest_signature(restored_manifest["payload"], restored_manifest["signature"], public_key)
        # Verify actual restored media bytes, not just database records.
        expires = int(time.time()) + 300
        from hmac import new as hmac_new
        signature = hmac_new(self.secret.encode(), f'media:{asset["storage_key"]}:{expires}'.encode(), hashlib.sha256).hexdigest()
        restored_bytes = self.request(agency, "GET", f'/media/{asset["storage_key"]}?expires={expires}&signature={signature}').content
        assert hashlib.sha256(restored_bytes).hexdigest() == asset["sha256"]
        self.upload(agency, restored_bytes, filename="after-restore.png")
        print("PASS: pg_dump/pg_restore into a different database plus media restore into a new volume; recreated containers retain auth/signing and process new work", flush=True)

    def cleanup(self):
        result = self.compose("down", "--volumes", "--remove-orphans", "--timeout", "15", check=False, timeout=90)
        # Compose may skip a formerly used volume after restore changes the
        # service mounts. Remove only volumes owned by this exact random project;
        # never prune Docker or touch another application's data.
        listed = self.run(["docker", "volume", "ls", "--filter", f"label=com.docker.compose.project={self.project}",
                           "--format", "{{.Name}}"], check=False, timeout=20)
        volumes = listed.stdout.split()
        safe = all(name.startswith(self.project + "_") for name in volumes)
        removed = True
        if volumes and safe and listed.returncode == 0:
            removed = self.run(["docker", "volume", "rm", *volumes], check=False, timeout=30).returncode == 0
        if result.returncode or listed.returncode or not safe or not removed:
            print(f"WARNING: cleanup incomplete; inspect only the disposable Compose project {self.project}", flush=True)
            return False
        print("Disposable Docker containers, network and volumes removed; existing services unchanged.", flush=True)
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true", help="Use the existing pixl-verification:local image")
    parser.add_argument("--skip-browser", action="store_true")
    parser.add_argument("--skip-suite", action="store_true", help="Only run deployment/browser/failure checks")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="pixl-docker-check-") as directory:
        check = DockerCheck(directory)
        try:
            check.run(["docker", "info"], timeout=20)
            if not args.skip_build:
                check.run(["docker", "build", "--tag", IMAGE, "."], timeout=600)
            check.start()
            if not args.skip_suite:
                check.migration_cycle()
                check.suite()
            check.bootstrap("master@example.com", check.master_totp)
            check.bootstrap("ops@example.com", check.ops_totp)
            if not args.skip_browser:
                from scripts.check_portals_browser import run_check
                asyncio.run(run_check(check.base_url, check.master_password, check.master_totp, directory, verify_tls=False))
                print("PASS: real Chrome workflow through HTTPS proxy with production Redis sessions and worker uploads", flush=True)
            check.api_workflow()
            print("Docker verification passed. This does not replace load/soak, device or independent security acceptance.", flush=True)
        except Exception as exc:
            # Logs never include access query strings; additionally redact all
            # generated credentials before emitting diagnostics.
            logs = check.compose("logs", "--no-color", "--tail", "20", check=False)
            print(check.redact((logs.stdout + logs.stderr)[-24000:]), flush=True)
            print(check.redact(f"Docker verification failed: {type(exc).__name__}: {exc}"), flush=True)
            raise SystemExit(1) from None
        finally:
            if not check.cleanup():
                raise SystemExit(1)


if __name__ == "__main__":
    main()
