/*
 * ================================================================
 *  ESP32 SENSORI — FIRMWARE SOLO I2C (WiFi/MQTT rimossi)
 *
 *  Il Raspberry Pi è l'UNICO punto di comunicazione con l'esterno.
 *  Questo ESP32 parla SOLO via I2C slave (0x09) col Pi — nessun WiFi,
 *  nessun MQTT, nessuna gestione credenziali/broker/mDNS. Tutto il
 *  traffico verso controller esterni/dashboard passa dal Pi, che
 *  legge il buffer sensori via I2C e scrive comandi servo via I2C.
 *
 *  FIX rispetto alla versione con WiFi/MQTT:
 *
 *  1. RIMOSSO tutto il networking (WiFi, MQTT, mDNS, NVS credenziali,
 *     ArduinoJson — non più necessario senza parsing JSON via MQTT)
 *
 *  2. AGGIUNTO opcode I2C 0xAD (ch, ang) → enqueueServo() [smooth]
 *     Il bridge Python sul Pi (testI2C.py) manda già questo opcode
 *     per i comandi servo (sia da MQTT robot/sensori/cmd sia da UDP
 *     diretto porta 5566) — prima d'ora l'I2C handler qui riconosceva
 *     solo 0xAA (posizione immediata) e 0xAB (relativo immediato),
 *     quindi 0xAD veniva SEMPRE ignorato silenziosamente: i comandi
 *     servo dal Pi non arrivavano mai a destinazione via I2C.
 *     Ora 0xAD usa la coda smooth (stesso movimento graduale già
 *     usato dai comandi seriali s0..s6).
 *
 *  3. ULTRASUONI — rivisti per correttezza e frequenza:
 *     - Macchina a stati a 3 fasi (ST_IDLE → ST_TRIG_HIGH → ST_WAIT_END)
 *       con lettura ISR atomica (noInterrupts/interrupts): CORRETTA,
 *       nessun bug di race condition trovato.
 *     - Timeout eco: 25ms = ~430cm (formula distanza_cm = durata_us/58
 *       verificata: 25000/58 ≈ 431cm) → margine coerente col taglio
 *       fisico a DIST_MAX_CM=300cm. CORRETTO.
 *     - TRIGGER_INTERVAL_US ridotto da 50ms a 30ms per aumentare la
 *       frequenza di refresh per sensore da ~20Hz a ~33Hz. Lo
 *       sfalsamento iniziale di 9ms tra i 6 sensori (al boot) è
 *       preservato nel tempo perché ogni sensore riprogramma il
 *       proprio prossimo trigger relativamente al proprio timestamp
 *       precedente, non a un clock globale — quindi il rischio di
 *       interferenza acustica tra sensori vicini resta basso.
 *       Se in pratica noti letture erratiche/rumorose con 6 sensori
 *       ravvicinati, alza di nuovo questo valore verso 40-50ms.
 *
 *  4. TUTTO IL RESTO invariato: servo coda smooth, MPU6050, TCRT,
 *     relè, comandi seriali via USB per debug.
 *
 * ────────────────────────────────────────────────────────────────
 *  COMANDI SERIALI (invariati, terminare con Invio):
 *  s0..s6 <gradi>   r0..r6 <delta>   set <s0>..<s6>
 *  raw <ch> <tick>  home  riposo  rele on/off
 *  pos  dist  imu  tcrt  tcrt watch  stato  help
 *
 * ────────────────────────────────────────────────────────────────
 *  COMANDI I2C IN INGRESSO (dal Pi, indirizzo slave 0x09):
 *   0xAA <ch> <ang>        → setServo immediato (0-180, salta la coda)
 *   0xAB <ch> <val+128>    → moveServo relativo immediato
 *   0xAC <val>             → relè (1=on, 0=off)
 *   0xAD <ch> <ang>        → enqueueServo SMOOTH (usato dal Pi bridge)
 *   0xAE                   → home (tutti i servo, smooth)
 *   0xAF                   → riposo (smooth)
 *   0xB0 <ms>              → velocità servo (ms/passo, 1-50)
 *   0xFD / 0xFE            → RIMOSSI (erano credenziali WiFi)
 *
 *  BUFFER I2C IN USCITA (26 byte, richiesta standard I2C read):
 *   [0-11]  distanze ultrasuoni (6 × uint16 LE, cm, 9999=fuori portata)
 *   [12-23] IMU (ax,ay,az,gx,gy,gz) int16 LE ×100
 *   [24]    TCRT mask (bit0=sx bit1=cen bit2=dx, 1=nero)
 *   [25]    relè (0/1)
 *
 * ────────────────────────────────────────────────────────────────
 *  MAPPA SERVO BRACCIO:
 *   CH0 → Base rotazione       CH4 → Polso rotazione
 *   CH1 → Spalla                CH5 → Pinza (home=120°)
 *   CH2 → Gomito                CH6 → Settimo/telecamera (80°-170°, home=125°)
 *   CH3 → Polso verticale
 * ================================================================
 */

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <MPU6050_light.h>

// ── I2C ──────────────────────────────────────────────────────────
#define I2C_SLAVE_ADDR 0x09
#define SDA_SLAVE 21
#define SCL_SLAVE 22
#define SDA_MASTER 32
#define SCL_MASTER 33

// ── SERVO (PCA9685 su Wire1) ──────────────────────────────────────
#define SERVO_MIN  102
#define SERVO_MAX  512
#define NUM_SERVO  7

#define SERVO6_MIN_DEG  80
#define SERVO6_MAX_DEG  170

const char* SERVO_NAMES[NUM_SERVO] = {
  "Base      ",
  "Spalla    ",
  "Gomito    ",
  "Polso-V   ",
  "Polso-R   ",
  "Pinza     ",
  "Settimo   "
};

const int SERVO_HOME[NUM_SERVO]   = { 90, 90,  90, 90, 90, 120, 125 };
const int SERVO_RIPOSO[NUM_SERVO] = { 90, 30,  60, 90, 90,  90, 125 };

Adafruit_PWMServoDriver pca = Adafruit_PWMServoDriver(0x40, Wire1);
int servoPos[NUM_SERVO] = { 90, 90, 90, 90, 90, 120, 125 };

// ── CODA SERVO (smooth, sequenziale) ─────────────────────────────
#define SERVO_QUEUE_SIZE 32

struct ServoMove {
  uint8_t ch;
  int     target;
};

ServoMove servoQueue[SERVO_QUEUE_SIZE];
uint8_t   servoQHead  = 0;
uint8_t   servoQTail  = 0;
uint8_t   servoQCount = 0;

int      servoCurrentTarget = -1;
uint32_t lastServoStepMs    = 0;
uint8_t  servoStepMs        = 8;

int  degreesToTick(int deg);

bool enqueueServo(uint8_t ch, int target) {
  if (servoQCount >= SERVO_QUEUE_SIZE) {
    Serial.println(F("[SERVO] Coda piena, mossa scartata!"));
    return false;
  }
  if (ch == 6) target = constrain(target, SERVO6_MIN_DEG, SERVO6_MAX_DEG);
  else         target = constrain(target, 0, 180);
  servoQueue[servoQTail] = { ch, target };
  servoQTail  = (servoQTail + 1) % SERVO_QUEUE_SIZE;
  servoQCount++;
  return true;
}

void updateServoQueue() {
  uint32_t now = millis();
  if ((now - lastServoStepMs) < servoStepMs) return;
  lastServoStepMs = now;

  if (servoCurrentTarget < 0) {
    if (servoQCount == 0) return;
    ServoMove& m = servoQueue[servoQHead];
    servoCurrentTarget = m.target;
    if (servoPos[m.ch] == servoCurrentTarget) {
      servoQHead  = (servoQHead + 1) % SERVO_QUEUE_SIZE;
      servoQCount--;
      servoCurrentTarget = -1;
      return;
    }
  }

  ServoMove& m = servoQueue[servoQHead];

  if      (servoPos[m.ch] < m.target) servoPos[m.ch]++;
  else if (servoPos[m.ch] > m.target) servoPos[m.ch]--;

  pca.setPWM(m.ch, 0, degreesToTick(servoPos[m.ch]));

  if (servoPos[m.ch] == m.target) {
    Serial.printf("[SERVO] S%d %s-> %d gradi OK\n", m.ch, SERVO_NAMES[m.ch], m.target);
    servoQHead  = (servoQHead + 1) % SERVO_QUEUE_SIZE;
    servoQCount--;
    servoCurrentTarget = -1;
  }
}

// ── ULTRASUONI ────────────────────────────────────────────────────
// Stato a 3 fasi. Timeout misurato da quando entriamo in ST_WAIT_END
// (dopo il pulse LOW). echoGot letto atomicamente con noInterrupts().
// echoGot NON viene mai azzerato in ST_IDLE per evitare race condition
// (si azzera solo quando lo leggiamo, in ST_WAIT_END).

#define NSENS 6
const uint8_t TRIG_PINS[NSENS]    = { 27, 25, 4,  13, 18, 16 };
const uint8_t ECHO_PINS[NSENS]    = { 14, 26, 5,  12, 19, 17 };
const char*   SENSOR_NAMES[NSENS] = { "FRONTE", "RETRO", "SINISTRA", "DESTRA", "CLIFF_F", "CLIFF_R" };

#define TRIGGER_PULSE_US       10      // durata pulse TRIG (10µs, min HC-SR04)

// Intervallo minimo tra due trigger dello STESSO sensore.
// Ridotto da 50ms a 30ms → refresh per sensore ~33Hz (era ~20Hz).
// Lo sfalsamento di 9ms tra sensori (impostato al boot) limita il
// rischio di crosstalk acustico tra HC-SR04 ravvicinati. Se nella
// pratica vedi letture rumorose/incoerenti con più sensori vicini,
// alza questo valore (es. torna a 40000-50000).
#define TRIGGER_INTERVAL_US    30000

// Timeout attesa eco: 25ms = ~430cm (distanza_cm = durata_us/58).
// HC-SR04 range reale: 2cm-400cm → eco max ~23ms, 25ms lascia margine.
#define ECHO_TIMEOUT_US        25000

// Distanza massima valida in cm (oltre = oggetto fuori portata)
#define DIST_MAX_CM            300

enum SensorState { ST_IDLE, ST_TRIG_HIGH, ST_WAIT_END };

struct Sensor {
  SensorState state;
  uint32_t    stateStartUs;
  uint32_t    lastTriggerUs;
  uint16_t    distanceCm;
  uint16_t    history[3];
  uint8_t     histIdx;
};
Sensor sensors[NSENS];

volatile uint32_t echoRiseUs[NSENS];
volatile uint32_t echoFallUs[NSENS];
volatile bool     echoGot[NSENS];

void IRAM_ATTR echoISR0(){ if(digitalRead(ECHO_PINS[0])){ echoRiseUs[0]=micros(); } else { echoFallUs[0]=micros(); echoGot[0]=true; } }
void IRAM_ATTR echoISR1(){ if(digitalRead(ECHO_PINS[1])){ echoRiseUs[1]=micros(); } else { echoFallUs[1]=micros(); echoGot[1]=true; } }
void IRAM_ATTR echoISR2(){ if(digitalRead(ECHO_PINS[2])){ echoRiseUs[2]=micros(); } else { echoFallUs[2]=micros(); echoGot[2]=true; } }
void IRAM_ATTR echoISR3(){ if(digitalRead(ECHO_PINS[3])){ echoRiseUs[3]=micros(); } else { echoFallUs[3]=micros(); echoGot[3]=true; } }
void IRAM_ATTR echoISR4(){ if(digitalRead(ECHO_PINS[4])){ echoRiseUs[4]=micros(); } else { echoFallUs[4]=micros(); echoGot[4]=true; } }
void IRAM_ATTR echoISR5(){ if(digitalRead(ECHO_PINS[5])){ echoRiseUs[5]=micros(); } else { echoFallUs[5]=micros(); echoGot[5]=true; } }

// ── TCRT5000 ──────────────────────────────────────────────────────
#define TCRT_SX     35
#define TCRT_CENTRO 36
#define TCRT_DX     23

uint8_t lastTcrtDebug = 0xFF;

// ── MPU6050 (su Wire1) ────────────────────────────────────────────
#define MPU_INT_PIN   34
#define MPU_UPDATE_MS 10
MPU6050 mpu(Wire1);

// ── RELÈ ─────────────────────────────────────────────────────────
#define RELE_PIN 2

// ── BUFFER I2C → Pi ───────────────────────────────────────────────
#define I2C_BUF_SIZE 26
volatile uint8_t i2cBuf[I2C_BUF_SIZE];

inline void bufWrite16(int o, uint16_t v) {
  i2cBuf[o]     = (uint8_t)(v & 0xFF);
  i2cBuf[o + 1] = (uint8_t)(v >> 8);
}
inline void bufWriteI16(int o, int16_t v) {
  bufWrite16(o, (uint16_t)v);
}

// ── RICEZIONE COMANDI I2C ─────────────────────────────────────────
uint8_t  rxBuf[128];
uint8_t  rxLen = 0;
volatile bool newCmd = false;

// ════════════════════════════════════════════════════════════════
//  Prototipi
// ════════════════════════════════════════════════════════════════
int  degreesToTick(int deg);
void setServo(uint8_t ch, int deg);
void moveServo(uint8_t ch, int delta);
void servoHome();
void servoRiposo();
void updateTCRT();
uint16_t mediana3(uint16_t a, uint16_t b, uint16_t c);

// ════════════════════════════════════════════════════════════════
//  SERVO
// ════════════════════════════════════════════════════════════════

int degreesToTick(int deg) {
  return map(deg, 0, 180, SERVO_MIN, SERVO_MAX);
}

void setServo(uint8_t ch, int deg) {
  if (ch >= NUM_SERVO) return;
  if (ch == 6) deg = constrain(deg, SERVO6_MIN_DEG, SERVO6_MAX_DEG);
  else         deg = constrain(deg, 0, 180);
  servoPos[ch] = deg;
  pca.setPWM(ch, 0, degreesToTick(deg));
}

void moveServo(uint8_t ch, int delta) {
  if (ch >= NUM_SERVO) return;
  setServo(ch, servoPos[ch] + delta);
}

void servoHome() {
  for (int i = 0; i < NUM_SERVO; i++) enqueueServo(i, SERVO_HOME[i]);
  Serial.println("Braccio -> HOME (accodato)");
}

void servoRiposo() {
  for (int i = 0; i < NUM_SERVO; i++) enqueueServo(i, SERVO_RIPOSO[i]);
  Serial.println("Braccio -> RIPOSO (accodato)");
}

// ════════════════════════════════════════════════════════════════
//  CALLBACK I2C SLAVE — UNICO canale di comunicazione col Pi
// ════════════════════════════════════════════════════════════════

void onRequest() {
  Wire.write((uint8_t*)i2cBuf, I2C_BUF_SIZE);
}

void onReceive(int numBytes) {
  rxLen = 0;
  while (Wire.available() && rxLen < sizeof(rxBuf) - 1)
    rxBuf[rxLen++] = Wire.read();
  newCmd = true;
}

// ════════════════════════════════════════════════════════════════
//  ESEGUI COMANDO I2C (chiamato nel loop, mai nell'ISR)
// ════════════════════════════════════════════════════════════════

void eseguiComando() {
  if (!newCmd) return;
  newCmd = false;
  uint8_t cmd = rxBuf[0];

  if (rxLen < 3) {
    // 0xAE (home) e 0xAF (riposo) sono comandi a 1 byte, gestiti sotto
    if (cmd == 0xAE) { servoHome();   return; }
    if (cmd == 0xAF) { servoRiposo(); return; }
    return;
  }

  uint8_t ch  = rxBuf[1];
  uint8_t val = rxBuf[2];

  if (cmd == 0xAA && ch < NUM_SERVO) {
    // Posizione assoluta IMMEDIATA (salta la coda, movimento a scatto)
    setServo(ch, (int)val);

  } else if (cmd == 0xAB && ch < NUM_SERVO) {
    // Movimento relativo IMMEDIATO
    moveServo(ch, (int)val - 128);

  } else if (cmd == 0xAC) {
    // Relè pompa
    digitalWrite(RELE_PIN, val ? HIGH : LOW);

  } else if (cmd == 0xAD && ch < NUM_SERVO) {
    // FIX: opcode usato dal bridge Pi (testI2C.py) — mancava prima.
    // Posizione assoluta SMOOTH (accodata, movimento graduale).
    enqueueServo(ch, (int)val);

  } else if (cmd == 0xB0) {
    // Velocità servo: ms tra un passo e l'altro (1-50)
    int ms = (int)val;
    if (ms >= 1 && ms <= 50) {
      servoStepMs = (uint8_t)ms;
      Serial.printf("Velocita servo -> %d ms/passo (~%.0f gradi/s)\n",
                    servoStepMs, 1000.0f / servoStepMs);
    }
  }
}

// ════════════════════════════════════════════════════════════════
//  SERIAL — print helpers
// ════════════════════════════════════════════════════════════════

void printHelp() {
  Serial.println(F("\n============== COMANDI SERIALI ==================="));
  Serial.println(F("  SERVO SINGOLO - posizione assoluta (0-180) [smooth]:"));
  Serial.println(F("    s0 <gradi>    Base rotazione"));
  Serial.println(F("    s1 <gradi>    Spalla"));
  Serial.println(F("    s2 <gradi>    Gomito"));
  Serial.println(F("    s3 <gradi>    Polso verticale"));
  Serial.println(F("    s4 <gradi>    Polso rotazione"));
  Serial.println(F("    s5 <gradi>    Pinza  (es: s5 30 = chiusa)"));
  Serial.println(F("    s6 <gradi>    Settimo servo (limiti: 80-170)"));
  Serial.println(F(""));
  Serial.println(F("  SERVO SINGOLO - movimento relativo (+/- gradi) [smooth]:"));
  Serial.println(F("    r0 <delta>    es: r0 10  oppure  r0 -15"));
  Serial.println(F("    r1..r6        (stessa sintassi)"));
  Serial.println(F(""));
  Serial.println(F("  PIU SERVO INSIEME - sequenza s0->s6 [smooth]:"));
  Serial.println(F("    set <s0> <s1> <s2> <s3> <s4> <s5> <s6>"));
  Serial.println(F("        usa -1 per lasciare un servo invariato"));
  Serial.println(F(""));
  Serial.println(F("  RAW TICK (calibrazione, movimento IMMEDIATO):"));
  Serial.println(F("    raw <ch> <tick>  es: raw 0 307"));
  Serial.println(F(""));
  Serial.println(F("  PRESET [smooth]:"));
  Serial.println(F("    home          Tutti i servo in posizione home"));
  Serial.println(F("    riposo        Posizione di riposo braccio"));
  Serial.println(F(""));
  Serial.println(F("  RELE POMPA:"));
  Serial.println(F("    rele on       Accende la pompa"));
  Serial.println(F("    rele off      Spegne la pompa"));
  Serial.println(F(""));
  Serial.println(F("  INFO SENSORI:"));
  Serial.println(F("    pos           Posizioni servo correnti"));
  Serial.println(F("    dist          Distanze ultrasuoni"));
  Serial.println(F("    imu           Dati accelerometro + giroscopio"));
  Serial.println(F("    tcrt          Stato sensori linea TCRT"));
  Serial.println(F("    tcrt watch    Monitor live TCRT (Invio per uscire)"));
  Serial.println(F("    stato         Tutto insieme"));
  Serial.println(F("    help          Questo elenco"));
  Serial.println(F("=================================================\n"));
}

void printPos() {
  Serial.println(F("\n--- POSIZIONI SERVO -----------------------------"));
  for (int i = 0; i < NUM_SERVO; i++)
    Serial.printf("  CH%d %s: %3d gradi\n", i, SERVO_NAMES[i], servoPos[i]);
  Serial.printf("  Velocita: %d ms/passo (~%.0f gradi/s)  |  Coda: %d mosse\n",
                servoStepMs, 1000.0f / servoStepMs, servoQCount);
  Serial.println(F("-------------------------------------------------\n"));
}

void printDist() {
  Serial.println(F("\n--- ULTRASUONI ----------------------------------"));
  for (int i = 0; i < NSENS; i++) {
    uint16_t d = i2cBuf[i*2] | ((uint16_t)i2cBuf[i*2+1] << 8);
    if (d == 9999) Serial.printf("  %-10s: ---\n", SENSOR_NAMES[i]);
    else           Serial.printf("  %-10s: %u cm\n", SENSOR_NAMES[i], d);
  }
  Serial.println(F("-------------------------------------------------\n"));
}

void printImu() {
  int16_t ax = (int16_t)(i2cBuf[12] | ((uint16_t)i2cBuf[13] << 8));
  int16_t ay = (int16_t)(i2cBuf[14] | ((uint16_t)i2cBuf[15] << 8));
  int16_t az = (int16_t)(i2cBuf[16] | ((uint16_t)i2cBuf[17] << 8));
  int16_t gx = (int16_t)(i2cBuf[18] | ((uint16_t)i2cBuf[19] << 8));
  int16_t gy = (int16_t)(i2cBuf[20] | ((uint16_t)i2cBuf[21] << 8));
  int16_t gz = (int16_t)(i2cBuf[22] | ((uint16_t)i2cBuf[23] << 8));
  Serial.println(F("\n--- IMU -----------------------------------------"));
  Serial.printf("  ACC  X:%.2f  Y:%.2f  Z:%.2f g\n",
    ax/100.0, ay/100.0, az/100.0);
  Serial.printf("  GYRO X:%.2f  Y:%.2f  Z:%.2f deg/s\n",
    gx/100.0, gy/100.0, gz/100.0);
  Serial.println(F("-------------------------------------------------\n"));
}

void printTcrt() {
  uint8_t mask = i2cBuf[24];
  bool sx  = mask & 0x01;
  bool cen = mask & 0x02;
  bool dx  = mask & 0x04;
  Serial.println(F("\n--- TCRT SENSORI LINEA --------------------------"));
  Serial.printf("  SX:%s  CENTRO:%s  DX:%s\n",
    sx  ? "ON " : "off",
    cen ? "ON " : "off",
    dx  ? "ON " : "off");
  Serial.print(F("  ["));
  Serial.print(sx  ? "XXX" : "   ");
  Serial.print(F("|"));
  Serial.print(cen ? "XXX" : "   ");
  Serial.print(F("|"));
  Serial.print(dx  ? "XXX" : "   ");
  Serial.println(F("]  <- nero=rilevato"));
  Serial.printf("   SX      CEN     DX    (mask=0x%02X)\n", mask);
  Serial.print(F("  Posizione: "));
  switch (mask & 0x07) {
    case 0b000: Serial.println(F("LINEA PERSA")); break;
    case 0b010: Serial.println(F("CENTRATO")); break;
    case 0b111: Serial.println(F("INCROCIO / linea larga")); break;
    case 0b001: Serial.println(F("DEVIARE A DESTRA (linea a sx)")); break;
    case 0b100: Serial.println(F("DEVIARE A SINISTRA (linea a dx)")); break;
    case 0b011: Serial.println(F("LEGGERMENTE A DESTRA")); break;
    case 0b110: Serial.println(F("LEGGERMENTE A SINISTRA")); break;
    case 0b101: Serial.println(F("LINEA SPEZZATA / rumore")); break;
    default:    Serial.printf("  mask=0x%02X\n", mask); break;
  }
  Serial.println(F("-------------------------------------------------\n"));
}

void printStato() {
  printPos();
  printDist();
  printImu();
  printTcrt();
  Serial.println(F("--- RELE ------------------------------------------"));
  Serial.printf("  Rele : %s\n", digitalRead(RELE_PIN) ? "ON" : "off");
  Serial.println(F("  Comunicazione: SOLO I2C 0x09 col Raspberry Pi."));
  Serial.println(F("-------------------------------------------------\n"));
}

// ════════════════════════════════════════════════════════════════
//  SERIAL — parsing comandi
// ════════════════════════════════════════════════════════════════

void manageSerial() {
  if (!Serial.available()) return;

  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;

  String lline = line;
  lline.toLowerCase();

  if (lline == "help" || lline == "?") { printHelp();   return; }
  if (lline == "pos")                  { printPos();    return; }
  if (lline == "dist")                 { printDist();   return; }
  if (lline == "imu")                  { printImu();    return; }
  if (lline == "tcrt")                 { printTcrt();   return; }
  if (lline == "stato")                { printStato();  return; }
  if (lline == "home")                 { servoHome();   return; }
  if (lline == "riposo")               { servoRiposo(); return; }

  if (lline == "rele on") {
    digitalWrite(RELE_PIN, HIGH);
    Serial.println("Pompa ON");
    return;
  }
  if (lline == "rele off") {
    digitalWrite(RELE_PIN, LOW);
    Serial.println("Pompa OFF");
    return;
  }

  if (lline == "tcrt watch") {
    Serial.println(F("TCRT watch - premi Invio per uscire"));
    uint8_t prevMask = 0xFF;
    while (!Serial.available()) {
      updateTCRT();
      uint8_t mask = i2cBuf[24];
      if (mask != prevMask) {
        prevMask = mask;
        Serial.printf("[%lu ms] SX:%s CEN:%s DX:%s (0x%02X) -> %s\n",
          millis(),
          (mask & 0x01) ? "ON " : "off",
          (mask & 0x02) ? "ON " : "off",
          (mask & 0x04) ? "ON " : "off",
          mask,
          (mask == 0b000) ? "PERSA"    : (mask == 0b010) ? "CENTRATO"
        : (mask == 0b111) ? "INCROCIO" : (mask == 0b001) ? "DEVIA DX"
        : (mask == 0b100) ? "DEVIA SX" : (mask == 0b011) ? "LIEVE DX"
        : (mask == 0b110) ? "LIEVE SX" : "RUMORE");
      }
      delay(50);
    }
    Serial.read();
    Serial.println(F("Watch terminato."));
    return;
  }

  int spazio1 = lline.indexOf(' ');
  if (spazio1 < 0) {
    Serial.printf("Comando non riconosciuto: '%s'  (digita 'help')\n", line.c_str());
    return;
  }
  String cmd  = lline.substring(0, spazio1);
  String args = lline.substring(spazio1 + 1);
  args.trim();

  if (cmd == "raw") {
    int sp2 = args.indexOf(' ');
    if (sp2 < 0) {
      Serial.println("Uso: raw <ch> <tick>  (es: raw 0 307)");
      return;
    }
    uint8_t ch   = (uint8_t)args.substring(0, sp2).toInt();
    int     tick = args.substring(sp2 + 1).toInt();
    if (ch >= NUM_SERVO) { Serial.println("Canale non valido (0-6)"); return; }
    pca.setPWM(ch, 0, tick);
    Serial.printf("RAW CH%d -> tick %d\n", ch, tick);
    return;
  }

  if (cmd.length() == 2 && cmd[0] == 's' && cmd[1] >= '0' && cmd[1] <= '6') {
    uint8_t ch  = cmd[1] - '0';
    int     deg = args.toInt();
    enqueueServo(ch, deg);
    Serial.printf("S%d %s-> %d gradi (accodato)\n", ch, SERVO_NAMES[ch],
                  (ch == 6) ? constrain(deg, SERVO6_MIN_DEG, SERVO6_MAX_DEG)
                            : constrain(deg, 0, 180));
    return;
  }

  if (cmd.length() == 2 && cmd[0] == 'r' && cmd[1] >= '0' && cmd[1] <= '6') {
    uint8_t ch     = cmd[1] - '0';
    int     delta  = args.toInt();
    int     target = servoPos[ch] + delta;
    enqueueServo(ch, target);
    Serial.printf("R%d %s%+d gradi -> %d gradi (accodato)\n", ch, SERVO_NAMES[ch], delta,
                  (ch == 6) ? constrain(target, SERVO6_MIN_DEG, SERVO6_MAX_DEG)
                            : constrain(target, 0, 180));
    return;
  }

  if (cmd == "set") {
    int vals[NUM_SERVO];
    for (int i = 0; i < NUM_SERVO; i++) vals[i] = -1;
    String rem = args;
    for (int i = 0; i < NUM_SERVO && rem.length() > 0; i++) {
      int    sp = rem.indexOf(' ');
      String token;
      if (sp < 0) { token = rem; rem = ""; }
      else        { token = rem.substring(0, sp); rem = rem.substring(sp+1); rem.trim(); }
      vals[i] = token.toInt();
    }
    Serial.println(F("SET servo (accodato):"));
    for (int i = 0; i < NUM_SERVO; i++) {
      if (vals[i] == -1) {
        Serial.printf("  S%d %s-> invariato (%d gradi)\n", i, SERVO_NAMES[i], servoPos[i]);
      } else {
        int deg = constrain(vals[i], 0, 180);
        enqueueServo(i, deg);
        Serial.printf("  S%d %s-> %d gradi\n", i, SERVO_NAMES[i], deg);
      }
    }
    return;
  }

  Serial.printf("Comando non riconosciuto: '%s'  (digita 'help')\n", line.c_str());
}

// ════════════════════════════════════════════════════════════════
//  SETUP
// ════════════════════════════════════════════════════════════════

void setup() {
  Serial.begin(115200);
  Serial.println("== ESP32 Sensori — SOLO I2C (WiFi/MQTT rimossi) ==");

  pinMode(RELE_PIN,    OUTPUT); digitalWrite(RELE_PIN, LOW);
  pinMode(TCRT_SX,     INPUT);
  pinMode(TCRT_CENTRO, INPUT);
  pinMode(TCRT_DX,     INPUT);
  pinMode(MPU_INT_PIN, INPUT);

  memset((void*)i2cBuf, 0, I2C_BUF_SIZE);

  // Inizializza sensori ultrasuoni, sfalsati di 9ms l'uno dall'altro
  // per ridurre il rischio di crosstalk acustico tra sensori vicini
  for (int i = 0; i < NSENS; i++) {
    pinMode(TRIG_PINS[i], OUTPUT);
    digitalWrite(TRIG_PINS[i], LOW);
    pinMode(ECHO_PINS[i], INPUT);
    sensors[i].state         = ST_IDLE;
    sensors[i].stateStartUs  = 0;
    sensors[i].lastTriggerUs = micros() - TRIGGER_INTERVAL_US + (uint32_t)(i * 9000);
    sensors[i].distanceCm    = 9999;
    sensors[i].history[0]    = 9999;
    sensors[i].history[1]    = 9999;
    sensors[i].history[2]    = 9999;
    sensors[i].histIdx       = 0;
    echoGot[i]    = false;
    echoRiseUs[i] = 0;
    echoFallUs[i] = 0;
    bufWrite16(i * 2, 9999);
  }

  attachInterrupt(digitalPinToInterrupt(ECHO_PINS[0]), echoISR0, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ECHO_PINS[1]), echoISR1, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ECHO_PINS[2]), echoISR2, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ECHO_PINS[3]), echoISR3, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ECHO_PINS[4]), echoISR4, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ECHO_PINS[5]), echoISR5, CHANGE);

  // Wire1 PRIMA — master (PCA9685 + MPU6050)
  Wire1.begin(SDA_MASTER, SCL_MASTER, 100000UL);

  byte mpuStatus = mpu.begin();
  if (mpuStatus != 0) {
    Serial.printf("MPU-6050 errore init: %d\n", mpuStatus);
  } else {
    Serial.println("MPU-6050 ok, calibrazione (~3s, tieni fermo)...");
    mpu.calcOffsets();
    Serial.println("MPU-6050 calibrato");
  }

  pca.begin();
  pca.setOscillatorFrequency(27000000);
  pca.setPWMFreq(50);
  delay(50);

  // Home IMMEDIATA al boot
  for (int i = 0; i < NUM_SERVO; i++) setServo(i, SERVO_HOME[i]);
  Serial.println("Braccio -> HOME (immediato, boot)");

  // Wire DOPO — slave verso Pi (UNICO canale di comunicazione)
  Wire.begin(I2C_SLAVE_ADDR, SDA_SLAVE, SCL_SLAVE, 100000);
  Wire.onRequest(onRequest);
  Wire.onReceive(onReceive);
  Serial.printf("I2C slave 0x%02X su SDA=%d SCL=%d\n", I2C_SLAVE_ADDR, SDA_SLAVE, SCL_SLAVE);

  Serial.printf("Velocita servo default: %d ms/passo (~%.0f gradi/s)\n",
                servoStepMs, 1000.0f / servoStepMs);
  Serial.printf("Ultrasuoni: trigger ogni %dms/sensore (~%.0fHz refresh), timeout eco %dms\n",
                TRIGGER_INTERVAL_US/1000, 1000000.0f/TRIGGER_INTERVAL_US, ECHO_TIMEOUT_US/1000);
  Serial.println("Comunicazione: SOLO I2C 0x09 col Raspberry Pi. Nessun WiFi/MQTT.");
  Serial.println("Digita 'help' per la lista comandi.");
}

// ════════════════════════════════════════════════════════════════
//  UPDATE ULTRASUONI
// ════════════════════════════════════════════════════════════════

void updateSensor(int idx) {
  Sensor& s = sensors[idx];
  uint32_t now  = micros();
  const uint8_t TRIG = TRIG_PINS[idx];

  switch (s.state) {

    case ST_IDLE:
      if ((now - s.lastTriggerUs) >= TRIGGER_INTERVAL_US) {
        // echoGot NON azzerato qui: potrebbe esserci un eco residuo
        // ancora in attesa di lettura da un trigger precedente.
        // Verrà azzerato solo quando lo leggiamo, in ST_WAIT_END.
        digitalWrite(TRIG, HIGH);
        s.state        = ST_TRIG_HIGH;
        s.stateStartUs = now;
      }
      break;

    case ST_TRIG_HIGH:
      if ((now - s.stateStartUs) >= TRIGGER_PULSE_US) {
        digitalWrite(TRIG, LOW);
        s.lastTriggerUs = now;
        s.state         = ST_WAIT_END;
        // stateStartUs impostato QUI (dopo il LOW del trigger), e
        // azzeramento echoGot atomico prima di iniziare l'attesa:
        // ora è sicuro azzerarlo, siamo appena partiti con QUESTO ping.
        noInterrupts();
        echoGot[idx] = false;
        interrupts();
        s.stateStartUs = now;
      }
      break;

    case ST_WAIT_END: {
      noInterrupts();
      bool     got  = echoGot[idx];
      uint32_t rise = echoRiseUs[idx];
      uint32_t fall = echoFallUs[idx];
      if (got) echoGot[idx] = false;  // reset atomico solo se lo leggiamo
      interrupts();

      if (got) {
        uint32_t dur = fall - rise;
        uint16_t cm  = (uint16_t)(dur / 58);
        if (cm > DIST_MAX_CM) cm = 9999;
        s.history[s.histIdx % 3] = cm;
        s.histIdx++;
        s.distanceCm = mediana3(s.history[0], s.history[1], s.history[2]);
        bufWrite16(idx * 2, s.distanceCm);
        s.state = ST_IDLE;

      } else if ((now - s.stateStartUs) >= ECHO_TIMEOUT_US) {
        s.history[s.histIdx % 3] = 9999;
        s.histIdx++;
        s.distanceCm = mediana3(s.history[0], s.history[1], s.history[2]);
        bufWrite16(idx * 2, s.distanceCm);
        s.state = ST_IDLE;
      }
      break;
    }
  }
}

uint16_t mediana3(uint16_t a, uint16_t b, uint16_t c) {
  if (a > b) { uint16_t t = a; a = b; b = t; }
  if (b > c) { uint16_t t = b; b = c; c = t; }
  if (a > b) { uint16_t t = a; a = b; b = t; }
  return b;
}

void updateTCRT() {
  uint8_t mask = 0;
  if (digitalRead(TCRT_SX)     == LOW) mask |= 0x01;
  if (digitalRead(TCRT_CENTRO) == LOW) mask |= 0x02;
  if (digitalRead(TCRT_DX)     == LOW) mask |= 0x04;
  i2cBuf[24] = mask;
}

void updateMPU() {
  static uint32_t lastMs = 0;
  if ((millis() - lastMs) < MPU_UPDATE_MS) return;
  lastMs = millis();
  mpu.update();
  bufWriteI16(12, (int16_t)(mpu.getAccX()  * 100));
  bufWriteI16(14, (int16_t)(mpu.getAccY()  * 100));
  bufWriteI16(16, (int16_t)(mpu.getAccZ()  * 100));
  bufWriteI16(18, (int16_t)(mpu.getGyroX() * 100));
  bufWriteI16(20, (int16_t)(mpu.getGyroY() * 100));
  bufWriteI16(22, (int16_t)(mpu.getGyroZ() * 100));
}

// ════════════════════════════════════════════════════════════════
//  LOOP
// ════════════════════════════════════════════════════════════════

void loop() {
  manageSerial();
  eseguiComando();
  updateServoQueue();

  for (int i = 0; i < NSENS; i++) updateSensor(i);

  updateTCRT();
  uint8_t curMask = i2cBuf[24];
  if (curMask != lastTcrtDebug) {
    lastTcrtDebug = curMask;
    Serial.printf("[%lu ms] TCRT -> SX:%s CEN:%s DX:%s (0x%02X) -> %s\n",
      millis(),
      (curMask & 0x01) ? "ON " : "off",
      (curMask & 0x02) ? "ON " : "off",
      (curMask & 0x04) ? "ON " : "off",
      curMask,
      (curMask == 0b000) ? "PERSA"    : (curMask == 0b010) ? "CENTRATO"
    : (curMask == 0b111) ? "INCROCIO" : (curMask == 0b001) ? "DEVIA DX"
    : (curMask == 0b100) ? "DEVIA SX" : (curMask == 0b011) ? "LIEVE DX"
    : (curMask == 0b110) ? "LIEVE SX" : "RUMORE");
  }

  updateMPU();

  // Stampa periodica ogni 500ms
  static uint32_t lastPrint = 0;
  if ((millis() - lastPrint) < 500) return;
  lastPrint = millis();

  for (int i = 0; i < NSENS; i++) {
    uint16_t d = i2cBuf[i*2] | ((uint16_t)i2cBuf[i*2+1] << 8);
    if (d == 9999) Serial.printf("%-10s: ---\n", SENSOR_NAMES[i]);
    else           Serial.printf("%-10s: %u cm\n", SENSOR_NAMES[i], d);
  }
  int16_t ax = (int16_t)(i2cBuf[12] | ((uint16_t)i2cBuf[13] << 8));
  int16_t ay = (int16_t)(i2cBuf[14] | ((uint16_t)i2cBuf[15] << 8));
  int16_t az = (int16_t)(i2cBuf[16] | ((uint16_t)i2cBuf[17] << 8));
  int16_t gx = (int16_t)(i2cBuf[18] | ((uint16_t)i2cBuf[19] << 8));
  int16_t gy = (int16_t)(i2cBuf[20] | ((uint16_t)i2cBuf[21] << 8));
  int16_t gz = (int16_t)(i2cBuf[22] | ((uint16_t)i2cBuf[23] << 8));
  Serial.printf("ACC  X:%.2f Y:%.2f Z:%.2f g\n",  ax/100.0, ay/100.0, az/100.0);
  Serial.printf("GYRO X:%.2f Y:%.2f Z:%.2f deg/s\n", gx/100.0, gy/100.0, gz/100.0);
  Serial.printf("TCRT: SX:%s CEN:%s DX:%s (0x%02X)\n",
    (i2cBuf[24] & 0x01) ? "NERO " : "BIANCO",
    (i2cBuf[24] & 0x02) ? "NERO " : "BIANCO",
    (i2cBuf[24] & 0x04) ? "NERO " : "BIANCO",
    i2cBuf[24]);
}
