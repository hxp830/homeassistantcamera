from __future__ import annotations

import pytest

from app.detector import MEDIAPIPE_MODEL_NAME, ModelRegistry


@pytest.fixture
def registry(tmp_path):
    return ModelRegistry(tmp_path)


@pytest.mark.parametrize(
    "name",
    ["../secret.pt", "../../etc/evil.pt", "sub/dir/model.pt", "sub\\dir\\model.pt", ""],
)
def test_names_that_escape_the_model_directory_are_rejected(registry, name):
    with pytest.raises(ValueError):
        registry.resolve_path(name)


def test_plain_names_resolve_inside_the_model_directory(registry, tmp_path):
    assert registry.resolve_path("best.pt") == tmp_path / "best.pt"


def test_acquiring_a_missing_model_raises(registry):
    with pytest.raises(FileNotFoundError):
        registry.acquire("best.pt")


def test_shared_handles_are_reused_and_released_once(tmp_path, monkeypatch):
    registry = ModelRegistry(tmp_path, share=True)
    (tmp_path / "best.pt").write_bytes(b"stub")

    loaded = []
    closed = []

    class StubModel:
        names = {0: "fist"}

        def close(self):
            closed.append(self)

    def fake_load(path):
        model = StubModel()
        loaded.append(model)
        return model

    monkeypatch.setattr(ModelRegistry, "_load_yolo", staticmethod(fake_load))

    first = registry.acquire("best.pt")
    second = registry.acquire("best.pt")
    assert first is second
    assert len(loaded) == 1
    assert first.class_names == ["fist"]

    registry.release(first)
    assert closed == []

    registry.release(second)
    assert len(closed) == 1


def test_sharing_can_be_disabled(tmp_path, monkeypatch):
    registry = ModelRegistry(tmp_path, share=False)
    (tmp_path / "best.pt").write_bytes(b"stub")
    monkeypatch.setattr(ModelRegistry, "_load_yolo", staticmethod(lambda path: object()))

    assert registry.acquire("best.pt") is not registry.acquire("best.pt")


def test_mediapipe_is_never_shared(registry, monkeypatch):
    created = []

    class StubEngine:
        def __init__(self):
            created.append(self)

    monkeypatch.setattr("app.detector.MediaPipeHandsEngine", StubEngine)
    first = registry.acquire(MEDIAPIPE_MODEL_NAME)
    second = registry.acquire(MEDIAPIPE_MODEL_NAME)
    assert first.instance is not second.instance
    assert first.shared is False
    assert len(created) == 2
