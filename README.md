![Rover icon](code/raspberry/rover_icon.png)

# Garden Rover

Garden Rover is a Raspberry Pi and ESP32 based drive system for a custom outdoor rover built around reclaimed hoverboard motors and scooter-style BLDC motor controllers. The Raspberry Pi hosts the browser UI, the camera stream, and the high-level drive logic. The ESP32 acts as a simple dual DAC throttle device. Direction changes are handled on the Raspberry Pi through two relay outputs.

## What This Repository Contains

- `code/raspberry/`: FastAPI web server, browser control UI, USB camera streaming, relay control, and USB serial bridge to the ESP32.
- `code/esp32/`: MicroPython firmware that receives two DAC values over USB serial and writes them to GPIO25/GPIO26.

## System Overview

The drivetrain is controlled as two sides: left and right.

1. A browser connects to the Raspberry Pi control page.
2. The UI sends control messages over WebSocket, with HTTP fallback if WebSocket is unavailable.
3. The Raspberry Pi mixes joystick or slider input into signed left/right side commands.
4. If a side needs to change direction, the Raspberry Pi briefly pulses the relay for that side.
5. The Raspberry Pi sends only throttle magnitude values (`0..255`) over USB serial to the ESP32.
6. The ESP32 writes those values to its two DAC outputs.
7. Each motor controller receives:
   - one analog throttle signal from the ESP32
   - one direction relay pulse path controlled by the Raspberry Pi
8. A USB camera connected to the Raspberry Pi is streamed back into the same control page.

## Hardware Used

Current software assumptions match this hardware setup:

- Raspberry Pi running the web server and control loop.
- ESP32-WROOM running MicroPython.
- 4 hoverboard hub motors.
- 4 BLDC motor controllers, organized as left side and right side drivetrain groups.
- 2 analog throttle channels from the ESP32 DAC outputs.
- 2 relay-controlled direction lines from the Raspberry Pi GPIO pins.
- 1 USB camera connected to the Raspberry Pi.
- USB serial link between Raspberry Pi and ESP32.

## Electrical / Signal Connections

### ESP32

- `GPIO25` (`DAC1`) -> left drivetrain throttle signal.
- `GPIO26` (`DAC2`) -> right drivetrain throttle signal.
- ESP32 GND must be shared with the motor controller throttle ground.
- ESP32 USB -> Raspberry Pi USB for serial communication.

### Raspberry Pi

- `GPIO26` -> left direction relay control.
- `GPIO19` -> right direction relay control.
- USB camera -> Raspberry Pi USB.

These relay pins are the current software defaults and can be changed through environment variables.

## Software Responsibilities

### Raspberry Pi

The Raspberry Pi process is the main control brain.

It handles:

- browser UI delivery
- low-latency control input over WebSocket
- HTTP fallback control input
- control ownership between clients
- deadman and heartbeat safety logic
- drive mixing from throttle/steer into left/right side commands
- relay pulse timing for direction changes
- serial transmission of left/right DAC values to the ESP32
- USB camera capture and MJPEG streaming
- telemetry/status reporting back to the UI

### ESP32

The ESP32 firmware is intentionally simple.

It does only this:

- reads serial lines in the form `left,right`
- clamps both values to `0..255`
- writes them directly to DAC1 and DAC2
- returns `ACK:<left>,<right>` over serial
- forces both outputs to `0` if no command arrives for 500 ms

The ESP32 does not decide direction. It only outputs throttle magnitudes.

## Drive Logic

The Raspberry Pi supports two drive input modes.

### 1. Mixed Drive

This is the normal joystick / throttle-steer mode.

- `throttle` and `steer` are received in the range `-1.0..1.0`.
- Outside the pivot zone, the rover uses curvature-style steering:
  - both sides start at the same throttle
  - the inner side is reduced based on steer amount
- In the pivot zone, throttle is treated as zero and steer becomes counter-rotating left/right side commands.

### 2. Direct Side Drive

The UI can also send explicit `left_cmd` and `right_cmd` values.

- this is used by the vertical side power bars next to the joystick
- each side command is signed
- positive means forward on that side
- negative means reverse on that side

### Direction Relay Handling

Each drivetrain side keeps track of a logical direction state.

- If a command crosses through zero and requests the opposite direction, that side is armed for a flip.
- Once the command is large enough, the Raspberry Pi pulses the relay for that side.
- During the relay pulse, the DAC output for that side is held at zero.
- After the pulse time expires, the logical direction state updates and throttle can resume.

This behavior is implemented in `code/raspberry/app.py`.

## Browser UI

The control page lives in `code/raspberry/index.html`.

It includes:

- live camera view
- central joystick for mixed drive
- left and right vertical bars for direct side drive
- deadman button
- emergency stop button
- manual flip buttons for left and right sides
- Fine Tuning panel with sliders for:
  - throttle
  - steer
  - max output limit (`max_dac`)
  - joystick minimum throttle
  - joystick maximum throttle
- status chips showing transport, serial/app health, camera state, deadman state, mode, and current direction states

The motor bars display actual output as a percentage of full possible DAC range, not percentage of the currently limited `max_dac` setting.

## Communications

### Browser -> Raspberry Pi

- `WS /ws`: primary low-latency control channel
- `POST /api/control`: fallback control channel

Control payload fields used by the app:

- `throttle`
- `steer`
- `left_cmd`
- `right_cmd`
- `deadman`
- `max_dac`
- `client_id`

### Raspberry Pi -> ESP32

Serial format:

```text
<left_dac>,<right_dac>\n
```

Example:

```text
180,180
0,120
0,0
```

### ESP32 -> Raspberry Pi

Example acknowledgements:

```text
ACK:180,180
ACK:0,120
```

## Safety Behavior

Several independent layers stop the rover if control is lost.

### In the browser / Raspberry Pi control path

- Deadman must be held for drive commands to remain active.
- The active client ownership expires if control heartbeats stop arriving.
- If the browser disconnects, the WebSocket handler releases control.
- Emergency stop forces the requested state to zero immediately.
- Relay pulses temporarily force that side to zero while direction is switching.

### In the ESP32

- If no valid serial command arrives for 500 ms, both DAC outputs are forced to zero.

## Runtime Configuration

The Raspberry Pi app is configured through environment variables.

### Control and drivetrain

- `ROVER_SERIAL_PORT`: serial port for the ESP32, for example `/dev/ttyUSB0`
- `ROVER_BAUD`: serial baud rate, default `115200`
- `ROVER_MAX_DAC`: default maximum DAC output, default `180`
- `ROVER_CONTROL_HZ`: control loop frequency, default `20`
- `ROVER_HEARTBEAT_TIMEOUT_SEC`: stale input timeout, default `0.35`
- `ROVER_CONTROL_OWNER_TTL_SEC`: client ownership timeout, default `0.8`
- `ROVER_RELAY_PULSE_SEC`: relay pulse length, default `0.15`
- `ROVER_SIDE_DEADZONE`: per-side magnitude deadzone, default `0.10`
- `ROVER_PIVOT_ZONE`: central pivot band, default `0.20`
- `ROVER_STEER_DEADZONE`: steer deadzone, default `0.08`
- `ROVER_RELAY_TRIGGER_THRESHOLD`: minimum magnitude needed before a flip is executed, default `0.15`
- `ROVER_LEFT_RELAY_PIN`: left relay GPIO pin, default `26`
- `ROVER_RIGHT_RELAY_PIN`: right relay GPIO pin, default `19`

### Camera

- `ROVER_CAMERA_INDEX`: preferred camera index, default `0`
- `ROVER_CAMERA_WIDTH`: capture width, default `640`
- `ROVER_CAMERA_HEIGHT`: capture height, default `480`
- `ROVER_CAMERA_FPS`: capture FPS, default `20`
- `ROVER_CAMERA_STREAM_WIDTH`: streamed width, default `480`
- `ROVER_CAMERA_STREAM_HEIGHT`: streamed height, default `360`
- `ROVER_CAMERA_JPEG_QUALITY`: JPEG quality, default `50`

## Raspberry Pi API

- `GET /` -> control UI
- `GET /rover_icon.png` -> rover icon used by the web UI
- `GET /api/status` -> serial, control, and camera telemetry
- `POST /api/control` -> fallback control input
- `POST /api/stop` -> emergency stop
- `POST /api/flip/{left|right}` -> manual relay pulse for a side
- `GET /api/camera.mjpg` -> MJPEG camera stream
- `WS /ws` -> live control socket

## Running the Raspberry Pi Server

From `code/raspberry/`:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ROVER_SERIAL_PORT=/dev/ttyUSB0
uvicorn app:app --host 0.0.0.0 --port 8000
```

Open the UI at:

```text
http://<raspberry-pi-ip>:8000/
```

## Flashing / Running the ESP32 Firmware

The ESP32 firmware entry point is:

```text
code/esp32/main.py
```

It is written for MicroPython and expects to run continuously after boot.

## Recommended Bring-Up Checklist

1. Lift the rover wheels off the ground for initial testing.
2. Verify the ESP32 appears on the Raspberry Pi as the expected serial port.
3. Start the Raspberry Pi web server.
4. Confirm `GET /api/status` shows serial connected and camera healthy.
5. Test deadman hold and release behavior.
6. Test emergency stop.
7. Test forward drive at a low `max_dac` limit first.
8. Test relay-based direction changes slowly before full-speed operation.

## Notes

- The repository root README is intended to describe the whole rover stack.
- More implementation-specific details are in `code/raspberry/` and `code/esp32/`.
