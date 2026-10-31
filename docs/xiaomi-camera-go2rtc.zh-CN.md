# 小米摄像头接入 HA / HomeKit（go2rtc）

[English](xiaomi-camera-go2rtc.md) | 简体中文

更新：2026-10-31

## 目标与结果

| 摄像头 | 型号 | 米家 | HA | HomeKit | 结论 |
|---|---|---|---|---|---|
| 小米云台摄像头 | `chuangmi.camera.ipc009`，fw 4.0.9，IP <CAM_IP> | 不变 | ✅ `camera.xiaomi_ptz` | ✅ 单配件模式（待配对） | 通过 go2rtc 接入 |
| 小蚁摄像机 | `yunyi.camera.v1`（Yi Home 17CN），fw 1.8.7.0C_201705091058，IP <YI_CAM_IP> | 不变 | ❌ | ❌ | go2rtc 报 `unsupported model`，见末尾 |

录像回看：不做（不需要 Surveillance Station）。

## 架构

```
ipc009 ──(TUTK P2P, 局域网 UDP)──> go2rtc @ OpenWrt <ROUTER_IP> (Docker)
                                     │  ↑ 每次连接都要从小米云取密钥（需外网）
                                     ├─ rtsp://<ROUTER_IP>:8554/ipc009       原始 HEVC 1080p + G.711
                                     ├─ rtsp://<ROUTER_IP>:8554/ipc009_h264  VAAPI 转码 H.264 + AAC
                                     └─ http://<ROUTER_IP>:1984/api/frame.jpeg?src=ipc009
HA (Docker @ 同一台 OpenWrt, <HA_IP>)
  └─ Generic Camera: camera.xiaomi_ptz（流用 ipc009_h264，截图用 frame.jpeg）
       ├─ neon-panel 总览 → CAMERAS 区「小米云台」卡片
       └─ HomeKit 单配件模式 → 家庭 App
```

## 1. 小米账号登录（扫码，绕开短信验证）

go2rtc 自带的「用户名+密码+短信验证」登录有缺陷（上游 issue #2237 未修），所以改用扫码登录拿 `passToken`：

```sh
cp go2rtc/go2rtc.example.yaml go2rtc/go2rtc.yaml   # 先填好 <...> 占位符
python3 -m pip install -r go2rtc/requirements.txt
python3 go2rtc/xiaomi_qr_login.py          # 默认写入 go2rtc/go2rtc.yaml
GO2RTC_CONFIG=/path/go2rtc.yaml python3 go2rtc/xiaomi_qr_login.py
```

- 用米家 App「我的 → 右上角扫一扫」扫弹出的二维码，并在手机上确认。
- 脚本会先按 go2rtc 的方式验证 token，通过后才写入 `xiaomi:` 段。token 不会打印出来，文件权限设为 600。
- 长轮询的超时要大于服务器挂起时间（约 70 秒）。早先用 10 秒超时，结果扫码成功但脚本没收到。
- 小米账号 userId 写在 `<XIAOMI_USER_ID>` 处，国内账号区域填 `cn`。摄像头 did 可在米家 App 设备信息或 HA xiaomi_home 集成里查到。
- **token 过期**：go2rtc 不会自动重新登录（上游 PR #2492 还没合并）。出现 401 时，先重启容器；不行就重新扫码。

## 2. go2rtc 部署（OpenWrt Docker）

主机：OpenWrt 24.10.3 x86/64，Celeron 6305（2 核），16GB 内存，Intel Xe 核显（`/dev/dri/renderD128`），Docker 数据目录 `/opt/docker`。

```sh
# Docker Hub 在国内连不上，改用 daocloud 镜像源（不稳定，失败多重试几次）
docker pull docker.m.daocloud.io/alexxit/go2rtc:1.9.15

docker run -d --name go2rtc \
  --network host \
  --restart no \
  --cpus=1 \
  --device /dev/dri:/dev/dri \
  -v /opt/go2rtc:/config \
  docker.m.daocloud.io/alexxit/go2rtc:1.9.15
```

- 配置文件是 `/opt/go2rtc/go2rtc.yaml`，模板见 [go2rtc/go2rtc.example.yaml](../go2rtc/go2rtc.example.yaml)。
- 修改配置的方法（只用 docker 命令；从 Mac 打 tar 包时要加 `--no-xattrs`，否则 `docker cp` 会报错）：
  ```sh
  COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata --uid 0 --gid 0 -cf - -C go2rtc go2rtc.yaml \
    | ssh root@<ROUTER_IP> 'docker cp - go2rtc:/config/ && docker restart go2rtc'
  ```
- 用普通版镜像，不用 `-hardware` 版：普通的 Alpine 镜像里已经带了 iHD/i965 驱动，支持 vaapi 和 qsv。
- `--memory` 在这个内核上无效：内核没有内存 cgroup，Docker 会提示后忽略。
- `--restart no` 是临时的。观察稳定后，改成 `docker update --restart unless-stopped go2rtc`。
- RTSP 监听在 `:8554`（所有网卡）：go2rtc 内部的 ffmpeg 要从 127.0.0.1 读流。WAN 口有防火墙挡着，但 VPN 区域（Tailscale/ipsec）允许入站，所以 API 和 RTSP 都要设用户名和密码（见模板）。
- ⚠️ **API 一定要加密码**：`/api/config` 会原样返回整个配置文件，里面就有 passToken。不加密码，局域网里谁都能拿到小米账号的 token。
- 自带的 `#hardware=vaapi` 模板在这台机器上会报 `hwupload: A hardware device reference is required`，所以 `ipc009_h264` 改用 `exec:ffmpeg`，并显式加上 `-hwaccel_device`。

### 实测性能

| 项目 | 结果 |
|---|---|
| 原始流转发 | go2rtc CPU < 1%，60 秒 1142 帧（约 19 fps） |
| VAAPI 转码 HEVC → H.264 | 1.03 倍实时，容器 CPU 3–6% |
| 冷启动出第一帧 | 截图约 6–7 秒，HA HLS 约 8 秒 |
| 码率 | 原始流夜间约 1.5MB/分钟；H.264 设为 2Mbps |

## 3. Home Assistant

- 集成：Generic Camera（标题「小米云台摄像头」）。
  - Stream source：`rtsp://<GO2RTC_USER>:<GO2RTC_PASSWORD>@<ROUTER_IP>:8554/ipc009_h264`，RTSP over TCP
  - Still image：`http://<ROUTER_IP>:1984/api/frame.jpeg?src=ipc009`，帧率 2，用户名/密码填在 Generic Camera 的 username/password 字段（basic auth）
  - 实体：`camera.xiaomi_ptz`，前端支持 WebRTC 和 HLS
  - ⚠️ 添加时 HA 会在 10 秒内校验流。冷启动太慢会报 `timeout`，先在路由器上用 `docker exec go2rtc ffmpeg -i rtsp://127.0.0.1:8554/ipc009_h264 -c copy -f null -` 把流预热。
- neon-panel（`/neon-panel/overview`）：在 CAMERAS 区 ESP32-CAM 下方加了一张 `picture-entity` 卡片，名字是「小米云台」。卡片样式照搬 ESP32-CAM（card_mod 霓虹风格）。
- 原有的 xiaomi_home 设备保持不变，继续负责控制类实体（云台、开关等）。

## 4. HomeKit

- HomeKit 集成，单配件模式（标题 `HomeKit-小米云台`），端口由 HA 自动分配。
- 选项：`camera_copy`（视频直接转发，不转码）+ `camera_audio`（AAC 转 Opus）。
- 配对：二维码和配对码在 HA 通知「HomeKit Pairing」里。
- 中文名在 HomeKit 里会被过滤成乱码（`Q9`），配对后在家庭 App 里改名。
- ⚠️ 坑：在 HomeKit 添加向导里选择 `camera` 域时，HA 会：
  - 给**所有**还没接入单配件模式的摄像头各建一个配件；
  - 再建一个**空过滤条件的桥接器**，这等于把全部实体暴露给 HomeKit。

  这次多出来的 P1S 摄像头配件和空桥接器，已经用 REST `DELETE /api/config/config_entries/entry/<id>` 删掉了。这个版本的 HA 不支持 WebSocket 命令 `config_entries/remove`。

## 5. 踩过的坑（排查记录）

1. **小米风控 20024「用户行为被限制」**：短时间内多次尝试密码 + 短信登录会触发。等一段时间会自动解除，扫码登录不受影响。
2. **从浏览器复制的 passToken 无效**：它和浏览器的 deviceId 绑定在一起，go2rtc 用不了。
3. **Mac 上测试连不上局域网**：
   - 全局 VPN 开着的时候，流量全走 VPN，局域网不通；
   - 从后台守护进程（launchd）启动的终端里，macOS 的「本地网络」隐私权限会拦掉非苹果程序发往局域网的包（报 `sendto: no route to host`），`curl`/`nc` 这类系统程序不受影响。所以 go2rtc 要在 Terminal/iTerm 里手动启动，而且要允许本地网络访问。
4. **go2rtc TUTK 握手只发一包**：`pkg/tutk/session0.go` 的 `writeAndWait` 里，`AfterFunc(1, …)` 读到的 `t` 还是 nil，所以不会重发。测试时发现官方版也能连上，所以没有改代码；Wi-Fi 不稳的时候可能会有影响。
5. **偶发 `read media: EOF` 或首连超时**：容器重建、或者刚连续失败过几次之后，摄像头会短暂拒绝新连接，过一会儿自己恢复。
6. **OpenWrt 死机（2026-10-31）**：
   - 经过：拉取 1.15GB 的 `-hardware` 镜像后，紧接着 `docker run`，路由器卡死，只能断电重启。原因不明：OpenWrt 的日志只存在内存里，重启后就没了。
   - 后续：同样的参数（`/dev/dri`、`--cpus`、`--memory`）换普通版镜像，没能复现。
   - 后遗症：
     - 解压到一半的镜像层变成了 0 字节。containerd 的 snapshot 在 `docker rmi` 之后仍然保留，重新拉取还会复用这些坏数据。
     - `/opt/go2rtc/go2rtc.yaml` 也被写成了全 0。
   - 坏掉的 `-hardware` 镜像还占着约 1GB，可以用 `ctr -a /var/run/docker/containerd/containerd.sock -n moby leases ls` 排查残留的租约。
   - **规则：路由器上只允许执行 docker 命令，改动前要先征得同意。**

## 6. 小蚁 yunyi.camera.v1（Yi Home 17CN）

- go2rtc 不支持：小米云返回的是小蚁自己的协议，go2rtc 直接报 `unsupported model`，它的支持列表（issue #1982）里也没有这个型号。
- 唯一的出路是刷 yi-hack，开启 RTSP：
  - 这台的固件 `1.8.7.0C_201705091058` 正好是 yi-hack-v3 列出的 17CN 基线版本。
  - 但这个版本的固件不允许从 SD 卡运行脚本，要降级到 1.8.6C，社区说法是**可能需要拆机焊串口**。
  - 刷完后官方 App（米家/小蚁）大概率不能用了。
- 建议：继续只在米家里用；想接 HA 和 HomeKit，就换一台 go2rtc 已验证支持的型号（C200/C300/C400、云台 2/3 等 cs2 协议机型）。

## 待办

- [ ] 在家庭 App 里配对 `HomeKit-小米云台`，然后改名。
- [ ] 观察 1–2 天，然后 `docker update --restart unless-stopped go2rtc`。
- [ ] passToken 过期的处理：定时重启容器，或者等上游 PR #2492 合并。
- [ ] （可选）清理坏掉的 `-hardware` 镜像，需要用 `ctr`。

## 参考

- go2rtc Xiaomi 源：https://github.com/AlexxIT/go2rtc/tree/master/internal/xiaomi
- 支持型号：https://github.com/AlexxIT/go2rtc/issues/1982
- 登录 401 问题：https://github.com/AlexxIT/go2rtc/issues/2237
- 自动重新登录 PR：https://github.com/AlexxIT/go2rtc/pull/2492
- 扫码登录流程参考：https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor
- 17CN 刷机：https://github.com/shadow-1/yi-hack-v3 、https://github.com/naveednajam/17CN-Yi-Home-Recovery
