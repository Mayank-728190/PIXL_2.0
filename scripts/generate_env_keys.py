"""
PIXL 2.0 Environment Keys Generator
Generates production-grade cryptographic secrets and ED25519 signing keys.
"""

import base64
import secrets
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

def generate_keys():
    # 1. 32-byte random hex secret key for sessions and tokens
    secret_key = secrets.token_hex(32)

    # 2. ED25519 Asymmetric Keypair for offline manifest signing
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    priv_raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption()
    )
    pub_raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw
    )

    priv_b64 = base64.b64encode(priv_raw).decode('utf-8')
    pub_b64 = base64.b64encode(pub_raw).decode('utf-8')

    print("==================================================================")
    print("           PIXL 2.0 PRODUCTION CRYPTOGRAPHIC SECRETS            ")
    print("==================================================================")
    print(f"SECRET_KEY={secret_key}")
    print()
    print(f"MANIFEST_SIGNING_PRIVATE_KEY_B64={priv_b64}")
    print(f"MANIFEST_SIGNING_PUBLIC_KEY_B64={pub_b64}")
    print("==================================================================")
    print("Copy the values above into your .env file.")

if __name__ == "__main__":
    generate_keys()

