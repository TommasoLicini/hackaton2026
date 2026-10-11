import json
import os
import secrets
import string
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

from arduino.app_utils import App, Bridge
from arduino.app_bricks.web_ui import WebUI
from arduino.app_bricks.video_imageclassification import VideoImageClassification
from arduino.app_peripherals.camera import WebSocketCamera
import time
from fastapi.responses import HTMLResponse
from arduino.app_bricks.telegram_bot import TelegramBot, Sender, Message
from arduino.app_utils import App
import numpy as np


ardino_s_bot = TelegramBot()

telegram_connected = False
senders = []

def bot_intro(sender: Sender, message: Message):
    global telegram_connected
    telegram_connected = True
    # Avoid adding the same chat twice if /connect is sent repeatedly.
    if any(c['id'] == sender.chat_id for c in senders):
        return
    # Timezone-aware epoch so it can be compared against datetime.now(timezone.utc).
    senders.append({
        'id': sender.chat_id,
        'last_message': datetime(1970, 1, 1, tzinfo=timezone.utc),
    })

ardino_s_bot.add_command('connect', bot_intro)


# ---------------------------------------------------------------------------
# Load key=value pairs from a .env file into the environment (stdlib only, no
# python-dotenv dependency). Existing environment variables take precedence, so
# the runtime can still override the file. The .env lives at the repo root, one
# directory above this python/ folder.
# ---------------------------------------------------------------------------
def load_dotenv(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except FileNotFoundError:
        pass


load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


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


def encode_frame_to_jpeg(frame):
    """Encode a camera frame (numpy array) to JPEG bytes for Telegram.

    camera.capture() returns a numpy image array; Telegram's send_photo needs
    encoded image-file bytes (JPEG/PNG), NOT the raw pixel buffer. Try OpenCV
    first, then Pillow. Returns None if the frame can't be encoded.
    """
    if frame is None:
        return None

    # Already-encoded bytes (e.g. a bytes/bytearray) pass straight through.
    if isinstance(frame, (bytes, bytearray)):
        return bytes(frame)

    arr = np.asarray(frame)

    # Try OpenCV (fast, already used for MJPEG elsewhere in the stack).
    try:
        import cv2
        ok, buf = cv2.imencode(".jpg", arr)
        if ok:
            return buf.tobytes()
    except Exception as exc:
        print("cv2 encode failed:", exc, flush=True)

    # Fall back to Pillow.
    try:
        import io
        from PIL import Image
        img = Image.fromarray(arr)
        if img.mode != "RGB":
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG")
        return out.getvalue()
    except Exception as exc:
        print("PIL encode failed:", exc, flush=True)

    return None


def send_telegram_msg(label):
    if label != 'damage':
        return

    now = datetime.now(timezone.utc)
    for chat in senders:
        # Rate-limit per chat: at most one alert every 10 minutes.
        if now - chat['last_message'] <= timedelta(minutes=10):
            continue

        # Commit the timestamp FIRST so rapid back-to-back detections can't
        # slip through the check before the (slow) send/capture work finishes.
        chat['last_message'] = now

        try:
            ardino_s_bot.send_message(chat['id'], 'Solar panel damaged!')
        except Exception as exc:
            print("telegram send_message failed:", exc, flush=True)

        try:
            photo = encode_frame_to_jpeg(camera.capture())
            if photo is not None:
                ardino_s_bot.send_photo(chat['id'], photo)
            else:
                print("telegram: no photo to send (capture/encode returned None)", flush=True)
        except Exception as exc:
            print("telegram send_photo failed:", exc, flush=True)

# VideoImageClassification.on_detect_all passes a FLAT dict mapping each class
# label to its confidence float: {"label": 0.87, ...}. (No nested dicts, no
# bounding boxes - that was the object-detection shape.) Push each to the UI.
def handle_detections(detections):
    print("DETECTIONS:", detections, flush=True)
    for label, confidence in detections.items():
        if telegram_connected:
            send_telegram_msg(label)
            
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
# Analog current reading (graph.html). The MCU sketch stores the latest analog
# current (mA) in an atomic variable and provides a 'get_current' RPC. Following
# the UNO Q Bridge model (Linux always initiates), the /value HTTP handler calls
# that RPC synchronously and returns the value it reads back.
# ---------------------------------------------------------------------------
def get_current_value():
    """HTTP handler for the trend chart: synchronously read the current (mA)."""
    try:
        value = float(Bridge.call("get_current"))
    except (TypeError, ValueError):
        value = None  # non-numeric / empty response from the MCU
    return {
        "value": value,
        "unit": "mA",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# Exposed at GET /value on the same origin that serves the web assets.
ui.expose_api("GET", "/value", get_current_value)


# ---------------------------------------------------------------------------
# Current weather (graph.html). The frontend shows the live weather to make the
# point that the panel/servo won't move when the weather is bad. The OpenWeather
# API key is read server-side from the environment and never sent to the
# browser; the frontend only ever sees the trimmed result from /weather.
# ---------------------------------------------------------------------------
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY", "").strip()
# City to report. Override with WEATHER_CITY in the environment if desired.
WEATHER_CITY = os.environ.get("WEATHER_CITY", "Turin,IT").strip()


def get_weather():
    """HTTP handler: fetch current weather from OpenWeather, server-side."""
    if not OPENWEATHER_API_KEY:
        return {"error": "OPENWEATHER_API_KEY not configured"}

    query = urllib.parse.urlencode({
        "q": WEATHER_CITY,
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
    })
    url = f"https://api.openweathermap.org/data/2.5/weather?{query}"

    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        return {"error": f"OpenWeather HTTP {exc.code}"}
    except Exception as exc:  # network error, timeout, bad JSON
        return {"error": f"weather fetch failed: {exc}"}

    weather = (data.get("weather") or [{}])[0]
    main = data.get("main") or {}
    # "bad weather" heuristic: anything that isn't clear/clouds, or rain/snow.
    group = (weather.get("main") or "").lower()
    is_bad = group in ("rain", "drizzle", "thunderstorm", "snow")

    return {
        "city": data.get("name", WEATHER_CITY),
        "description": weather.get("description", ""),
        "main": weather.get("main", ""),
        "icon": weather.get("icon", ""),
        "temp": main.get("temp"),
        "is_bad": is_bad,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# Exposed at GET /weather on the same origin that serves the web assets.
ui.expose_api("GET", "/weather", get_weather)


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
