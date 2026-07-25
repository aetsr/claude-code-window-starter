from __future__ import annotations

import platform
import ssl
import subprocess
from pathlib import Path


def trusted_ssl_context() -> ssl.SSLContext:
    """Build a verified TLS context that also honors trusted macOS Keychain CAs."""
    context = ssl.create_default_context()
    if platform.system() != "Darwin":
        return context

    security = Path("/usr/bin/security")
    if not security.is_file():
        return context

    # Python.org and Homebrew builds do not always inherit Apple's system root
    # store. Import only Apple's immutable roots; do not trust arbitrary
    # certificates merely because they are present in a user's login Keychain.
    keychain = Path("/System/Library/Keychains/SystemRootCertificates.keychain")
    if not keychain.is_file():
        return context
    process = subprocess.run(
        [str(security), "find-certificate", "-a", "-p", str(keychain)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        shell=False,
    )
    if process.returncode == 0 and "BEGIN CERTIFICATE" in process.stdout:
        context.load_verify_locations(cadata=process.stdout)
    return context
