# Xiaomi Cameras in HA / HomeKit (go2rtc)

English | [简体中文](xiaomi-camera-go2rtc.zh-CN.md)

Updated: 2026-10-31

## Goals and results

| Camera | Model | Mi Home | HA | HomeKit | Outcome |
|---|---|---|---|---|---|
| Xiaomi PTZ camera | `chuangmi.camera.ipc009`, fw 4.0.9, IP <CAM_IP> | unchanged | ✅ `camera.xiaomi_ptz` | ✅ accessory mode (pending pairing) | works via go2rtc |
| Yi camera | `yunyi.camera.v1` (Yi Home 17CN), fw 1.8.7.0C_201705091058, IP <YI_CAM_IP> | unchanged | ❌ | ❌ | go2rtc reports `unsupported model`, see the end |

Recording / playback: out of scope (no Surveillance Station).

## Architecture

```
ipc009 ──(TUTK P2P, LAN UDP)──> go2rtc @ OpenWrt <ROUTER_IP> (Docker)
                                     │  ↑ each connection fetches keys from Xiaomi cloud (needs internet)
                                     ├─ rtsp://<ROUTER_IP>:8554/ipc009       raw HEVC 1080p + G.711
                                     ├─ rtsp://<ROUTER_IP>:8554/ipc009_h264  VAAPI-transcoded H.264 + AAC
                                     └─ http://<ROUTER_IP>:1984/api/frame.jpeg?src=ipc009
HA (Docker on the same OpenWrt box, <HA_IP>)
  └─ Generic Camera: camera.xiaomi_ptz (stream = ipc009_h264, snapshot = frame.jpeg)
       ├─ neon-panel overview → "Xiaomi PTZ" card in the CAMERAS section
       └─ HomeKit accessory mode → Apple Home
```

## 1. Xiaomi account login (QR code, skips SMS verification)

go2rtc's built-in "username + password + SMS code" login is broken (upstream issue #2237, still open), so a QR-code login is used to obtain the `passToken`:

```sh
cp go2rtc/go2rtc.example.yaml go2rtc/go2rtc.yaml   # fill in the <...> placeholders first
python3 -m pip install -r go2rtc/requirements.txt
python3 go2rtc/xiaomi_qr_login.py          # writes to go2rtc/go2rtc.yaml by default
GO2RTC_CONFIG=/path/go2rtc.yaml python3 go2rtc/xiaomi_qr_login.py
```

- In the Mi Home app go to "Profile → scan icon (top right)", scan the QR code that pops up, then confirm on the phone.
- The script first validates the token the same way go2rtc does, and only writes the `xiaomi:` section if it passes. The token is never printed and the file is set to mode 600.
- The long-poll timeout must exceed how long the server holds the request (~70 s). An earlier 10 s timeout meant the scan succeeded on the phone but the script never saw it.
- Put the Xiaomi account userId at `<XIAOMI_USER_ID>`; use region `cn` for mainland China accounts. The camera did is shown in the Mi Home device info page or in HA's xiaomi_home integration.
- **Token expiry**: go2rtc does not re-login automatically (upstream PR #2492 not merged yet). On a 401, restart the container first; if that doesn't help, scan again.

## 2. go2rtc deployment (OpenWrt Docker)

Host: OpenWrt 24.10.3 x86/64, Celeron 6305 (2 cores), 16 GB RAM, Intel Xe iGPU (`/dev/dri/renderD128`), Docker data root `/opt/docker`.

```sh
# Docker Hub is unreachable from mainland China; use the daocloud mirror (flaky, retry on failure)
docker pull docker.m.daocloud.io/alexxit/go2rtc:1.9.15

docker run -d --name go2rtc \
  --network host \
  --restart no \
  --cpus=1 \
  --device /dev/dri:/dev/dri \
  -v /opt/go2rtc:/config \
  docker.m.daocloud.io/alexxit/go2rtc:1.9.15
```

- Config file: `/opt/go2rtc/go2rtc.yaml`; template: [go2rtc/go2rtc.example.yaml](../go2rtc/go2rtc.example.yaml).
- Updating the config (docker commands only; when building the tar on a Mac add `--no-xattrs`, otherwise `docker cp` fails):
  ```sh
  COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata --uid 0 --gid 0 -cf - -C go2rtc go2rtc.yaml \
    | ssh root@<ROUTER_IP> 'docker cp - go2rtc:/config/ && docker restart go2rtc'
  ```
- Use the regular image, not `-hardware`: the regular Alpine image already ships the iHD/i965 drivers and supports vaapi and qsv.
- `--memory` has no effect on this kernel: there is no memory cgroup, so Docker warns and ignores it.
- `--restart no` is temporary. Once it has proven stable, switch to `docker update --restart unless-stopped go2rtc`.
- RTSP listens on `:8554` (all interfaces) because go2rtc's own ffmpeg reads the stream from 127.0.0.1. The WAN port is firewalled, but the VPN zones (Tailscale/ipsec) accept inbound traffic, so set a username and password on both the API and RTSP (see the template).
- ⚠️ **Always password-protect the API**: `/api/config` returns the whole config file verbatim, passToken included. Without a password, anyone on the LAN can read the Xiaomi account token.
- The built-in `#hardware=vaapi` template fails on this machine with `hwupload: A hardware device reference is required`, so `ipc009_h264` uses `exec:ffmpeg` with an explicit `-hwaccel_device`.

### Measured performance

| Item | Result |
|---|---|
| Raw stream passthrough | go2rtc CPU < 1%, 1142 frames in 60 s (~19 fps) |
| VAAPI transcode HEVC → H.264 | 1.03× realtime, container CPU 3–6% |
| Cold start to first frame | snapshot ~6–7 s, HA HLS ~8 s |
| Bitrate | raw stream ~1.5 MB/min at night; H.264 set to 2 Mbps |

## 3. Home Assistant

- Integration: Generic Camera (title "小米云台摄像头").
  - Stream source: `rtsp://<GO2RTC_USER>:<GO2RTC_PASSWORD>@<ROUTER_IP>:8554/ipc009_h264`, RTSP over TCP
  - Still image: `http://<ROUTER_IP>:1984/api/frame.jpeg?src=ipc009`, frame rate 2; put the credentials in the Generic Camera username/password fields (basic auth)
  - Entity: `camera.xiaomi_ptz`; the frontend supports WebRTC and HLS
  - ⚠️ When adding the camera, HA validates the stream within 10 s. A slow cold start fails with `timeout`; warm the stream up first on the router with `docker exec go2rtc ffmpeg -i rtsp://127.0.0.1:8554/ipc009_h264 -c copy -f null -`.
- neon-panel (`/neon-panel/overview`): added a `picture-entity` card named "小米云台" below the ESP32-CAM in the CAMERAS section, styled like the ESP32-CAM card (card_mod neon style).
- The existing xiaomi_home device is left unchanged and keeps providing the control entities (PTZ, switches, etc.).

## 4. HomeKit

- HomeKit integration in accessory mode (title `HomeKit-小米云台`); the port is assigned by HA.
- Options: `camera_copy` (pass video through without transcoding) + `camera_audio` (AAC → Opus).
- Pairing: the QR code and setup code are in the HA notification "HomeKit Pairing".
- Chinese names get filtered into garbage in HomeKit (`Q9`); rename the accessory in the Home app after pairing.
- ⚠️ Gotcha: when you pick the `camera` domain in the HomeKit setup flow, HA will:
  - create an accessory for **every** camera not already in accessory mode;
  - also create a **bridge with an empty filter**, which exposes every entity to HomeKit.

  The extra P1S camera accessory and the empty bridge created this time were removed via REST `DELETE /api/config/config_entries/entry/<id>`. This HA version does not support the WebSocket command `config_entries/remove`.

## 5. Pitfalls (troubleshooting log)

1. **Xiaomi risk control 20024 "user behavior restricted"**: triggered by repeated password + SMS login attempts in a short time. It clears by itself after a while; QR login is not affected.
2. **A passToken copied from the browser doesn't work**: it is bound to the browser's deviceId, so go2rtc can't use it.
3. **LAN unreachable when testing on a Mac**:
   - with a full-tunnel VPN on, all traffic goes through the VPN and the LAN is unreachable;
   - in a terminal spawned by a background daemon (launchd), macOS Local Network privacy blocks LAN packets from non-Apple binaries (`sendto: no route to host`), while system tools like `curl`/`nc` are unaffected. Start go2rtc manually in Terminal/iTerm and allow Local Network access.
4. **go2rtc TUTK handshake sends only one packet**: in `writeAndWait` in `pkg/tutk/session0.go`, the `t` read inside `AfterFunc(1, …)` is still nil, so nothing is resent. The official build still connected in testing, so the code was left unchanged; it may matter on flaky Wi-Fi.
5. **Occasional `read media: EOF` or first-connect timeout**: after the container is recreated, or after several failed attempts in a row, the camera briefly refuses new connections and recovers by itself.
6. **OpenWrt froze (2026-10-31)**:
   - What happened: right after pulling the 1.15 GB `-hardware` image, `docker run` froze the router and it had to be power-cycled. Cause unknown: OpenWrt keeps logs in RAM only, so they were lost on reboot.
   - Follow-up: the same flags (`/dev/dri`, `--cpus`, `--memory`) with the regular image did not reproduce it.
   - Aftermath:
     - half-unpacked image layers became zero-byte files. The containerd snapshots survive `docker rmi`, and a re-pull reuses the corrupt data.
     - `/opt/go2rtc/go2rtc.yaml` was also overwritten with zeros.
   - The broken `-hardware` image still takes ~1 GB; inspect leftover leases with `ctr -a /var/run/docker/containerd/containerd.sock -n moby leases ls`.
   - **Rule: only docker commands on the router, and ask before every change.**

## 6. Yi yunyi.camera.v1 (Yi Home 17CN)

- Not supported by go2rtc: Xiaomi cloud returns Yi's own protocol, go2rtc reports `unsupported model`, and the model is not on its support list (issue #1982).
- The only way is flashing yi-hack to enable RTSP:
  - this unit's firmware `1.8.7.0C_201705091058` is exactly the 17CN baseline listed by yi-hack-v3;
  - but this firmware refuses to run scripts from the SD card, so it needs a downgrade to 1.8.6C, which according to the community **may require opening the case and soldering a serial adapter**;
  - after flashing, the official apps (Mi Home / Yi) most likely stop working.
- Recommendation: keep it in Mi Home only; for HA and HomeKit, replace it with a model go2rtc is verified to support (C200/C300/C400, PTZ 2/3 and other cs2-protocol models).

## TODO

- [ ] Pair `HomeKit-小米云台` in the Home app, then rename it.
- [ ] Watch it for 1–2 days, then `docker update --restart unless-stopped go2rtc`.
- [ ] Handle passToken expiry: restart the container periodically, or wait for upstream PR #2492.
- [ ] (Optional) Remove the broken `-hardware` image; needs `ctr`.

## References

- go2rtc Xiaomi source: https://github.com/AlexxIT/go2rtc/tree/master/internal/xiaomi
- Supported models: https://github.com/AlexxIT/go2rtc/issues/1982
- Login 401 issue: https://github.com/AlexxIT/go2rtc/issues/2237
- Auto re-login PR: https://github.com/AlexxIT/go2rtc/pull/2492
- QR login flow reference: https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor
- 17CN flashing: https://github.com/shadow-1/yi-hack-v3, https://github.com/naveednajam/17CN-Yi-Home-Recovery
