# Gesture YOLO HA

Multi-source gesture recognition system for Home Assistant, with YOLO + MediaPipe, MQTT Discovery, and a multilingual web UI.

## Docs

- Chinese: [README.zh-CN.md](README.zh-CN.md)
- English: [README.en.md](README.en.md)
- Russian: [README.ru.md](README.ru.md)

## Quick Start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

On Windows, `.\run.ps1` does all of the above.

## Security

Loading a `.pt` model **executes code from the file**. Anyone who can reach this
service can upload and activate a model, so treat the port as privileged.

Set `API_TOKEN` in `.env` to require a token on every `/api`, `/snapshot` and
`/stream` request. The token is accepted as an `Authorization: Bearer` header, an
`X-API-Token` header, a `?token=` query parameter, or a cookie obtained from
`POST /api/login`. When `API_TOKEN` is empty the API is unauthenticated and the
service logs a warning on start-up.

## Endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /healthz` | Health check, never requires auth |
| `GET /api/status` | Active model, MQTT state, per-source status |
| `GET /snapshot/{source_id}.jpg` | Single preview frame |
| `GET /stream/{source_id}.mjpg` | MJPEG stream, usable as a Home Assistant `mjpeg` camera |
| `POST /api/models/upload` | Upload a `.pt` model (size capped by `MAX_UPLOAD_MB`) |
| `POST /api/models/activate` | Switch the global model |
| `GET/POST/PUT/DELETE /api/sources` | Manage cameras |
| `GET/PUT /api/mqtt`, `POST /api/mqtt/test` | Manage the broker connection |

Cameras and MQTT settings are persisted under `data/` and restored on restart.

## Preview latency

Capture, inference and JPEG encoding run on separate threads per source, and the
preview encoder drops frames instead of queueing them, so a slow encoder can never
push the capture loop behind the stream and build up delay. FFmpeg input buffering
is disabled by default; override `OPENCV_FFMPEG_CAPTURE_OPTIONS` to retune it.

To find out whether a remaining delay belongs to the camera or to this service:

```bash
python tools/latency_probe.py 102 --headless --seconds 12
```

A high `read avg` means the camera is the bottleneck, a near-zero one means we are.
The language-specific READMEs have a full checklist, including the camera exposure
setting that silently halves the frame rate in low light.

## Development

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

## Release

- GitHub Releases are generated automatically when pushing tags like `v*` (see `.github/workflows/release.yml`).

## CI/CD Deployment

On every push to `main`, GitHub Actions runs the dependency-light tests, syncs to
your server, restarts the system service, and then polls `/healthz` to confirm
the deployment came up.

- Workflow: `.github/workflows/deploy.yml`
- Example unit file: `deploy/gesture-yolo-ha.service`
- Required repository secrets:
  - `DEPLOY_HOST`
  - `DEPLOY_USER`
  - `DEPLOY_PASSWORD`
  - `DEPLOY_PORT` (optional, default `22`)
  - `DEPLOY_PATH` (for example: `/home/linaro/gesture-yolo-ha`)
  - `DEPLOY_SERVICE` (for example: `gesture-yolo-ha.service`)
  - `DEPLOY_HEALTH_PORT` (optional, default `8000`)
