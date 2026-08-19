from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

PUBLISH_MODES = ("change", "always")


def _text(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(float(_text(name, str(default))))
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _float(name: str, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        value = float(_text(name, str(default)))
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _bool(name: str, default: bool) -> bool:
    raw = _text(name, "").lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    app_name: str
    host: str
    port: int

    model_dir: Path
    model_file: str
    source: str
    conf: float
    iou: float
    image_size: int
    detect_interval: float

    share_models: bool
    jpeg_quality: int
    preview_width: int
    preview_fps: float
    idle_encode_timeout: float

    mqtt_host: str
    mqtt_port: int
    mqtt_user: str
    mqtt_password: str
    mqtt_client_id: str
    mqtt_discovery_prefix: str
    mqtt_state_topic: str
    mqtt_keepalive: int
    mqtt_publish_mode: str
    mqtt_heartbeat: float

    api_token: str
    max_upload_mb: int


def _resolve_source() -> str:
    """Use SOURCE verbatim unless it is empty/"auto", in which case build an RTSP URL."""
    raw_source = _text("SOURCE", "0")
    if raw_source and raw_source.lower() != "auto":
        return raw_source

    rtsp_host = _text("RTSP_HOST")
    if not rtsp_host:
        return "0"

    rtsp_user = quote(_text("RTSP_USER"), safe="")
    rtsp_password = quote(_text("RTSP_PASSWORD"), safe="")
    rtsp_port = _text("RTSP_PORT")
    rtsp_path = _text("RTSP_PATH", "/") or "/"
    if not rtsp_path.startswith("/"):
        rtsp_path = "/" + rtsp_path

    auth = ""
    if rtsp_user and rtsp_password:
        auth = f"{rtsp_user}:{rtsp_password}@"
    elif rtsp_user:
        auth = f"{rtsp_user}@"

    host_part = f"{rtsp_host}:{rtsp_port}" if rtsp_port else rtsp_host
    return f"rtsp://{auth}{host_part}{rtsp_path}"


def _resolve_model_dir() -> Path:
    raw = _text("MODEL_DIR", "models") or "models"
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    return path.resolve()


def load_settings() -> Settings:
    publish_mode = _text("MQTT_PUBLISH_MODE", "change").lower()
    if publish_mode not in PUBLISH_MODES:
        publish_mode = "change"

    # YOLO strides require the inference size to be a multiple of 32.
    image_size = max(32, (_int("IMG_SIZE", 640, 32, 2048) // 32) * 32)

    return Settings(
        app_name=_text("APP_NAME", "gesture-yolo-ha"),
        host=_text("HOST", "0.0.0.0"),
        port=_int("PORT", 8000, 1, 65535),
        model_dir=_resolve_model_dir(),
        model_file=_text("MODEL_FILE", "best.pt"),
        source=_resolve_source(),
        conf=_float("CONF", 0.5, 0.01, 1.0),
        iou=_float("IOU", 0.45, 0.01, 1.0),
        image_size=image_size,
        detect_interval=_float("DETECT_INTERVAL", 0.35, 0.05, 60.0),
        share_models=_bool("SHARE_MODELS", True),
        jpeg_quality=_int("JPEG_QUALITY", 80, 30, 100),
        preview_width=_int("PREVIEW_WIDTH", 0, 0, 4096),
        preview_fps=_float("PREVIEW_FPS", 15.0, 0.0, 60.0),
        idle_encode_timeout=_float("IDLE_ENCODE_TIMEOUT", 15.0, 0.0, 3600.0),
        mqtt_host=_text("MQTT_HOST", "127.0.0.1"),
        mqtt_port=_int("MQTT_PORT", 1883, 1, 65535),
        mqtt_user=_text("MQTT_USER"),
        mqtt_password=os.getenv("MQTT_PASSWORD", ""),
        mqtt_client_id=_text("MQTT_CLIENT_ID", "gesture_yolo_ha"),
        mqtt_discovery_prefix=_text("MQTT_DISCOVERY_PREFIX", "homeassistant"),
        mqtt_state_topic=_text("MQTT_STATE_TOPIC", "gesture_yolo_ha/state"),
        mqtt_keepalive=_int("MQTT_KEEPALIVE", 60, 10, 3600),
        mqtt_publish_mode=publish_mode,
        mqtt_heartbeat=_float("MQTT_HEARTBEAT", 60.0, 0.0, 3600.0),
        api_token=os.getenv("API_TOKEN", "").strip(),
        max_upload_mb=_int("MAX_UPLOAD_MB", 200, 1, 4096),
    )
