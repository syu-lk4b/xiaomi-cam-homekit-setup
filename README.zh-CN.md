# homelab-config

[English](README.md) | 简体中文

家庭网络的部署笔记和配置：OpenWrt、Home Assistant、HomeKit、go2rtc 摄像头。

目前包含：小米摄像头通过 OpenWrt Docker 上的 go2rtc 接入 Home Assistant 和 HomeKit，使用 VAAPI 硬件把 H.265 转成 H.264，并用米家扫码登录。

## 架构

```
小米摄像头 ──(TUTK P2P，局域网 UDP)──> go2rtc（OpenWrt 上的 Docker，Intel 核显）
                                      ├─ rtsp://<ROUTER_IP>:8554/ipc009       原始 HEVC + G.711
                                      ├─ rtsp://<ROUTER_IP>:8554/ipc009_h264  VAAPI 转码 H.264 + AAC
                                      └─ http://<ROUTER_IP>:1984/api/frame.jpeg?src=ipc009
Home Assistant ── Generic Camera ──> 仪表盘 + HomeKit（单配件模式）──> 家庭 App
```

## 目录

| 路径 | 内容 |
|---|---|
| [docs/xiaomi-camera-go2rtc.md](docs/xiaomi-camera-go2rtc.md) | 完整教程：登录、部署、HA、HomeKit、踩坑记录、实测性能 |
| [go2rtc/go2rtc.example.yaml](go2rtc/go2rtc.example.yaml) | go2rtc 配置模板 |
| [go2rtc/xiaomi_qr_login.py](go2rtc/xiaomi_qr_login.py) | 米家扫码登录，把 `passToken` 写进 `go2rtc.yaml` |
| [openwrt/run-go2rtc.sh](openwrt/run-go2rtc.sh) | 在路由器上创建 go2rtc 容器 |
| [openwrt/deploy-config.sh](openwrt/deploy-config.sh) | 把 `go2rtc.yaml` 推进容器并重启 |

## 安装

```sh
cp .env.example .env && $EDITOR .env          # 路由器 SSH 地址、镜像
cp go2rtc/go2rtc.example.yaml go2rtc/go2rtc.yaml && $EDITOR go2rtc/go2rtc.yaml   # 填好 <...> 占位符
python3 -m venv .venv && .venv/bin/pip install -r go2rtc/requirements.txt
.venv/bin/python go2rtc/xiaomi_qr_login.py    # 用米家 App 扫码

set -a && . ./.env && set +a
openwrt/run-go2rtc.sh
openwrt/deploy-config.sh
```

然后在 Home Assistant 里添加 Generic Camera，再用 HomeKit 集成以单配件模式暴露出去，详见文档。

## 密钥

`go2rtc/go2rtc.yaml`（含小米 `passToken`）和 `.env` 已加入 git 忽略，仓库里只提交带 `<占位符>` 的模板。

## 占位符

| 占位符 | 含义 |
|---|---|
| `<ROUTER_IP>` | 运行 go2rtc 的 OpenWrt 主机 |
| `<HA_IP>` | Home Assistant |
| `<CAM_IP>` / `<YI_CAM_IP>` | 摄像头的局域网 IP |
| `<XIAOMI_USER_ID>` | 小米账号的数字 ID |
| `<CAMERA_DID>` | 米家里的摄像头设备 ID |
| `<GO2RTC_USER>` / `<GO2RTC_PASSWORD>` | go2rtc API 和 RTSP 的账号密码（`/api/config` 会返回 passToken，所以 API 必须设密码） |
