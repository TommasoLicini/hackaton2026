#include "Arduino_RouterBridge.h"
#include <Servo.h>

// --- Configurazione servo ---
// Pin a cui e' collegato il segnale del servo (filo arancione/giallo).
// Su UNO Q usa un pin PWM: 3, 5, 6, 9, 10 o 11.
const int SERVO_PIN = 9;

// Limiti meccanici del servo (gradi). Adattali al tuo servo.
const int ANGLE_MIN = 0;
const int ANGLE_MAX = 180;

Servo servo;
int currentAngle = 90;  // posizione iniziale (centro)

// Vincola un valore tra due estremi.
int clampAngle(int angle) {
  if (angle < ANGLE_MIN) return ANGLE_MIN;
  if (angle > ANGLE_MAX) return ANGLE_MAX;
  return angle;
}

// Funzione RPC chiamata da Python: imposta l'angolo del servo.
// Restituisce l'angolo effettivamente applicato (dopo il clamp).
int set_servo(int angle) {
  currentAngle = clampAngle(angle);
  servo.write(currentAngle);
  Monitor.print("set_servo -> ");
  Monitor.println(currentAngle);
  return currentAngle;
}

// Funzione RPC chiamata da Python: restituisce l'angolo corrente.
int get_servo() {
  return currentAngle;
}

void setup() {
  Bridge.begin();
  Monitor.begin();

  servo.attach(SERVO_PIN);
  servo.write(currentAngle);

  // Registra le funzioni richiamabili dal lato Linux via Bridge.
  Bridge.provide_safe("set_servo", set_servo);
  Bridge.provide_safe("get_servo", get_servo);

  Monitor.println("Servo bridge ready");
}

void loop() {
  // Nessuna logica bloccante nel loop: il controllo arriva via Bridge.
}
