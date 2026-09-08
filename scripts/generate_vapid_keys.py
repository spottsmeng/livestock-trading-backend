"""One-off VAPID key pair generator for Web Push (§10). Run once per
environment and paste the output into .env — never commit real keys.

Run with: uv run python -m scripts.generate_vapid_keys
"""

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02


def main() -> None:
    vapid = Vapid02()
    vapid.generate_keys()

    private_raw = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962, format=serialization.PublicFormat.UncompressedPoint
    )

    def b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    print("Add these to backend/.env:")
    print(f"VAPID_PUBLIC_KEY={b64url(public_raw)}")
    print(f"VAPID_PRIVATE_KEY={b64url(private_raw)}")
    print()
    print("The public key also needs to reach the frontend's PushManager.subscribe() call —")
    print("set NEXT_PUBLIC_VAPID_PUBLIC_KEY in frontend/.env.local to the same VAPID_PUBLIC_KEY value.")


if __name__ == "__main__":
    main()
