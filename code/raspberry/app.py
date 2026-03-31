import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from camera import UsbCamera
from serial_bridge import Esp32SerialBridge


CONTROL_HZ = float(os.getenv("ROVER_CONTROL_HZ", "20"))
HEARTBEAT_TIMEOUT_SEC = float(os.getenv("ROVER_HEARTBEAT_TIMEOUT_SEC", "0.35"))
MAX_DAC = int(os.getenv("ROVER_MAX_DAC", "180"))


@dataclass
class ControlInput:
    throttle: float = 0.0
    steer: float = 0.0
    deadman: bool = False
    max_dac: int = MAX_DAC
    updated_at: float = 0.0


class RoverController:
    def __init__(self, bridge: Esp32SerialBridge) -> None:
        self.bridge = bridge
        self._lock = threading.Lock()
        self._state = ControlInput(updated_at=time.monotonic())
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.last_output = (0, 0)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.5)
        self.bridge.send(0, 0)
        self.last_output = (0, 0)

    def update_input(self, throttle: float, steer: float, deadman: bool, max_dac: Optional[int] = None) -> None:
        throttle = max(-1.0, min(1.0, throttle))
        steer = max(-1.0, min(1.0, steer))

        with self._lock:
            self._state.throttle = throttle
            self._state.steer = steer
            self._state.deadman = bool(deadman)
            if max_dac is not None:
                self._state.max_dac = max(0, min(255, int(max_dac)))
            self._state.updated_at = time.monotonic()

    def emergency_stop(self) -> None:
        with self._lock:
            self._state.deadman = False
            self._state.throttle = 0.0
            self._state.steer = 0.0
            self._state.updated_at = time.monotonic()
        self.bridge.send(0, 0)
        self.last_output = (0, 0)

    def snapshot(self) -> dict:
        with self._lock:
            state = ControlInput(
                throttle=self._state.throttle,
                steer=self._state.steer,
                deadman=self._state.deadman,
                max_dac=self._state.max_dac,
                updated_at=self._state.updated_at,
            )
        now = time.monotonic()
        age_ms = int((now - state.updated_at) * 1000)
        return {
            "input": {
                "throttle": state.throttle,
                "steer": state.steer,
                "deadman": state.deadman,
                "max_dac": state.max_dac,
                "age_ms": age_ms,
            },
            "output": {"left": self.last_output[0], "right": self.last_output[1]},
        }

    def _run_loop(self) -> None:
        period = 1.0 / CONTROL_HZ
        while not self._stop_event.is_set():
            start = time.monotonic()
            with self._lock:
                state = ControlInput(
                    throttle=self._state.throttle,
                    steer=self._state.steer,
                    deadman=self._state.deadman,
                    max_dac=self._state.max_dac,
                    updated_at=self._state.updated_at,
                )

            alive = (start - state.updated_at) <= HEARTBEAT_TIMEOUT_SEC
            if not state.deadman or not alive:
                left, right = 0, 0
            else:
                left, right = mix_forward_only(state.throttle, state.steer, state.max_dac)

            self.bridge.send(left, right)
            self.last_output = (left, right)

            elapsed = time.monotonic() - start
            sleep_for = max(0.0, period - elapsed)
            time.sleep(sleep_for)


def mix_forward_only(throttle: float, steer: float, max_dac: int) -> tuple[int, int]:
    # Forward-only safety profile:
    # throttle in [0..1], steer in [-1..1]
    t = max(0.0, throttle)
    s = max(-1.0, min(1.0, steer))

    left = t
    right = t

    if s > 0:
        right *= 1.0 - s
    elif s < 0:
        left *= 1.0 - abs(s)

    left_dac = int(round(max(0.0, min(1.0, left)) * max_dac))
    right_dac = int(round(max(0.0, min(1.0, right)) * max_dac))
    return left_dac, right_dac


SERIAL_PORT = os.getenv("ROVER_SERIAL_PORT", "")
SERIAL_BAUD = int(os.getenv("ROVER_BAUD", "115200"))

CAMERA_INDEX = int(os.getenv("ROVER_CAMERA_INDEX", "0"))
CAMERA_WIDTH = int(os.getenv("ROVER_CAMERA_WIDTH", "640"))
CAMERA_HEIGHT = int(os.getenv("ROVER_CAMERA_HEIGHT", "480"))
CAMERA_FPS = int(os.getenv("ROVER_CAMERA_FPS", "20"))

bridge = Esp32SerialBridge(port=SERIAL_PORT, baudrate=SERIAL_BAUD)
controller = RoverController(bridge)
camera = UsbCamera(index=CAMERA_INDEX, width=CAMERA_WIDTH, height=CAMERA_HEIGHT, fps=CAMERA_FPS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    bridge.start()
    controller.start()
    camera.start()
    try:
        yield
    finally:
        controller.stop()
        bridge.stop()
        camera.stop()


app = FastAPI(title="Garden Rover Control", lifespan=lifespan)


class ControlMessage(BaseModel):
    throttle: float = 0.0
    steer: float = 0.0
    deadman: bool = False
    max_dac: Optional[int] = None


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    html_path = Path(__file__).with_name("index.html")
    return html_path.read_text(encoding="utf-8")


@app.get("/api/status")
async def status() -> JSONResponse:
    payload = {
        "serial": bridge.status(),
        "control": controller.snapshot(),
        "camera": camera.status(),
    }
    return JSONResponse(payload)


@app.post("/api/stop")
async def stop() -> JSONResponse:
    controller.emergency_stop()
    return JSONResponse({"ok": True, "left": 0, "right": 0})


@app.post("/api/control")
async def control(msg: ControlMessage) -> JSONResponse:
    controller.update_input(
        throttle=msg.throttle,
        steer=msg.steer,
        deadman=msg.deadman,
        max_dac=msg.max_dac,
    )
    return JSONResponse({"ok": True, "input": controller.snapshot()["input"]})


@app.get("/api/camera.mjpg")
async def mjpeg_stream() -> StreamingResponse:
    if not camera.available:
        raise HTTPException(status_code=503, detail="Camera backend unavailable")
    return StreamingResponse(camera.frame_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.websocket("/ws")
async def ws_control(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            msg = await websocket.receive_json()
            throttle = float(msg.get("throttle", 0.0))
            steer = float(msg.get("steer", 0.0))
            deadman = bool(msg.get("deadman", False))
            max_dac = msg.get("max_dac")
            controller.update_input(throttle=throttle, steer=steer, deadman=deadman, max_dac=max_dac)
            await websocket.send_json({"ok": True})
    except WebSocketDisconnect:
        controller.emergency_stop()
