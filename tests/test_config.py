from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def config_module(monkeypatch):
    def _load(env: dict[str, str]):
        for key in list(env):
            monkeypatch.setenv(key, env[key])
        module = importlib.import_module("app.config")
        return importlib.reload(module)

    return _load


def test_source_is_used_verbatim(config_module, monkeypatch):
    monkeypatch.setenv("SOURCE", "rtsp://cam.local/stream")
    settings = config_module({}).load_settings()
    assert settings.source == "rtsp://cam.local/stream"


def test_auto_source_builds_rtsp_url_with_escaped_credentials(config_module, monkeypatch):
    monkeypatch.setenv("SOURCE", "auto")
    monkeypatch.setenv("RTSP_HOST", "192.168.1.10")
    monkeypatch.setenv("RTSP_USER", "admin")
    monkeypatch.setenv("RTSP_PASSWORD", "p@ss/word")
    monkeypatch.setenv("RTSP_PATH", "stream1")
    settings = config_module({}).load_settings()
    assert settings.source == "rtsp://admin:p%40ss%2Fword@192.168.1.10/stream1"


def test_auto_source_without_host_falls_back_to_local_camera(config_module, monkeypatch):
    monkeypatch.setenv("SOURCE", "auto")
    monkeypatch.setenv("RTSP_HOST", "")
    settings = config_module({}).load_settings()
    assert settings.source == "0"


def test_invalid_numbers_fall_back_to_defaults(config_module, monkeypatch):
    monkeypatch.setenv("CONF", "not-a-number")
    monkeypatch.setenv("MQTT_PORT", "999999")
    settings = config_module({}).load_settings()
    assert settings.conf == 0.5
    assert settings.mqtt_port == 65535


def test_image_size_is_rounded_to_a_multiple_of_32(config_module, monkeypatch):
    monkeypatch.setenv("IMG_SIZE", "650")
    settings = config_module({}).load_settings()
    assert settings.image_size == 640


def test_unknown_publish_mode_falls_back_to_change(config_module, monkeypatch):
    monkeypatch.setenv("MQTT_PUBLISH_MODE", "sometimes")
    settings = config_module({}).load_settings()
    assert settings.mqtt_publish_mode == "change"
