# Garden Rover (Hoverboard-Motor Drive)

This project is a custom garden rover built from reclaimed hoverboard hardware and controlled from a Raspberry Pi through an ESP32.

## Project Goals

- Build a robust outdoor rover with 4 harvested hoverboard motors.
- Use existing 36V/48V 350W BLDC motor controllers (one controller per motor).
- Control drivetrain as two sides (left/right) using ESP32 DAC throttle outputs.
- Steer the rover from a Raspberry Pi over USB.
- Host a Python web server (Uvicorn) with minimal external libraries and a practical steering UI.

## Current Hardware Setup

- **Motors:** 4x hoverboard motors.
- **Motor controllers:** 4x Linel brushless motor controller (36V/48V, 350W, BLDC, e-bike/scooter style).
- **Throttle input expected by controller:** `0V .. 3.3V`.
- **Mechanical drive:** custom 3D-printed TPU chain/drive components.
- **Control split:**
  - Left side motors share one throttle signal.
  - Right side motors share one throttle signal.

## Control Architecture

- **Raspberry Pi** runs high-level control (web UI + command logic).
- **ESP32 (MicroPython)** acts as motor throttle interface.
- **Link between Pi and ESP32:** USB serial.
- **Throttle outputs from ESP32:**
  - `GPIO25` (DAC1) -> left side throttle
  - `GPIO26` (DAC2) -> right side throttle
- **Ground reference:** motor controller throttle GND is tied to ESP32 GND.

## ESP32 Firmware (Implemented)

Firmware location: `code/esp32/main.py`

Behavior implemented today:

- Initializes DAC outputs on boot.
- Forces immediate motor stop at startup by writing `0` to both DAC channels.
- Reads serial input in non-blocking mode.
- Accepts commands in this format:

```text
left,right\n
```

Example:

```text
120,120
200,80
0,0
```

- Valid range per channel: `0..255` (clamped).
- Writes values directly to DAC1/DAC2.
- Sends acknowledgment back over serial:

```text
ACK:<left>,<right>
```

- Safety watchdog:
  - If no valid command is received for `500 ms`, both outputs are set to `0`.
  - Emits timeout message and clears stale input buffer.

## Safety Assumptions

- `0V` throttle is confirmed as **STOP**.
- Startup defaults to stop.
- Communication timeout defaults to stop.

Even with software safety in place, initial tests should be done with wheels lifted or drivetrain disengaged.

## Raspberry Pi Web Control (Planned)

Directory: `code/raspberry/`

Target design:

- Python ASGI app served by `uvicorn`.
- Minimal dependency footprint.
- Browser-based UI for:
  - Forward/reverse and left/right steering
  - Live stop command
  - Adjustable max throttle limit
  - Connection/status display (ESP32 serial link)

Recommended minimal stack:

- `uvicorn`
- `fastapi` (lightweight routing/API)
- `pyserial` (USB serial communication with ESP32)

UI can be plain HTML/CSS/JavaScript served directly by the same app.

## Repository Layout

```text
Rover/
  README.md                # Project-level documentation
  code/
    esp32/
      main.py              # MicroPython firmware on ESP32
      README.md            # ESP32 notes
    raspberry/             # Raspberry Pi server + web UI (to be implemented)
```

## Next Steps

1. Implement the Raspberry Pi control server in `code/raspberry/`.
2. Add serial bridge logic (HTTP/WebSocket input -> serial output to ESP32).
3. Build a mobile-friendly steering UI with a dead-man stop behavior.
4. Add startup checks and an emergency-stop endpoint.
5. Document calibration and field-test procedure.
