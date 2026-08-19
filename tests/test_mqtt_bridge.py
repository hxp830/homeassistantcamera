from __future__ import annotations

import json

import pytest

from app.mqtt_bridge import MqttBridge


class FakeClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, bool]] = []

    def publish(self, topic, payload="", retain=False, **_):
        self.published.append((topic, payload, retain))

    def username_pw_set(self, *_args, **_kwargs):
        pass

    def will_set(self, *_args, **_kwargs):
        pass

    def reconnect_delay_set(self, *_args, **_kwargs):
        pass


@pytest.fixture
def bridge():
    instance = MqttBridge(
        host="127.0.0.1",
        port=1883,
        client_id="gesture_test",
        discovery_prefix="homeassistant/",
        state_topic="gesture/state",
        publish_mode="change",
        heartbeat=0,
    )
    instance.client = FakeClient()
    return instance


def test_state_topic_is_namespaced_per_source(bridge):
    assert bridge._state_topic_for("cam1") == "gesture/state/cam1"
    assert bridge._state_topic_for("") == "gesture/state/default"


def test_discovery_prefix_trailing_slash_is_stripped(bridge):
    assert bridge.discovery_prefix == "homeassistant"
    assert bridge.availability_topic == "gesture/state/availability"


def test_change_mode_suppresses_repeated_gestures(bridge):
    for _ in range(3):
        bridge.publish_state("fist", 0.9, "m", "t", source_id="cam1")
    assert len(bridge.client.published) == 1

    bridge.publish_state("open_palm", 0.9, "m", "t", source_id="cam1")
    assert len(bridge.client.published) == 2


def test_force_bypasses_deduplication(bridge):
    bridge.publish_state("fist", 0.9, "m", "t", source_id="cam1")
    bridge.publish_state("fist", 0.9, "m", "t", source_id="cam1", force=True)
    assert len(bridge.client.published) == 2


def test_always_mode_publishes_every_detection(bridge):
    bridge.publish_mode = "always"
    for _ in range(3):
        bridge.publish_state("fist", 0.9, "m", "t", source_id="cam1")
    assert len(bridge.client.published) == 3


def test_confidence_is_published_as_a_percentage(bridge):
    bridge.publish_state("fist", 0.8125, "m", "t", source_id="cam1")
    _topic, payload, _retain = bridge.client.published[0]
    assert json.loads(payload)["confidence"] == 81.25


def test_discovery_includes_availability_and_clears_legacy_entities(bridge):
    bridge.publish_discovery(["fist"], [{"source_id": "cam1", "name": "Living Room"}])
    by_topic = {topic: payload for topic, payload, _ in bridge.client.published}

    assert by_topic["homeassistant/sensor/gesture_test/gesture/config"] == ""

    config = json.loads(by_topic["homeassistant/sensor/gesture_test_cam1/gesture/config"])
    assert config["availability_topic"] == "gesture/state/availability"
    assert config["state_topic"] == "gesture/state/cam1"
    assert config["unique_id"] == "gesture_test_cam1_gesture"


def test_deleting_a_source_clears_its_discovery_topics(bridge):
    bridge.clear_source_discovery("cam1")
    assert bridge.client.published == [
        ("homeassistant/sensor/gesture_test_cam1/gesture/config", "", True),
        ("homeassistant/sensor/gesture_test_cam1/confidence/config", "", True),
    ]
