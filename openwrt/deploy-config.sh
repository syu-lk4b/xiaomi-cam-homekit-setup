#!/usr/bin/env bash
# Push go2rtc/go2rtc.yaml into the running container and restart it.
set -euo pipefail

usage() { echo "usage: ROUTER_HOST=root@<ROUTER_IP> $0   (see .env.example)"; }
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { usage; exit 0; }

: "${ROUTER_HOST:?$(usage)}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f "${REPO_ROOT}/go2rtc/go2rtc.yaml" ]] || { echo "missing go2rtc/go2rtc.yaml" >&2; exit 1; }

# macOS tar adds xattrs/AppleDouble files that make `docker cp -` fail
COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata --uid 0 --gid 0 \
  -cf - -C "${REPO_ROOT}/go2rtc" go2rtc.yaml \
  | ssh "${ROUTER_HOST}" 'docker cp - go2rtc:/config/ && docker restart go2rtc'
