/*
 * ================================================================
 *  ESP32 SENSORI — FIRMWARE v5
 *
 *  FIX v5 rispetto a v4:
 *  1. Ultrasuoni: lettura atomica echoGot/Rise/Fall con noInterrupts()
 *  2. Ultrasuoni: timeout aumentato a 25ms (era 38ms ma partiva da
 *     stateStartUs = dopo il trigger, non dopo l'invio del pulse)
 *     → ora il timeout è misurato CORRETTAMENTE dall'inizio di ST_WAIT_END
 *  3. Ultrasuoni: stato ST_WAIT_START rimosso dalla macchina a stati
 *     (non era usato ma causava confusione)
 *  4. Ultrasuoni: echoGot viene resettato SOLO quando lo leggiamo,
 *     mai all'inizio di ST_IDLE, per evitare race condition
 *  5. MQTT: resolveBroker() rimossa da manageMqtt() (loop ogni 5s
 *     che bloccava il loop principale per 3s di timeout mDNS)
 *     → ora resolveBroker viene chiamata SOLO al boot (setup) e
 *       quando arrivano nuove credenziali via I2C
 *  6. MQTT: setServer() chiamata una volta sola, non ad ogni riconnessione
 *  7. Loop: tutto il codice che era in setup() rimane invariato
 *
 *  Ultrasuoni + TCRT + MPU6050 + PCA9685 servo
 *  + WiFi + MQTT (PubSubClient) + NVS credentials
 *  + WiFi recovery con retry al boot (20 tentativi × 500ms)
 *  + Controllo servo braccio via Seriale (115200 baud)
 *  + Controllo servo braccio via MQTT
 *  + Coda servo sequenziale con movimento smooth (un servo alla volta)
 *  + Controllo velocità servo via MQTT
 *  + 7° servo (CH6) con limiti 80°–170°
 *
 * ────────────────────────────────────────────────────────────────
 *  COMANDI SERIALI SERVO (terminare con Invio):
 *
 *  ── SERVO SINGOLO (posizione assoluta) ────────────────────────
 *  s0 <0-180>     → Servo canale 0  (es: s0 90)  [accodato, smooth]
 *  s1..s6         → idem per altri canali
 *                   NOTA: s6 è limitato a 80°–170°
 *
 *  ── SERVO SINGOLO (movimento relativo) ────────────────────────
 *  r0 <-90..90>   → Muovi servo 0 di +/- gradi (es: r0 10) [accodato]
 *  r1..r6         → idem per altri canali
 *
 *  ── PIÙ SERVO INSIEME (posizione assoluta) ────────────────────
 *  set <s0> <s1> <s2> <s3> <s4> <s5> <s6>
 *                 → Imposta tutti e 7 in sequenza s0→s6 [accodato]
 *                   Usa -1 per lasciare invariato un servo
 *
 *  ── RAW TICK ─────────────────────────────────────────────────
 *  raw <ch> <tick> → Imposta tick PWM diretto IMMEDIATO (es: raw 0 307)
 *
 *  ── PRESET ────────────────────────────────────────────────────
 *  home           → Tutti i servo in posizione home [accodato]
 *  riposo         → Posizione di riposo braccio abbassato [accodato]
 *
 *  ── RELÈ POMPA ────────────────────────────────────────────────
 *  rele on        → Accende la pompa
 *  rele off       → Spegne la pompa
 *
 *  ── INFO ──────────────────────────────────────────────────────
 *  pos            → Posizione attuale di tutti i servo
 *  dist           → Distanze ultrasuoni
 *  imu            → Dati IMU (acc + gyro)
 *  tcrt           → Stato sensori TCRT
 *  tcrt watch     → Monitor live TCRT (premi Invio per uscire)
 *  stato          → Stato completo (servo + sensori + WiFi + MQTT)
 *  help           → Mostra questo elenco
 *
 * ────────────────────────────────────────────────────────────────
 *  MQTT TOPICS IN INGRESSO  →  robot/sensori/cmd
 *  Payload JSON:
 *
 *  {"cmd":"servo",       "ch":0,   "ang":90}
 *  {"cmd":"servo_rel",   "ch":0,   "delta":10}
 *  {"cmd":"set",         "s0":90,  "s1":45, "s2":135, "s3":90, "s4":90, "s5":60, "s6":125}
 *                        (usa -1 per lasciare invariato)
 *  {"cmd":"home"}
 *  {"cmd":"riposo"}
 *  {"cmd":"servo_speed", "ms":8}   → velocità: ms tra un passo e l'altro (1-50)
 *                                    default=8 (~125°/s), più alto=più lento
 *  {"cmd":"rele",        "val":1}  (1=on, 0=off)
 *  {"cmd":"get_stato"}             → forza pubblicazione immediata tutto
 *
 *  MQTT TOPICS IN USCITA:
 *  robot/sensori/servo   → posizioni correnti (publish al completamento mossa)
 *  robot/sensori/servo_speed → velocità corrente in ms/passo (retain)
 *
 * ────────────────────────────────────────────────────────────────
 *  MAPPA SERVO BRACCIO:
 *   CH0 → Base rotazione
 *   CH1 → Spalla
 *   CH2 → Gomito
 *   CH3 → Polso verticale
 *   CH4 → Polso rotazione
 *   CH5 → Pinza (home=120°)
 *   CH6 → Settimo servo (limiti: 80°–170°, home=125°)
 * ================================================================
 */

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <MPU6050_light.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <Preferences.h>
#include <ArduinoJson.h>

// ── CREDENZIALI DEFAULT ───────────────────────────────────────────
#define WIFI_SSID_DEFAULT   "LAPTOP1234"
#define WIFI_PASS_DEFAULT   "12345678"
#define MQTT_BROKER_DEFAULT "LagmaBills"   // hostname mDNS del Pi
#define MQTT_PORT           1883
#define MQTT_CLIENT_ID      "esp32_sensori"

// ── NVS ──────────────────────────────────────────────────────────
#define NVS_NAMESPACE  "wifi_cfg"
#define NVS_KEY_SSID   "ssid"
#define NVS_KEY_PASS   "pass"
#define NVS_KEY_BROKER "broker"

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

// Limiti per servo 6 (CH6)
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
void publishServoStato();

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
    publishServoStato();
    servoQHead  = (servoQHead + 1) % SERVO_QUEUE_SIZE;
    servoQCount--;
    servoCurrentTarget = -1;
  }
}

// ── ULTRASUONI ────────────────────────────────────────────────────
// FIX v5: stato a 3 fasi (rimosso ST_WAIT_START inutile).
// Timeout misurato da quando entriamo in ST_WAIT_END (dopo il pulse LOW).
// echoGot letto atomicamente con noInterrupts()/interrupts().
// echoGot NON viene mai azzerato in ST_IDLE per evitare race condition.

#define NSENS 6
const uint8_t TRIG_PINS[NSENS]    = { 27, 25, 4,  13, 18, 16 };
const uint8_t ECHO_PINS[NSENS]    = { 14, 26, 5,  12, 19, 17 };
const char*   SENSOR_NAMES[NSENS] = { "FRONTE", "RETRO", "SINISTRA", "DESTRA", "CLIFF_F", "CLIFF_R" };

#define TRIGGER_PULSE_US       10      // durata pulse TRIG (10µs)
#define TRIGGER_INTERVAL_US    50000   // intervallo tra trigger (50ms)

// Timeout attesa eco: 25ms = ~430cm, abbondante per un robot indoor.
// HC-SR04 range reale: 2cm-400cm → eco max ~23ms.
// 25ms lascia margine per latenza del loop.
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

// Variabili ISR — IRAM, volatile, accesso atomico obbligatorio
volatile uint32_t echoRiseUs[NSENS];
volatile uint32_t echoFallUs[NSENS];
volatile bool     echoGot[NSENS];

// ISR per ogni sensore: salva timestamp rise/fall, setta echoGot
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

uint8_t  lastTcrtDebug = 0xFF;

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

// ── WiFi / MQTT ───────────────────────────────────────────────────
WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);
Preferences  prefs;

char wifiSsid[64];
char wifiPass[64];
char mqttBroker[64];

uint32_t lastWifiCheck   = 0;
uint32_t lastMqttCheck   = 0;
uint32_t lastPublishSens = 0;
uint32_t lastPublishImu  = 0;
uint32_t lastPublishTcrt = 0;
uint8_t  lastTcrtMask    = 0xFF;

volatile bool wifiReconnectRequest = false;
volatile bool mqttReconnectRequest = false;

// ════════════════════════════════════════════════════════════════
//  Prototipi
// ════════════════════════════════════════════════════════════════
int  degreesToTick(int deg);
void setServo(uint8_t ch, int deg);
void moveServo(uint8_t ch, int delta);
void servoHome();
void servoRiposo();
void publishServoStato();
void publishServoSpeed();
void publishReleStato();
void publishDistanze();
void publishImu();
void publishTcrt(uint8_t mask);
void updateTCRT();
uint16_t mediana3(uint16_t a, uint16_t b, uint16_t c);

// ════════════════════════════════════════════════════════════════
//  NVS
// ════════════════════════════════════════════════════════════════

void loadCredentials() {
  prefs.begin(NVS_NAMESPACE, true);
  String ssid   = prefs.getString(NVS_KEY_SSID,   WIFI_SSID_DEFAULT);
  String pass   = prefs.getString(NVS_KEY_PASS,   WIFI_PASS_DEFAULT);
  String broker = prefs.getString(NVS_KEY_BROKER, MQTT_BROKER_DEFAULT);
  prefs.end();
  ssid.toCharArray(wifiSsid,    sizeof(wifiSsid));
  pass.toCharArray(wifiPass,    sizeof(wifiPass));
  broker.toCharArray(mqttBroker, sizeof(mqttBroker));
  Serial.printf("Creds: SSID=%s BROKER=%s\n", wifiSsid, mqttBroker);
}

void saveCredentials(const char* ssid, const char* pass, const char* broker) {
  prefs.begin(NVS_NAMESPACE, false);
  if (ssid   && ssid[0])   prefs.putString(NVS_KEY_SSID,   ssid);
  if (pass   && pass[0])   prefs.putString(NVS_KEY_PASS,   pass);
  if (broker && broker[0]) prefs.putString(NVS_KEY_BROKER, broker);
  prefs.end();
  Serial.printf("NVS saved: SSID=%s BROKER=%s\n",
                ssid   ? ssid   : "-",
                broker ? broker : "-");
}

// ════════════════════════════════════════════════════════════════
//  mDNS — FIX v5: chiamata SOLO al boot e su cambio credenziali,
//  NON più dentro manageMqtt() (evita blocco 3s ogni 5s)
// ════════════════════════════════════════════════════════════════

void resolveBroker() {
  const char* host = MQTT_BROKER_DEFAULT;
  MDNS.begin("esp32-sensori");
  Serial.printf("[mDNS] Risoluzione %s.local...\n", host);
  IPAddress ip = MDNS.queryHost(host, 3000);
  if (ip != INADDR_NONE) {
    String ipStr = ip.toString();
    ipStr.toCharArray(mqttBroker, sizeof(mqttBroker));
    Serial.printf("[mDNS] Trovato: %s\n", mqttBroker);
    prefs.begin(NVS_NAMESPACE, false);
    prefs.putString(NVS_KEY_BROKER, ipStr);
    prefs.end();
  } else {
    Serial.printf("[mDNS] Non trovato, uso NVS fallback: %s\n", mqttBroker);
  }
}

// ════════════════════════════════════════════════════════════════
//  WiFi
// ════════════════════════════════════════════════════════════════

void manageWifi() {
  if ((millis() - lastWifiCheck) < 5000) return;
  lastWifiCheck = millis();
  if (wifiReconnectRequest) {
    wifiReconnectRequest = false;
    loadCredentials();
    WiFi.disconnect(true);
    delay(200);
    WiFi.begin(wifiSsid, wifiPass);
    Serial.println("Riconnessione WiFi con nuove credenziali...");
    return;
  }
  if (!WiFi.isConnected()) {
    Serial.println("WiFi disconnesso, riconnessione...");
    WiFi.reconnect();
  }
}

// ════════════════════════════════════════════════════════════════
//  MQTT callback
// ════════════════════════════════════════════════════════════════

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  char msg[256];
  if (length >= sizeof(msg)) return;
  memcpy(msg, payload, length);
  msg[length] = '\0';
  Serial.printf("MQTT RX [%s]: %s\n", topic, msg);

  StaticJsonDocument<256> doc;
  if (deserializeJson(doc, msg) != DeserializationError::Ok) return;
  const char* cmd = doc["cmd"];
  if (!cmd) return;

  if (strcmp(cmd, "servo") == 0) {
    uint8_t ch  = doc["ch"]  | 0;
    int     ang = doc["ang"] | 90;
    if (ch < NUM_SERVO) {
      enqueueServo(ch, ang);
      Serial.printf("MQTT -> S%d %s-> %d gradi (accodato)\n", ch, SERVO_NAMES[ch], ang);
    }

  } else if (strcmp(cmd, "servo_rel") == 0) {
    uint8_t ch    = doc["ch"]    | 0;
    int     delta = doc["delta"] | 0;
    if (ch < NUM_SERVO) {
      enqueueServo(ch, servoPos[ch] + delta);
      Serial.printf("MQTT -> R%d %s%+d gradi (accodato)\n", ch, SERVO_NAMES[ch], delta);
    }

  } else if (strcmp(cmd, "set") == 0) {
    Serial.println(F("MQTT SET servo (accodato s0->s6):"));
    for (uint8_t i = 0; i < NUM_SERVO; i++) {
      char key[3] = { 's', (char)('0' + i), '\0' };
      int v = doc[key] | -1;
      if (v >= 0) {
        enqueueServo(i, v);
        Serial.printf("  S%d %s-> %d gradi\n", i, SERVO_NAMES[i], v);
      } else {
        Serial.printf("  S%d %sinvariato (%d gradi)\n", i, SERVO_NAMES[i], servoPos[i]);
      }
    }

  } else if (strcmp(cmd, "home") == 0) {
    servoHome();

  } else if (strcmp(cmd, "riposo") == 0) {
    servoRiposo();

  } else if (strcmp(cmd, "servo_speed") == 0) {
    int ms = doc["ms"] | -1;
    if (ms >= 1 && ms <= 50) {
      servoStepMs = (uint8_t)ms;
      Serial.printf("MQTT -> Velocita servo: %d ms/passo (~%.0f gradi/s)\n",
                    servoStepMs, 1000.0f / servoStepMs);
      publishServoSpeed();
    } else {
      Serial.printf("MQTT -> servo_speed: valore %d fuori range (1-50)\n", ms);
    }

  } else if (strcmp(cmd, "rele") == 0) {
    bool on = (doc["val"] | 0) ? true : false;
    digitalWrite(RELE_PIN, on ? HIGH : LOW);
    Serial.printf("MQTT -> Rele %s\n", on ? "ON" : "OFF");
    publishReleStato();

  } else if (strcmp(cmd, "get_stato") == 0) {
    publishDistanze();
    publishImu();
    publishTcrt(i2cBuf[24]);
    publishServoStato();
    publishServoSpeed();
    publishReleStato();
  }
}

// ════════════════════════════════════════════════════════════════
//  MQTT management — FIX v5: resolveBroker() RIMOSSA da qui.
//  setServer() chiamata solo se il broker è cambiato.
// ════════════════════════════════════════════════════════════════

void manageMqtt() {
  if (!WiFi.isConnected()) return;

  // Se arrivano nuove credenziali via I2C, aggiorna server e riconnetti
  if (mqttReconnectRequest) {
    mqttReconnectRequest = false;
    mqtt.disconnect();
    mqtt.setServer(mqttBroker, MQTT_PORT);
    Serial.printf("MQTT broker aggiornato: %s\n", mqttBroker);
    lastMqttCheck = 0; // forza riconnessione immediata
  }

  if (!mqtt.connected()) {
    if ((millis() - lastMqttCheck) < 5000) return;
    lastMqttCheck = millis();
    // FIX: NON chiamiamo più resolveBroker() qui (bloccava il loop 3s)
    Serial.printf("Connessione MQTT a %s:%d...\n", mqttBroker, MQTT_PORT);
    const char* lwtPayload = "{\"online\":false}";
    if (mqtt.connect(MQTT_CLIENT_ID,
                     nullptr, nullptr,
                     "robot/sensori/stato",
                     0, true, lwtPayload)) {
      Serial.println("MQTT connesso");
      mqtt.subscribe("robot/sensori/cmd");
      mqtt.publish("robot/sensori/stato", "{\"online\":true}", true);
      mqtt.publish("robot/sensori/log",   "esp32_sensori online");
      publishServoStato();
      publishServoSpeed();
      publishReleStato();
    } else {
      Serial.printf("MQTT fallito rc=%d\n", mqtt.state());
    }
    return;
  }

  mqtt.loop();

  if ((millis() - lastPublishSens) >= 200) {
    lastPublishSens = millis();
    publishDistanze();
  }
  if ((millis() - lastPublishImu) >= 200) {
    lastPublishImu = millis();
    publishImu();
  }
  if ((millis() - lastPublishTcrt) >= 100) {
    lastPublishTcrt = millis();
    uint8_t mask = i2cBuf[24];
    if (mask != lastTcrtMask) {
      lastTcrtMask = mask;
      publishTcrt(mask);
    }
  }
}

// ════════════════════════════════════════════════════════════════
//  MQTT publish helpers
// ════════════════════════════════════════════════════════════════

void publishDistanze() {
  if (!mqtt.connected()) return;
  uint16_t fr  = i2cBuf[0]  | ((uint16_t)i2cBuf[1]  << 8);
  uint16_t re  = i2cBuf[2]  | ((uint16_t)i2cBuf[3]  << 8);
  uint16_t sx  = i2cBuf[4]  | ((uint16_t)i2cBuf[5]  << 8);
  uint16_t dx  = i2cBuf[6]  | ((uint16_t)i2cBuf[7]  << 8);
  uint16_t clf = i2cBuf[8]  | ((uint16_t)i2cBuf[9]  << 8);
  uint16_t clr = i2cBuf[10] | ((uint16_t)i2cBuf[11] << 8);
  char buf[160];
  snprintf(buf, sizeof(buf),
    "{\"FRONTE\":%u,\"RETRO\":%u,\"SINISTRA\":%u,\"DESTRA\":%u,\"CLIFF_F\":%u,\"CLIFF_R\":%u}",
    fr, re, sx, dx, clf, clr);
  mqtt.publish("robot/sensori/distanze", buf);
}

void publishImu() {
  if (!mqtt.connected()) return;
  int16_t ax = (int16_t)(i2cBuf[12] | ((uint16_t)i2cBuf[13] << 8));
  int16_t ay = (int16_t)(i2cBuf[14] | ((uint16_t)i2cBuf[15] << 8));
  int16_t az = (int16_t)(i2cBuf[16] | ((uint16_t)i2cBuf[17] << 8));
  int16_t gx = (int16_t)(i2cBuf[18] | ((uint16_t)i2cBuf[19] << 8));
  int16_t gy = (int16_t)(i2cBuf[20] | ((uint16_t)i2cBuf[21] << 8));
  int16_t gz = (int16_t)(i2cBuf[22] | ((uint16_t)i2cBuf[23] << 8));
  char buf[160];
  snprintf(buf, sizeof(buf),
    "{\"ax\":%.2f,\"ay\":%.2f,\"az\":%.2f,\"gx\":%.2f,\"gy\":%.2f,\"gz\":%.2f}",
    ax/100.0f, ay/100.0f, az/100.0f,
    gx/100.0f, gy/100.0f, gz/100.0f);
  mqtt.publish("robot/sensori/imu", buf);
}

void publishTcrt(uint8_t mask) {
  if (!mqtt.connected()) return;
  char buf[48];
  snprintf(buf, sizeof(buf),
    "{\"sx\":%d,\"cen\":%d,\"dx\":%d}",
    mask & 1, (mask >> 1) & 1, (mask >> 2) & 1);
  mqtt.publish("robot/sensori/tcrt", buf);
}

void publishServoStato() {
  if (!mqtt.connected()) return;
  char buf[160];
  snprintf(buf, sizeof(buf),
    "{\"s0\":%d,\"s1\":%d,\"s2\":%d,\"s3\":%d,\"s4\":%d,\"s5\":%d,\"s6\":%d}",
    servoPos[0], servoPos[1], servoPos[2],
    servoPos[3], servoPos[4], servoPos[5], servoPos[6]);
  mqtt.publish("robot/sensori/servo", buf, true);
}

void publishServoSpeed() {
  if (!mqtt.connected()) return;
  char buf[48];
  snprintf(buf, sizeof(buf),
    "{\"ms_per_step\":%d,\"deg_per_sec\":%.0f}",
    servoStepMs, 1000.0f / servoStepMs);
  mqtt.publish("robot/sensori/servo_speed", buf, true);
}

void publishReleStato() {
  if (!mqtt.connected()) return;
  char buf[24];
  snprintf(buf, sizeof(buf), "{\"rele\":%d}", digitalRead(RELE_PIN) ? 1 : 0);
  mqtt.publish("robot/sensori/rele", buf, true);
}

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
//  CALLBACK I2C SLAVE
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
//  ESEGUI COMANDO I2C
// ════════════════════════════════════════════════════════════════

void eseguiComando() {
  if (!newCmd) return;
  newCmd = false;
  uint8_t cmd = rxBuf[0];

  if (cmd == 0xFD && rxLen >= 4) {
    uint8_t lenIp = rxBuf[1];
    if (lenIp == 0 || (2 + lenIp + 1) > (int)rxLen) return;
    char newBroker[64]={0}, newSsid[64]={0}, newPass[64]={0};
    memcpy(newBroker, rxBuf + 2, min((int)lenIp, 63));
    int idx = 2 + lenIp;
    uint8_t lenSsid = rxBuf[idx++];
    if (lenSsid == 0 || idx + lenSsid > (int)rxLen) return;
    memcpy(newSsid, rxBuf + idx, min((int)lenSsid, 63));
    idx += lenSsid;
    if (idx < (int)rxLen) {
      uint8_t lenPass = rxBuf[idx++];
      if (lenPass > 0 && idx + lenPass <= (int)rxLen)
        memcpy(newPass, rxBuf + idx, min((int)lenPass, 63));
    }
    saveCredentials(newSsid, newPass, newBroker);
    strncpy(wifiSsid,   newSsid,   sizeof(wifiSsid));
    strncpy(wifiPass,   newPass,   sizeof(wifiPass));
    strncpy(mqttBroker, newBroker, sizeof(mqttBroker));
    wifiReconnectRequest = true;
    mqttReconnectRequest = true;
    return;
  }

  if (cmd == 0xFE && rxLen >= 4) {
    uint8_t lenSsid = rxBuf[1];
    if (lenSsid > 0 && (2 + lenSsid + 1) <= (int)rxLen) {
      char newSsid[64]={0}, newPass[64]={0};
      memcpy(newSsid, rxBuf + 2, min((int)lenSsid, 63));
      uint8_t lenPass = rxBuf[2 + lenSsid];
      if (lenPass > 0 && (2 + lenSsid + 1 + lenPass) <= (int)rxLen)
        memcpy(newPass, rxBuf + 3 + lenSsid, min((int)lenPass, 63));
      saveCredentials(newSsid, newPass, nullptr);
      strncpy(wifiSsid, newSsid, sizeof(wifiSsid));
      strncpy(wifiPass, newPass, sizeof(wifiPass));
      wifiReconnectRequest = true;
    }
    return;
  }

  if (rxLen < 3) return;
  uint8_t ch  = rxBuf[1];
  uint8_t val = rxBuf[2];

  if      (cmd == 0xAA && ch < NUM_SERVO) setServo(ch, (int)val);
  else if (cmd == 0xAB && ch < NUM_SERVO) moveServo(ch, (int)val - 128);
  else if (cmd == 0xAC) digitalWrite(RELE_PIN, val ? HIGH : LOW);
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
  Serial.println(F("        es: set 90 45 135 90 -1 -1 125"));
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
  Serial.println(F("--- RETE ----------------------------------------"));
  Serial.printf("  WiFi : %s\n",
    WiFi.isConnected() ? WiFi.localIP().toString().c_str() : "DISCONNESSO");
  Serial.printf("  MQTT : %s  broker=%s\n",
    mqtt.connected() ? "OK" : "DISCONNESSO", mqttBroker);
  Serial.printf("  Rele : %s\n", digitalRead(RELE_PIN) ? "ON" : "off");
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
  Serial.println("== ESP32 Sensori v5 — ultrasuoni fix + MQTT fix ==");

  pinMode(RELE_PIN,    OUTPUT); digitalWrite(RELE_PIN, LOW);
  pinMode(TCRT_SX,     INPUT);
  pinMode(TCRT_CENTRO, INPUT);
  pinMode(TCRT_DX,     INPUT);
  pinMode(MPU_INT_PIN, INPUT);

  memset((void*)i2cBuf, 0, I2C_BUF_SIZE);

  // Inizializza sensori ultrasuoni
  // FIX v5: echoGot inizializzato a false, stagger temporale per evitare
  // che 6 sensori sparino contemporaneamente (ogni 9ms di offset)
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

  // Collega interrupt DOPO aver fatto i pinMode
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

  // Wire DOPO — slave verso Pi
  Wire.begin(I2C_SLAVE_ADDR, SDA_SLAVE, SCL_SLAVE, 100000);
  Wire.onRequest(onRequest);
  Wire.onReceive(onReceive);
  Serial.printf("I2C slave 0x%02X su SDA=%d SCL=%d\n", I2C_SLAVE_ADDR, SDA_SLAVE, SCL_SLAVE);

  // WiFi
  loadCredentials();
  WiFi.mode(WIFI_STA);
  WiFi.begin(wifiSsid, wifiPass);
  Serial.printf("Connessione WiFi a '%s'", wifiSsid);
  {
    uint8_t attempts = 0;
    while (!WiFi.isConnected() && attempts < 20) {
      delay(500);
      Serial.print(".");
      attempts++;
    }
    Serial.println();
  }
  if (WiFi.isConnected()) {
    Serial.printf("WiFi OK -> IP: %s\n", WiFi.localIP().toString().c_str());
    // FIX v5: resolveBroker() chiamata UNA SOLA VOLTA qui al boot
    resolveBroker();
  } else {
    Serial.println("WiFi non raggiunto al boot — riprovo in background (manageWifi)");
  }

  // FIX v5: setServer() chiamata UNA SOLA VOLTA, non in ogni ciclo manageMqtt
  mqtt.setServer(mqttBroker, MQTT_PORT);
  mqtt.setCallback(mqttCallback);
  mqtt.setKeepAlive(15);

  Serial.printf("WiFi->%s | MQTT->%s\n", wifiSsid, mqttBroker);
  Serial.printf("Velocita servo default: %d ms/passo (~%.0f gradi/s)\n",
                servoStepMs, 1000.0f / servoStepMs);
  Serial.println("Digita 'help' per la lista comandi.");
}

// ════════════════════════════════════════════════════════════════
//  UPDATE ULTRASUONI — FIX v5
//
//  Cambiamenti rispetto a v4:
//  1. Lettura atomica: echoGot/Rise/Fall letti con noInterrupts()
//  2. echoGot NON azzerato in ST_IDLE (azzerato solo quando lo leggiamo)
//  3. Timeout misurato da stateStartUs impostato all'entrata in ST_WAIT_END
//  4. Timeout = ECHO_TIMEOUT_US (25ms), sufficiente per ~430cm + margine loop
//  5. Stato ST_WAIT_START rimosso (non era usato)
// ════════════════════════════════════════════════════════════════

void updateSensor(int idx) {
  Sensor& s = sensors[idx];
  uint32_t now  = micros();
  const uint8_t TRIG = TRIG_PINS[idx];

  switch (s.state) {

    case ST_IDLE:
      // Aspetta l'intervallo minimo tra trigger
      if ((now - s.lastTriggerUs) >= TRIGGER_INTERVAL_US) {
        // FIX v5: NON azzeriamo echoGot qui. Potrebbe esserci un eco residuo
        // da un trigger precedente ancora in attesa di lettura — se lo azzeriamo
        // qui, perdiamo quella misura. Lo azzereremo solo quando lo leggiamo
        // in ST_WAIT_END.
        digitalWrite(TRIG, HIGH);
        s.state        = ST_TRIG_HIGH;
        s.stateStartUs = now;
      }
      break;

    case ST_TRIG_HIGH:
      // Mantieni TRIG HIGH per almeno TRIGGER_PULSE_US (10µs)
      if ((now - s.stateStartUs) >= TRIGGER_PULSE_US) {
        digitalWrite(TRIG, LOW);
        s.lastTriggerUs = now;
        s.state         = ST_WAIT_END;
        // FIX v5: stateStartUs impostato QUI (dopo il LOW del trigger)
        // e azzeramento echoGot in modo atomico prima di iniziare l'attesa
        noInterrupts();
        echoGot[idx] = false;  // ora è sicuro: siamo appena partiti
        interrupts();
        s.stateStartUs = now;
      }
      break;

    case ST_WAIT_END: {
      // FIX v5: lettura atomica delle variabili ISR
      noInterrupts();
      bool     got  = echoGot[idx];
      uint32_t rise = echoRiseUs[idx];
      uint32_t fall = echoFallUs[idx];
      if (got) echoGot[idx] = false;  // reset atomico solo se lo leggiamo
      interrupts();

      if (got) {
        // Eco ricevuto: calcola distanza
        uint32_t dur = fall - rise;
        uint16_t cm  = (uint16_t)(dur / 58);
        if (cm > DIST_MAX_CM) cm = 9999;
        s.history[s.histIdx % 3] = cm;
        s.histIdx++;
        s.distanceCm = mediana3(s.history[0], s.history[1], s.history[2]);
        bufWrite16(idx * 2, s.distanceCm);
        s.state = ST_IDLE;

      } else if ((now - s.stateStartUs) >= ECHO_TIMEOUT_US) {
        // Timeout: nessun eco ricevuto entro 25ms → oggetto fuori portata
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

  // Aggiorna tutti i sensori ultrasuoni (state machine non bloccante)
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
  manageWifi();
  manageMqtt();

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
  Serial.printf("TCRT: SX:%s CEN:%s DX:%s (0x%02X) | WiFi:%s MQTT:%s Broker:%s\n",
    (i2cBuf[24] & 0x01) ? "BIANCO" : "NERO ",
    (i2cBuf[24] & 0x02) ? "BIANCO" : "NERO ", // Corretto: rimosso il punto interrogativo di troppo
    (i2cBuf[24] & 0x04) ? "BIANCO" : "NERO ",
    i2cBuf[24],
    WiFi.isConnected() ? "OK" : "NO",
    mqtt.connected()   ? "OK" : "NO",
    mqttBroker);
}
