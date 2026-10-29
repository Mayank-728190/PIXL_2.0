import base64
import hashlib
import json
import secrets
from typing import Tuple, Dict, Any

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
import pyotp

# Argon2id password hasher with secure enterprise parameters
_ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16
)


def hash_password(password: str) -> str:
    """Hash password using Argon2id."""
    return _ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against Argon2id hash."""
    try:
        return _ph.verify(hashed_password, plain_password)
    except (VerifyMismatchError, Exception):
        return False


def generate_secure_token(length: int = 32) -> str:
    """Generate cryptographically secure random token (URL safe)."""
    return secrets.token_urlsafe(length)


def generate_pin(length: int = 6) -> str:
    """Generate high-entropy alphanumeric device pairing PIN (e.g. 'PK8921')."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # omit ambiguous O, 0, 1, I
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_totp_secret() -> str:
    """Generate random base32 TOTP secret for MFA."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, account_name: str, issuer_name: str = "PIXL Signage") -> str:
    """Generate TOTP URI for QR code generation."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=account_name, issuer_name=issuer_name)


def verify_totp_code(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP MFA code."""
    if not secret or not code:
        return False
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def sha256_checksum(data: bytes) -> str:
    """Compute hex SHA-256 hash of bytes."""
    return hashlib.sha256(data).hexdigest()


# ED25519 Manifest Signing & Verification
def generate_ed25519_keypair() -> Tuple[str, str]:
    """Generate ED25519 private and public keys as Base64 strings."""
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    priv_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    )
    pub_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )

    return (
        base64.b64encode(priv_bytes).decode("utf-8"),
        base64.b64encode(pub_bytes).decode("utf-8")
    )


# System-wide default ED25519 manifest signing keypair
_SERVER_PRIV_KEY, _SERVER_PUB_KEY = generate_ed25519_keypair()


def get_server_signing_keys() -> Tuple[str, str]:
    """Retrieve consistent private and public ED25519 signing keys."""
    from pixl.core.config import settings
    priv = settings.MANIFEST_SIGNING_PRIVATE_KEY_B64 or _SERVER_PRIV_KEY
    pub = settings.MANIFEST_SIGNING_PUBLIC_KEY_B64 or _SERVER_PUB_KEY
    return priv, pub


def sign_manifest_payload(payload_dict: Dict[str, Any], private_key_b64: str) -> str:
    """
    Sign canonical JSON bytes of manifest using ED25519 private key.
    Returns Base64 signature string.
    """
    canonical_json_bytes = json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    priv_bytes = base64.b64decode(private_key_b64)
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(priv_bytes)
    signature = private_key.sign(canonical_json_bytes)
    return base64.b64encode(signature).decode("utf-8")


def verify_manifest_signature(payload_dict: Dict[str, Any], signature_b64: str, public_key_b64: str) -> bool:
    """
    Verify canonical JSON manifest payload against an ED25519 signature.
    """
    try:
        canonical_json_bytes = json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
        pub_bytes = base64.b64decode(public_key_b64)
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_bytes)
        signature = base64.b64decode(signature_b64)
        public_key.verify(signature, canonical_json_bytes)
        return True
    except Exception:
        return False
