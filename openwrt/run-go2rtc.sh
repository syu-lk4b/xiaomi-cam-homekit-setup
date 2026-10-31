#!/usr/bin/env bash
# Create the go2rtc container on the OpenWrt router (docker commands only).
set -euo pipefail

usage() { echo "usage: ROUTER_HOST=root@<ROUTER_IP> $0   (see .env.example)"; }
[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && { usage; exit 0; }

: "${ROUTER_HOST:?$(usage)}"
GO2RTC_IMAGE="${GO2RTC_IMAGE:-docker.m.daocloud.io/alexxit/go2rtc:1.9.15}"

# --restart no until it has proven stable; --memory is omitted (no memory cgroup on this kernel)
ssh "${ROUTER_HOST}" "docker pull '${GO2RTC_IMAGE}' && docker run -d --name go2rtc \
  --network host --restart no --cpus=1 \
  --device /dev/dri:/dev/dri \
  -v /opt/go2rtc:/config \
  '${GO2RTC_IMAGE}'"
