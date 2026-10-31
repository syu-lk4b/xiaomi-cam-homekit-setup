# homelab-config

Home lab setup notes and configs: OpenWrt, Home Assistant, HomeKit, go2rtc cameras.

Current content: Xiaomi camera → Home Assistant & HomeKit via go2rtc on OpenWrt Docker, with VAAPI H.265→H.264 transcoding and QR-code Mi login.

## Architecture

```
Xiaomi cam ──(TUTK P2P, LAN UDP)──> go2rtc (Docker on OpenWrt, Intel iGPU)
                                      ├─ rtsp://<ROUTER_IP>:8554/ipc009       raw HEVC + G.711
                                      ├─ rtsp://<ROUTER_IP>:8554/ipc009_h264  VAAPI H.264 + AAC
                                      └─ http://<ROUTER_IP>:1984/api/frame.jpeg?src=ipc009
Home Assistant ── Generic Camera ──> dashboard + HomeKit (accessory mode) ──> Apple Home
```

## Layout

| Path | What |
|---|---|
| [docs/xiaomi-camera-go2rtc.md](docs/xiaomi-camera-go2rtc.md) | Full walkthrough (Chinese): login, deploy, HA, HomeKit, pitfalls, measured performance |
| [go2rtc/go2rtc.example.yaml](go2rtc/go2rtc.example.yaml) | go2rtc config template |
| [go2rtc/xiaomi_qr_login.py](go2rtc/xiaomi_qr_login.py) | Xiaomi QR-code login → writes `passToken` into `go2rtc.yaml` |
| [openwrt/run-go2rtc.sh](openwrt/run-go2rtc.sh) | Create the go2rtc container on the router |
| [openwrt/deploy-config.sh](openwrt/deploy-config.sh) | Push `go2rtc.yaml` into the container and restart |

## Setup

```sh
cp .env.example .env && $EDITOR .env          # router SSH target, image
cp go2rtc/go2rtc.example.yaml go2rtc/go2rtc.yaml && $EDITOR go2rtc/go2rtc.yaml   # fill <...> placeholders
python3 -m venv .venv && .venv/bin/pip install -r go2rtc/requirements.txt
.venv/bin/python go2rtc/xiaomi_qr_login.py    # scan with Mi Home app

set -a && . ./.env && set +a
openwrt/run-go2rtc.sh
openwrt/deploy-config.sh
```

Then add a Generic Camera in Home Assistant and expose it through the HomeKit integration in accessory mode — see the doc.

## Secrets

`go2rtc/go2rtc.yaml` (contains the Xiaomi `passToken`) and `.env` are git-ignored. Only templates with `<PLACEHOLDER>` values are committed.

## Placeholders

| Placeholder | Meaning |
|---|---|
| `<ROUTER_IP>` | OpenWrt host running go2rtc |
| `<HA_IP>` | Home Assistant |
| `<CAM_IP>` / `<YI_CAM_IP>` | Camera LAN IPs |
| `<XIAOMI_USER_ID>` | Xiaomi account numeric user ID |
| `<CAMERA_DID>` | Camera device ID from Mi Home |
| `<GO2RTC_USER>` / `<GO2RTC_PASSWORD>` | go2rtc API + RTSP credentials (required: `/api/config` exposes the passToken) |
