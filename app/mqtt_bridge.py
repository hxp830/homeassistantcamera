from __future__ import annotations

import json
from typing import Iterable

import paho.mqtt.client as mqtt


class MqttBridge:
    def __init__(
        self,
        host: str,
        port: int,
        client_id: str,
        discovery_prefix: str,
        state_topic: str,
        username: str = "",
        password: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.discovery_prefix = discovery_prefix.rstrip("/")
        self.state_topic = state_topic
        self.client_id = client_id
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._on_connect
        self._class_names: list[str] = []
        self._sources: list[dict] = []

    def start(self) -> None:
        self.client.connect(self.host, self.port, keepalive=60)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client: mqtt.Client, userdata, flags, reason_code, properties) -> None:
        if reason_code != 0:
            return
        self.publish_discovery(self._class_names, self._sources)

    def _state_topic_for(self, source_id: str) -> str:
        sid = (source_id or "default").strip()
        return f"{self.state_topic}/{sid}"

    def publish_discovery(self, class_names: Iterable[str], sources: list[dict] | None = None) -> None:
        self._class_names = list(class_names)
        self._sources = list(sources or [])
        if not self._sources:
            self._sources = [{"source_id": "cam1", "name": "cam1"}]

        # Clear legacy single-source entities from older versions.
        legacy_text_topic = f"{self.discovery_prefix}/sensor/{self.client_id}/gesture/config"
        legacy_conf_topic = f"{self.discovery_prefix}/sensor/{self.client_id}/confidence/config"
        self.client.publish(legacy_text_topic, "", retain=True)
        self.client.publish(legacy_conf_topic, "", retain=True)

        for src in self._sources:
            source_id = str(src.get("source_id", "cam1"))
            source_name = str(src.get("name", source_id))
            entity_key = f"{self.client_id}_{source_id}"
            src_state_topic = self._state_topic_for(source_id)
            text_topic = f"{self.discovery_prefix}/sensor/{entity_key}/gesture/config"
            conf_topic = f"{self.discovery_prefix}/sensor/{entity_key}/confidence/config"

            gesture_payload = {
                "name": f"{source_name} Gesture",
                "unique_id": f"{entity_key}_gesture",
                "state_topic": src_state_topic,
                "value_template": "{{ value_json.gesture }}",
                "icon": "mdi:hand-back-right",
                "json_attributes_topic": src_state_topic,
                "device": {
                    "identifiers": [entity_key],
                    "name": f"YOLO {source_name}",
                    "manufacturer": "Custom",
                    "model": "YOLO + FastAPI",
                },
            }

            confidence_payload = {
                "name": f"{source_name} Gesture Confidence",
                "unique_id": f"{entity_key}_confidence",
                "state_topic": src_state_topic,
                "value_template": "{{ value_json.confidence }}",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "icon": "mdi:percent",
                "device": {
                    "identifiers": [entity_key],
                    "name": f"YOLO {source_name}",
                },
            }

            self.client.publish(text_topic, json.dumps(gesture_payload), retain=True)
            self.client.publish(conf_topic, json.dumps(confidence_payload), retain=True)

    def clear_source_discovery(self, source_id: str) -> None:
        entity_key = f"{self.client_id}_{source_id}"
        text_topic = f"{self.discovery_prefix}/sensor/{entity_key}/gesture/config"
        conf_topic = f"{self.discovery_prefix}/sensor/{entity_key}/confidence/config"
        self.client.publish(text_topic, "", retain=True)
        self.client.publish(conf_topic, "", retain=True)

    def publish_state(self, gesture: str, confidence: float, model: str, timestamp: str, source_id: str = "") -> None:
        payload = {
            "gesture": gesture,
            "confidence": round(confidence * 100.0, 2),
            "model": model,
            "timestamp": timestamp,
            "source_id": source_id,
        }
        self.client.publish(self._state_topic_for(source_id), json.dumps(payload), retain=False)
