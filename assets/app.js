// Inizializza la Web UI (connessione WebSocket verso il backend Python).
const ui = new WebUI();

const statusText = document.getElementById("statusText");
const slider = document.getElementById("angleSlider");
const angleValue = document.getElementById("angleValue");
const needle = document.getElementById("gaugeNeedle");
const presetButtons = document.querySelectorAll(".preset");

let connected = false;

// --- Aggiornamento interfaccia ---

function setControlsEnabled(enabled) {
  slider.disabled = !enabled;
  presetButtons.forEach((btn) => (btn.disabled = !enabled));
}

function updateView(angle) {
  angle = Math.max(0, Math.min(180, Number(angle)));
  slider.value = angle;
  angleValue.textContent = `${angle}\u00B0`;
  // La lancetta ruota da -90deg (0) a +90deg (180).
  needle.style.transform = `rotate(${angle - 90}deg)`;
}

// --- Invio comandi al backend ---

function sendAngle(angle) {
  if (!connected) return;
  updateView(angle);
  ui.send_message("set_angle", { angle: Number(angle) });
}

// --- Eventi UI ---

// Aggiorna la vista mentre si trascina, invia il comando al rilascio
// per non saturare il WebSocket.
slider.addEventListener("input", () => updateView(slider.value));
slider.addEventListener("change", () => sendAngle(slider.value));

presetButtons.forEach((btn) => {
  btn.addEventListener("click", () => sendAngle(btn.dataset.angle));
});

// --- Eventi WebSocket ---

ui.on_connect(() => {
  connected = true;
  statusText.textContent = "Connesso";
  statusText.classList.remove("status--off");
  statusText.classList.add("status--on");
  setControlsEnabled(true);
});

ui.on_disconnect(() => {
  connected = false;
  statusText.textContent = "Disconnesso";
  statusText.classList.remove("status--on");
  statusText.classList.add("status--off");
  setControlsEnabled(false);
});

// Stato del servo inviato dal backend (sincronizza la UI con l'MCU).
ui.on_message("servo_state", (message) => {
  if (message && typeof message.angle !== "undefined") {
    updateView(message.angle);
  }
});
