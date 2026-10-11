# Smart Solar Panel Monitor — Arduino UNO Q

Progetto hackathon per il monitoraggio intelligente di pannelli solari basato su **Arduino UNO Q**. Il sistema unisce un microcontrollore (sketch Arduino), un backend Python con AI edge e una Web UI per: misurare la corrente prodotta, rilevare pannelli sporchi o danneggiati tramite una camera con modello AI, orientare il pannello con un servo e inviare avvisi su Telegram.

## Architettura

Il progetto sfrutta il modello **Bridge** della UNO Q, dove la parte Linux (Python) e il microcontrollore (sketch) comunicano via RPC. La parte Linux è sempre quella che inizia la comunicazione.

```
┌───────────────┐   Bridge RPC    ┌────────────────┐   Web UI / HTTP   ┌──────────┐
│  Sketch (MCU) │ <-------------> │  Python (Linux)│ <---------------> │ Browser  │
│  servo + ADC  │  set_servo      │  AI + Web UI   │  /camera /value   │  pagine  │
│               │  get_current    │  Telegram bot  │  /weather socket  │  web     │
└───────────────┘                 └────────────────┘                   └──────────┘
```

- **MCU (`sketch/sketch.ino`)**: legge la corrente del pannello dall'ADC e controlla il servo. Espone tre funzioni RPC via Bridge: `set_servo`, `get_servo`, `get_current`.
- **Backend (`python/main.py`)**: AI edge, Web UI, API HTTP, bot Telegram e integrazione meteo. Fa da ponte tra MCU e browser.
- **Frontend (`assets/`)**: tre pagine web servite dalla Web UI brick.

## Concetti principali

### 1. Misura della corrente e soiling ratio
Lo sketch misura la tensione ai capi di una resistenza di carico (`R_OHM`) e ricava la corrente con la legge di Ohm (`I = V / R`). Il valore viene mediato su più campioni (`N_SAMPLES`) e salvato in una variabile atomica (`lastCurrentMa`) perché letto da un contesto diverso (la callback RPC del Bridge). L'idea è confrontare un pannello pulito con uno sporco per stimare il *soiling ratio*. Controlli di sicurezza avvisano se la tensione è vicina al fondo scala o se la luce è troppo bassa.


### 2. Rilevamento AI dei pannelli sporchi/danneggiati
Il backend usa `VideoImageClassification` con un modello **Edge Impulse** distribuito manualmente (`model.yaml`). Ogni rilevamento (coppia `label: confidence`) viene inoltrato al frontend. Quando viene rilevato il label `damage`, parte un avviso Telegram.

### 3. Streaming camera e pairing con lo smartphone
La `WebSocketCamera` si accoppia con l'app Arduino IoT Remote tramite un **secret numerico a 6 cifre** mostrato come QR code. Il flusso elaborato (con overlay delle detection) viene esposto come stream **MJPEG** su `/camera` e mostrato in un `<img>` nel browser. La pagina alterna tra schermata di pairing (QR) e stream live in base allo stato della camera.

### 4. Controllo del servo
`servo.html` permette di orientare il pannello tramite slider e preset. Il browser invia il messaggio `set_angle`; il backend chiama `Bridge.call("set_servo", angle)` sull'MCU, che applica l'angolo (con clamp tra `ANGLE_MIN` e `ANGLE_MAX`) e restituisce il valore effettivo, rimandato al frontend.

### 5. Trend della corrente e meteo
`graph.html` mostra un grafico live della corrente. Il frontend fa polling su `GET /value`, che chiama in modo sincrono `get_current` sull'MCU. La pagina mostra anche il meteo corrente (`GET /weather`): la chiave OpenWeather è letta **solo lato server** dall'ambiente e mai inviata al browser. Il meteo serve a spiegare perché il pannello non si muove / la corrente resta piatta quando il tempo è brutto.

### 6. Avvisi Telegram
Un `TelegramBot` con comando `/connect` registra le chat interessate. Alla rilevazione di un `damage`, invia un messaggio e una foto del frame (codificato in JPEG via OpenCV o Pillow). Gli avvisi sono limitati a uno ogni 10 minuti per chat.

## Struttura del progetto

```
.
├── app.yaml              # Config app Arduino (Web UI + classificazione video)
├── model.yaml            # Config modello Edge Impulse (edge AI)
├── .env                  # Variabili d'ambiente (OPENWEATHER_API_KEY, WEATHER_CITY)
├── python/
│   └── main.py           # Backend: AI, Web UI, API, Telegram, Bridge
├── sketch/
│   ├── sketch.ino        # Firmware MCU: ADC corrente + controllo servo
│   └── sketch.yaml       # Profilo build (platform arduino:zephyr)
├── assets/
│   ├── index.html        # Camera stream + pairing + ultima detection
│   ├── servo.html        # Controllo servo
│   ├── graph.html        # Trend corrente live + meteo
│   ├── app.js, graph.js  # Logica frontend
│   ├── style.css, graph.css
│   └── libs/             # socket.io, arduino.js (WebUI), qrcode (locali)
├── CAD/Assem1.STEP       # Modello CAD meccanico
└── ardino.kicad_sch      # Schema elettrico KiCad
```

## Configurazione

Crea/compila il file `.env` nella root del progetto:

```
OPENWEATHER_API_KEY=la_tua_chiave
WEATHER_CITY=Turin,IT
```

Le variabili d'ambiente già presenti nel sistema hanno la precedenza sul file `.env`.

## API ed eventi

**HTTP (stessa origin della Web UI)**
- `GET /camera` — stream MJPEG con overlay delle detection
- `GET /value` — ultima corrente misurata in mA (via RPC `get_current`)
- `GET /weather` — meteo corrente trimmato da OpenWeather

**Messaggi Web UI (socket)**
- Backend → frontend: `welcome`, `connected`, `streaming`, `paused`, `disconnected`, `detection`, `servo_state`
- Frontend → backend: `set_angle`, `override_th`

**RPC Bridge (MCU)**
- `set_servo(angle)` → angolo applicato
- `get_servo()` → angolo corrente
- `get_current()` → ultima corrente (mA)

## Hardware

- Arduino UNO Q
- Pannelli solari (riferimento pulito + confronto)
- Resistenza di carico + filtro RC (1 kΩ / 100 nF) sul pin analogico
- Servo su pin PWM (pin 9)
- Camera dello smartphone via app Arduino IoT Remote
