# Raspberry Pi Rover Server

This service runs on the Raspberry Pi and provides:

- browser-based rover steering UI
- USB serial bridge to the ESP32 (`left,right\n` commands)
- dead-man and emergency stop behavior
- live USB camera stream in the same web page

## Features

- FastAPI + Uvicorn server with low dependency count.
- WebSocket control channel (`/ws`) for low-latency steering.
- HTTP control fallback (`/api/control`) if WebSocket is unavailable.
- Fixed-rate control loop (default 20 Hz).
- Forward-only mixing (safety-first): steering reduces one side.
- Automatic stop when:
  - dead-man is released
  - UI heartbeat times out
  - websocket disconnects
- Manual emergency stop endpoint (`POST /api/stop`).
- USB camera MJPEG stream (`/api/camera.mjpg`) using OpenCV.

## Dependencies

Install from `requirements.txt`:

- `fastapi`
- `uvicorn`
- `pyserial`
- `opencv-python-headless`

## Configuration

Set via environment variables:

- `ROVER_SERIAL_PORT` (required): e.g. `/dev/ttyUSB0`
- `ROVER_BAUD` (default `115200`)
- `ROVER_MAX_DAC` (default `180`, range `0..255`)
- `ROVER_CONTROL_HZ` (default `20`)
- `ROVER_HEARTBEAT_TIMEOUT_SEC` (default `0.35`)
- `ROVER_CAMERA_INDEX` (default `0`)
- `ROVER_CAMERA_WIDTH` (default `640`)
- `ROVER_CAMERA_HEIGHT` (default `480`)
- `ROVER_CAMERA_FPS` (default `20`)

## Run

From `code/raspberry/`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ROVER_SERIAL_PORT=/dev/ttyUSB0
uvicorn app:app --host 0.0.0.0 --port 8000
```

Then open:

- `http://<raspberry-ip>:8000/`

## API and Endpoints

- `GET /` -> web control UI
- `WS /ws` -> control input (`throttle`, `steer`, `deadman`, `max_dac`)
- `POST /api/control` -> HTTP fallback control input
- `GET /api/status` -> serial, control, and camera status
- `POST /api/stop` -> immediate `0,0` output
- `GET /api/camera.mjpg` -> USB camera stream

## Control Notes

- Throttle in the UI is forward-only (`0..100`).
- Steering in the UI is `-100..100`.
- Joystick: drag up to move forward, left/right to steer, release to stop.
- Output values sent to ESP32 are DAC integers `0..255`.
- ESP32 watchdog still provides an extra safety layer if commands stop.

## Safety Checklist Before Field Use

1. Lift wheels or disengage drivetrain for first power-on tests.
2. Verify `POST /api/stop` stops both sides immediately.
3. Verify releasing dead-man sends `0,0`.
4. Verify unplugging browser client causes stop.
5. Verify unplugging ESP32 USB results in stopped state.
