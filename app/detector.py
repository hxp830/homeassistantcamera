from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Prefer TCP for RTSP, disable the demuxer's input buffering (otherwise frames queue
# up and the preview runs about a second behind), and give FFmpeg a read timeout so a
# dead stream cannot block cap.read() forever. Override the whole string via the same
# environment variable if a camera needs different tuning.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|reorder_queue_size;0"
    "|max_delay;0|stimeout;5000000",
)

import cv2

logger = logging.getLogger(__name__)

DetectionCallback = Callable[[dict], None]
MEDIAPIPE_MODEL_NAME = "mediapipe_hands"

_MIN_RECONNECT_DELAY = 0.5
_MAX_RECONNECT_DELAY = 10.0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _close_quietly(instance: Any) -> None:
    closer = getattr(instance, "close", None)
    if callable(closer):
        try:
            closer()
        except Exception:
            logger.debug("Failed to close model instance", exc_info=True)


class MediaPipeHandsEngine:
    CLASS_NAMES = ["none", "fist", "open_palm", "point_up", "victory", "thumbs_up"]

    def __init__(self, min_detection_confidence: float = 0.5, min_tracking_confidence: float = 0.5) -> None:
        try:
            import mediapipe as mp  # type: ignore[import-untyped]
        except Exception as exc:  # pragma: no cover - import-time dependency failure
            raise RuntimeError("MediaPipe is not installed. Please install mediapipe first.") from exc
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    def close(self) -> None:
        self._hands.close()

    @property
    def names(self) -> list[str]:
        return list(self.CLASS_NAMES)

    def predict(self, frame) -> tuple[str, float]:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = self._hands.process(rgb)
        if not results.multi_hand_landmarks:
            return "none", 0.0

        hand_landmarks = results.multi_hand_landmarks[0]
        handedness = "Right"
        if results.multi_handedness:
            handedness = results.multi_handedness[0].classification[0].label or "Right"

        return self._classify_gesture(hand_landmarks.landmark, handedness)

    @staticmethod
    def _classify_gesture(landmarks, handedness: str) -> tuple[str, float]:
        def finger_up(tip_idx: int, pip_idx: int) -> bool:
            return landmarks[tip_idx].y < landmarks[pip_idx].y

        thumb_tip_x = landmarks[4].x
        thumb_ip_x = landmarks[3].x
        if handedness.lower() == "left":
            thumb_up = thumb_tip_x > thumb_ip_x
        else:
            thumb_up = thumb_tip_x < thumb_ip_x

        index_up = finger_up(8, 6)
        middle_up = finger_up(12, 10)
        ring_up = finger_up(16, 14)
        pinky_up = finger_up(20, 18)
        up_count = sum([thumb_up, index_up, middle_up, ring_up, pinky_up])

        if up_count == 0:
            return "fist", 0.9
        if index_up and middle_up and ring_up and pinky_up:
            return "open_palm", 0.92
        if index_up and not middle_up and not ring_up and not pinky_up:
            return "point_up", 0.9
        if index_up and middle_up and not ring_up and not pinky_up:
            return "victory", 0.9
        if thumb_up and not index_up and not middle_up and not ring_up and not pinky_up:
            return "thumbs_up", 0.88
        if up_count >= 3:
            return "open_palm", 0.7
        return "none", 0.4


@dataclass
class ModelHandle:
    """A loaded model plus the lock that serialises access to it."""

    name: str
    instance: Any
    lock: threading.Lock = field(default_factory=threading.Lock)
    shared: bool = False
    key: str = ""

    @property
    def class_names(self) -> list[str]:
        names = getattr(self.instance, "names", None)
        if isinstance(names, dict):
            return [str(names[k]) for k in sorted(names.keys())]
        if isinstance(names, (list, tuple)):
            return [str(v) for v in names]
        return []


class ModelRegistry:
    """Loads each YOLO weight file once and shares it between detectors.

    Ultralytics models are stateless across ``predict`` calls, so one instance can
    serve every camera as long as calls are serialised. MediaPipe keeps per-stream
    tracking state, so it is never shared.
    """

    def __init__(self, model_dir: Path, share: bool = True) -> None:
        self.model_dir = model_dir
        self.share = share
        self._lock = threading.Lock()
        self._handles: dict[str, ModelHandle] = {}
        self._refs: dict[str, int] = {}

    def resolve_path(self, model_file: str) -> Path:
        """Reject anything that would escape the model directory."""
        name = Path(model_file).name
        if not name or name != model_file:
            raise ValueError(f"Invalid model name: {model_file}")
        return self.model_dir / name

    def acquire(self, model_file: str) -> ModelHandle:
        if model_file == MEDIAPIPE_MODEL_NAME:
            return ModelHandle(name=model_file, instance=MediaPipeHandsEngine(), shared=False)

        model_path = self.resolve_path(model_file)
        if not model_path.is_file():
            raise FileNotFoundError(f"Model not found: {model_path}")

        if not self.share:
            return ModelHandle(name=model_file, instance=self._load_yolo(model_path), shared=False)

        key = str(model_path)
        with self._lock:
            handle = self._handles.get(key)
            if handle is None:
                handle = ModelHandle(
                    name=model_file,
                    instance=self._load_yolo(model_path),
                    shared=True,
                    key=key,
                )
                self._handles[key] = handle
                self._refs[key] = 0
            self._refs[key] += 1
            return handle

    def release(self, handle: ModelHandle | None) -> None:
        if handle is None:
            return
        if not handle.shared:
            _close_quietly(handle.instance)
            return
        with self._lock:
            remaining = self._refs.get(handle.key, 1) - 1
            if remaining > 0:
                self._refs[handle.key] = remaining
                return
            self._refs.pop(handle.key, None)
            self._handles.pop(handle.key, None)
        _close_quietly(handle.instance)

    @staticmethod
    def _load_yolo(model_path: Path) -> Any:
        # Imported lazily: pulling in torch costs seconds of start-up time and is
        # pure waste when only MediaPipe is used.
        from ultralytics import YOLO

        logger.info("Loading YOLO weights: %s", model_path)
        return YOLO(str(model_path))


class DetectorService:
    def __init__(
        self,
        model_registry: ModelRegistry,
        model_file: str,
        source: str,
        detector_id: str,
        conf: float,
        iou: float,
        img_size: int,
        detect_interval: float,
        jpeg_quality: int = 80,
        preview_width: int = 0,
        preview_fps: float = 15.0,
        idle_encode_timeout: float = 15.0,
        on_detection: DetectionCallback | None = None,
    ) -> None:
        self.registry = model_registry
        self.source = source
        self.detector_id = detector_id
        self.conf = conf
        self.iou = iou
        self.img_size = img_size
        self.detect_interval = max(0.05, detect_interval)
        self.preview_width = preview_width
        self.preview_interval = 1.0 / preview_fps if preview_fps > 0 else 0.0
        self.idle_encode_timeout = idle_encode_timeout
        self.on_detection = on_detection
        self._encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)]

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self._preview_thread: threading.Thread | None = None

        # Single-slot handoff from the capture loop to the inference worker.
        self._job_cv = threading.Condition()
        self._pending_frame = None

        # Single-slot handoff from the capture loop to the preview encoder. Keeping
        # overlay drawing and JPEG encoding off the capture thread is what stops the
        # decoder queue from backing up on RTSP sources.
        self._preview_cv = threading.Condition()
        self._preview_frame = None

        # Wakes MJPEG subscribers as soon as a new frame is encoded.
        self._frame_cv = threading.Condition()
        self._latest_jpeg: bytes | None = None
        self._frame_seq = 0

        self._handle = model_registry.acquire(model_file)
        self._infer_running = False
        self._last_infer_ts = 0.0
        self._last_label = "none"
        self._last_conf = 0.0
        self._last_error = ""
        self._last_viewer_ts = 0.0
        self._connected = False
        self._fps = 0.0
        self._latest_result: dict = {
            "source_id": self.detector_id,
            "gesture": "none",
            "confidence": 0.0,
            "timestamp": _utc_now_iso(),
            "model": model_file,
        }

    @property
    def model_name(self) -> str:
        with self._lock:
            return self._handle.name

    @property
    def class_names(self) -> list[str]:
        with self._lock:
            handle = self._handle
        return self._class_names_of(handle)

    @staticmethod
    def _class_names_of(handle: ModelHandle) -> list[str]:
        if handle.name == MEDIAPIPE_MODEL_NAME:
            return list(MediaPipeHandsEngine.CLASS_NAMES)
        return handle.class_names

    def set_source(self, source: str) -> None:
        with self._lock:
            self.source = source

    def set_model(self, model_file: str) -> None:
        """Swap models without dropping frames; the old handle is released after."""
        new_handle = self.registry.acquire(model_file)
        with self._lock:
            old_handle = self._handle
            self._handle = new_handle
        if old_handle is not new_handle:
            self.registry.release(old_handle)

    def get_status(self) -> dict:
        with self._lock:
            handle = self._handle
            status = {
                "source_id": self.detector_id,
                "source": self.source,
                "model": handle.name,
                "worker_alive": bool(self._capture_thread and self._capture_thread.is_alive()),
                "connected": self._connected,
                "fps": round(self._fps, 1),
                "last_error": self._last_error,
                "latest": self._latest_result,
            }
        status["classes"] = self._class_names_of(handle)
        return status

    def mark_viewer(self) -> None:
        """Record live interest so the capture loop knows to encode JPEG frames."""
        with self._lock:
            self._last_viewer_ts = time.time()

    def latest_jpeg(self) -> bytes | None:
        self.mark_viewer()
        with self._frame_cv:
            if self._latest_jpeg is not None:
                return self._latest_jpeg
            # No encoded frame yet (idle encoding); wait briefly for the next one.
            self._frame_cv.wait(timeout=2.0)
            return self._latest_jpeg

    def wait_for_jpeg(self, last_seq: int, timeout: float = 5.0) -> tuple[int, bytes | None]:
        self.mark_viewer()
        with self._frame_cv:
            if self._frame_seq == last_seq or self._latest_jpeg is None:
                self._frame_cv.wait(timeout=timeout)
            return self._frame_seq, self._latest_jpeg

    def start(self) -> None:
        if self._capture_thread and self._capture_thread.is_alive():
            return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._inference_loop, name=f"infer-{self.detector_id}", daemon=True
        )
        self._worker_thread.start()
        self._preview_thread = threading.Thread(
            target=self._preview_loop, name=f"preview-{self.detector_id}", daemon=True
        )
        self._preview_thread.start()
        self._capture_thread = threading.Thread(
            target=self._capture_loop, name=f"capture-{self.detector_id}", daemon=True
        )
        self._capture_thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        with self._job_cv:
            self._job_cv.notify_all()
        with self._preview_cv:
            self._preview_cv.notify_all()
        with self._frame_cv:
            self._frame_cv.notify_all()
        for thread in (self._capture_thread, self._worker_thread, self._preview_thread):
            if thread and thread.is_alive():
                thread.join(timeout=3)
        with self._lock:
            handle = self._handle
        self.registry.release(handle)

    @staticmethod
    def _open_capture(source: str) -> cv2.VideoCapture:
        parsed = int(source) if source.isdigit() else source
        cap = cv2.VideoCapture(parsed, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(parsed)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _submit_frame(self, frame) -> bool:
        """Hand a frame to the worker. Returns False when the worker is busy."""
        with self._job_cv:
            if self._pending_frame is not None:
                return False
            self._pending_frame = frame
            self._job_cv.notify()
        return True

    def _publish_frame(self, jpeg: bytes) -> None:
        with self._frame_cv:
            self._latest_jpeg = jpeg
            self._frame_seq += 1
            self._frame_cv.notify_all()

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message

    def _should_encode(self) -> bool:
        if self.idle_encode_timeout <= 0:
            return True
        with self._lock:
            last_viewer = self._last_viewer_ts
        return (time.time() - last_viewer) <= self.idle_encode_timeout

    def _build_preview(self, frame):
        height, width = frame.shape[:2]
        if self.preview_width and width > self.preview_width:
            scale = self.preview_width / float(width)
            # resize allocates a new array, so no extra copy is needed afterwards.
            return cv2.resize(frame, (self.preview_width, max(1, int(height * scale))), interpolation=cv2.INTER_AREA)
        # The capture thread still owns the original buffer, so never draw on it.
        return frame.copy()

    def _submit_preview(self, frame) -> None:
        """Replace any frame the encoder has not picked up yet, so it never lags behind."""
        with self._preview_cv:
            self._preview_frame = frame
            self._preview_cv.notify()

    def _preview_loop(self) -> None:
        last_encode_ts = 0.0
        while not self._stop_event.is_set():
            with self._preview_cv:
                while self._preview_frame is None and not self._stop_event.is_set():
                    self._preview_cv.wait(timeout=0.5)
                if self._stop_event.is_set():
                    return
                frame = self._preview_frame
                self._preview_frame = None

            now = time.time()
            if self.preview_interval:
                wait = self.preview_interval - (now - last_encode_ts)
                if wait > 0:
                    if self._stop_event.wait(wait):
                        return
                    now = time.time()
            last_encode_ts = now

            try:
                with self._lock:
                    label = self._last_label
                    confidence = self._last_conf
                preview = self._build_preview(frame)
                self._draw_overlay(preview, label, confidence)
                ok, buffer = cv2.imencode(".jpg", preview, self._encode_params)
                if ok:
                    self._publish_frame(buffer.tobytes())
            except Exception as exc:
                logger.warning("[%s] preview encoding failed: %s", self.detector_id, exc)

    def _draw_overlay(self, frame, label: str, confidence: float) -> None:
        cv2.putText(
            frame,
            f"{label} {confidence * 100.0:.1f}%",
            (18, 38),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            frame,
            datetime.now().strftime("%H:%M:%S"),
            (18, 72),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 255),
            2,
        )

    def _inference_loop(self) -> None:
        while not self._stop_event.is_set():
            with self._job_cv:
                while self._pending_frame is None and not self._stop_event.is_set():
                    self._job_cv.wait(timeout=0.5)
                if self._stop_event.is_set():
                    return
                frame = self._pending_frame
                self._pending_frame = None
            with self._lock:
                handle = self._handle
            try:
                self._run_inference(frame, handle)
            finally:
                with self._lock:
                    self._infer_running = False
                    self._last_infer_ts = time.time()

    def _run_inference(self, frame, handle: ModelHandle) -> None:
        try:
            with handle.lock:
                if handle.name == MEDIAPIPE_MODEL_NAME:
                    best_name, best_conf = handle.instance.predict(frame)
                else:
                    best_name, best_conf = self._predict_yolo(frame, handle)

            payload = {
                "source_id": self.detector_id,
                "gesture": best_name,
                "confidence": best_conf,
                "timestamp": _utc_now_iso(),
                "model": handle.name,
            }
            with self._lock:
                self._last_label = best_name
                self._last_conf = best_conf
                self._latest_result = payload
                self._last_error = ""
            if self.on_detection:
                self.on_detection(payload)
        except Exception as exc:
            logger.warning("[%s] inference failed: %s", self.detector_id, exc)
            self._set_error(f"infer_error: {exc}")

    def _predict_yolo(self, frame, handle: ModelHandle) -> tuple[str, float]:
        results = handle.instance.predict(
            frame,
            conf=self.conf,
            iou=self.iou,
            imgsz=self.img_size,
            verbose=False,
        )
        result = results[0]
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return "none", 0.0

        confidences = boxes.conf.cpu().tolist()
        classes = boxes.cls.cpu().tolist()
        best_idx = max(range(len(confidences)), key=lambda i: confidences[i])
        names = getattr(result, "names", {})
        class_idx = int(classes[best_idx])
        return str(names.get(class_idx, class_idx)), float(confidences[best_idx])

    def _capture_loop(self) -> None:
        cap: cv2.VideoCapture | None = None
        active_source: str | None = None
        reconnect_delay = _MIN_RECONNECT_DELAY
        last_frame_ts = time.time()
        read_failures = 0
        fps_window_start = time.time()
        fps_frames = 0

        try:
            while not self._stop_event.is_set():
                try:
                    with self._lock:
                        source = self.source
                        infer_running = self._infer_running
                        last_infer_ts = self._last_infer_ts

                    if cap is None or source != active_source or not cap.isOpened():
                        if cap is not None:
                            cap.release()
                        cap = self._open_capture(source)
                        active_source = source
                        read_failures = 0
                        last_frame_ts = time.time()
                        if not cap.isOpened():
                            with self._lock:
                                self._connected = False
                                self._last_error = "capture_open_failed"
                            cap.release()
                            cap = None
                            self._stop_event.wait(reconnect_delay)
                            reconnect_delay = min(_MAX_RECONNECT_DELAY, reconnect_delay * 2)
                            continue
                        reconnect_delay = _MIN_RECONNECT_DELAY
                        with self._lock:
                            self._connected = True
                            self._last_error = ""
                        continue

                    ok, frame = cap.read()
                    if not ok or frame is None:
                        read_failures += 1
                        with self._lock:
                            self._last_error = "capture_read_failed"
                            self._connected = False
                        if read_failures >= 25 or (time.time() - last_frame_ts) >= 5:
                            cap.release()
                            cap = None
                            read_failures = 0
                        self._stop_event.wait(0.05)
                        continue

                    read_failures = 0
                    last_frame_ts = time.time()
                    fps_frames += 1
                    elapsed = last_frame_ts - fps_window_start
                    if elapsed >= 2.0:
                        with self._lock:
                            self._fps = fps_frames / elapsed
                            self._connected = True
                        fps_frames = 0
                        fps_window_start = last_frame_ts

                    if (not infer_running) and (last_frame_ts - last_infer_ts >= self.detect_interval):
                        with self._lock:
                            self._infer_running = True
                        if not self._submit_frame(frame):
                            with self._lock:
                                self._infer_running = False

                    # Hand the frame off and go straight back to reading; anything
                    # slower than the stream rate here shows up as preview latency.
                    if self._should_encode():
                        self._submit_preview(frame)
                except Exception as exc:
                    logger.warning("[%s] capture loop error: %s", self.detector_id, exc)
                    with self._lock:
                        self._last_error = str(exc)
                        self._connected = False
                    if cap is not None:
                        cap.release()
                        cap = None
                    read_failures = 0
                    self._stop_event.wait(reconnect_delay)
                    reconnect_delay = min(_MAX_RECONNECT_DELAY, reconnect_delay * 2)
        finally:
            if cap is not None:
                cap.release()
            with self._lock:
                self._connected = False
