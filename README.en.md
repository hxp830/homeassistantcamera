# Gesture YOLO HA (English)

Gesture YOLO HA is a multi-source gesture recognition system for Home Assistant.
It supports YOLO `.pt` models, built-in MediaPipe gestures, MQTT Discovery, and a multilingual web console.

## 1. Features

- Multi-source video input (USB camera / RTSP)
- Model support:
  - YOLO `.pt` files (uploadable)
  - Built-in `mediapipe_hands`
- Model switching:
  - Global model
  - Per-video-card model
- Web UI:
  - Live monitoring matrix
  - Clone card
  - Copy MQTT topic
  - Language switcher (Chinese / English / Russian)
- Home Assistant integration via MQTT Discovery

## 2. Requirements

- Python 3.10+ (3.11 recommended)
- Reachable camera stream(s)
- MQTT Broker + Home Assistant MQTT Integration (for HA integration)

## 3. Quick Start

### Windows PowerShell

```powershell
cd gesture-yolo-ha
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Linux / macOS

```bash
cd gesture-yolo-ha
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open: `http://127.0.0.1:8000/`

## 4. Configuration (.env)

Important variables:

- `HOST`, `PORT`
- `MODEL_DIR`, `MODEL_FILE` (`.pt` name or `mediapipe_hands`)
- `SOURCE` (`0`, `rtsp://...`, or `auto`)
- `CONF`, `IOU`, `IMG_SIZE`, `DETECT_INTERVAL`
- `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASSWORD`
- `MQTT_CLIENT_ID`, `MQTT_DISCOVERY_PREFIX`, `MQTT_STATE_TOPIC`

When `SOURCE=auto`, the app builds RTSP URL from:

- `RTSP_HOST`
- `RTSP_USER`
- `RTSP_PASSWORD`
- `RTSP_PATH`

## 5. Web Console

- Add/remove source cards
- Upload and switch models
- Per-card independent model selection
- Clone card from an existing source
- Multi-language switch in top-right corner

The UI includes local pending-state protection, so polling refresh does not overwrite your current edits.

## 6. Home Assistant Integration

MQTT Discovery is published on startup.

State payload includes:

- `gesture`
- `confidence`
- `model`
- `timestamp`
- `source_id`

## 7. Main APIs

- `GET /api/status`
- `GET /api/models`
- `POST /api/models/upload`
- `POST /api/models/activate`
- `GET /api/sources`
- `POST /api/sources`
- `PUT /api/sources/{source_id}`
- `DELETE /api/sources/{source_id}`
- `GET /snapshot/{source_id}.jpg`
- `GET /api/mqtt`, `PUT /api/mqtt`, `POST /api/mqtt/test`

## 8. Release & Auto Deploy

### GitHub Release

- Pushing tag `v*` (for example `v1.0.0`) auto-creates GitHub Release
- Workflow: `.github/workflows/release.yml`

### Auto Deploy on Push

- Push to `main` triggers deployment workflow
- Workflow: `.github/workflows/deploy.yml`
- Required repository secrets:
  - `DEPLOY_HOST`
  - `DEPLOY_USER`
  - `DEPLOY_PASSWORD`
  - `DEPLOY_PORT` (optional, default `22`)
  - `DEPLOY_PATH` (for example `/home/linaro/gesture-yolo-ha`)
  - `DEPLOY_SERVICE` (for example `gesture-yolo-ha.service`)
