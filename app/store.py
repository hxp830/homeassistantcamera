from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class JsonStore:
    """Small atomic JSON file store used to persist runtime configuration."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def load(self, default: Any) -> Any:
        with self._lock:
            if not self.path.is_file():
                return default
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("Failed to read %s: %s", self.path, exc)
                return default

    def save(self, data: Any) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                # Write to a temp file first so a crash cannot truncate the config.
                fd, tmp_name = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        json.dump(data, handle, ensure_ascii=False, indent=2)
                    os.replace(tmp_name, self.path)
                except BaseException:
                    Path(tmp_name).unlink(missing_ok=True)
                    raise
            except OSError as exc:
                logger.warning("Failed to write %s: %s", self.path, exc)
