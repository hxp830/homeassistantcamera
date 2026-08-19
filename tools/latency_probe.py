"""Measure how much of the preview delay comes from the camera itself.

This opens an RTSP stream with the same FFmpeg options the app uses, but with no
inference, no JPEG encoding and no HTTP layer in between. Whatever delay is left
belongs to the camera, the network or the decoder.

To read the actual glass-to-glass latency, point the camera at the monitor showing
this window: the clock baked into the video lags behind the clock drawn in the
corner by exactly the end-to-end delay.

Usage:
    python tools/latency_probe.py            # first RTSP source in data/sources.json
    python tools/latency_probe.py 101        # match a source whose URL contains "101"
    python tools/latency_probe.py rtsp://... # explicit URL

Add --headless to drop the preview window and measure raw decode throughput, and
--seconds N to stop automatically.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.detector import cv2  # noqa: E402  (importing app.detector applies the FFmpeg options)

STORE = ROOT / "data" / "sources.json"


def mask(url: str) -> str:
    return re.sub(r"://[^@/]*@", "://***@", url)


def pick_source(argument: str | None) -> str:
    if argument and argument.startswith("rtsp://"):
        return argument

    if not STORE.is_file():
        raise SystemExit(f"No {STORE} yet, pass an rtsp:// URL directly.")

    saved = json.loads(STORE.read_text(encoding="utf-8")).get("sources", [])
    streams = [entry["source"] for entry in saved if str(entry.get("source", "")).startswith("rtsp://")]
    if not streams:
        raise SystemExit("No RTSP source saved yet, pass an rtsp:// URL directly.")

    if argument:
        matches = [url for url in streams if argument in url]
        if not matches:
            raise SystemExit(f"No saved source matches {argument!r}.")
        return matches[0]
    return streams[0]


def main() -> None:
    args = sys.argv[1:]
    headless = "--headless" in args
    limit = 0.0
    if "--seconds" in args:
        limit = float(args[args.index("--seconds") + 1])
    selector = next((a for a in args if not a.startswith("--") and not a.replace(".", "").isdigit()), None)
    if selector is None:
        selector = next((a for a in args if not a.startswith("--") and a.isdigit() and len(a) == 3), None)

    url = pick_source(selector)
    print(f"Opening {mask(url)}")

    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        raise SystemExit("Could not open the stream.")

    reported = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Stream reports {width}x{height} @ {reported:.1f} fps")
    if not headless:
        print("Point the camera at this window, then compare the two clocks. Press q to quit.")

    started = time.time()
    frames = 0
    window_start = time.time()
    read_total = 0.0
    slowest_read = 0.0
    show_total = 0.0

    try:
        while True:
            read_start = time.time()
            ok, frame = cap.read()
            read_ms = (time.time() - read_start) * 1000.0
            if not ok:
                print("Stream ended.")
                break

            read_total += read_ms
            slowest_read = max(slowest_read, read_ms)
            frames += 1

            show_start = time.time()
            if not headless:
                stamp = time.strftime("%H:%M:%S") + f".{int(time.time() % 1 * 1000):03d}"
                cv2.putText(frame, stamp, (16, 46), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 6)
                cv2.putText(frame, stamp, (16, 46), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 255, 0), 2)
                cv2.imshow("latency probe", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            show_total += (time.time() - show_start) * 1000.0

            elapsed = time.time() - window_start
            if elapsed >= 2.0:
                # A high average read time means we are waiting on the camera; a near
                # zero one means frames were already queued, i.e. we are the bottleneck.
                print(
                    f"decode {frames / elapsed:5.1f} fps   "
                    f"read avg {read_total / frames:6.1f} ms  max {slowest_read:6.1f} ms   "
                    f"display avg {show_total / frames:5.1f} ms"
                )
                frames = 0
                read_total = 0.0
                slowest_read = 0.0
                show_total = 0.0
                window_start = time.time()

            if limit and (time.time() - started) >= limit:
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
