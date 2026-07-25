from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone

from .io_utils import atomic_write_json
from .paths import AppPaths
from .usage import normalized_rate_limits


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--home", required=True)
    args = parser.parse_args()
    try:
        payload = json.loads(sys.stdin.read(1024 * 1024))
    except (json.JSONDecodeError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    rate_limits = normalized_rate_limits(payload.get("rate_limits"))
    if rate_limits is None:
        return 0
    paths = AppPaths.discover(args.home)
    paths.ensure()
    atomic_write_json(
        paths.usage_status_file,
        {
            "schema_version": 1,
            "source": "claude_statusline",
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "captured_at_epoch": time.time(),
            "claude_cli_version": payload.get("version"),
            "rate_limits": rate_limits,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
