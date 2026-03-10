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
  - 实时监控矩阵
  - 每卡复制（快速克隆视频卡）
  - MQTT Topic 一键复制
  - 多语言切换（右上角）
- 与 Home Assistant 集成：
  - MQTT Discovery 自动创建设备实体
  - 发布手势结果（gesture / confidence / model / source_id）

## 2. 环境要求

- Python 3.10+（建议 3.11）
- 系统可访问视频源（本地摄像头或 RTSP）
- 如需 HA 联动：可访问 MQTT Broker + Home Assistant 已启用 MQTT Integration

## 3. 快速启动

### 3.1 Windows PowerShell

```powershell
cd gesture-yolo-ha
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

## 4. 配置说明（.env）

- `HOST` / `PORT`：FastAPI 监听地址
- `MODEL_DIR`：模型目录，默认 `models`
- `MODEL_FILE`：启动模型名，支持 `.pt` 文件名或 `mediapipe_hands`
- `SOURCE`：默认视频源（`0` / `rtsp://...` / `auto`）
- `CONF` / `IOU` / `IMG_SIZE` / `DETECT_INTERVAL`：识别参数
- `MQTT_HOST` / `MQTT_PORT` / `MQTT_USER` / `MQTT_PASSWORD`
- `MQTT_CLIENT_ID` / `MQTT_DISCOVERY_PREFIX` / `MQTT_STATE_TOPIC`

`SOURCE=auto` 时会用以下参数拼接 RTSP：

- `RTSP_HOST`
- `RTSP_USER`
- `RTSP_PASSWORD`
- `RTSP_PATH`

## 5. Web 管理界面

- 右上角语言切换：中文 / English / Русский
- 支持新增视频源、模型上传、全局模型切换
- 每个视频卡支持独立模型、标签、名称、克隆、删除

说明：前端已加入“待保存状态保护”，轮询刷新不会覆盖你正在输入/选择的内容。

## 6. Home Assistant 集成

服务启动后自动发布 MQTT Discovery。

每个视频源状态包含：

- `gesture`
- `confidence`
- `model`
- `timestamp`
- `source_id`

你可以在 HA Dashboard 直接添加对应实体。

## 7. 常用 API

- `GET /api/status`
- `GET /api/models`
- `POST /api/models/upload`
- `POST /api/models/activate`
- `GET /api/sources`
- `POST /api/sources`
- `PUT /api/sources/{source_id}`
- `DELETE /api/sources/{source_id}`
- `GET /snapshot/{source_id}.jpg`
- `GET /api/mqtt` / `PUT /api/mqtt` / `POST /api/mqtt/test`

## 8. 自动发布与自动部署

### 8.1 GitHub Release

- 推送标签 `v*`（例如 `v1.0.0`）会自动创建 GitHub Release
- 工作流：`.github/workflows/release.yml`

### 8.2 Push 自动同步服务器

- 推送到 `main` 会触发自动部署
- 工作流：`.github/workflows/deploy.yml`
- 需要配置仓库 Secrets：
  - `DEPLOY_HOST`
  - `DEPLOY_USER`
  - `DEPLOY_PASSWORD`
  - `DEPLOY_PORT`（可选，默认 22）
  - `DEPLOY_PATH`（例如 `/home/linaro/gesture-yolo-ha`）
  - `DEPLOY_SERVICE`（例如 `gesture-yolo-ha.service`）
