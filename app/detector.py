from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Prefer TCP for RTSP to reduce packet-loss freezes on unstable networks.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2
from ultralytics import YOLO


DetectionCallback = Callable[[dict], None]
MEDIAPIPE_MODEL_NAME = "mediapipe_hands"


class MediaPipeHandsEngine:
    CLASS_NAMES = ["none", "fist", "open_palm", "point_up", "victory", "thumbs_up"]

    def __init__(self) -> None:
        try:
            import mediapipe as mp  # type: ignore[import-untyped]
        except Exception as exc:  # pragma: no cover - import-time dependency failure
            raise RuntimeError("MediaPipe is not installed. Please install mediapipe first.") from exc
        self._mp = mp
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def close(self) -> None:
        self._hands.close()

    def predict(self, frame) -> tuple[str, float]:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
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


class DetectorService:
    def __init__(
        self,
        model_dir: Path,
        model_file: str,
        source: str,
        detector_id: str,
        conf: float,
        iou: float,
        img_size: int,
        detect_interval: float,
        on_detection: DetectionCallback | None = None,
    ) -> None:
        self.model_dir = model_dir
        self.model_file = model_file
        self.source = source
        self.detector_id = detector_id
        self.conf = conf
        self.iou = iou
        self.img_size = img_size
        self.detect_interval = max(0.05, detect_interval)
        self.on_detection = on_detection

        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._model = self._load_model(model_file)
        self._model_name = model_file
        self._infer_running = False
        self._last_infer_ts = 0.0
        self._last_label = "none"
        self._last_conf = 0.0
        self._latest_jpeg: bytes | None = None
        self._last_error = ""
        self._latest_result: dict = {
            "source_id": self.detector_id,
            "gesture": "none",
            "confidence": 0.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": self._model_name,
        }

    @property
    def class_names(self) -> list[str]:
        if self._model_name == MEDIAPIPE_MODEL_NAME:
            return list(MediaPipeHandsEngine.CLASS_NAMES)
        names = getattr(self._model, "names", {})
        if isinstance(names, dict):
            return [names[k] for k in sorted(names.keys())]
        return [str(v) for v in names]

    def _close_model(self, model: Any) -> None:
        closer = getattr(model, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass

    def _load_model(self, model_file: str) -> Any:
        if model_file == MEDIAPIPE_MODEL_NAME:
            return MediaPipeHandsEngine()
        model_path = self.model_dir / model_file
        if not model_path.exists():
            raise FileNotFoundError(f"Model not found: {model_path}")
        return YOLO(str(model_path))

    def set_source(self, source: str) -> None:
        with self._lock:
            self.source = source

    def set_model(self, model_file: str) -> None:
        new_model = self._load_model(model_file)
        with self._lock:
            old_model = self._model
            self._model = new_model
            self._model_name = model_file
            infer_running = self._infer_running
        if not infer_running:
            self._close_model(old_model)

    def get_status(self) -> dict:
        with self._lock:
            return {
                "source_id": self.detector_id,
                "source": self.source,
                "model": self._model_name,
                "classes": self.class_names,
                "worker_alive": bool(self._thread and self._thread.is_alive()),
                "last_error": self._last_error,
                "latest": self._latest_result,
            }

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        with self._lock:
            model = self._model
        self._close_model(model)

    @staticmethod
    def _to_capture_source(source: str):
        return int(source) if source.isdigit() else source

    @staticmethod
    def _open_capture(source: str) -> cv2.VideoCapture:
        parsed = int(source) if source.isdigit() else source
        cap = cv2.VideoCapture(parsed, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(parsed)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _run_inference(self, frame, model: Any, model_name: str) -> None:
        try:
            if model_name == MEDIAPIPE_MODEL_NAME:
                best_name, best_conf = model.predict(frame)
            else:
                results = model.predict(frame, conf=self.conf, iou=self.iou, imgsz=self.img_size, verbose=False)
                result = results[0]
                best_name = "none"
                best_conf = 0.0
                if result.boxes is not None and len(result.boxes) > 0:
                    confidences = result.boxes.conf.cpu().tolist()
                    classes = result.boxes.cls.cpu().tolist()
                    best_idx = max(range(len(confidences)), key=lambda i: confidences[i])
                    best_conf = float(confidences[best_idx])
                    class_idx = int(classes[best_idx])
                    names = getattr(result, "names", {})
                    best_name = str(names.get(class_idx, class_idx))

            payload = {
                "source_id": self.detector_id,
                "gesture": best_name,
                "confidence": best_conf,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "model": model_name,
            }
            with self._lock:
                self._last_label = best_name
                self._last_conf = best_conf
                self._last_infer_ts = time.time()
                self._latest_result = payload
                self._last_error = ""
            if self.on_detection:
                self.on_detection(payload)
        except Exception as exc:
            with self._lock:
                self._last_error = f"infer_error: {exc}"
        finally:
            with self._lock:
                self._infer_running = False

    def _loop(self) -> None:
        cap = None
        active_source = None
        read_failures = 0
        last_frame_ts = time.time()
        while not self._stop_event.is_set():
            try:
                with self._lock:
                    source = self.source
                    model = self._model
                    model_name = self._model_name
                    infer_running = self._infer_running
                    last_infer_ts = self._last_infer_ts
                    last_label = self._last_label
                    last_conf = self._last_conf

                if cap is None or source != active_source or not cap.isOpened():
                    if cap is not None:
                        cap.release()
                    cap = self._open_capture(source)
                    active_source = source
                    read_failures = 0
                    last_frame_ts = time.time()
                    if not cap.isOpened():
                        with self._lock:
                            self._last_error = "capture_open_failed"
                        time.sleep(0.4)
                        continue
                    time.sleep(0.2)
                    continue

                ok, frame = cap.read()
                if not ok or frame is None:
                    with self._lock:
                        self._last_error = "capture_read_failed"
                    read_failures += 1
                    stale_seconds = time.time() - last_frame_ts
                    if read_failures >= 25 or stale_seconds >= 5:
                        cap.release()
                        cap = None
                        read_failures = 0
                    time.sleep(0.05)
                    continue
                read_failures = 0
                last_frame_ts = time.time()
                now = time.time()

                # Keep preview live and trigger inference asynchronously.
                if (not infer_running) and (now - last_infer_ts >= self.detect_interval):
                    with self._lock:
                        self._infer_running = True
                    infer_frame = frame.copy()
                    threading.Thread(
                        target=self._run_inference,
                        args=(infer_frame, model, model_name),
                        daemon=True,
                    ).start()

                frame_to_show = frame.copy()
                overlay = f"{last_label} {last_conf * 100.0:.1f}%"
                cv2.putText(frame_to_show, overlay, (18, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
                clock_text = datetime.now().strftime("%H:%M:%S")
                cv2.putText(frame_to_show, clock_text, (18, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)
                ok_jpg, jpg = cv2.imencode(".jpg", frame_to_show)
                if ok_jpg:
                    with self._lock:
                        self._latest_jpeg = jpg.tobytes()
                        self._last_error = ""

                time.sleep(0.005)
            except Exception as exc:
                with self._lock:
                    self._last_error = str(exc)
                if cap is not None:
                    cap.release()
                    cap = None
                read_failures = 0
                time.sleep(0.2)

        if cap is not None:
            cap.release()
