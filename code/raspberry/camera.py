import threading
import time
from typing import Generator, Optional

try:
    import cv2
except ImportError:
    cv2 = None


class UsbCamera:
    def __init__(self, index: int = 0, width: int = 640, height: int = 480, fps: int = 20) -> None:
        self.index = index
        self.width = width
        self.height = height
        self.fps = fps
        self.available = cv2 is not None

        self._capture = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._frame_jpeg: Optional[bytes] = None
        self._last_error = ""
        self._last_frame_at = 0.0

    def start(self) -> None:
        if not self.available:
            self._last_error = "opencv-python not installed"
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        self._release_capture()

    def status(self) -> dict:
        age_ms = None
        if self._last_frame_at > 0:
            age_ms = int((time.monotonic() - self._last_frame_at) * 1000)
        return {
            "available": self.available,
            "camera_index": self.index,
            "last_error": self._last_error,
            "has_frame": self._frame_jpeg is not None,
            "last_frame_age_ms": age_ms,
        }

    def frame_generator(self) -> Generator[bytes, None, None]:
        boundary = b"--frame\r\n"
        while not self._stop_event.is_set():
            with self._lock:
                frame = self._frame_jpeg
            if frame is None:
                time.sleep(0.05)
                continue
            yield boundary + b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(1.0 / max(1, self.fps))

    def _loop(self) -> None:
        period = 1.0 / max(1, self.fps)
        while not self._stop_event.is_set():
            start = time.monotonic()
            if not self._ensure_capture_open():
                time.sleep(0.5)
                continue

            ok, frame = self._capture.read()
            if not ok or frame is None:
                self._last_error = "camera read failed"
                self._release_capture()
                time.sleep(0.2)
                continue

            ok, encoded = cv2.imencode(".jpg", frame)
            if not ok:
                self._last_error = "jpeg encode failed"
                time.sleep(0.05)
                continue

            with self._lock:
                self._frame_jpeg = encoded.tobytes()
                self._last_frame_at = time.monotonic()
                self._last_error = ""

            sleep_for = max(0.0, period - (time.monotonic() - start))
            time.sleep(sleep_for)

    def _ensure_capture_open(self) -> bool:
        if self._capture is not None and self._capture.isOpened():
            return True

        self._capture = cv2.VideoCapture(self.index)
        if not self._capture or not self._capture.isOpened():
            self._last_error = f"cannot open camera index {self.index}"
            self._release_capture()
            return False

        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._capture.set(cv2.CAP_PROP_FPS, self.fps)
        return True

    def _release_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = None
