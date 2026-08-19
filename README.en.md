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
  - Live monitoring matrix with connection state and frame rate
  - Clone card
  - Copy MQTT topic
  - Language switcher (Chinese / English / Russian)
- Home Assistant integration via MQTT Discovery, plus an MJPEG stream that can be
  used directly as an `mjpeg` camera entity
- Cameras and MQTT settings persist across restarts

## 2. Requirements

- Python 3.10+ (3.11 recommended)
- Reachable camera stream(s)
- MQTT Broker + Home Assistant MQTT Integration (for HA integration)

## 3. Quick Start

### Windows PowerShell

```powershell
cd gesture-yolo-ha
.\run.ps1
```

`run.ps1` creates the virtualenv, installs dependencies only when
`requirements.txt` changes, creates `.env`, and starts the server.

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

## 4. Security

Loading a `.pt` model **executes code contained in the file**. Anyone who can
reach this service can therefore upload and activate a model and run arbitrary
code on your host.

- Set `API_TOKEN` in `.env` to require authentication on every `/api`,
  `/snapshot` and `/stream` request.
- The token may be supplied via `Authorization: Bearer <token>`, the
  `X-API-Token` header, a `?token=` query parameter, or the cookie set by
  `POST /api/login`.
- With `API_TOKEN` empty the API is open; only do this on a fully trusted LAN.
  The service logs a warning at start-up in that case.
- `GET /api/mqtt` returns `********` instead of the stored broker password.
- Never put real credentials in `.env.example`. `.env` is git-ignored.

## 5. Configuration (.env)

### Core

- `HOST`, `PORT`
- `API_TOKEN` — empty disables authentication
- `MAX_UPLOAD_MB` — model upload size cap, default 200

### Detection

- `MODEL_DIR`, `MODEL_FILE` (`.pt` name or `mediapipe_hands`)
- `SOURCE` (`0`, `rtsp://...`, or `auto`)
- `CONF`, `IOU`, `IMG_SIZE`, `DETECT_INTERVAL`
- `SHARE_MODELS` — share one loaded copy of a `.pt` file across all cameras
  (default `true`, cuts memory use substantially)

When `SOURCE=auto`, the RTSP URL is built from `RTSP_HOST`, `RTSP_PORT`,
`RTSP_USER`, `RTSP_PASSWORD` and `RTSP_PATH`.

### Preview performance

- `JPEG_QUALITY` — preview JPEG quality, default 80
- `PREVIEW_WIDTH` — downscale width for previews, `0` keeps native resolution
- `PREVIEW_FPS` — cap on preview encoding, default 15. **This only limits how often
  a JPEG is produced; detection always runs at the full stream rate.** Lower it when
  running many cameras on weak hardware
- `IDLE_ENCODE_TIMEOUT` — stop encoding preview frames when nobody has watched
  for this many seconds (detection is unaffected), default 15

### MQTT

- `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASSWORD`
- `MQTT_CLIENT_ID`, `MQTT_DISCOVERY_PREFIX`, `MQTT_STATE_TOPIC`
- `MQTT_KEEPALIVE` — default 60
- `MQTT_PUBLISH_MODE` — `change` publishes only when the gesture changes
  (default); `always` publishes every detection
- `MQTT_HEARTBEAT` — republish the current gesture at least this often in
  seconds, `0` disables

## 6. Web Console

- Add/remove source cards
- Upload and switch models
- Per-card independent model selection
- Clone card from an existing source
- Multi-language switch in top-right corner
- Connection dot and live frame rate per card; click a preview for a full-screen
  MJPEG view

Notes:

- The UI protects pending edits, so polling refresh does not overwrite what you
  are typing or selecting.
- Tailwind is vendored under `app/static/vendor/`, so the console works on an
  isolated network with no internet access.

## 7. Home Assistant Integration

MQTT Discovery is published on start-up and on every reconnect, including an
availability topic so entities show as unavailable when the service stops.

State payload includes:

- `gesture`
- `confidence`
- `model`
- `timestamp`
- `source_id`

### Camera entity

`/stream/{source_id}.mjpg` is a standard MJPEG stream:

```yaml
camera:
  - platform: mjpeg
    name: Living Room Gesture
    mjpeg_url: http://<server-ip>:8000/stream/cam1.mjpg
```

Append `?token=<your-token>` when `API_TOKEN` is enabled.

## 8. Main APIs

- `GET /healthz` (no auth, for health checks)
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
- `GET /api/mqtt`, `PUT /api/mqtt`, `POST /api/mqtt/test`
- `POST /api/login` (exchange a token for a cookie)

## 9. Development

```bash
pip install -r requirements-dev.txt
pytest
ruff check .
```

## 10. Release & Auto Deploy

### GitHub Release

- Pushing tag `v*` (for example `v1.0.0`) auto-creates a GitHub Release
- Workflow: `.github/workflows/release.yml`

### Auto Deploy on Push

- Push to `main` runs tests, deploys, and verifies `/healthz`
- Workflow: `.github/workflows/deploy.yml`
- Example systemd unit: `deploy/gesture-yolo-ha.service`
- Required repository secrets:
  - `DEPLOY_HOST`
  - `DEPLOY_USER`
  - `DEPLOY_PASSWORD`
  - `DEPLOY_PORT` (optional, default `22`)
  - `DEPLOY_PATH` (for example `/home/linaro/gesture-yolo-ha`)
  - `DEPLOY_SERVICE` (for example `gesture-yolo-ha.service`)
  - `DEPLOY_HEALTH_PORT` (optional, default `8000`)

## 11. Troubleshooting preview latency

An RTSP preview running behind reality is the most common complaint. The delay can
come from three places: the camera, this service, or the browser. This section
describes what the service already does about it, then how to locate the rest.

### 11.1 What the service already does

**Capture is separated from encoding.** Each source runs three threads: the capture
thread only calls `cap.read()`, hands the frame to the inference and preview threads,
and immediately goes back to reading. Overlay drawing and JPEG encoding never happen
on the capture thread. This matters because a capture thread that falls behind the
stream rate lets frames pile up in the FFmpeg decode queue, which shows up as a
constant delay of roughly a second.

**Frames are dropped, not queued.** If the preview encoder has not finished the
previous frame, the new one replaces it. Encoding can therefore never slow capture
down, and latency does not accumulate over time.

**FFmpeg input buffering is disabled.** The default capture options are:

```
rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|reorder_queue_size;0|max_delay;0|stimeout;5000000
```

Override the whole string with `OPENCV_FFMPEG_CAPTURE_OPTIONS` in `.env` if a camera
needs different tuning. On a LAN, UDP can shave off a little more latency at the cost
of visible artefacts when packets are lost:

```bash
OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;udp|fflags;nobuffer|flags;low_delay|max_delay;0
```

### 11.2 Locating the delay with the probe

`tools/latency_probe.py` decodes a stream with exactly the same FFmpeg options the
service uses, but with no inference, no JPEG encoding, no HTTP and no browser in
between. Whatever delay remains belongs to the camera, the network or the decoder.

```bash
python tools/latency_probe.py                     # first RTSP source in data/sources.json
python tools/latency_probe.py 102                 # match a source whose URL contains "102"
python tools/latency_probe.py rtsp://... --headless --seconds 12
```

Without `--headless` a preview window opens with a live clock drawn in the corner.
**Point the camera at that window on your monitor**: the video then contains a
picture of the clock, and the gap between it and the live clock is the true
end-to-end latency. Press `q` to quit.

The number to read is `read avg`:

- **`read avg` is large (tens of milliseconds)** — every frame is spent waiting for
  the camera, so the bottleneck is the camera or the network; go to 11.3
- **`read avg` is near zero** — frames were already queued, so the bottleneck is on
  our side; lower `PREVIEW_FPS`, `PREVIEW_WIDTH` or `JPEG_QUALITY`
- **`display avg` is large** — only the preview window is slow to render; add
  `--headless` to remove that variable

Comparing the main and sub streams with `--headless` is especially telling: if
1280x720 and 352x288 produce an identical frame rate, decode cost cannot be the
bottleneck, since the larger frame is more than ten times more expensive to decode.

### 11.3 Camera-side checklist

The camera's own settings are usually the larger share of the delay. On Hikvision
models, check the web console for:

- **Exposure time / slow shutter** (Configuration - Image - Display Settings). **This
  is the most commonly missed setting and the most impactful.** In low light the
  camera lengthens exposure to brighten the picture, which halves the frame rate. An
  exposure of 1/12 s means 12 fps, 83 ms of built-in delay per frame, and motion
  blur. Set it to 1/50 s or faster; if the image goes dark, the scene needs more light
- **I-frame interval** — set it to one or two times the frame rate (25 or less at
  25 fps). Denser keyframes mean faster decoder start-up and reconnection
- **Stream smoothing** — drag it fully towards the "clear" end. Smoothing flattens the
  output bitrate by buffering, and that buffer is latency
- **Video encoding** — prefer H.264; H.265 is much slower to decode on a CPU
- **Encoding complexity** — set it to low. Higher complexity adds cross-frame analysis
  and therefore delay
- **Stream type** — make sure you are editing the stream you actually pull.
  `/Streaming/Channels/101` is the main stream and `/102` is the sub stream; editing
  the wrong one changes nothing

Also watch the resolution. At the 352x288 (CIF) commonly used for sub streams,
MediaPipe struggles to resolve finger joints and gesture detection becomes unreliable.
If recognition is poor, raise the sub stream above 640x480 or point that source at the
main stream instead.

### 11.4 Cross-checking with VLC

VLC buffers **1000 ms of network cache by default**, so opening an RTSP URL straight
away shows about a second of delay and invites the wrong conclusion. Always disable
the cache:

```bash
vlc --network-caching=0 --rtsp-tcp "rtsp://user:pass@host:554/Streaming/Channels/102"
```

The same applies to Hikvision's iVMS-4200 client: set System Configuration - Live View
- Play Performance to shortest delay, otherwise the measurement is meaningless.
