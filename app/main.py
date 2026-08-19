from __future__ import annotations

import asyncio
import logging
import secrets
import threading
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.config import BASE_DIR, load_settings
from app.detector import MEDIAPIPE_MODEL_NAME, DetectorService, ModelRegistry
from app.mqtt_bridge import MqttBridge
from app.store import JsonStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("gesture_yolo_ha")

settings = load_settings()

STATIC_DIR = BASE_DIR / "app" / "static"
INDEX_FILE = STATIC_DIR / "index.html"
DATA_DIR = BASE_DIR / "data"
TOKEN_COOKIE = "gesture_token"
NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

settings.model_dir.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

sources_store = JsonStore(DATA_DIR / "sources.json")
mqtt_store = JsonStore(DATA_DIR / "mqtt.json")
model_registry = ModelRegistry(settings.model_dir, share=settings.share_models)


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #


class SourceCreateReq(BaseModel):
    source: str = Field(min_length=1, max_length=1024)
    name: str = Field(default="", max_length=128)
    labels: str = Field(default="", max_length=1024)
    model: str | None = Field(default=None, max_length=255)


class SourceUpdateReq(BaseModel):
    source: str | None = Field(default=None, max_length=1024)
    name: str | None = Field(default=None, max_length=128)
    labels: str | None = Field(default=None, max_length=1024)
    model: str | None = Field(default=None, max_length=255)


class ActivateModelReq(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class MqttConfigReq(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    user: str = Field(default="", max_length=255)
    password: str = Field(default="", max_length=255)
    client_id: str = Field(min_length=1, max_length=255)
    discovery_prefix: str = Field(default="homeassistant", max_length=255)
    state_topic: str = Field(default="gesture_yolo_ha/state", max_length=255)


class LoginReq(BaseModel):
    token: str = Field(default="", max_length=512)


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #


def _extract_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    for candidate in (
        request.headers.get("x-api-token"),
        request.cookies.get(TOKEN_COOKIE),
        request.query_params.get("token"),
    ):
        if candidate:
            return candidate.strip()
    return ""


def require_auth(request: Request) -> None:
    if not settings.api_token:
        return
    if secrets.compare_digest(_extract_token(request), settings.api_token):
        return
    raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Bearer"})


# --------------------------------------------------------------------------- #
# MQTT
# --------------------------------------------------------------------------- #


def _default_mqtt_config() -> dict:
    return {
        "host": settings.mqtt_host,
        "port": settings.mqtt_port,
        "user": settings.mqtt_user,
        "password": settings.mqtt_password,
        "client_id": settings.mqtt_client_id,
        "discovery_prefix": settings.mqtt_discovery_prefix,
        "state_topic": settings.mqtt_state_topic,
    }


class MqttManager:
    """Owns the active bridge so it can be swapped atomically at runtime."""

    def __init__(self, config: dict) -> None:
        self._lock = threading.RLock()
        self._config = config
        self._bridge = self._build(config)

    @staticmethod
    def _build(cfg: dict) -> MqttBridge:
        return MqttBridge(
            host=cfg["host"],
            port=int(cfg["port"]),
            client_id=cfg["client_id"],
            discovery_prefix=cfg["discovery_prefix"],
            state_topic=cfg["state_topic"],
            username=cfg.get("user", ""),
            password=cfg.get("password", ""),
            keepalive=settings.mqtt_keepalive,
            publish_mode=settings.mqtt_publish_mode,
            heartbeat=settings.mqtt_heartbeat,
        )

    def config(self, redacted: bool = True) -> dict:
        with self._lock:
            cfg = dict(self._config)
        if redacted:
            cfg["password"] = "********" if cfg.get("password") else ""
        return cfg

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._bridge.connected

    def start(self) -> None:
        with self._lock:
            self._bridge.start()

    def stop(self) -> None:
        with self._lock:
            self._bridge.stop()

    def replace(self, new_cfg: dict, wait_timeout: float = 6.0) -> None:
        """Swap in a new broker connection, keeping the old one if it fails."""
        new_bridge = self._build(new_cfg)
        try:
            if not new_bridge.start(wait_timeout=wait_timeout):
                raise RuntimeError(f"could not connect to {new_cfg['host']}:{new_cfg['port']}")
        except Exception:
            new_bridge.stop()
            raise
        with self._lock:
            old_bridge = self._bridge
            self._bridge = new_bridge
            self._config = new_cfg
        old_bridge.stop()
        mqtt_store.save(dict(new_cfg))

    def publish_state(self, **kwargs) -> None:
        with self._lock:
            bridge = self._bridge
        bridge.publish_state(**kwargs)

    def publish_discovery(self, class_names, sources) -> None:
        with self._lock:
            bridge = self._bridge
        bridge.publish_discovery(class_names, sources)

    def clear_source_discovery(self, source_id: str) -> None:
        with self._lock:
            bridge = self._bridge
        bridge.clear_source_discovery(source_id)


_stored_mqtt = mqtt_store.load(None)
mqtt_manager = MqttManager({**_default_mqtt_config(), **(_stored_mqtt or {})})


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


@dataclass
class SourceConfig:
    source_id: str
    source: str
    name: str
    labels: set[str] = field(default_factory=set)
    model: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["labels"] = sorted(self.labels)
        return data


def parse_labels(text: str) -> set[str]:
    return {x.strip().lower() for x in (text or "").split(",") if x.strip()}


class SourceManager:
    def __init__(self, model_file: str) -> None:
        self._lock = threading.Lock()
        self._model_file = model_file
        self._detectors: dict[str, DetectorService] = {}
        self._configs: dict[str, SourceConfig] = {}

    @property
    def active_model(self) -> str:
        with self._lock:
            return self._model_file

    def _on_detection(self, payload: dict) -> None:
        source_id = payload.get("source_id", "")
        gesture = str(payload.get("gesture", "")).strip().lower()
        with self._lock:
            config = self._configs.get(source_id)
            labels = set(config.labels) if config else set()
        if labels and gesture not in labels:
            return
        mqtt_manager.publish_state(
            gesture=payload["gesture"],
            confidence=payload["confidence"],
            model=payload["model"],
            timestamp=payload["timestamp"],
            source_id=source_id,
        )

    def _build_detector(self, source: str, source_id: str, model_file: str) -> DetectorService:
        return DetectorService(
            model_registry=model_registry,
            model_file=model_file,
            source=source,
            detector_id=source_id,
            conf=settings.conf,
            iou=settings.iou,
            img_size=settings.image_size,
            detect_interval=settings.detect_interval,
            jpeg_quality=settings.jpeg_quality,
            preview_width=settings.preview_width,
            preview_fps=settings.preview_fps,
            idle_encode_timeout=settings.idle_encode_timeout,
            on_detection=self._on_detection,
        )

    def add_source(
        self,
        source: str,
        source_id: str | None = None,
        name: str = "",
        labels: str = "",
        model: str | None = None,
        persist: bool = True,
    ) -> str:
        sid = source_id or f"cam_{uuid.uuid4().hex[:8]}"
        with self._lock:
            if sid in self._detectors:
                raise ValueError(f"Source id exists: {sid}")
            model_file = model or self._model_file

        # Loading weights can take seconds, so it happens outside the manager lock
        # to keep status/preview requests responsive while a camera is added.
        detector = self._build_detector(source, sid, model_file)

        with self._lock:
            if sid in self._detectors:
                detector.stop()
                raise ValueError(f"Source id exists: {sid}")
            self._detectors[sid] = detector
            self._configs[sid] = SourceConfig(
                source_id=sid,
                source=source,
                name=(name or sid).strip() or sid,
                labels=parse_labels(labels),
                model=model_file,
            )
        detector.start()
        if persist:
            self.persist()
        return sid

    def remove_source(self, source_id: str) -> bool:
        with self._lock:
            detector = self._detectors.pop(source_id, None)
            self._configs.pop(source_id, None)
        if detector is None:
            return False
        detector.stop()
        self.persist()
        return True

    def update_source(
        self,
        source_id: str,
        source: str | None = None,
        name: str | None = None,
        labels: str | None = None,
        model: str | None = None,
    ) -> bool:
        with self._lock:
            detector = self._detectors.get(source_id)
            config = self._configs.get(source_id)
        if detector is None or config is None:
            return False

        if source is not None:
            detector.set_source(source)
        if model is not None:
            detector.set_model(model)

        with self._lock:
            if source is not None:
                config.source = source
            if name is not None:
                config.name = name.strip() or source_id
            if labels is not None:
                config.labels = parse_labels(labels)
            if model is not None:
                config.model = model
        self.persist()
        return True

    def set_model(self, model_file: str) -> None:
        with self._lock:
            self._model_file = model_file
            detectors = list(self._detectors.values())
            configs = list(self._configs.values())
        for detector in detectors:
            detector.set_model(model_file)
        with self._lock:
            for config in configs:
                config.model = model_file
        self.persist()

    def get_detector(self, source_id: str) -> DetectorService | None:
        with self._lock:
            return self._detectors.get(source_id)

    def class_names(self) -> list[str]:
        with self._lock:
            detectors = list(self._detectors.values())
        return detectors[0].class_names if detectors else []

    def list_status(self) -> list[dict]:
        with self._lock:
            pairs = [(d, self._configs.get(sid)) for sid, d in self._detectors.items()]
        output = []
        for detector, config in pairs:
            item = detector.get_status()
            if config is not None:
                labels = sorted(config.labels)
                item["name"] = config.name
                item["labels"] = labels
                item["labels_text"] = ", ".join(labels)
            output.append(item)
        return output

    def list_sources_brief(self) -> list[dict]:
        with self._lock:
            return [{"source_id": c.source_id, "name": c.name} for c in self._configs.values()]

    def first_source_id(self) -> str | None:
        with self._lock:
            return next(iter(self._detectors), None)

    def persist(self) -> None:
        with self._lock:
            data = {
                "model": self._model_file,
                "sources": [c.to_dict() for c in self._configs.values()],
            }
        sources_store.save(data)

    def stop_all(self) -> None:
        with self._lock:
            detectors = list(self._detectors.values())
            self._detectors.clear()
            self._configs.clear()
        for detector in detectors:
            detector.stop()


def _choose_startup_model() -> str:
    if settings.model_file == MEDIAPIPE_MODEL_NAME:
        return MEDIAPIPE_MODEL_NAME
    default_model = settings.model_dir / Path(settings.model_file).name
    if default_model.is_file() and default_model.suffix.lower() == ".pt":
        return default_model.name
    candidates = sorted(settings.model_dir.glob("*.pt"))
    return candidates[0].name if candidates else MEDIAPIPE_MODEL_NAME


def validate_model_name(model_name: str) -> str:
    if model_name == MEDIAPIPE_MODEL_NAME:
        return model_name
    try:
        model_path = model_registry.resolve_path(model_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid model name: {model_name}") from exc
    if model_path.suffix.lower() != ".pt" or not model_path.is_file():
        raise HTTPException(status_code=404, detail=f"model not found: {model_name}")
    return model_path.name


_persisted = sources_store.load({}) or {}
source_manager = SourceManager(model_file=_persisted.get("model") or _choose_startup_model())


def _restore_sources() -> None:
    """Recreate cameras from disk, falling back to the SOURCE env var on first run."""
    saved = _persisted.get("sources") or []
    restored = 0
    for entry in saved:
        try:
            source_manager.add_source(
                source=entry.get("source", ""),
                source_id=entry.get("source_id"),
                name=entry.get("name", ""),
                labels=", ".join(entry.get("labels", [])),
                model=entry.get("model") or None,
                persist=False,
            )
            restored += 1
        except Exception as exc:
            logger.warning("Could not restore source %s: %s", entry.get("source_id"), exc)

    if not saved:
        try:
            source_manager.add_source(settings.source, source_id="cam1", name="cam1")
        except Exception as exc:
            logger.error("Could not start default source: %s", exc)
    elif restored < len(saved):
        # Rewriting the file here would permanently drop the cameras that failed,
        # so the stored config is left alone until the user changes something.
        logger.error(
            "Only %d of %d saved sources could be restored; stored configuration left untouched.",
            restored,
            len(saved),
        )


def _refresh_discovery() -> None:
    mqtt_manager.publish_discovery(source_manager.class_names(), source_manager.list_sources_brief())


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not settings.api_token:
        logger.warning(
            "API_TOKEN is not set: the API is unauthenticated. Anyone who can reach this "
            "port can upload and activate model files, which execute code on load."
        )
    mqtt_manager.start()
    await asyncio.to_thread(_restore_sources)
    _refresh_discovery()
    try:
        yield
    finally:
        source_manager.stop_all()
        mqtt_manager.stop()


app = FastAPI(title="YOLO Gesture + Home Assistant", lifespan=lifespan)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

api = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])
media = APIRouter(dependencies=[Depends(require_auth)])


# --------------------------------------------------------------------------- #
# Public routes
# --------------------------------------------------------------------------- #


@app.get("/", include_in_schema=False)
def ui() -> FileResponse:
    return FileResponse(INDEX_FILE, headers=NO_CACHE_HEADERS)


@app.get("/healthz")
def healthz() -> JSONResponse:
    sources = source_manager.list_status()
    return JSONResponse(
        {
            "status": "ok",
            "mqtt_connected": mqtt_manager.connected,
            "sources": len(sources),
            "sources_connected": sum(1 for s in sources if s.get("connected")),
        }
    )


@app.post("/api/login")
def login(req: LoginReq) -> JSONResponse:
    if not settings.api_token:
        return JSONResponse({"ok": True, "auth_required": False})
    if not secrets.compare_digest(req.token, settings.api_token):
        raise HTTPException(status_code=401, detail="Invalid token")
    response = JSONResponse({"ok": True, "auth_required": True})
    response.set_cookie(
        TOKEN_COOKIE,
        req.token,
        httponly=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
    )
    return response


@app.get("/api/auth")
def auth_state() -> JSONResponse:
    return JSONResponse({"auth_required": bool(settings.api_token)})


# --------------------------------------------------------------------------- #
# Status & MQTT
# --------------------------------------------------------------------------- #


@api.get("/status")
def status() -> JSONResponse:
    return JSONResponse(
        {
            "model": source_manager.active_model,
            "mqtt_connected": mqtt_manager.connected,
            "sources": source_manager.list_status(),
        }
    )


@api.get("/mqtt")
def get_mqtt() -> JSONResponse:
    return JSONResponse(mqtt_manager.config(redacted=True))


def _normalise_mqtt(req: MqttConfigReq) -> dict:
    current = mqtt_manager.config(redacted=False)
    password = req.password
    # The UI receives a masked password; an unchanged mask means "keep existing".
    if password == "********":
        password = current.get("password", "")
    return {
        "host": req.host.strip(),
        "port": int(req.port),
        "user": req.user.strip(),
        "password": password,
        "client_id": req.client_id.strip(),
        "discovery_prefix": req.discovery_prefix.strip() or "homeassistant",
        "state_topic": req.state_topic.strip() or "gesture_yolo_ha/state",
    }


@api.put("/mqtt")
def set_mqtt(req: MqttConfigReq) -> JSONResponse:
    new_cfg = _normalise_mqtt(req)
    if not new_cfg["host"] or not new_cfg["client_id"]:
        raise HTTPException(status_code=400, detail="MQTT host/client_id required")
    try:
        mqtt_manager.replace(new_cfg)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"MQTT connect failed: {exc}") from exc
    _refresh_discovery()
    return JSONResponse({"ok": True, "mqtt": mqtt_manager.config(redacted=True)})


@api.post("/mqtt/test")
def test_mqtt(req: MqttConfigReq) -> JSONResponse:
    cfg = _normalise_mqtt(req)
    cfg["client_id"] = cfg["client_id"] or "gesture_yolo_test"
    bridge = MqttBridge(
        host=cfg["host"],
        port=cfg["port"],
        client_id=cfg["client_id"],
        discovery_prefix=cfg["discovery_prefix"],
        state_topic=cfg["state_topic"],
        username=cfg["user"],
        password=cfg["password"],
        keepalive=settings.mqtt_keepalive,
    )
    try:
        if not bridge.start(wait_timeout=6.0):
            raise RuntimeError(f"could not connect to {cfg['host']}:{cfg['port']}")
        bridge.publish_state(
            gesture="mqtt_test_ok",
            confidence=1.0,
            model="test",
            timestamp="now",
            source_id="_test",
            force=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"MQTT test failed: {exc}") from exc
    finally:
        bridge.stop()
    return JSONResponse({"ok": True, "message": "MQTT connect and publish success"})


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


@api.get("/models")
def list_models() -> JSONResponse:
    files = sorted(p.name for p in settings.model_dir.glob("*.pt") if p.is_file())
    return JSONResponse({"models": [MEDIAPIPE_MODEL_NAME] + files})


@api.post("/models/upload")
async def upload_model(file: UploadFile = File(...)) -> JSONResponse:
    filename = Path(file.filename or "").name
    if not filename or not filename.lower().endswith(".pt"):
        raise HTTPException(status_code=400, detail="Only .pt model files are supported")

    max_bytes = settings.max_upload_mb * 1024 * 1024
    dst = settings.model_dir / filename
    tmp = dst.with_suffix(dst.suffix + ".part")
    written = 0
    try:
        with tmp.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Model exceeds the {settings.max_upload_mb} MB limit",
                    )
                handle.write(chunk)
        tmp.replace(dst)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise

    logger.info("Uploaded model %s (%.1f MB)", filename, written / 1024 / 1024)
    return JSONResponse({"ok": True, "file": dst.name})


@api.post("/models/activate")
def activate_model(req: ActivateModelReq) -> JSONResponse:
    name = validate_model_name(req.name)
    try:
        source_manager.set_model(name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"could not load model: {exc}") from exc
    _refresh_discovery()
    return JSONResponse({"ok": True, "active": name})


@api.delete("/models/{name}")
def delete_model(name: str) -> JSONResponse:
    if name == MEDIAPIPE_MODEL_NAME:
        raise HTTPException(status_code=400, detail="The built-in model cannot be deleted")
    resolved = validate_model_name(name)
    if source_manager.active_model == resolved:
        raise HTTPException(status_code=409, detail="Cannot delete the active model")
    (settings.model_dir / resolved).unlink(missing_ok=True)
    return JSONResponse({"ok": True})


# --------------------------------------------------------------------------- #
# Sources
# --------------------------------------------------------------------------- #


@api.get("/sources")
def list_sources() -> JSONResponse:
    return JSONResponse({"sources": source_manager.list_status()})


@api.post("/sources")
def add_source(req: SourceCreateReq) -> JSONResponse:
    model = validate_model_name(req.model) if req.model else None
    try:
        sid = source_manager.add_source(req.source.strip(), name=req.name, labels=req.labels, model=model)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"could not add source: {exc}") from exc
    _refresh_discovery()
    return JSONResponse({"ok": True, "source_id": sid})


@api.put("/sources/{source_id}")
def update_source(source_id: str, req: SourceUpdateReq) -> JSONResponse:
    model = validate_model_name(req.model) if req.model else None
    try:
        ok = source_manager.update_source(
            source_id,
            source=req.source.strip() if req.source is not None else None,
            name=req.name,
            labels=req.labels,
            model=model,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"could not update source: {exc}") from exc
    if not ok:
        raise HTTPException(status_code=404, detail="source not found")
    if req.name is not None:
        _refresh_discovery()
    return JSONResponse({"ok": True})


@api.delete("/sources/{source_id}")
def delete_source(source_id: str) -> JSONResponse:
    if not source_manager.remove_source(source_id):
        raise HTTPException(status_code=404, detail="source not found")
    mqtt_manager.clear_source_discovery(source_id)
    _refresh_discovery()
    return JSONResponse({"ok": True})


@api.post("/source")
def set_source_compat(req: SourceUpdateReq) -> JSONResponse:
    """Backwards-compatible endpoint for the original single-camera API."""
    if req.source is None:
        raise HTTPException(status_code=400, detail="source required")
    sid = source_manager.first_source_id()
    if not sid:
        sid = source_manager.add_source(req.source.strip(), source_id="cam1", name="cam1")
    else:
        source_manager.update_source(sid, source=req.source.strip())
    return JSONResponse({"ok": True, "source": req.source, "source_id": sid})


# --------------------------------------------------------------------------- #
# Media
# --------------------------------------------------------------------------- #


def _require_detector(source_id: str) -> DetectorService:
    detector = source_manager.get_detector(source_id)
    if detector is None:
        raise HTTPException(status_code=404, detail="source not found")
    return detector


@media.get("/snapshot/{source_id}.jpg")
def snapshot_by_source(source_id: str) -> Response:
    frame = _require_detector(source_id).latest_jpeg()
    if frame is None:
        return Response(status_code=503, content=b"No frame")
    return Response(content=frame, media_type="image/jpeg", headers=NO_CACHE_HEADERS)


@media.get("/snapshot.jpg")
def snapshot_first() -> Response:
    sid = source_manager.first_source_id()
    if not sid:
        return Response(status_code=503, content=b"No source")
    return snapshot_by_source(sid)


@media.get("/stream/{source_id}.mjpg")
def stream_source(source_id: str) -> StreamingResponse:
    """Push frames as they are produced instead of having the browser poll."""
    detector = _require_detector(source_id)

    def frames():
        last_seq = -1
        while True:
            seq, jpeg = detector.wait_for_jpeg(last_seq, timeout=5.0)
            if seq == last_seq or jpeg is None:
                continue
            last_seq = seq
            yield (
                b"--frame\r\nContent-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
            )

    return StreamingResponse(
        frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers=NO_CACHE_HEADERS,
    )


app.include_router(api)
app.include_router(media)
