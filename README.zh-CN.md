# Gesture YOLO HA（中文文档）

一个面向 Home Assistant 的多路视频手势识别系统，支持 YOLO 与 MediaPipe 模型，支持 MQTT Discovery，支持多语言 Web 管理界面（中文/English/Русский）。

## 1. 功能概览

- 多路视频源管理（USB 摄像头、RTSP）
- 手势识别模型支持：
  - YOLO `.pt` 模型（可上传）
  - `Google MediaPipe` 手势模型（内置）
- 模型切换能力：
  - 全局模型切换
  - 每个视频卡独立模型选择
- Web 控制台：
  - 实时监控矩阵（含在线状态与帧率）
  - 每卡复制（快速克隆视频卡）
  - MQTT Topic 一键复制
  - 多语言切换（右上角）
- 与 Home Assistant 集成：
  - MQTT Discovery 自动创建设备实体
  - 发布手势结果（gesture / confidence / model / source_id）
  - 提供 MJPEG 流，可直接作为 HA 的 `mjpeg` 摄像头实体
- 配置持久化：新增的视频源与 MQTT 设置会保存到 `data/`，重启后自动恢复

## 2. 环境要求

- Python 3.10+（建议 3.11）
- 系统可访问视频源（本地摄像头或 RTSP）
- 如需 HA 联动：可访问 MQTT Broker + Home Assistant 已启用 MQTT Integration

## 3. 快速启动

### 3.1 Windows PowerShell

```powershell
cd gesture-yolo-ha
.\run.ps1
```

`run.ps1` 会自动创建虚拟环境、按需安装依赖、生成 `.env` 并启动服务。

手动方式：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 3.2 Linux / macOS

```bash
cd gesture-yolo-ha
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

访问：`http://127.0.0.1:8000/`

## 4. 安全说明（重要）

上传 `.pt` 模型时，加载过程会**执行文件中的代码**。因此任何能访问本服务端口的人，都可以通过上传并激活恶意模型在你的主机上执行任意代码。

- 在 `.env` 中设置 `API_TOKEN` 即可开启鉴权。所有 `/api`、`/snapshot`、`/stream` 请求都需要携带令牌。
- 令牌可通过 `Authorization: Bearer <token>` 头、`X-API-Token` 头、`?token=` 查询参数或登录后的 Cookie 提供。
- 未设置 `API_TOKEN` 时服务不鉴权，仅建议在完全可信的内网中这样使用（启动日志会有告警）。
- `GET /api/mqtt` 只返回掩码 `********`，不会回传真实的 MQTT 密码。
- 不要把真实凭据写进 `.env.example`；`.env` 已在 `.gitignore` 中。

## 5. 配置说明（.env）

### 基础

- `HOST` / `PORT`：FastAPI 监听地址
- `API_TOKEN`：留空关闭鉴权，设置后启用（强烈建议设置）
- `MAX_UPLOAD_MB`：模型上传大小上限，默认 200

### 识别

- `MODEL_DIR`：模型目录，默认 `models`
- `MODEL_FILE`：启动模型名，支持 `.pt` 文件名或 `mediapipe_hands`
- `SOURCE`：默认视频源（`0` / `rtsp://...` / `auto`）
- `CONF` / `IOU` / `IMG_SIZE` / `DETECT_INTERVAL`：识别参数
- `SHARE_MODELS`：多路摄像头共用同一份已加载的 `.pt` 权重，默认 `true`，可显著降低内存占用

`SOURCE=auto` 时会用以下参数拼接 RTSP：`RTSP_HOST`、`RTSP_PORT`、`RTSP_USER`、`RTSP_PASSWORD`、`RTSP_PATH`。

### 预览性能

- `JPEG_QUALITY`：预览图 JPEG 质量，默认 80，调低可省 CPU 与带宽
- `PREVIEW_WIDTH`：预览缩放宽度，`0` 表示保持原始分辨率
- `PREVIEW_FPS`：预览编码帧率上限，默认 15。**只限制生成 JPEG 的频率，手势识别始终按码流的完整帧率运行**。多路摄像头跑在低配设备上时调低这个值
- `IDLE_ENCODE_TIMEOUT`：无人观看超过该秒数后停止编码预览帧（识别不受影响），默认 15

### MQTT

- `MQTT_HOST` / `MQTT_PORT` / `MQTT_USER` / `MQTT_PASSWORD`
- `MQTT_CLIENT_ID` / `MQTT_DISCOVERY_PREFIX` / `MQTT_STATE_TOPIC`
- `MQTT_KEEPALIVE`：心跳间隔，默认 60
- `MQTT_PUBLISH_MODE`：`change` 仅在手势变化时发布（默认），`always` 每次识别都发布
- `MQTT_HEARTBEAT`：即使手势未变化也至少每 N 秒重发一次，`0` 表示关闭

## 6. Web 管理界面

- 右上角语言切换：中文 / English / Русский
- 支持新增视频源、模型上传、全局模型切换
- 每个视频卡支持独立模型、标签、名称、克隆、删除
- 卡片显示在线状态圆点与实时帧率；点击画面进入 MJPEG 全屏预览

说明：

- 前端已加入"待保存状态保护"，轮询刷新不会覆盖你正在输入/选择的内容。
- Tailwind 已随项目本地分发（`app/static/vendor/`），断网的内网环境也能正常显示。

## 7. Home Assistant 集成

服务启动后自动发布 MQTT Discovery，并带上 availability 主题，HA 中可正确显示"不可用"状态。

每个视频源状态包含：

- `gesture`
- `confidence`
- `model`
- `timestamp`
- `source_id`

### 作为摄像头实体

`/stream/{source_id}.mjpg` 是标准 MJPEG 流，可在 HA 中这样配置：

```yaml
camera:
  - platform: mjpeg
    name: 客厅手势
    mjpeg_url: http://<服务器IP>:8000/stream/cam1.mjpg
```

若启用了 `API_TOKEN`，在 URL 后追加 `?token=<你的令牌>`。

## 8. 常用 API

- `GET /healthz`（无需鉴权，用于健康检查）
- `GET /api/status`
- `GET /api/models`
- `POST /api/models/upload`
- `POST /api/models/activate`
- `DELETE /api/models/{name}`
- `GET /api/sources`
- `POST /api/sources`
- `PUT /api/sources/{source_id}`
- `DELETE /api/sources/{source_id}`
- `GET /snapshot/{source_id}.jpg`
- `GET /stream/{source_id}.mjpg`
- `GET /api/mqtt` / `PUT /api/mqtt` / `POST /api/mqtt/test`
- `POST /api/login`（用令牌换取 Cookie）

## 9. 开发与测试

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

## 10. 自动发布与自动部署

### 10.1 GitHub Release

- 推送标签 `v*`（例如 `v1.0.0`）会自动创建 GitHub Release
- 工作流：`.github/workflows/release.yml`

### 10.2 Push 自动同步服务器

- 推送到 `main` 会触发自动部署，部署后会轮询 `/healthz` 校验服务是否正常
- 工作流：`.github/workflows/deploy.yml`
- 需要配置仓库 Secrets：
  - `DEPLOY_HOST`
  - `DEPLOY_USER`
  - `DEPLOY_PASSWORD`
  - `DEPLOY_PORT`（可选，默认 22）
  - `DEPLOY_PATH`（例如 `/home/linaro/gesture-yolo-ha`）
  - `DEPLOY_SERVICE`（例如 `gesture-yolo-ha.service`）
  - `DEPLOY_HEALTH_PORT`（可选，默认 8000）

systemd 服务示例见 `deploy/gesture-yolo-ha.service`。

## 11. 预览延迟排查

RTSP 画面比现实慢一拍是最常见的问题。延迟可能出在三个地方：摄像机、我们的程序、浏览器。下面先说明程序已经做了什么，再给出定位方法。

### 11.1 程序侧已做的处理

**采集与编码分离。** 每一路视频有三个线程：采集线程只负责 `cap.read()`，拿到帧立刻交给推理线程和预览编码线程，自己马上回去读下一帧。叠加层绘制和 JPEG 编码都不在采集线程上。这一点很关键——如果采集线程被编码拖慢到跟不上码流帧率，帧就会堆积在 FFmpeg 的解码队列里，表现为稳定不变的一秒左右延迟。

**丢帧而不是排队。** 预览编码器还没处理完上一帧时，新帧会直接顶掉它，所以编码永远不会反过来拖慢采集，延迟也不会随时间累积。

**关闭 FFmpeg 输入缓冲。** 默认的抓流参数是：

```
rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|reorder_queue_size;0|max_delay;0|stimeout;5000000
```

需要调整时，在 `.env` 里用 `OPENCV_FFMPEG_CAPTURE_OPTIONS` 整体覆盖。局域网内可以试试改用 UDP 进一步降低延迟，代价是丢包时画面会花：

```bash
OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;udp|fflags;nobuffer|flags;low_delay|max_delay;0
```

### 11.2 用探测脚本定位

`tools/latency_probe.py` 用与程序完全相同的 FFmpeg 参数直接解码，中间没有推理、没有 JPEG 编码、没有 HTTP 和浏览器。剩下的延迟只可能来自摄像机、网络或解码本身。

```bash
python tools/latency_probe.py                     # data/sources.json 里的第一路 RTSP
python tools/latency_probe.py 102                 # 匹配 URL 中含 "102" 的源
python tools/latency_probe.py rtsp://... --headless --seconds 12
```

不加 `--headless` 时会开一个预览窗口，左上角画着实时时钟。**把摄像机对准显示器上的这个窗口**，画面里就会套娃出现一个"视频里的时钟"，它和左上角实时时钟的差值就是完整的端到端延迟。按 `q` 退出。

关键是看输出里的 `read avg`：

- **`read avg` 很大（几十毫秒以上）**：每帧都在等摄像机发数据，瓶颈在摄像机或网络，去看 11.3
- **`read avg` 接近 0**：帧早已排在队列里，瓶颈在我们这侧，调低 `PREVIEW_FPS`、`PREVIEW_WIDTH` 或 `JPEG_QUALITY`
- **`display avg` 很大**：只是预览窗口渲染慢，加 `--headless` 即可排除这项干扰

用 `--headless` 分别测主码流和子码流很能说明问题：如果 1280×720 和 352×288 跑出完全一样的帧率，那就绝不是解码开销的问题，因为高分辨率的解码成本要高十几倍。

### 11.3 摄像机侧检查项

摄像机自身的设置往往才是延迟的大头。以海康为例，在 web 后台检查：

- **曝光时间 / 慢快门**（配置 → 图像 → 显示设置）：**这是最容易被忽略、影响却最大的一项**。光线不足时摄像机会自动拉长曝光来提亮画面，帧率随之减半。曝光 1/12 秒就意味着实际只有 12 fps，每帧还自带 83 毫秒固有延迟并伴有运动拖影。设成 1/50 或更快，若画面变暗则说明现场需要补光
- **I 帧间隔**：设为帧率的 1～2 倍（25 fps 就填 25 或更小），关键帧越密，解码起步和断线重连越快
- **码流平滑**：拖到最靠"清晰"的一端。平滑指的是摄像机把码率摊平输出，代价就是缓冲，直接转化为延迟
- **视频编码**：优先 H.264。H.265 在 CPU 上解码慢得多
- **编码复杂度**：设为"低"。高复杂度会引入跨帧分析，同样增加延迟
- **码流类型**：确认你改的是实际拉流的那一路。海康的 `/Streaming/Channels/101` 是主码流，`/102` 是子码流，改错了不会有任何效果

另外注意分辨率：子码流常见的 352×288（CIF）下 MediaPipe 很难看清手指关节，手势识别会很不稳定。识别效果不好时，把子码流提到 640×480 以上，或者这一路直接改用主码流。

### 11.4 用 VLC 交叉验证

VLC **默认的网络缓存是 1000 毫秒**，直接打开 RTSP 会看到差不多一秒的延迟，容易误判成摄像机的问题。务必关掉缓存：

```bash
vlc --network-caching=0 --rtsp-tcp "rtsp://user:pass@host:554/Streaming/Channels/102"
```

海康官方客户端 iVMS-4200 同理，装完要把「系统配置 → 画面 → 播放性能」改成**最短延时**，否则同样测不准。
