from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterable

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

PAYLOAD_AVAILABLE = "online"
PAYLOAD_NOT_AVAILABLE = "offline"


class MqttBridge:
    """Publishes gesture state and Home Assistant discovery config over MQTT.

    Connection is established asynchronously so a broker that is down or slow can
    never block or crash application start-up; paho reconnects on its own and
    discovery is re-published on every successful (re)connect.
    """

    def __init__(
        self,
        host: str,
        port: int,
        client_id: str,
        discovery_prefix: str,
        state_topic: str,
        username: str = "",
        password: str = "",
        keepalive: int = 60,
        publish_mode: str = "change",
        heartbeat: float = 60.0,
    ) -> None:
        self.host = host
        self.port = port
        self.discovery_prefix = discovery_prefix.rstrip("/")
        self.state_topic = state_topic.rstrip("/")
        self.client_id = client_id
        self.keepalive = keepalive
        self.publish_mode = publish_mode if publish_mode in ("change", "always") else "change"
        self.heartbeat = heartbeat

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=30)
        self.client.will_set(self.availability_topic, PAYLOAD_NOT_AVAILABLE, retain=True)

        self._connected = threading.Event()
        self._started = False
        self._lock = threading.Lock()
        self._class_names: list[str] = []
        self._sources: list[dict] = []
        self._last_published: dict[str, tuple[str, float]] = {}

    @property
    def availability_topic(self) -> str:
        return f"{self.state_topic}/availability"

    @property
    def connected(self) -> bool:
        return self._connected.is_set()

    def start(self, wait_timeout: float = 0.0) -> bool:
        """Start the network loop. Returns True once connected within wait_timeout."""
        if not self._started:
            self.client.connect_async(self.host, self.port, keepalive=self.keepalive)
            self.client.loop_start()
            self._started = True
        if wait_timeout > 0:
            return self._connected.wait(timeout=wait_timeout)
        return self.connected

    def stop(self) -> None:
        if not self._started:
            return
        try:
            if self.connected:
                self.client.publish(self.availability_topic, PAYLOAD_NOT_AVAILABLE, retain=True)
            self.client.disconnect()
        except Exception:
            logger.debug("MQTT disconnect failed", exc_info=True)
        finally:
            self.client.loop_stop()
            self._started = False
            self._connected.clear()

    def _on_connect(self, client: mqtt.Client, userdata, flags, reason_code, properties) -> None:
        if reason_code != 0:
            logger.warning("MQTT connect refused: %s", reason_code)
            return
        logger.info("MQTT connected to %s:%s", self.host, self.port)
        self._connected.set()
        client.publish(self.availability_topic, PAYLOAD_AVAILABLE, retain=True)
        with self._lock:
            class_names = list(self._class_names)
            sources = list(self._sources)
        self.publish_discovery(class_names, sources)

    def _on_disconnect(self, client: mqtt.Client, userdata, flags, reason_code, properties) -> None:
        self._connected.clear()
        if reason_code != 0:
            logger.warning("MQTT disconnected unexpectedly: %s", reason_code)

    def _state_topic_for(self, source_id: str) -> str:
        return f"{self.state_topic}/{(source_id or 'default').strip()}"

    def publish_discovery(self, class_names: Iterable[str], sources: list[dict] | None = None) -> None:
        with self._lock:
            self._class_names = list(class_names)
            self._sources = list(sources or []) or [{"source_id": "cam1", "name": "cam1"}]
            targets = list(self._sources)

        # Clear legacy single-source entities published by older versions.
        for suffix in ("gesture", "confidence"):
            self.client.publish(
                f"{self.discovery_prefix}/sensor/{self.client_id}/{suffix}/config", "", retain=True
            )

        for src in targets:
            source_id = str(src.get("source_id", "cam1"))
            source_name = str(src.get("name", source_id))
            entity_key = f"{self.client_id}_{source_id}"
            src_state_topic = self._state_topic_for(source_id)
            device = {
                "identifiers": [entity_key],
                "name": f"YOLO {source_name}",
                "manufacturer": "Custom",
                "model": "YOLO + FastAPI",
            }
            availability = {
                "availability_topic": self.availability_topic,
                "payload_available": PAYLOAD_AVAILABLE,
                "payload_not_available": PAYLOAD_NOT_AVAILABLE,
            }

            gesture_payload = {
                "name": f"{source_name} Gesture",
                "unique_id": f"{entity_key}_gesture",
                "state_topic": src_state_topic,
                "value_template": "{{ value_json.gesture }}",
                "icon": "mdi:hand-back-right",
                "json_attributes_topic": src_state_topic,
                "device": device,
                **availability,
            }
            confidence_payload = {
                "name": f"{source_name} Gesture Confidence",
                "unique_id": f"{entity_key}_confidence",
                "state_topic": src_state_topic,
                "value_template": "{{ value_json.confidence }}",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "icon": "mdi:percent",
                "device": device,
                **availability,
            }

            self.client.publish(
                f"{self.discovery_prefix}/sensor/{entity_key}/gesture/config",
                json.dumps(gesture_payload),
                retain=True,
            )
            self.client.publish(
                f"{self.discovery_prefix}/sensor/{entity_key}/confidence/config",
                json.dumps(confidence_payload),
                retain=True,
            )

    def clear_source_discovery(self, source_id: str) -> None:
        entity_key = f"{self.client_id}_{source_id}"
        for suffix in ("gesture", "confidence"):
            self.client.publish(
                f"{self.discovery_prefix}/sensor/{entity_key}/{suffix}/config", "", retain=True
            )
        with self._lock:
            self._last_published.pop(source_id, None)

    def _should_publish(self, source_id: str, gesture: str) -> bool:
        if self.publish_mode == "always":
            return True
        now = time.time()
        with self._lock:
            previous = self._last_published.get(source_id)
            if previous is not None:
                last_gesture, last_ts = previous
                if last_gesture == gesture and (self.heartbeat <= 0 or now - last_ts < self.heartbeat):
                    return False
            self._last_published[source_id] = (gesture, now)
        return True

    def publish_state(
        self,
        gesture: str,
        confidence: float,
        model: str,
        timestamp: str,
        source_id: str = "",
        force: bool = False,
    ) -> None:
        if not force and not self._should_publish(source_id, gesture):
            return
        payload = {
            "gesture": gesture,
            "confidence": round(confidence * 100.0, 2),
            "model": model,
            "timestamp": timestamp,
            "source_id": source_id,
        }
        self.client.publish(self._state_topic_for(source_id), json.dumps(payload), retain=False)
