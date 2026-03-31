import threading
import time
from dataclasses import dataclass
from typing import Optional

import serial
from serial import SerialException


@dataclass
class BridgeState:
    connected: bool = False
    port: str = ""
    baudrate: int = 115200
    last_error: str = ""
    last_ack: str = ""
    last_ack_at: float = 0.0
    last_message: str = ""
    last_write: str = ""
    last_message_at: float = 0.0


class Esp32SerialBridge:
    def __init__(self, port: str, baudrate: int = 115200) -> None:
        self._port = port
        self._baudrate = baudrate
        self._serial: Optional[serial.Serial] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._write_lock = threading.Lock()
        self._state = BridgeState(port=port, baudrate=baudrate)
        self._state_lock = threading.Lock()
        self._buffer = b""

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.5)
        self._close_serial()

    def send(self, left: int, right: int) -> bool:
        left = max(0, min(255, int(left)))
        right = max(0, min(255, int(right)))
        line = f"{left},{right}\n".encode("ascii")

        ser = self._serial
        if not ser or not ser.is_open:
            return False

        try:
            with self._write_lock:
                ser.write(line)
                ser.flush()
            with self._state_lock:
                self._state.last_write = line.decode("ascii").strip()
            return True
        except SerialException as exc:
            self._set_error(f"write failed: {exc}")
            self._close_serial()
            return False

    def status(self) -> dict:
        with self._state_lock:
            state = BridgeState(
                connected=self._state.connected,
                port=self._state.port,
                baudrate=self._state.baudrate,
                last_error=self._state.last_error,
                last_ack=self._state.last_ack,
                last_ack_at=self._state.last_ack_at,
                last_message=self._state.last_message,
                last_write=self._state.last_write,
                last_message_at=self._state.last_message_at,
            )

        now = time.monotonic()
        age_ms = None
        if state.last_message_at > 0:
            age_ms = int((now - state.last_message_at) * 1000)

        ack_age_ms = None
        if state.last_ack_at > 0:
            ack_age_ms = int((now - state.last_ack_at) * 1000)

        app_running = bool(state.connected and state.last_ack and ack_age_ms is not None and ack_age_ms <= 1500)

        return {
            "connected": state.connected,
            "port": state.port,
            "baudrate": state.baudrate,
            "last_error": state.last_error,
            "last_ack": state.last_ack,
            "last_message": state.last_message,
            "last_write": state.last_write,
            "last_message_age_ms": age_ms,
            "last_ack_age_ms": ack_age_ms,
            "app_running": app_running,
        }

    def _read_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self._ensure_open():
                time.sleep(1.0)
                continue

            ser = self._serial
            if not ser:
                time.sleep(0.2)
                continue

            try:
                chunk = ser.read(256)
                if chunk:
                    self._buffer += chunk
                    self._parse_buffer_lines()
                else:
                    time.sleep(0.01)
            except SerialException as exc:
                self._set_error(f"read failed: {exc}")
                self._close_serial()

    def _parse_buffer_lines(self) -> None:
        while b"\n" in self._buffer:
            raw_line, self._buffer = self._buffer.split(b"\n", 1)
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            with self._state_lock:
                self._state.last_message = line
                self._state.last_message_at = time.monotonic()
                if line.startswith("ACK:"):
                    self._state.last_ack = line
                    self._state.last_ack_at = self._state.last_message_at

    def _ensure_open(self) -> bool:
        if self._serial and self._serial.is_open:
            return True
        if not self._port:
            self._set_error("ROVER_SERIAL_PORT not configured")
            return False

        try:
            self._serial = serial.Serial(
                port=self._port,
                baudrate=self._baudrate,
                timeout=0.05,
                write_timeout=0.2,
            )
            with self._state_lock:
                self._state.connected = True
                self._state.last_error = ""
        except SerialException as exc:
            self._set_error(f"open failed: {exc}")
            self._close_serial()
            return False
        return True

    def _set_error(self, message: str) -> None:
        with self._state_lock:
            self._state.last_error = message
            self._state.connected = False

    def _close_serial(self) -> None:
        ser = self._serial
        self._serial = None
        if ser:
            try:
                ser.close()
            except SerialException:
                pass
        with self._state_lock:
            self._state.connected = False
