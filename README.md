# Gesture YOLO HA

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

## 2. 目录结构

```text
gesture-yolo-ha/
├─ app/
│  ├─ main.py              # FastAPI 主服务与 API
│  ├─ detector.py          # YOLO / MediaPipe 推理服务
│  ├─ mqtt_bridge.py       # MQTT Discovery 与状态发布
│  ├─ config.py            # 环境变量配置加载
│  └─ static/index.html    # Web 管理界面
├─ models/                 # YOLO 模型目录（*.pt）
├─ requirements.txt
├─ .env.example
└─ README.md
```

## 3. 环境要求

- Python 3.10+（建议 3.11）
- 系统可访问视频源（本地摄像头或 RTSP）
- 如需 HA 联动：可访问 MQTT Broker + Home Assistant 已启用 MQTT Integration

## 4. 本地运行

### 4.1 Windows PowerShell

```powershell
cd gesture-yolo-ha
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 4.2 Linux / macOS

```bash
cd gesture-yolo-ha
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

打开：`http://127.0.0.1:8000/`

## 5. 配置说明（.env）

以下是常用配置：

- `HOST` / `PORT`：FastAPI 监听地址
- `MODEL_DIR`：模型目录，默认 `models`
- `MODEL_FILE`：启动时模型名。支持：
  - `.pt` 文件名（如 `best.pt`）
  - `mediapipe_hands`
- `SOURCE`：默认视频源。可填：
  - `0`（本地摄像头）
  - 完整 `rtsp://...`
  - `auto`（由 RTSP_* 拼接）
- `CONF` / `IOU` / `IMG_SIZE` / `DETECT_INTERVAL`：检测参数
- `MQTT_HOST` / `MQTT_PORT` / `MQTT_USER` / `MQTT_PASSWORD`
- `MQTT_CLIENT_ID` / `MQTT_DISCOVERY_PREFIX` / `MQTT_STATE_TOPIC`

当 `SOURCE=auto` 时，还可使用：

- `RTSP_HOST`
- `RTSP_USER`
- `RTSP_PASSWORD`
- `RTSP_PATH`

## 6. Web 界面使用

### 6.1 顶部语言切换

右上角可在 `中文 / English / Русский` 间切换，语言偏好会保存在浏览器本地。

### 6.2 新增视频源

填写：

- 名称
- 视频源地址
- 推送标签（可选，逗号分隔）

点击“添加”后会创建新的视频卡。

### 6.3 模型管理

- 上传 `.pt` 模型到服务器
- 在“模型管理”区域切换全局模型
- 在“实时监控矩阵”每个视频卡中可独立选模型并保存

### 6.4 视频卡操作

每个卡支持：

- 自定义名称
- 推送标签
- 选择卡片独立模型
- 复制 MQTT topic
- 复制视频卡（克隆同源配置）
- 删除视频卡

### 6.5 轮询更新说明

前端已针对输入框与模型下拉做“本地待保存保护”，编辑中不会被自动刷新覆盖。

## 7. Home Assistant 接入

服务启动后会自动发布 MQTT Discovery。

每个视频源会生成对应实体（名称与 source_id 相关），状态内容包含：

- `gesture`
- `confidence`
- `model`
- `timestamp`
- `source_id`

在 HA 中可直接将实体加入 Dashboard。

## 8. API 速览

主要接口：

- `GET /api/status`：系统状态 + 各视频源状态
- `GET /api/models`：可选模型列表
- `POST /api/models/upload`：上传 `.pt`
- `POST /api/models/activate`：切换全局模型
- `GET /api/sources`：视频源列表
- `POST /api/sources`：新增视频源
- `PUT /api/sources/{source_id}`：更新视频源（含 `name/labels/model/source`）
- `DELETE /api/sources/{source_id}`：删除视频源
- `GET /snapshot/{source_id}.jpg`：单源快照
- `GET /api/mqtt` / `PUT /api/mqtt` / `POST /api/mqtt/test`

## 9. 服务器部署（systemd 示例）

示例服务文件：`/etc/systemd/system/gesture-yolo-ha.service`

```ini
[Unit]
Description=YOLO Gesture FastAPI Service
After=network.target

[Service]
Type=simple
User=linaro
WorkingDirectory=/home/linaro/gesture-yolo-ha
ExecStart=/home/linaro/gesture-yolo-ha/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3
EnvironmentFile=/home/linaro/gesture-yolo-ha/.env

[Install]
WantedBy=multi-user.target
```

启用与启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable gesture-yolo-ha.service
sudo systemctl restart gesture-yolo-ha.service
sudo systemctl status gesture-yolo-ha.service
```

## 10. 常见问题

1. 模型选择后自动跳回
- 已修复：前端采用待保存状态，不会被轮询覆盖。

2. 修改视频卡名称会被清空
- 已修复：名称/标签输入也采用待保存状态。

3. 没有画面
- 检查 source 是否可访问（本地索引或 RTSP URL）
- 检查服务器与摄像头网络连通

4. HA 没有自动出现实体
- 检查 MQTT 集成与账号密码
- 检查 `MQTT_DISCOVERY_PREFIX` 与 Broker 可用性

## 11. 开发建议

- 新增模型类型时，优先在 `app/detector.py` 扩展统一推理接口
- 前端字符串请统一走 i18n 字典，避免多语言遗漏
- 生产环境建议加反向代理（Nginx）和 HTTPS

---

如需自动化部署到远程设备，可结合项目中的 `deploy_remote.py` 做文件同步与服务重启。
