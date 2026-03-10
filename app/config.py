import os
from dataclasses import dataclass
from urllib.parse import quote

from dotenv import load_dotenv


load_dotenv()


@dataclass
class Settings:
    app_name: str = os.getenv("APP_NAME", "gesture-yolo-ha")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))

    model_dir: str = os.getenv("MODEL_DIR", "models")
    model_file: str = os.getenv("MODEL_FILE", "best.pt")
    source: str = os.getenv("SOURCE", "0")
    conf: float = float(os.getenv("CONF", "0.5"))
    iou: float = float(os.getenv("IOU", "0.45"))
    image_size: int = int(os.getenv("IMG_SIZE", "640"))
    detect_interval: float = float(os.getenv("DETECT_INTERVAL", "0.35"))

    mqtt_host: str = os.getenv("MQTT_HOST", "127.0.0.1")
    mqtt_port: int = int(os.getenv("MQTT_PORT", "1883"))
    mqtt_user: str = os.getenv("MQTT_USER", "")
    mqtt_password: str = os.getenv("MQTT_PASSWORD", "")
    mqtt_client_id: str = os.getenv("MQTT_CLIENT_ID", "gesture_yolo_ha")
    mqtt_discovery_prefix: str = os.getenv("MQTT_DISCOVERY_PREFIX", "homeassistant")
    mqtt_state_topic: str = os.getenv("MQTT_STATE_TOPIC", "gesture_yolo_ha/state")


def load_settings() -> Settings:
    settings = Settings()

    # When SOURCE is empty or "auto", build RTSP URL from dedicated env vars.
    raw_source = settings.source.strip()
    if raw_source and raw_source.lower() != "auto":
        return settings

    rtsp_host = os.getenv("RTSP_HOST", "").strip()
    if not rtsp_host:
        settings.source = "0"
        return settings

    rtsp_user = quote(os.getenv("RTSP_USER", "").strip(), safe="")
    rtsp_password = quote(os.getenv("RTSP_PASSWORD", "").strip(), safe="")
    rtsp_path = os.getenv("RTSP_PATH", "/").strip() or "/"
    if not rtsp_path.startswith("/"):
        rtsp_path = "/" + rtsp_path

    auth = ""
    if rtsp_user and rtsp_password:
        auth = f"{rtsp_user}:{rtsp_password}@"
    elif rtsp_user:
        auth = f"{rtsp_user}@"

    settings.source = f"rtsp://{auth}{rtsp_host}{rtsp_path}"
    return settings
