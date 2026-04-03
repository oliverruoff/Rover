import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from camera import UsbCamera
from relay_controller import DirectionRelayController
from serial_bridge import Esp32SerialBridge


CONTROL_HZ = max(10.0, float(os.getenv("ROVER_CONTROL_HZ", "20")))
HEARTBEAT_TIMEOUT_SEC = max(0.35, float(os.getenv("ROVER_HEARTBEAT_TIMEOUT_SEC", "0.35")))
MAX_DAC = int(os.getenv("ROVER_MAX_DAC", "180"))
CONTROL_OWNER_TTL_SEC = max(0.5, float(os.getenv("ROVER_CONTROL_OWNER_TTL_SEC", "0.8")))
RELAY_PULSE_SEC = max(0.1, float(os.getenv("ROVER_RELAY_PULSE_SEC", "0.15")))
SIDE_DEADZONE = max(0.0, float(os.getenv("ROVER_SIDE_DEADZONE", "0.10")))
PIVOT_ZONE = max(0.0, float(os.getenv("ROVER_PIVOT_ZONE", "0.20")))
STEER_DEADZONE = max(0.0, float(os.getenv("ROVER_STEER_DEADZONE", "0.08")))
RELAY_TRIGGER_THRESHOLD = max(SIDE_DEADZONE, float(os.getenv("ROVER_RELAY_TRIGGER_THRESHOLD", "0.15")))
LEFT_RELAY_PIN = int(os.getenv("ROVER_LEFT_RELAY_PIN", "26"))
RIGHT_RELAY_PIN = int(os.getenv("ROVER_RIGHT_RELAY_PIN", "19"))


@dataclass
class ControlInput:
    throttle: float = 0.0
    steer: float = 0.0
    left_cmd: Optional[float] = None
    right_cmd: Optional[float] = None
    deadman: bool = False
    max_dac: int = MAX_DAC
    updated_at: float = 0.0


@dataclass
class SideState:
    direction: int = 1
    pulse_until: float = 0.0
    pending_direction: int = 1
    ready_for_flip: bool = False
    last_command_sign: int = 0

    @property
    def relay_active(self) -> bool:
        return self.pulse_until > 0.0


class RoverController:
    def __init__(self, bridge: Esp32SerialBridge, relays: DirectionRelayController) -> None:
        self.bridge = bridge
        self.relays = relays
        self._lock = threading.Lock()
        self._state = ControlInput(updated_at=time.monotonic())
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.last_output = (0, 0)
        self._active_client: Optional[str] = None
        self._active_until: float = 0.0
        self._left_side = SideState()
        self._right_side = SideState()
        self._drive_mode = "idle"

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
        self.relays.off()
        self.bridge.send(0, 0)
        self.last_output = (0, 0)

    def update_input(
        self,
        throttle: float,
        steer: float,
        deadman: bool,
        left_cmd: Optional[float] = None,
        right_cmd: Optional[float] = None,
        max_dac: Optional[int] = None,
        source_id: str = "",
    ) -> bool:
        throttle = max(-1.0, min(1.0, throttle))
        steer = max(-1.0, min(1.0, steer))
        source = (source_id or "unknown")[:128]
        now = time.monotonic()

        with self._lock:
            if self._active_client and now > self._active_until:
                self._active_client = None

            requested_deadman = bool(deadman)
            if requested_deadman:
                if self._active_client not in (None, source):
                    return False
                self._active_client = source
                self._active_until = now + CONTROL_OWNER_TTL_SEC
            else:
                if self._active_client and self._active_client != source:
                    return False
                self._active_client = None
                self._active_until = 0.0

            self._state.throttle = throttle
            self._state.steer = steer
            self._state.left_cmd = None if left_cmd is None else max(-1.0, min(1.0, float(left_cmd)))
            self._state.right_cmd = None if right_cmd is None else max(-1.0, min(1.0, float(right_cmd)))
            self._state.deadman = requested_deadman
            if max_dac is not None:
                self._state.max_dac = max(0, min(255, int(max_dac)))
            self._state.updated_at = now
        return True

    def emergency_stop(self) -> None:
        with self._lock:
            self._active_client = None
            self._active_until = 0.0
            self._state.deadman = False
            self._state.throttle = 0.0
            self._state.steer = 0.0
            self._state.left_cmd = None
            self._state.right_cmd = None
            self._state.updated_at = time.monotonic()
            self._left_side.pulse_until = 0.0
            self._right_side.pulse_until = 0.0
            self._left_side.pending_direction = self._left_side.direction
            self._right_side.pending_direction = self._right_side.direction
        self.relays.off()
        self.bridge.send(0, 0)
        self.last_output = (0, 0)

    def manual_flip(self, side: str) -> bool:
        now = time.monotonic()
        with self._lock:
            target = self._left_side if side == "left" else self._right_side
            if target.relay_active and now < target.pulse_until:
                return False
            # Manual flip button should only pulse the relay and must not
            # overwrite the controller's logical direction state.
            target.pending_direction = target.direction
            target.pulse_until = now + RELAY_PULSE_SEC
            # A manual flip should not leave the side armed for an immediate
            # automatic flip-back on the next tiny command.
            target.ready_for_flip = False
        return True

    def snapshot(self) -> dict:
        with self._lock:
            state = ControlInput(
                throttle=self._state.throttle,
                steer=self._state.steer,
                left_cmd=self._state.left_cmd,
                right_cmd=self._state.right_cmd,
                deadman=self._state.deadman,
                max_dac=self._state.max_dac,
                updated_at=self._state.updated_at,
            )
            active_client = self._active_client
            left_direction = self._left_side.direction
            right_direction = self._right_side.direction
            left_relay_active = self._left_side.relay_active
            right_relay_active = self._right_side.relay_active
            drive_mode = self._drive_mode
        now = time.monotonic()
        age_ms = int((now - state.updated_at) * 1000)
        return {
            "input": {
                "throttle": state.throttle,
                "steer": state.steer,
                "left_cmd": state.left_cmd,
                "right_cmd": state.right_cmd,
                "deadman": state.deadman,
                "max_dac": state.max_dac,
                "age_ms": age_ms,
                "active_client": active_client,
            },
            "output": {"left": self.last_output[0], "right": self.last_output[1]},
            "direction": {
                "left": "forward" if left_direction > 0 else "reverse",
                "right": "forward" if right_direction > 0 else "reverse",
            },
            "relay": {
                "left_active": left_relay_active,
                "right_active": right_relay_active,
            },
            "drive_mode": drive_mode,
        }

    def _run_loop(self) -> None:
        period = 1.0 / CONTROL_HZ
        while not self._stop_event.is_set():
            start = time.monotonic()
            with self._lock:
                if self._active_client and start > self._active_until:
                    self._active_client = None

                state = ControlInput(
                    throttle=self._state.throttle,
                    steer=self._state.steer,
                    left_cmd=self._state.left_cmd,
                    right_cmd=self._state.right_cmd,
                    deadman=self._state.deadman,
                    max_dac=self._state.max_dac,
                    updated_at=self._state.updated_at,
                )

                left_side = SideState(
                    direction=self._left_side.direction,
                    pulse_until=self._left_side.pulse_until,
                    pending_direction=self._left_side.pending_direction,
                    ready_for_flip=self._left_side.ready_for_flip,
                    last_command_sign=self._left_side.last_command_sign,
                )
                right_side = SideState(
                    direction=self._right_side.direction,
                    pulse_until=self._right_side.pulse_until,
                    pending_direction=self._right_side.pending_direction,
                    ready_for_flip=self._right_side.ready_for_flip,
                    last_command_sign=self._right_side.last_command_sign,
                )

            alive = (start - state.updated_at) <= HEARTBEAT_TIMEOUT_SEC
            if not state.deadman or not alive:
                requested_left, requested_right = 0.0, 0.0
                drive_mode = "idle"
            elif state.left_cmd is not None and state.right_cmd is not None:
                requested_left, requested_right = state.left_cmd, state.right_cmd
                drive_mode = "direct"
            else:
                requested_left, requested_right, drive_mode = mix_signed_drive(state.throttle, state.steer)

            left, next_left = resolve_side_output(requested_left, state.max_dac, left_side, start)
            right, next_right = resolve_side_output(requested_right, state.max_dac, right_side, start)

            self.relays.set_left(next_left.relay_active and start < next_left.pulse_until)
            self.relays.set_right(next_right.relay_active and start < next_right.pulse_until)

            with self._lock:
                self._left_side = next_left
                self._right_side = next_right
                self._drive_mode = drive_mode

            self.bridge.send(left, right)
            self.last_output = (left, right)

            elapsed = time.monotonic() - start
            sleep_for = max(0.0, period - elapsed)
            time.sleep(sleep_for)


def mix_signed_drive(throttle: float, steer: float) -> tuple[float, float, str]:
    t = max(-1.0, min(1.0, throttle))
    s = max(-1.0, min(1.0, steer))

    if abs(t) <= PIVOT_ZONE and abs(s) < STEER_DEADZONE:
        left = 0.0
        right = 0.0
        mode = "pivot-idle"
    elif abs(t) <= PIVOT_ZONE:
        # Pivot direction is intentionally mirrored so joystick left turns
        # the rover nose left and joystick right turns it right.
        left = -s
        right = s
        mode = "pivot"
    else:
        # Curvature steering without speed boost:
        # outer side keeps |t|, inner side is reduced by steer amount.
        left = t
        right = t
        turn = abs(s)
        if s > 0:
            right = t * (1.0 - turn)
        elif s < 0:
            left = t * (1.0 - turn)
        mode = "forward" if t > 0 else "reverse"

    return left, right, mode


def resolve_side_output(command: float, max_dac: int, side: SideState, now: float) -> tuple[int, SideState]:
    next_side = SideState(
        direction=side.direction,
        pulse_until=side.pulse_until,
        pending_direction=side.pending_direction,
        ready_for_flip=side.ready_for_flip,
        last_command_sign=side.last_command_sign,
    )

    if next_side.relay_active and now >= next_side.pulse_until:
        next_side.direction = next_side.pending_direction
        next_side.pulse_until = 0.0

    magnitude = abs(command)
    desired_direction = 0
    if magnitude >= SIDE_DEADZONE:
        desired_direction = 1 if command > 0 else -1
    else:
        magnitude = 0.0

    # Arm flips on explicit zero crossing even if the control stream
    # jumps across zero between two samples.
    if desired_direction != 0 and next_side.last_command_sign != 0 and desired_direction != next_side.last_command_sign:
        next_side.ready_for_flip = True

    if desired_direction != 0:
        next_side.last_command_sign = desired_direction
    else:
        next_side.last_command_sign = 0

    if magnitude <= SIDE_DEADZONE:
        next_side.ready_for_flip = True

    if (
        desired_direction != 0
        and desired_direction != next_side.direction
        and not next_side.relay_active
        and next_side.ready_for_flip
        and magnitude >= RELAY_TRIGGER_THRESHOLD
    ):
        next_side.pending_direction = desired_direction
        next_side.pulse_until = now + RELAY_PULSE_SEC
        next_side.ready_for_flip = False

    if next_side.relay_active:
        return 0, next_side

    if desired_direction == next_side.direction and magnitude >= RELAY_TRIGGER_THRESHOLD:
        next_side.ready_for_flip = False

    output = int(round(max(0.0, min(1.0, magnitude)) * max_dac))
    return output, next_side


SERIAL_PORT = os.getenv("ROVER_SERIAL_PORT", "")
SERIAL_BAUD = int(os.getenv("ROVER_BAUD", "115200"))

CAMERA_INDEX = int(os.getenv("ROVER_CAMERA_INDEX", "0"))
CAMERA_WIDTH = int(os.getenv("ROVER_CAMERA_WIDTH", "640"))
CAMERA_HEIGHT = int(os.getenv("ROVER_CAMERA_HEIGHT", "480"))
CAMERA_FPS = int(os.getenv("ROVER_CAMERA_FPS", "20"))
CAMERA_STREAM_WIDTH = int(os.getenv("ROVER_CAMERA_STREAM_WIDTH", "480"))
CAMERA_STREAM_HEIGHT = int(os.getenv("ROVER_CAMERA_STREAM_HEIGHT", "360"))
CAMERA_JPEG_QUALITY = int(os.getenv("ROVER_CAMERA_JPEG_QUALITY", "50"))

bridge = Esp32SerialBridge(port=SERIAL_PORT, baudrate=SERIAL_BAUD)
relays = DirectionRelayController(left_pin=LEFT_RELAY_PIN, right_pin=RIGHT_RELAY_PIN, active_high=True)
controller = RoverController(bridge, relays)
camera = UsbCamera(
    index=CAMERA_INDEX,
    width=CAMERA_WIDTH,
    height=CAMERA_HEIGHT,
    fps=CAMERA_FPS,
    stream_width=CAMERA_STREAM_WIDTH,
    stream_height=CAMERA_STREAM_HEIGHT,
    jpeg_quality=CAMERA_JPEG_QUALITY,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    bridge.start()
    controller.start()
    camera.start()
    try:
        yield
    finally:
        controller.stop()
        relays.close()
        bridge.stop()
        camera.stop()


app = FastAPI(title="Rover Control", lifespan=lifespan)


class ControlMessage(BaseModel):
    throttle: float = 0.0
    steer: float = 0.0
    left_cmd: Optional[float] = None
    right_cmd: Optional[float] = None
    deadman: bool = False
    max_dac: Optional[int] = None
    client_id: Optional[str] = None
@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    html_path = Path(__file__).with_name("index.html")
    return html_path.read_text(encoding="utf-8")


@app.get("/favicon.svg")
async def favicon() -> FileResponse:
    icon_path = Path(__file__).with_name("favicon.svg")
    return FileResponse(icon_path, media_type="image/svg+xml")


@app.get("/favicon.ico")
async def favicon_ico() -> FileResponse:
    icon_path = Path(__file__).with_name("favicon.ico")
    return FileResponse(icon_path, media_type="image/x-icon")


@app.get("/favicon.png")
async def favicon_png() -> FileResponse:
    icon_path = Path(__file__).with_name("rover_icon.png")
    return FileResponse(icon_path, media_type="image/png")


@app.get("/rover_icon.png")
async def rover_icon() -> FileResponse:
    icon_path = Path(__file__).with_name("rover_icon.png")
    return FileResponse(icon_path, media_type="image/png")


@app.get("/api/status")
async def status() -> JSONResponse:
    payload = {
        "config": {
            "control_hz": CONTROL_HZ,
            "heartbeat_timeout_sec": HEARTBEAT_TIMEOUT_SEC,
            "max_dac_default": MAX_DAC,
            "relay_pulse_sec": RELAY_PULSE_SEC,
            "pivot_zone": PIVOT_ZONE,
        },
        "serial": bridge.status(),
        "control": controller.snapshot(),
        "camera": camera.status(),
    }
    return JSONResponse(payload)


@app.post("/api/stop")
async def stop() -> JSONResponse:
    controller.emergency_stop()
    return JSONResponse({"ok": True, "left": 0, "right": 0})


@app.post("/api/flip/{side}")
async def flip_side(side: str) -> JSONResponse:
    if side not in {"left", "right"}:
        raise HTTPException(status_code=400, detail="side must be 'left' or 'right'")
    applied = controller.manual_flip(side)
    return JSONResponse({"ok": True, "applied": applied, "control": controller.snapshot()})


@app.post("/api/control")
async def control(msg: ControlMessage, request: Request) -> JSONResponse:
    client_host = request.client.host if request.client else "http"
    source_id = f"http:{client_host}:{msg.client_id or 'anon'}"
    applied = controller.update_input(
        throttle=msg.throttle,
        steer=msg.steer,
        deadman=msg.deadman,
        left_cmd=msg.left_cmd,
        right_cmd=msg.right_cmd,
        max_dac=msg.max_dac,
        source_id=source_id,
    )
    return JSONResponse({"ok": True, "applied": applied, "input": controller.snapshot()["input"]})


@app.get("/api/camera.mjpg")
async def mjpeg_stream() -> StreamingResponse:
    if not camera.available:
        raise HTTPException(status_code=503, detail="Camera backend unavailable")
    return StreamingResponse(camera.frame_generator(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.websocket("/ws")
async def ws_control(websocket: WebSocket) -> None:
    await websocket.accept()
    ws_client = websocket.client
    ws_source_base = f"ws:{ws_client.host if ws_client else 'unknown'}:{ws_client.port if ws_client else '0'}"
    last_source_id = ws_source_base
    try:
        while True:
            msg = await websocket.receive_json()
            throttle = float(msg.get("throttle", 0.0))
            steer = float(msg.get("steer", 0.0))
            deadman = bool(msg.get("deadman", False))
            left_cmd = msg.get("left_cmd")
            right_cmd = msg.get("right_cmd")
            max_dac = msg.get("max_dac")
            client_id = str(msg.get("client_id", "anon"))[:64]
            source_id = f"{ws_source_base}:{client_id}"
            last_source_id = source_id
            applied = controller.update_input(
                throttle=throttle,
                steer=steer,
                deadman=deadman,
                left_cmd=left_cmd,
                right_cmd=right_cmd,
                max_dac=max_dac,
                source_id=source_id,
            )
            await websocket.send_json({"ok": True, "applied": applied})
    except WebSocketDisconnect:
        controller.update_input(throttle=0.0, steer=0.0, deadman=False, source_id=last_source_id)
