/*
  ╔══════════════════════════════════════════════════════════╗
  ║          Arduino Robot Arm - ESP32 Firmware              ║
  ║  PCA9685 (servo driver) + I2C slave verso Raspberry Pi   ║
  ╚══════════════════════════════════════════════════════════╝

  Connessioni:
    ESP32 SDA (GPIO21) → PCA9685 SDA  (bus I2C servo)
    ESP32 SCL (GPIO22) → PCA9685 SCL
    ESP32 SDA2 (GPIO17) → RPi SDA     (bus I2C slave, separato)
    ESP32 SCL2 (GPIO16) → RPi SCL
    PCA9685 VCC → 3.3V
    PCA9685 V+ → 5V (alimentazione servo)
    PCA9685 GND → GND comune

  Servo mappatura (canali PCA9685):
    0 → Base / Waist   (MG996R)
    1 → Spalla         (MG996R)
    2 → Gomito         (MG996R)
    3 → Polso Pitch    (SG90)
    4 → Polso Roll     (SG90)
    5 → Gripper        (SG90)

  Protocollo I2C slave (da RPi):
    Byte 0: comando
      0x01 = muovi singolo servo
      0x02 = muovi tutti i servo (snapshot)
      0x03 = vai alla posizione HOME
      0x04 = richiedi stato (lettura)
      0x05 = imposta velocità globale
      0x06 = salva posizione corrente (step)
      0x07 = esegui sequenza salvata
      0x08 = reset sequenza

    Per 0x01: [0x01, servo_id, angolo]
    Per 0x02: [0x02, a0, a1, a2, a3, a4, a5]
    Per 0x05: [0x05, velocità (1-100)]
*/

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// ──────────────────────────────────────────
//  Configurazione I2C
// ──────────────────────────────────────────
#define I2C_SERVO_SDA   21
#define I2C_SERVO_SCL   22
#define I2C_SLAVE_SDA   17
#define I2C_SLAVE_SCL   16
#define I2C_SLAVE_ADDR  0x08   // indirizzo ESP32 come slave
#define PCA9685_ADDR    0x40   // indirizzo PCA9685

// ──────────────────────────────────────────
//  Servo: limiti in microseconds (pulse width)
// ──────────────────────────────────────────
#define SERVO_FREQ      50     // Hz
#define SERVO_MIN_US    500    // µs → 0°
#define SERVO_MAX_US    2400   // µs → 180°

// Limiti angolari per ogni servo [min, max, home]
const int SERVO_LIMITS[6][3] = {
  {0,   180,  90},   // 0: Base
  {30,  170, 150},   // 1: Spalla
  {0,   150,  35},   // 2: Gomito
  {0,   180, 140},   // 3: Polso Pitch
  {0,   180,  85},   // 4: Polso Roll
  {20,  160,  80},   // 5: Gripper
};

// ──────────────────────────────────────────
//  Stato del braccio
// ──────────────────────────────────────────
int currentPos[6];     // posizione corrente (gradi)
int targetPos[6];      // posizione target
int speedDelay = 15;   // ms tra ogni step di movimento (15=veloce, 50=lento)

// Sequenza programmata (max 50 step)
int sequence[50][6];
int seqLength = 0;
bool runningSequence = false;

// Buffer I2C in ingresso
volatile uint8_t i2cBuffer[10];
volatile uint8_t i2cLen = 0;
volatile bool    i2cNewCmd = false;

// ──────────────────────────────────────────
//  PCA9685
// ──────────────────────────────────────────
TwoWire I2C_servo = TwoWire(0);   // bus 0 → PCA9685
TwoWire I2C_slave = TwoWire(1);   // bus 1 → Raspberry Pi

Adafruit_PWMServoDriver pca = Adafruit_PWMServoDriver(PCA9685_ADDR, I2C_servo);

// ──────────────────────────────────────────
//  Utility
// ──────────────────────────────────────────
uint16_t angleToPulse(int angle) {
  // Mappa angolo 0-180 in pulse width in unità PCA9685 (0-4095)
  int us = map(angle, 0, 180, SERVO_MIN_US, SERVO_MAX_US);
  return (uint16_t)(us / (1000000.0 / (SERVO_FREQ * 4096)));
}

int clampAngle(int servo_id, int angle) {
  int lo = SERVO_LIMITS[servo_id][0];
  int hi = SERVO_LIMITS[servo_id][1];
  return constrain(angle, lo, hi);
}

void writeServo(int id, int angle) {
  angle = clampAngle(id, angle);
  pca.setPWM(id, 0, angleToPulse(angle));
  currentPos[id] = angle;
}

// Movimento fluido con rampa
void moveServoSmooth(int id, int target) {
  target = clampAngle(id, target);
  int from = currentPos[id];
  int step  = (target > from) ? 1 : -1;
  for (int pos = from; pos != target; pos += step) {
    pca.setPWM(id, 0, angleToPulse(pos));
    delay(speedDelay);
  }
  pca.setPWM(id, 0, angleToPulse(target));
  currentPos[id] = target;
}

// Muovi tutti i servo simultaneamente (interpolazione parallela)
void moveAllSmooth(int targets[6]) {
  int steps[6], dirs[6], remaining[6];
  int maxSteps = 0;

  for (int i = 0; i < 6; i++) {
    targets[i] = clampAngle(i, targets[i]);
    remaining[i] = abs(targets[i] - currentPos[i]);
    dirs[i] = (targets[i] > currentPos[i]) ? 1 : -1;
    if (remaining[i] > maxSteps) maxSteps = remaining[i];
    steps[i] = 0;
  }

  for (int s = 0; s < maxSteps; s++) {
    for (int i = 0; i < 6; i++) {
      if (steps[i] < remaining[i]) {
        currentPos[i] += dirs[i];
        pca.setPWM(i, 0, angleToPulse(currentPos[i]));
        steps[i]++;
      }
    }
    delay(speedDelay);
  }
}

void goHome() {
  int home[6];
  for (int i = 0; i < 6; i++) home[i] = SERVO_LIMITS[i][2];
  moveAllSmooth(home);
}

// ──────────────────────────────────────────
//  Callback I2C slave
// ──────────────────────────────────────────
void onReceive(int numBytes) {
  i2cLen = 0;
  while (Wire.available() && i2cLen < 10) {
    i2cBuffer[i2cLen++] = Wire.read();
  }
  i2cNewCmd = true;
}

void onRequest() {
  // Il Raspberry chiede lo stato: invia i 6 angoli correnti
  for (int i = 0; i < 6; i++) {
    Wire.write((uint8_t)currentPos[i]);
  }
}

// ──────────────────────────────────────────
//  Elabora comando I2C
// ──────────────────────────────────────────
void processCommand() {
  if (!i2cNewCmd || i2cLen == 0) return;
  i2cNewCmd = false;

  uint8_t cmd = i2cBuffer[0];

  switch (cmd) {

    case 0x01: // Muovi singolo servo
      if (i2cLen >= 3) {
        int id  = i2cBuffer[1];
        int ang = i2cBuffer[2];
        if (id < 6) moveServoSmooth(id, ang);
      }
      break;

    case 0x02: // Muovi tutti i servo
      if (i2cLen >= 7) {
        int targets[6];
        for (int i = 0; i < 6; i++) targets[i] = i2cBuffer[1 + i];
        moveAllSmooth(targets);
      }
      break;

    case 0x03: // HOME
      goHome();
      break;

    case 0x04: // Richiesta stato (la risposta avviene in onRequest)
      break;

    case 0x05: // Imposta velocità
      if (i2cLen >= 2) {
        int spd = i2cBuffer[1];           // 1 (lento) - 100 (veloce)
        speedDelay = map(spd, 1, 100, 50, 3);
      }
      break;

    case 0x06: // Salva posizione corrente nella sequenza
      if (seqLength < 50) {
        for (int i = 0; i < 6; i++) sequence[seqLength][i] = currentPos[i];
        seqLength++;
      }
      break;

    case 0x07: // Esegui sequenza
      runningSequence = true;
      break;

    case 0x08: // Reset sequenza
      seqLength = 0;
      runningSequence = false;
      break;
  }
}

// ──────────────────────────────────────────
//  Setup
// ──────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Serial.println("=== Robot Arm ESP32 ===");

  // Bus I2C verso PCA9685
  I2C_servo.begin(I2C_SERVO_SDA, I2C_SERVO_SCL, 400000);

  // Inizializza PCA9685
  pca.begin();
  pca.setOscillatorFrequency(27000000);
  pca.setPWMFreq(SERVO_FREQ);
  delay(10);

  // Bus I2C slave verso Raspberry Pi
  I2C_slave.begin(I2C_SLAVE_ADDR, I2C_SLAVE_SDA, I2C_SLAVE_SCL, 400000);
  I2C_slave.onReceive(onReceive);
  I2C_slave.onRequest(onRequest);

  // Posizione iniziale
  for (int i = 0; i < 6; i++) {
    currentPos[i] = SERVO_LIMITS[i][2]; // HOME
    targetPos[i]  = currentPos[i];
    writeServo(i, currentPos[i]);
    delay(30);
  }

  Serial.println("Pronto! In ascolto su I2C slave 0x08");
}

// ──────────────────────────────────────────
//  Loop
// ──────────────────────────────────────────
void loop() {
  // Processa comandi I2C ricevuti
  processCommand();

  // Esegui sequenza programmata
  if (runningSequence && seqLength > 0) {
    for (int step = 0; step < seqLength && runningSequence; step++) {
      int targets[6];
      for (int i = 0; i < 6; i++) targets[i] = sequence[step][i];
      moveAllSmooth(targets);
      delay(200); // pausa tra step
      processCommand(); // controlla stop durante sequenza
    }
    // Loop continuo finché non arriva RESET
    if (runningSequence) {
      // ricomincia (il flag viene abbassato dal cmd 0x08)
    } else {
      runningSequence = false;
    }
  }

  delay(5);
}
