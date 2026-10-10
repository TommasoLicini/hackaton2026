import time

from arduino.app_utils import App, Bridge, WebUI

# Angolo corrente conosciuto lato Linux (viene sincronizzato con l'MCU).
current_angle = 90

# Istanza della Web UI (brick arduino:web_ui).
ui = WebUI()


def apply_angle(angle):
    """Invia l'angolo all'MCU via Bridge e restituisce il valore applicato."""
    global current_angle
    try:
        angle = int(angle)
    except (TypeError, ValueError):
        return current_angle

    # L'MCU applica il clamp e restituisce l'angolo effettivo.
    result = Bridge.call("set_servo", angle)
    try:
        current_angle = int(result)
    except (TypeError, ValueError):
        # Se il Bridge non restituisce un intero, teniamo il valore richiesto.
        current_angle = angle
    return current_angle


def on_set_angle(message):
    """Ricevuto dal browser quando l'utente muove lo slider/preset."""
    angle = message.get("angle") if isinstance(message, dict) else message
    applied = apply_angle(angle)
    # Rimanda lo stato aggiornato a tutti i client collegati.
    ui.send_message("servo_state", {"angle": applied})


def on_ui_connected():
    """Alla connessione del browser invia lo stato attuale del servo."""
    ui.send_message("servo_state", {"angle": current_angle})


# Registra gli handler dei messaggi WebSocket provenienti dalla Web UI.
ui.on_connect(on_ui_connected)
ui.on_message("set_angle", on_set_angle)


def loop():
    """Chiamato ripetutamente dal framework App."""
    time.sleep(1)


App.run(user_loop=loop)
