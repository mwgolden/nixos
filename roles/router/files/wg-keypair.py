"""Writes a WireGuard key pair: <prefix>.key (private, mode 0600) and
<prefix>.pub. Leaves an existing pair alone, so keys survive redeploys.

    python wg-keypair.py secrets/lab/vpn/router

Run by roles/router on the machine running Ansible, with Ansible's own
Python, which has the cryptography package. Gives the same keys as
'wg genkey | tee key | wg pubkey'.
"""

import base64
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey


def main(prefix):
    if os.path.exists(prefix + ".key"):
        return
    raw = bytearray(os.urandom(32))
    # Clamp the key the way 'wg genkey' does.
    raw[0] &= 248
    raw[31] &= 127
    raw[31] |= 64
    key = X25519PrivateKey.from_private_bytes(bytes(raw))
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    fd = os.open(prefix + ".key", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(base64.b64encode(bytes(raw)).decode() + "\n")
    with open(prefix + ".pub", "w") as f:
        f.write(base64.b64encode(public).decode() + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
