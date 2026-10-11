#include "Arduino_RouterBridge.h"
#include <Servo.h>
#include "ArduinoGraphics.h"
#include "Arduino_LED_Matrix.h"
#include <atomic>

/*
 * Misura del soiling ratio con due pannelli identici (uno pulito, uno sporco).
 *
 * Schema (per ciascun pannello):
 *
 *   PANNELLO + ----+---------------- R_carico ---- GND
 *                  |
 *                  +-- 1 kΩ --+--> pin analogico
 *                             |
 *                           100 nF
 *                             |
 *                            GND
 *   PANNELLO - ------------------------------------ GND
 *
 * La corrente si ricava dalla legge di Ohm: I = V / R.
 * NON collegare mai il pannello direttamente al pin analogico.

 */

// ---------------- CONFIGURAZIONE (da adattare) ----------------
const int PIN_PANEL = A0;            // pannello di riferimento (pulito)

const float R_OHM = 9;

const float    VREF       = 3.3;     // tensione di riferimento dell'ADC
const uint8_t  ADC_BITS   = 12;      // risoluzione richiesta: verifica quella supportata dalla scheda
const uint16_t N_SAMPLES  = 64;      // campioni mediati per ogni misura

const float I_MIN_MA      = 5.0;    // sotto questa corrente la luce e' troppo bassa
const float V_WARN_FRAC   = 0.90;    // avviso se la tensione supera il 90% del fondo scala

const unsigned long PERIOD_MS = 1000; // intervallo tra le stampe
// ----------------------------------------------------------------


float adc_max() {
  return (float)((1UL << ADC_BITS) - 1);
}

// Tensione media sul pin, in volt
float read_voltage(int pin) {
  analogRead(pin); 
  delayMicroseconds(100);
  uint32_t sum = 0;
  for (uint16_t i = 0; i < N_SAMPLES; i++) {
    sum += analogRead(pin);
    delayMicroseconds(200);
  }
  float avg = (float)sum / (float)N_SAMPLES;
  return avg * VREF / adc_max();
}

// Misura contemporanea (in rapida successione) di entrambi i canali
void measure(float &vPanel, float &iPanel) {
  vPanel = read_voltage(PIN_PANEL);
  iPanel = vPanel / R_OHM * 1000.0;
}


// --- Configurazione servo ---
// Pin a cui e' collegato il segnale del servo (filo arancione/giallo).
// Su UNO Q usa un pin PWM: 3, 5, 6, 9, 10 o 11.
const int SERVO_PIN = 9;

// Limiti meccanici del servo (gradi). Adattali al tuo servo.
const int ANGLE_MIN = 0;
const int ANGLE_MAX = 180;

Servo servo;
int currentAngle = 90;  // posizione iniziale (centro)

// Ultima corrente misurata (mA). Scritta nel loop() e letta dalla callback RPC
// del Bridge (contesti diversi): atomica per evitare letture incoerenti.
std::atomic<float> lastCurrentMa{0.0f};

// Vincola un valore tra due estremi.
int clamp_angle(int angle) {
  if (angle < ANGLE_MIN) return ANGLE_MIN;
  if (angle > ANGLE_MAX) return ANGLE_MAX;
  return angle;
}

// Funzione RPC chiamata da Python: imposta l'angolo del servo.
// Restituisce l'angolo effettivamente applicato (dopo il clamp).
int set_servo(int angle) {
  currentAngle = clamp_angle(angle);
  servo.write(currentAngle);
  Monitor.print("set_servo -> ");
  Monitor.println(currentAngle);
  return currentAngle;
}

// Funzione RPC chiamata da Python: restituisce l'angolo corrente.
int get_servo() {
  return currentAngle;
}

// Funzione RPC chiamata da Python: restituisce l'ultima corrente misurata (mA).
// Python interroga questa funzione a intervalli regolari (pattern Linux->MCU).
float get_current() {
  return lastCurrentMa.load();
}

void setup() {
  Bridge.begin();
  Monitor.begin();
  servo.attach(SERVO_PIN);
  servo.write(currentAngle);

  analogReadResolution(ADC_BITS);
  // Registra le funzioni richiamabili dal lato Linux via Bridge.
  Bridge.provide_safe("set_servo", set_servo);
  Bridge.provide_safe("get_servo", get_servo);
  Bridge.provide_safe("get_current", get_current);

  Monitor.println("Servo bridge ready");
}

void loop() {
  float v, i;
  measure(v, i);

  // Memorizza l'ultima misura: Python la legge via Bridge.call("get_current").
  lastCurrentMa.store(i);

  // Controlli di sicurezza/validita'
  if (v > VREF * V_WARN_FRAC) {
    Monitor.println("ATTENZIONE: tensione vicina al fondo scala. Riduci la resistenza di carico.");
  }

  if (i < I_MIN_MA) {
    Monitor.println("Luce bassa");
  }

  Monitor.print(i);
  Monitor.println(" mA");
}
