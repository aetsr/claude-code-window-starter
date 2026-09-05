#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# This launcher is placed at the root of the downloadable installer archive.
if ! /bin/bash "$ROOT/scripts/install-macos.sh"; then
  echo "Installation did not finish. Read the error above and INSTALL.md."
  read -r -p "Press Return to close. " _reply
  exit 1
fi
