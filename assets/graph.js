// Live trend chart for a single-value variable polled from an HTTP endpoint.
// Keeps a sliding window of the most recent readings and redraws a line chart
// on a <canvas> on every poll. No external chart libraries.

// --- DOM ---
const statusText = document.getElementById("statusText");
const currentValue = document.getElementById("currentValue");
const canvas = document.getElementById("chart");
const ctx = canvas.getContext("2d");

const intervalInput = document.getElementById("intervalInput");
const windowInput = document.getElementById("windowInput");

// Hardcoded data source: the backend exposes the latest analog current (mA)
// at GET /value as {"value": <number>, "unit": "mA", "timestamp": ...}.
const ENDPOINT_URL = "/value";
const JSON_KEY = "value";

const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");
const clearBtn = document.getElementById("clearBtn");

const statMin = document.getElementById("statMin");
const statMax = document.getElementById("statMax");
const statAvg = document.getElementById("statAvg");
const statCount = document.getElementById("statCount");

// Weather card elements + its own data source (key kept server-side).
const weatherIcon = document.getElementById("weatherIcon");
const weatherTemp = document.getElementById("weatherTemp");
const weatherDesc = document.getElementById("weatherDesc");
const weatherBadge = document.getElementById("weatherBadge");
const WEATHER_URL = "/weather";
const WEATHER_REFRESH_MS = 5 * 60 * 1000; // refresh every 5 minutes

// --- State ---
let samples = [];        // sliding window of { t, v }
let windowSize = 60;     // max points retained
let timer = null;        // poll interval handle
let polling = false;
let inFlight = false;    // guard against overlapping fetches

// --- Status helpers ---
function setStatus(text, kind) {
  statusText.textContent = text;
  statusText.classList.toggle("status--on", kind === "on");
  statusText.classList.toggle("status--off", kind !== "on");
}

// --- Value extraction -----------------------------------------------------
// The endpoint may return a raw number ("42.1"), raw JSON number (42.1), or a
// JSON object. If a JSON key is given, read that (supports dotted paths like
// "sensor.temp"); otherwise accept the first number we can find.
function extractValue(raw, key) {
  const text = String(raw).trim();

  // Try JSON first.
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (_) {
    parsed = undefined;
  }

  if (parsed !== undefined) {
    if (typeof parsed === "number") return parsed;
    if (typeof parsed === "object" && parsed !== null) {
      if (key) {
        const found = key.split(".").reduce(
          (o, k) => (o == null ? undefined : o[k]),
          parsed
        );
        return Number(found);
      }
      // No key: grab the first numeric property.
      const firstNum = Object.values(parsed).find((v) => typeof v === "number");
      return firstNum !== undefined ? firstNum : NaN;
    }
    // Parsed to a string/bool — fall through to Number().
  }

  // Plain text number.
  return Number(text);
}

// --- Polling --------------------------------------------------------------
async function poll() {
  if (inFlight) return; // skip if the previous request hasn't resolved
  inFlight = true;

  try {
    const res = await fetch(ENDPOINT_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const raw = await res.text();
    const value = extractValue(raw, JSON_KEY);

    if (!Number.isFinite(value)) {
      setStatus("Non-numeric response", "off");
      inFlight = false;
      return;
    }

    samples.push({ t: Date.now(), v: value });
    while (samples.length > windowSize) samples.shift();

    currentValue.textContent = formatNum(value);
    setStatus("Polling", "on");
    updateStats();
    draw();
  } catch (err) {
    setStatus(`Error: ${err.message}`, "off");
  } finally {
    inFlight = false;
  }
}

function start() {
  if (polling) return;
  const interval = Math.max(100, Number(intervalInput.value) || 1000);
  windowSize = Math.max(5, Number(windowInput.value) || 60);

  polling = true;
  startBtn.disabled = true;
  stopBtn.disabled = false;
  intervalInput.disabled = true;
  windowInput.disabled = true;

  setStatus("Polling", "on");
  poll(); // immediate first read
  timer = setInterval(poll, interval);
}

function stop() {
  polling = false;
  if (timer) clearInterval(timer);
  timer = null;
  startBtn.disabled = false;
  stopBtn.disabled = true;
  intervalInput.disabled = false;
  windowInput.disabled = false;
  setStatus("Stopped", "off");
}

function clear() {
  samples = [];
  currentValue.textContent = "--";
  updateStats();
  draw();
}

// --- Stats ----------------------------------------------------------------
function formatNum(n) {
  if (!Number.isFinite(n)) return "--";
  return Math.abs(n) >= 1000 || Number.isInteger(n)
    ? n.toLocaleString()
    : n.toFixed(2);
}

function updateStats() {
  statCount.textContent = String(samples.length);
  if (samples.length === 0) {
    statMin.textContent = statMax.textContent = statAvg.textContent = "--";
    return;
  }
  const vals = samples.map((s) => s.v);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
  statMin.textContent = formatNum(min);
  statMax.textContent = formatNum(max);
  statAvg.textContent = formatNum(avg);
}

// --- Drawing --------------------------------------------------------------
const PAD = { top: 20, right: 16, bottom: 24, left: 48 };

function draw() {
  const W = canvas.width;
  const H = canvas.height;
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  ctx.clearRect(0, 0, W, H);

  if (samples.length === 0) {
    ctx.fillStyle = "#666";
    ctx.font = "16px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Waiting for data...", W / 2, H / 2);
    return;
  }

  const vals = samples.map((s) => s.v);
  let min = Math.min(...vals);
  let max = Math.max(...vals);
  if (min === max) {
    // Flat line — give it some vertical breathing room.
    min -= 1;
    max += 1;
  } else {
    const margin = (max - min) * 0.1;
    min -= margin;
    max += margin;
  }

  const xFor = (i) =>
    PAD.left +
    (samples.length === 1 ? plotW / 2 : (i / (samples.length - 1)) * plotW);
  const yFor = (v) =>
    PAD.top + plotH - ((v - min) / (max - min)) * plotH;

  // Grid + Y axis labels (5 horizontal lines).
  ctx.strokeStyle = "#2a2a2a";
  ctx.fillStyle = "#888";
  ctx.lineWidth = 1;
  ctx.font = "11px system-ui, sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  const ROWS = 4;
  for (let r = 0; r <= ROWS; r++) {
    const y = PAD.top + (r / ROWS) * plotH;
    const val = max - (r / ROWS) * (max - min);
    ctx.beginPath();
    ctx.moveTo(PAD.left, y);
    ctx.lineTo(W - PAD.right, y);
    ctx.stroke();
    ctx.fillText(formatNum(val), PAD.left - 8, y);
  }

  // Area fill under the line.
  ctx.beginPath();
  ctx.moveTo(xFor(0), yFor(samples[0].v));
  for (let i = 1; i < samples.length; i++) ctx.lineTo(xFor(i), yFor(samples[i].v));
  ctx.lineTo(xFor(samples.length - 1), PAD.top + plotH);
  ctx.lineTo(xFor(0), PAD.top + plotH);
  ctx.closePath();
  ctx.fillStyle = "rgba(22, 165, 136, 0.12)";
  ctx.fill();

  // Trend line.
  ctx.beginPath();
  ctx.moveTo(xFor(0), yFor(samples[0].v));
  for (let i = 1; i < samples.length; i++) ctx.lineTo(xFor(i), yFor(samples[i].v));
  ctx.strokeStyle = "#16a588";
  ctx.lineWidth = 2;
  ctx.stroke();

  // Latest point marker.
  const lastI = samples.length - 1;
  ctx.beginPath();
  ctx.arc(xFor(lastI), yFor(samples[lastI].v), 4, 0, Math.PI * 2);
  ctx.fillStyle = "#16a588";
  ctx.fill();
}

// --- Events ---------------------------------------------------------------
startBtn.addEventListener("click", start);
stopBtn.addEventListener("click", stop);
clearBtn.addEventListener("click", clear);

windowInput.addEventListener("change", () => {
  windowSize = Math.max(5, Number(windowInput.value) || 60);
  while (samples.length > windowSize) samples.shift();
  updateStats();
  draw();
});

// --- Weather --------------------------------------------------------------
// Fetches the current weather from the backend (which holds the API key) and
// renders it. Makes it obvious that the panel won't move in bad weather.
async function fetchWeather() {
  try {
    const res = await fetch(WEATHER_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (data.error) {
      weatherDesc.textContent = data.error;
      weatherTemp.textContent = "--";
      weatherIcon.hidden = true;
      weatherBadge.textContent = "";
      weatherBadge.className = "weather__badge";
      return;
    }

    weatherTemp.textContent =
      data.temp != null ? `${Math.round(data.temp)}\u00B0C` : "--";
    weatherDesc.textContent = `${data.description || data.main || ""}${
      data.city ? " \u00B7 " + data.city : ""
    }`;

    if (data.icon) {
      weatherIcon.src = `https://openweathermap.org/img/wn/${data.icon}@2x.png`;
      weatherIcon.hidden = false;
    } else {
      weatherIcon.hidden = true;
    }

    if (data.is_bad) {
      weatherBadge.textContent = "Bad weather \u2014 panel idle";
      weatherBadge.className = "weather__badge weather__badge--bad";
    } else {
      weatherBadge.textContent = "Good weather";
      weatherBadge.className = "weather__badge weather__badge--good";
    }
  } catch (err) {
    weatherDesc.textContent = `Weather unavailable: ${err.message}`;
    weatherTemp.textContent = "--";
    weatherIcon.hidden = true;
    weatherBadge.textContent = "";
    weatherBadge.className = "weather__badge";
  }
}

// Initial render.
updateStats();
draw();
fetchWeather();
setInterval(fetchWeather, WEATHER_REFRESH_MS);
