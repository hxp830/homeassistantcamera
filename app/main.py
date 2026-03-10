from __future__ import annotations

import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from app.config import load_settings
from app.detector import MEDIAPIPE_MODEL_NAME, DetectorService
from app.mqtt_bridge import MqttBridge


settings = load_settings()
app = FastAPI(title="YOLO Gesture + Home Assistant")

model_dir = Path(settings.model_dir)
model_dir.mkdir(parents=True, exist_ok=True)


class SourceCreateReq(BaseModel):
    source: str
    name: str = ""
    labels: str = ""


class SourceUpdateReq(BaseModel):
    source: str | None = None
    name: str | None = None
    labels: str | None = None
    model: str | None = None


class ActivateModelReq(BaseModel):
    name: str


class MqttConfigReq(BaseModel):
    host: str
    port: int
    user: str = ""
    password: str = ""
    client_id: str
    discovery_prefix: str
    state_topic: str


class MqttTestReq(BaseModel):
    host: str
    port: int
    user: str = ""
    password: str = ""
    client_id: str
    discovery_prefix: str
    state_topic: str


mqtt_config = {
    "host": settings.mqtt_host,
    "port": settings.mqtt_port,
    "user": settings.mqtt_user,
    "password": settings.mqtt_password,
    "client_id": settings.mqtt_client_id,
    "discovery_prefix": settings.mqtt_discovery_prefix,
    "state_topic": settings.mqtt_state_topic,
}
mqtt_lock = threading.Lock()


def _build_mqtt_bridge(cfg: dict) -> MqttBridge:
    return MqttBridge(
        host=cfg["host"],
        port=int(cfg["port"]),
        client_id=cfg["client_id"],
        discovery_prefix=cfg["discovery_prefix"],
        state_topic=cfg["state_topic"],
        username=cfg["user"],
        password=cfg["password"],
    )


mqtt_bridge = _build_mqtt_bridge(mqtt_config)


class SourceManager:
    def __init__(self, model_file: str) -> None:
        self._lock = threading.Lock()
        self._model_file = model_file
        self._detectors: dict[str, DetectorService] = {}
        self._names: dict[str, str] = {}
        self._labels: dict[str, set[str]] = {}

    @staticmethod
    def _parse_labels(text: str) -> set[str]:
        return {x.strip().lower() for x in text.split(",") if x.strip()}

    def _on_detection(self, payload: dict) -> None:
        source_id = payload.get("source_id", "")
        gesture = str(payload.get("gesture", "")).strip().lower()
        with self._lock:
            labels = set(self._labels.get(source_id, set()))
        if labels and gesture not in labels:
            return
        with mqtt_lock:
            bridge = mqtt_bridge
        bridge.publish_state(
            gesture=payload["gesture"],
            confidence=payload["confidence"],
            model=payload["model"],
            timestamp=payload["timestamp"],
            source_id=payload.get("source_id", ""),
        )

    def add_source(self, source: str, source_id: str | None = None, name: str = "", labels: str = "") -> str:
        with self._lock:
            sid = source_id or f"cam_{uuid.uuid4().hex[:8]}"
            if sid in self._detectors:
                raise ValueError(f"Source id exists: {sid}")
            detector = DetectorService(
                model_dir=model_dir,
                model_file=self._model_file,
                source=source,
                detector_id=sid,
                conf=settings.conf,
                iou=settings.iou,
                img_size=settings.image_size,
                detect_interval=settings.detect_interval,
                on_detection=self._on_detection,
            )
            self._detectors[sid] = detector
            self._names[sid] = (name or sid).strip() or sid
            self._labels[sid] = self._parse_labels(labels or "")
            detector.start()
            return sid

    def remove_source(self, source_id: str) -> bool:
        with self._lock:
            detector = self._detectors.pop(source_id, None)
        if detector is None:
            return False
        detector.stop()
        with self._lock:
            self._names.pop(source_id, None)
            self._labels.pop(source_id, None)
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
        if detector is None:
            return False
        if source is not None:
            detector.set_source(source)
        if name is not None:
            with self._lock:
                self._names[source_id] = name.strip() or source_id
        if labels is not None:
            with self._lock:
                self._labels[source_id] = self._parse_labels(labels)
        if model is not None:
            detector.set_model(model)
        return True

    def set_model(self, model_file: str) -> None:
        with self._lock:
            self._model_file = model_file
            detectors = list(self._detectors.values())
        for d in detectors:
            d.set_model(model_file)

    def class_names(self) -> list[str]:
        with self._lock:
            detectors = list(self._detectors.values())
        if detectors:
            return detectors[0].class_names
        return []

    def list_status(self) -> list[dict]:
        with self._lock:
            detectors = list(self._detectors.values())
            names = dict(self._names)
            labels_map = {k: sorted(v) for k, v in self._labels.items()}
        output = []
        for d in detectors:
            item = d.get_status()
            item["name"] = names.get(item["source_id"], item["source_id"])
            labels = labels_map.get(item["source_id"], [])
            item["labels"] = labels
            item["labels_text"] = ", ".join(labels)
            output.append(item)
        return output

    def list_sources_brief(self) -> list[dict]:
        with self._lock:
            source_ids = list(self._detectors.keys())
            names = dict(self._names)
        return [{"source_id": sid, "name": names.get(sid, sid)} for sid in source_ids]

    def latest_jpeg(self, source_id: str) -> bytes | None:
        with self._lock:
            detector = self._detectors.get(source_id)
        if detector is None:
            return None
        return detector.latest_jpeg()

    def first_source_id(self) -> str | None:
        with self._lock:
            for sid in self._detectors:
                return sid
        return None

    def stop_all(self) -> None:
        with self._lock:
            detectors = list(self._detectors.values())
            self._detectors.clear()
        for d in detectors:
            d.stop()


def _choose_startup_model() -> str:
    default_model = model_dir / settings.model_file
    if settings.model_file == MEDIAPIPE_MODEL_NAME:
        return MEDIAPIPE_MODEL_NAME
    if default_model.exists() and default_model.suffix.lower() == ".pt":
        return settings.model_file
    candidates = sorted(model_dir.glob("*.pt"))
    if candidates:
        return candidates[0].name
    return MEDIAPIPE_MODEL_NAME


def _validate_model_name(model_name: str) -> None:
    if model_name == MEDIAPIPE_MODEL_NAME:
        return
    model_path = model_dir / model_name
    if model_path.suffix.lower() != ".pt" or not model_path.exists():
        raise HTTPException(status_code=404, detail=f"model not found: {model_name}")


source_manager = SourceManager(model_file=_choose_startup_model())


@app.on_event("startup")
def startup() -> None:
    with mqtt_lock:
        mqtt_bridge.start()
    source_manager.add_source(settings.source, source_id="cam1", name="cam1", labels="")
    with mqtt_lock:
        mqtt_bridge.publish_discovery(source_manager.class_names(), source_manager.list_sources_brief())


@app.on_event("shutdown")
def shutdown() -> None:
    source_manager.stop_all()
    with mqtt_lock:
        mqtt_bridge.stop()


@app.get("/")
def ui() -> FileResponse:
    return FileResponse(
        Path("app/static/index.html"),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/api/status")
def status() -> JSONResponse:
    return JSONResponse(
        {
            "model": source_manager._model_file,
            "sources": source_manager.list_status(),
        }
    )


@app.get("/api/mqtt")
def get_mqtt() -> JSONResponse:
    with mqtt_lock:
        return JSONResponse(mqtt_config)


@app.put("/api/mqtt")
def set_mqtt(req: MqttConfigReq) -> JSONResponse:
    global mqtt_bridge
    new_cfg = {
        "host": req.host.strip(),
        "port": int(req.port),
        "user": req.user.strip(),
        "password": req.password,
        "client_id": req.client_id.strip(),
        "discovery_prefix": req.discovery_prefix.strip(),
        "state_topic": req.state_topic.strip(),
    }
    if not new_cfg["host"] or not new_cfg["client_id"]:
        raise HTTPException(status_code=400, detail="MQTT host/client_id required")

    new_bridge = _build_mqtt_bridge(new_cfg)
    with mqtt_lock:
        old_bridge = mqtt_bridge
        try:
            new_bridge.start()
            mqtt_bridge = new_bridge
            mqtt_config.update(new_cfg)
            mqtt_bridge.publish_discovery(source_manager.class_names(), source_manager.list_sources_brief())
            old_bridge.stop()
        except Exception as exc:
            try:
                new_bridge.stop()
            except Exception:
                pass
            raise HTTPException(status_code=400, detail=f"MQTT connect failed: {exc}")

    return JSONResponse({"ok": True, "mqtt": mqtt_config})


@app.post("/api/mqtt/test")
def test_mqtt(req: MqttTestReq) -> JSONResponse:
    cfg = {
        "host": req.host.strip(),
        "port": int(req.port),
        "user": req.user.strip(),
        "password": req.password,
        "client_id": req.client_id.strip() or "gesture_yolo_test",
        "discovery_prefix": req.discovery_prefix.strip() or "homeassistant",
        "state_topic": req.state_topic.strip() or "gesture_yolo_ha/state",
    }
    bridge = _build_mqtt_bridge(cfg)
    try:
        bridge.start()
        bridge.publish_state(
            gesture="mqtt_test_ok",
            confidence=1.0,
            model="test",
            timestamp="now",
            source_id="_test",
        )
    except Exception as exc:
        try:
            bridge.stop()
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=f"MQTT test failed: {exc}")
    bridge.stop()
    return JSONResponse({"ok": True, "message": "MQTT connect and publish success"})


@app.get("/api/models")
def list_models() -> JSONResponse:
    files = [MEDIAPIPE_MODEL_NAME] + sorted([p.name for p in model_dir.glob("*.pt")])
    return JSONResponse({"models": files})


@app.post("/api/models/upload")
async def upload_model(file: UploadFile = File(...)) -> JSONResponse:
    if not file.filename or not file.filename.endswith(".pt"):
        raise HTTPException(status_code=400, detail="Only .pt model files are supported")

    dst = model_dir / Path(file.filename).name
    with dst.open("wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    return JSONResponse({"ok": True, "file": dst.name})


@app.post("/api/models/activate")
def activate_model(req: ActivateModelReq) -> JSONResponse:
    _validate_model_name(req.name)
    source_manager.set_model(req.name)
    with mqtt_lock:
        mqtt_bridge.publish_discovery(source_manager.class_names(), source_manager.list_sources_brief())
    return JSONResponse({"ok": True, "active": req.name})


@app.get("/api/sources")
def list_sources() -> JSONResponse:
    return JSONResponse({"sources": source_manager.list_status()})


@app.post("/api/sources")
def add_source(req: SourceCreateReq) -> JSONResponse:
    sid = source_manager.add_source(req.source, name=req.name, labels=req.labels)
    with mqtt_lock:
        mqtt_bridge.publish_discovery(source_manager.class_names(), source_manager.list_sources_brief())
    return JSONResponse({"ok": True, "source_id": sid})


@app.put("/api/sources/{source_id}")
def update_source(source_id: str, req: SourceUpdateReq) -> JSONResponse:
    if req.model is not None:
        _validate_model_name(req.model)
    ok = source_manager.update_source(
        source_id,
        source=req.source,
        name=req.name,
        labels=req.labels,
        model=req.model,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="source not found")
    if req.name is not None:
        with mqtt_lock:
            mqtt_bridge.publish_discovery(source_manager.class_names(), source_manager.list_sources_brief())
    return JSONResponse({"ok": True})


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: str) -> JSONResponse:
    ok = source_manager.remove_source(source_id)
    if not ok:
        raise HTTPException(status_code=404, detail="source not found")
    with mqtt_lock:
        mqtt_bridge.clear_source_discovery(source_id)
        mqtt_bridge.publish_discovery(source_manager.class_names(), source_manager.list_sources_brief())
    return JSONResponse({"ok": True})


@app.get("/snapshot/{source_id}.jpg")
def snapshot_by_source(source_id: str) -> Response:
    frame = source_manager.latest_jpeg(source_id)
    if frame is None:
        return Response(status_code=503, content=b"No frame")
    return Response(
        content=frame,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/snapshot.jpg")
def snapshot_first() -> Response:
    sid = source_manager.first_source_id()
    if not sid:
        return Response(status_code=503, content=b"No source")
    return snapshot_by_source(sid)


@app.post("/api/source")
def set_source_compat(req: SourceUpdateReq) -> JSONResponse:
    sid = source_manager.first_source_id()
    if req.source is None:
        raise HTTPException(status_code=400, detail="source required")
    if not sid:
        sid = source_manager.add_source(req.source, source_id="cam1", name="cam1", labels="")
        return JSONResponse({"ok": True, "source": req.source, "source_id": sid})
    source_manager.update_source(sid, source=req.source)
    return JSONResponse({"ok": True, "source": req.source, "source_id": sid})
