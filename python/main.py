import secrets
import string
from datetime import datetime, timezone

from arduino.app_utils import App, Bridge
from arduino.app_bricks.web_ui import WebUI
from arduino.app_bricks.video_imageclassification import VideoImageClassification
from arduino.app_peripherals.camera import WebSocketCamera
import time
from fastapi.responses import HTMLResponse

# ---------------------------------------------------------------------------
# Shared Web UI. Both pages (index.html = camera, servo.html = servo control)
# connect to this same backend over the same WebUI socket.
# ---------------------------------------------------------------------------
ui = WebUI()


# ---------------------------------------------------------------------------
# Camera / object detection
# ---------------------------------------------------------------------------

# The Arduino IoT Remote companion app authenticates the camera stream with a
# 6-digit NUMERIC secret.
def generate_secret() -> str:
    return ''.join(secrets.choice(string.digits) for _ in range(6))


secret = generate_secret()

resolution = (480, 640)  # Portrait resolution for mobile devices
camera = WebSocketCamera(secret=secret, encrypt=True, resolution=resolution)

# The brick emits status events ('connected', 'disconnected', 'streaming',
# 'paused'). Relay each one straight to the frontend so it can swap between the
# pairing QR and the live stream.
camera.on_status_changed(lambda evt_type, data: ui.send_message(evt_type, data))

detect = VideoImageClassification(camera, confidence=0.3, debounce_sec=0.0)


# VideoImageClassification.on_detect_all passes a FLAT dict mapping each class
# label to its confidence float: {"label": 0.87, ...}. (No nested dicts, no
# bounding boxes - that was the object-detection shape.) Push each to the UI.
def handle_detections(detections):
    print("DETECTIONS:", detections, flush=True)
    for label, confidence in detections.items():
        ui.send_message("detection", {
            "content": label,
            "confidence": confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

detect.on_detect_all(handle_detections)
# Expose the processed camera feed (with detection overlays) as an MJPEG stream
# the browser can render directly in an <img>. Served on the Web UI origin at
# /camera, separate from the phone pairing WebSocket.
ui.expose_camera('/camera', camera, jpeg_quality=50)

# Adjust the detection confidence threshold from the UI.
ui.on_message("override_th", lambda sid, threshold: detect.override_threshold(threshold))


# ---------------------------------------------------------------------------
# Servo control (servo.html). The MCU exposes a 'set_servo' RPC via the Bridge
# which applies the angle and returns the actually-applied value.
# ---------------------------------------------------------------------------
current_angle = 90  # last known angle, synced with the MCU


def apply_angle(angle):
    """Send the angle to the MCU via Bridge; return the applied value."""
    global current_angle
    try:
        angle = int(angle)
    except (TypeError, ValueError):
        return current_angle

    result = Bridge.call("set_servo", angle)
    try:
        current_angle = int(result)
    except (TypeError, ValueError):
        current_angle = angle
    return current_angle


def on_set_angle(sid, message):
    """Received from the browser when the user moves the slider/preset."""
    angle = message.get("angle") if isinstance(message, dict) else message
    applied = apply_angle(angle)
    ui.send_message("servo_state", {"angle": applied})


ui.on_message("set_angle", on_set_angle)


# ---------------------------------------------------------------------------
# On UI connect: send both the camera pairing payload and the servo state so
# whichever page is open gets what it needs. Each page ignores messages it
# doesn't listen for.
# ---------------------------------------------------------------------------
def handle_connect(sid):
    ui.send_message("welcome", {
        "client_name": camera.name,
        "secret": secret,
        "status": camera.status,
        "protocol": camera.protocol,
        "ip": camera.ip,
        "port": camera.port,
    })
    ui.send_message("servo_state", {"angle": current_angle})


ui.on_connect(handle_connect)

# NOTE: do NOT define a custom "/" route. The WebUI brick serves assets/ static
# files automatically (index.html at /, servo.html at /servo.html) and
# bootstraps the socket session itself.

App.run()
