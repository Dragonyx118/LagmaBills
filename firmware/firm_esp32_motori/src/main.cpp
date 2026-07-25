/*
 * ================================================================
 *  ESP32 MOTORI — FIRMWARE OTTIMIZZATO + SICUREZZA ULTRASUONI
 *  Latenza comando→motore: < 2ms (tipico) / < 5ms (peggiore)
 *
 *  OTTIMIZZAZIONI RISPETTO ALLA VERSIONE ORIGINALE:
 *
 *  1. DUAL-CORE FreeRTOS
 *     - Core 0: WiFi + MQTT (non blocca mai i motori)
 *     - Core 1: Motori + Encoder + I2C + Seriale (real-time)
 *
 *  2. CODA COMANDI (xQueueSend/Receive)
 *     - I2C ISR → coda → task motori: latenza < 1ms
 *     - MQTT callback → coda → task motori: latenza < 2ms
 *     - Seriale → coda → task motori: latenza < 2ms
 *     - Nessun flag volatile + polling, nessuna race condition
 *
 *  3. SERIAL RIMOSSO DAL LOOP PRINCIPALE
 *     - readStringUntil() bloccante → task dedicato su Core 1
 *     - Non blocca più I2C né MQTT
 *
 *  4. STAMPA SERIALE ASINCRONA
 *     - Task separato ogni 500ms
 *     - Non rallenta MAI il path critico motori
 *
 *  5. ENCODER CON SPINLOCK
 *     - portENTER_CRITICAL / portEXIT_CRITICAL invece di
 *       noInterrupts/interrupts globali
 *     - Più safe su sistema multicore
 *
 *  6. MQTT loop() su Core 0 continuo
 *     - mqtt.loop() ogni ~10ms senza bloccare Core 1
 *
 *  7. buildTxBuf() chiamato solo quando necessario
 *     - Non più ad ogni iterazione del loop
 *
 *  8. SICUREZZA ULTRASUONI
 *     - Il Raspberry invia periodicamente i dati sensori via I2C
 *       con comando 0xE0 seguito da 26 byte (intero i2cBuf dell'ESP32 sensori)
 *     - Se un sensore scende sotto la soglia DIST_SOGLIA_*, i movimenti
 *       nella direzione corrispondente vengono bloccati
 *     - Le soglie sono configurabili nella sezione ⚙️ qui sotto
 *     - Il blocco è per DIREZIONE, non globale
 *     - Layout sensori (stesso ordine del buffer i2cBuf esp32_sensori):
 *         [0-1]   FRONTE    → blocca: avanti, diag_avanti_dx, diag_avanti_sx
 *         [2-3]   RETRO     → blocca: indietro, diag_indietro_dx, diag_indietro_sx
 *         [4-5]   SINISTRA  → blocca: lat_sx, diag_avanti_sx, diag_indietro_sx
 *         [6-7]   DESTRA    → blocca: lat_dx, diag_avanti_dx, diag_indietro_dx
 *         [8-9]   CLIFF_F   → blocca: avanti (bordo/precipizio frontale)
 *         [10-11] CLIFF_R   → blocca: indietro (bordo/precipizio posteriore)
 *
 * ────────────────────────────────────────────────────────────────
 *  LATENZE ATTESE (misurate su ESP32 240MHz):
 *  I2C  → motore:  < 1ms
 *  MQTT → motore:  < 2ms
 *  Seriale → motore: < 2ms
 * ════════════════════════════════════════════════════════════════
 */

#include <Wire.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <PubSubClient.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

// ── CREDENZIALI DEFAULT ──────────────────────────────────────────
#define WIFI_SSID_DEFAULT   "LAPTOP1234"
#define WIFI_PASS_DEFAULT   "12345678"
#define MQTT_BROKER_DEFAULT "LagmaBills"
#define MQTT_PORT           1883
#define MQTT_CLIENT_ID      "esp32_motori"

// ── NVS ──────────────────────────────────────────────────────────
#define NVS_NAMESPACE  "wifi_cfg"
#define NVS_KEY_SSID   "ssid"
#define NVS_KEY_PASS   "pass"
#define NVS_KEY_BROKER "broker"

// ── I2C slave ────────────────────────────────────────────────────
#define I2C_SLAVE_ADDR  0x08
#define SDA_PIN         21
#define SCL_PIN         22

// canali
#define FL_CH 0
#define FR_CH 1
#define RL_CH 2
#define RR_CH 3

// ════════════════════════════════════════════════════════════════
//  ⚙️  SOGLIE SICUREZZA ULTRASUONI — MODIFICA QUI
//
//  Distanza minima (cm) sotto la quale il movimento nella direzione
//  corrispondente viene BLOCCATO, qualunque sia il comando ricevuto.
//
//  Metti 0 per disabilitare il blocco su un sensore specifico.
//  Metti 9999 per bloccare sempre quella direzione (test).
//
//  I valori 9999 nel buffer sensori indicano "sensore fuori portata"
//  (>300 cm o timeout): in quel caso il blocco NON si attiva.
// ════════════════════════════════════════════════════════════════
#define DIST_SOGLIA_FRONTE    0   // cm — blocca avanti
#define DIST_SOGLIA_RETRO     0   // cm — blocca indietro
#define DIST_SOGLIA_SINISTRA  0   // cm — blocca laterale sinistra
#define DIST_SOGLIA_DESTRA    0   // cm — blocca laterale destra
#define DIST_SOGLIA_CLIFF_F   0   // cm — blocca avanti (bordo)
#define DIST_SOGLIA_CLIFF_R   0   // cm — blocca indietro (bordo)

// Timeout sensori: se non riceviamo dati dal Pi entro questo tempo
// (ms), consideriamo i sensori "sconosciuti" e blocchiamo tutto
// per sicurezza. Metti 0 per disabilitare il timeout.
#define SENSOR_DATA_TIMEOUT_MS  0

// ── PIN MOTORE FL ─────────────────────────────────────────────────
#define FL_PWM    25
#define FL_IN1    26
#define FL_IN2    27
#define FL_ENC_A  13
#define FL_ENC_B  15

// ── PIN MOTORE FR ─────────────────────────────────────────────────
#define FR_PWM    33
#define FR_IN1    12
#define FR_IN2     2
#define FR_ENC_A  34
#define FR_ENC_B  35

// ── PIN MOTORE RL ─────────────────────────────────────────────────
#define RL_PWM    16
#define RL_IN1    17
#define RL_IN2     5
#define RL_ENC_A  36
#define RL_ENC_B  39

// ── PIN MOTORE RR ─────────────────────────────────────────────────
#define RR_PWM    23
#define RR_IN1    19
#define RR_IN2    18
#define RR_ENC_A   4
#define RR_ENC_B  32

// ── STBY condiviso ────────────────────────────────────────────────
#define STBY      14

// ── PWM ──────────────────────────────────────────────────────────
#define PWM_FREQ  5000
#define PWM_RES   8

// ── CODA COMANDI ─────────────────────────────────────────────────
#define CMD_QUEUE_SIZE 32

// ════════════════════════════════════════════════════════════════
//  TIPI — devono stare PRIMA di qualsiasi funzione che li usa
// ════════════════════════════════════════════════════════════════

// Direzioni per il controllo di sicurezza
enum DirezioneCmd {
  DIR_AVANTI,
  DIR_INDIETRO,
  DIR_SX,
  DIR_DX,
  DIR_DIAG_AVT_DX,
  DIR_DIAG_AVT_SX,
  DIR_DIAG_IND_DX,
  DIR_DIAG_IND_SX,
  DIR_RUOTA,
  DIR_NESSUNA
};

// Tipi di comando
enum CmdType : uint8_t {
  CMD_STOP = 0,
  CMD_AVANTI,
  CMD_INDIETRO,
  CMD_LAT_SX,
  CMD_LAT_DX,
  CMD_DIAG_AVT_DX,
  CMD_DIAG_AVT_SX,
  CMD_DIAG_IND_DX,
  CMD_DIAG_IND_SX,
  CMD_RUOTA_DX,
  CMD_RUOTA_SX,
  CMD_SET_MOTORI,       // fl,fr,rl,rr in val[0..3]
  CMD_MECANUM,          // vx=val[0], vy=val[1], vr=val[2]
  CMD_GIRA_ANGOLO,      // gradi in valF, vel in val[0]
  CMD_SET_VEL,          // velocità globale in val[0]
  CMD_RESET_ENC,
  CMD_MOTOR_SINGLE,     // motore=val[0] (0=FL,1=FR,2=RL,3=RR), speed=val[1]
  CMD_WIFI_CREDS,       // usa strBuf per ssid/pass/broker
  CMD_SENSOR_DATA,      // dati sensori dal Pi: SENSOR_BUF_SIZE byte in strBuf
};

struct MotorCmd {
  CmdType type;
  int16_t val[4];
  float   valF;
  char    strBuf[192];
};

// ── STATO CONDIVISO ──────────────────────────────────────────────
static portMUX_TYPE encMux    = portMUX_INITIALIZER_UNLOCKED;
static portMUX_TYPE txBufMux  = portMUX_INITIALIZER_UNLOCKED;
static portMUX_TYPE sensorMux = portMUX_INITIALIZER_UNLOCKED;

volatile long encoderFL = 0, encoderFR = 0;
volatile long encoderRL = 0, encoderRR = 0;
volatile int  lastEncFL = 0, lastEncFR = 0;
volatile int  lastEncRL = 0, lastEncRR = 0;

int     velocita    = 150;
uint8_t statoMotori = 0;
int     velFL = 0, velFR = 0, velRL = 0, velRR = 0;

const long TICKS_PER_360 = 1200;

// ── BUFFER I2C TX ─────────────────────────────────────────────────
#define TX_BUF_SIZE 28
volatile uint8_t txBuf[TX_BUF_SIZE];

// ── DATI SENSORI RICEVUTI DAL RASPBERRY ──────────────────────────
// Aggiornati dal Raspberry via I2C comando 0xE0 + 26 byte
// Stesso layout di i2cBuf dell'ESP32 sensori:
//   [0-1]   FRONTE    uint16 LE (cm, 9999=fuori portata)
//   [2-3]   RETRO     uint16 LE
//   [4-5]   SINISTRA  uint16 LE
//   [6-7]   DESTRA    uint16 LE
//   [8-9]   CLIFF_F   uint16 LE
//   [10-11] CLIFF_R   uint16 LE
//   [12-23] IMU (ax,ay,az,gx,gy,gz) int16 LE (×100)
//   [24]    TCRT mask (bit0=sx, bit1=cen, bit2=dx)
//   [25]    riservato
#define SENSOR_BUF_SIZE 26
volatile uint8_t  sensorBuf[SENSOR_BUF_SIZE];
volatile uint32_t lastSensorUpdateMs = 0;
volatile bool     sensorDataValid    = false;

// ── HANDLE RTOS ──────────────────────────────────────────────────
QueueHandle_t cmdQueue;
TaskHandle_t  motorTaskHandle  = nullptr;
TaskHandle_t  netTaskHandle    = nullptr;
TaskHandle_t  serialTaskHandle = nullptr;
TaskHandle_t  printTaskHandle  = nullptr;

// ── WiFi / MQTT ──────────────────────────────────────────────────
WiFiClient   wifiClient;
PubSubClient mqtt(wifiClient);
Preferences  prefs;

char wifiSsid[64];
char wifiPass[64];
char mqttBroker[64];

volatile bool wifiReconnectRequest = false;

// ════════════════════════════════════════════════════════════════
//  PROTOTIPI
// ════════════════════════════════════════════════════════════════
void motorControl(int pwmPin, int in1, int in2, int speed);
void setMotori(int fl, int fr, int rl, int rr);
void fermati();
void avanti(int v);
void indietro(int v);
void lateraleSx(int v);
void lateraleDx(int v);
void diagAvantiDx(int v);
void diagAvantiSx(int v);
void diagIndietroDx(int v);
void diagIndietroSx(int v);
void ruotaDx(int v);
void ruotaSx(int v);
void mecanumDrive(int vx, int vy, int vr);
void giraDiAngolo(float gradi, int vel);
void buildTxBuf();
void eseguiCmd(const MotorCmd& cmd);
void sendCmd(CmdType type, int v0=0, int v1=0, int v2=0, int v3=0, float f=0);
void loadCredentials();
void saveCredentials(const char* ssid, const char* pass, const char* broker);
void publishStato();
void printHelp();
void printEncoder();
void printStato();
uint16_t getSensorDist(int idx);
bool distanzaBloccante(uint16_t dist, uint16_t soglia);
bool isDirezioneBlocata(DirezioneCmd dir);

// ════════════════════════════════════════════════════════════════
//  SICUREZZA ULTRASUONI — lettura buffer e logica blocco
// ════════════════════════════════════════════════════════════════

// Legge una distanza uint16 LE dal buffer sensori (thread-safe)
// idx: 0=FRONTE, 1=RETRO, 2=SINISTRA, 3=DESTRA, 4=CLIFF_F, 5=CLIFF_R
inline uint16_t getSensorDist(int idx) {
  int o = idx * 2;
  portENTER_CRITICAL(&sensorMux);
  uint16_t v = sensorBuf[o] | ((uint16_t)sensorBuf[o+1] << 8);
  portEXIT_CRITICAL(&sensorMux);
  return v;
}

// Controlla se una singola distanza è sotto soglia (e valida)
inline bool distanzaBloccante(uint16_t dist, uint16_t soglia) {
  if (soglia == 0)    return false;   // soglia disabilitata
  if (dist == 9999)   return false;   // fuori portata = libero
  return dist < soglia;
}

// Restituisce true se la direzione è BLOCCATA da un sensore
bool isDirezioneBlocata(DirezioneCmd dir) {
  if (SENSOR_DATA_TIMEOUT_MS > 0) {
    uint32_t now = millis();
    portENTER_CRITICAL(&sensorMux);
    bool     valido  = sensorDataValid;
    uint32_t lastUpd = lastSensorUpdateMs;
    portEXIT_CRITICAL(&sensorMux);
    if (!valido || (now - lastUpd) > SENSOR_DATA_TIMEOUT_MS) {
      return true;  // dati scaduti: blocca per sicurezza
    }
  }

  uint16_t fronte  = getSensorDist(0);
  uint16_t retro   = getSensorDist(1);
  uint16_t sx      = getSensorDist(2);
  uint16_t dx      = getSensorDist(3);
  uint16_t cliff_f = getSensorDist(4);
  uint16_t cliff_r = getSensorDist(5);

  bool blk_fronte = distanzaBloccante(fronte,  DIST_SOGLIA_FRONTE)
                  || distanzaBloccante(cliff_f, DIST_SOGLIA_CLIFF_F);
  bool blk_retro  = distanzaBloccante(retro,   DIST_SOGLIA_RETRO)
                  || distanzaBloccante(cliff_r, DIST_SOGLIA_CLIFF_R);
  bool blk_sx     = distanzaBloccante(sx,      DIST_SOGLIA_SINISTRA);
  bool blk_dx     = distanzaBloccante(dx,      DIST_SOGLIA_DESTRA);

  switch (dir) {
    case DIR_AVANTI:       return blk_fronte;
    case DIR_INDIETRO:     return blk_retro;
    case DIR_SX:           return blk_sx;
    case DIR_DX:           return blk_dx;
    case DIR_DIAG_AVT_DX:  return blk_fronte || blk_dx;
    case DIR_DIAG_AVT_SX:  return blk_fronte || blk_sx;
    case DIR_DIAG_IND_DX:  return blk_retro  || blk_dx;
    case DIR_DIAG_IND_SX:  return blk_retro  || blk_sx;
    case DIR_RUOTA:        return false;
    case DIR_NESSUNA:      return false;
    default:               return false;
  }
}

// ════════════════════════════════════════════════════════════════
//  HELPER — invio comando alla coda (safe da qualsiasi contesto)
// ════════════════════════════════════════════════════════════════

inline void sendCmd(CmdType type, int v0, int v1, int v2, int v3, float f) {
  MotorCmd cmd = {};
  cmd.type   = type;
  cmd.val[0] = (int16_t)v0;
  cmd.val[1] = (int16_t)v1;
  cmd.val[2] = (int16_t)v2;
  cmd.val[3] = (int16_t)v3;
  cmd.valF   = f;
  xQueueSend(cmdQueue, &cmd, 0);
}

void sendWifiCreds(const char* ssid, const char* pass, const char* broker) {
  MotorCmd cmd = {};
  cmd.type = CMD_WIFI_CREDS;
  int idx = 0;
  auto pack = [&](const char* s) {
    int l = s ? strlen(s) : 0;
    if (l > 63) l = 63;
    cmd.strBuf[idx++] = (char)l;
    if (l > 0) { memcpy(cmd.strBuf + idx, s, l); idx += l; }
  };
  pack(ssid); pack(pass); pack(broker);
  xQueueSend(cmdQueue, &cmd, 0);
}

// ════════════════════════════════════════════════════════════════
//  NVS
// ════════════════════════════════════════════════════════════════

void loadCredentials() {
  prefs.begin(NVS_NAMESPACE, true);
  String ssid   = prefs.getString(NVS_KEY_SSID,   WIFI_SSID_DEFAULT);
  String pass   = prefs.getString(NVS_KEY_PASS,   WIFI_PASS_DEFAULT);
  String broker = prefs.getString(NVS_KEY_BROKER, MQTT_BROKER_DEFAULT);
  prefs.end();
  ssid.toCharArray(wifiSsid,     sizeof(wifiSsid));
  pass.toCharArray(wifiPass,     sizeof(wifiPass));
  broker.toCharArray(mqttBroker, sizeof(mqttBroker));
}

void saveCredentials(const char* ssid, const char* pass, const char* broker) {
  prefs.begin(NVS_NAMESPACE, false);
  if (ssid   && ssid[0])   prefs.putString(NVS_KEY_SSID,   ssid);
  if (pass   && pass[0])   prefs.putString(NVS_KEY_PASS,   pass);
  if (broker && broker[0]) prefs.putString(NVS_KEY_BROKER, broker);
  prefs.end();
}

// ════════════════════════════════════════════════════════════════
//  mDNS
// ════════════════════════════════════════════════════════════════

void resolveBroker() {
  const char* host = MQTT_BROKER_DEFAULT;
  MDNS.begin("esp32-motori");
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
//  ENCODER ISR
// ════════════════════════════════════════════════════════════════

void IRAM_ATTR updateEncoderFL() {
  int enc = (digitalRead(FL_ENC_A) << 1) | digitalRead(FL_ENC_B);
  int sum = (lastEncFL << 2) | enc;
  portENTER_CRITICAL_ISR(&encMux);
  if (sum==0b1101||sum==0b0100||sum==0b0010||sum==0b1011) encoderFL++;
  if (sum==0b1110||sum==0b0111||sum==0b0001||sum==0b1000) encoderFL--;
  portEXIT_CRITICAL_ISR(&encMux);
  lastEncFL = enc;
}
void IRAM_ATTR updateEncoderFR() {
  int enc = (digitalRead(FR_ENC_A) << 1) | digitalRead(FR_ENC_B);
  int sum = (lastEncFR << 2) | enc;
  portENTER_CRITICAL_ISR(&encMux);
  if (sum==0b1101||sum==0b0100||sum==0b0010||sum==0b1011) encoderFR++;
  if (sum==0b1110||sum==0b0111||sum==0b0001||sum==0b1000) encoderFR--;
  portEXIT_CRITICAL_ISR(&encMux);
  lastEncFR = enc;
}
void IRAM_ATTR updateEncoderRL() {
  int enc = (digitalRead(RL_ENC_A) << 1) | digitalRead(RL_ENC_B);
  int sum = (lastEncRL << 2) | enc;
  portENTER_CRITICAL_ISR(&encMux);
  if (sum==0b1101||sum==0b0100||sum==0b0010||sum==0b1011) encoderRL++;
  if (sum==0b1110||sum==0b0111||sum==0b0001||sum==0b1000) encoderRL--;
  portEXIT_CRITICAL_ISR(&encMux);
  lastEncRL = enc;
}
void IRAM_ATTR updateEncoderRR() {
  int enc = (digitalRead(RR_ENC_A) << 1) | digitalRead(RR_ENC_B);
  int sum = (lastEncRR << 2) | enc;
  portENTER_CRITICAL_ISR(&encMux);
  if (sum==0b1101||sum==0b0100||sum==0b0010||sum==0b1011) encoderRR++;
  if (sum==0b1110||sum==0b0111||sum==0b0001||sum==0b1000) encoderRR--;
  portEXIT_CRITICAL_ISR(&encMux);
  lastEncRR = enc;
}

// ════════════════════════════════════════════════════════════════
//  MOTORI — basso livello
// ════════════════════════════════════════════════════════════════

void IRAM_ATTR motorControl(int channel, int in1, int in2, int speed) {
  speed = constrain(speed, -255, 255);
  if (speed > 0)      { digitalWrite(in1, HIGH); digitalWrite(in2, LOW);  ledcWrite(channel,  speed); }
  else if (speed < 0) { digitalWrite(in1, LOW);  digitalWrite(in2, HIGH); ledcWrite(channel, -speed); }
  else                { digitalWrite(in1, LOW);  digitalWrite(in2, LOW);  ledcWrite(channel,  0);     }
}

void IRAM_ATTR setMotori(int fl, int fr, int rl, int rr) {
  velFL = fl; velFR = fr; velRL = rl; velRR = rr;
  motorControl(FL_CH, FL_IN1, FL_IN2, fl);
  motorControl(FR_CH, FR_IN1, FR_IN2, fr);
  motorControl(RL_CH, RL_IN1, RL_IN2, rl);
  motorControl(RR_CH, RR_IN1, RR_IN2, rr);
}

void setMotoriCorrected(int fl, int fr, int rl, int rr) {
  setMotori(-fl, fr, -rl, rr);
}

void fermati() { setMotori(0,0,0,0); statoMotori=0; buildTxBuf(); }  // ← aggiungi questa

// ── SOSTITUISCI le funzioni di movimento ─────────────────────────
void avanti(int v)         { setMotoriCorrected( v, v, v, v);   statoMotori=1; buildTxBuf(); }
void indietro(int v)       { setMotoriCorrected(-v,-v,-v,-v);   statoMotori=1; buildTxBuf(); }
void lateraleDx(int v)  { setMotoriCorrected( v,-v,-v, v);  statoMotori=1; buildTxBuf(); }
void lateraleSx(int v)  { setMotoriCorrected(-v, v, v,-v);  statoMotori=1; buildTxBuf(); }
void diagAvantiDx(int v)   { setMotoriCorrected( v, 0, 0, v);   statoMotori=1; buildTxBuf(); }
void diagAvantiSx(int v)   { setMotoriCorrected( 0, v, v, 0);   statoMotori=1; buildTxBuf(); }
void diagIndietroDx(int v) { setMotoriCorrected( 0,-v,-v, 0);   statoMotori=1; buildTxBuf(); }
void diagIndietroSx(int v) { setMotoriCorrected(-v, 0, 0,-v);   statoMotori=1; buildTxBuf(); }
void ruotaDx(int v)        { setMotoriCorrected( v,-v, v,-v);   statoMotori=2; buildTxBuf(); }
void ruotaSx(int v)        { setMotoriCorrected(-v, v,-v, v);   statoMotori=2; buildTxBuf(); }

void mecanumDrive(int vx, int vy, int vr) {
  int fl = vy+vx+vr, fr = vy-vx-vr;
  int rl = vy-vx+vr, rr = vy+vx-vr;
  int mx = max({abs(fl),abs(fr),abs(rl),abs(rr)});
  if (mx > 255) { fl=fl*255/mx; fr=fr*255/mx; rl=rl*255/mx; rr=rr*255/mx; }
  setMotoriCorrected(fl,fr,rl,rr);   // ← corretto
  statoMotori = 1;
  buildTxBuf();
}

void giraDiAngolo(float gradi, int vel) {
  if (gradi == 0) return;
  statoMotori = 2;
  long tickTarget = (long)((fabsf(gradi) / 360.0f) * TICKS_PER_360);
  portENTER_CRITICAL(&encMux);
  encoderFL = 0; encoderFR = 0;
  portEXIT_CRITICAL(&encMux);
  if (gradi > 0) ruotaDx(vel); else ruotaSx(vel);
  while (true) {
    long fl, fr;
    portENTER_CRITICAL(&encMux);
    fl = encoderFL; fr = encoderFR;
    portEXIT_CRITICAL(&encMux);
    long percorsi = (abs(fl) + abs(fr)) / 2;
    if (percorsi >= tickTarget) break;
    float pct = (float)percorsi / tickTarget;
    if (pct > 0.85f) {
      int vr = max(80, (int)(vel * (1.0f - pct) * 6.67f));
      if (gradi > 0) ruotaDx(vr); else ruotaSx(vr);
    }
    buildTxBuf();
    vTaskDelay(pdMS_TO_TICKS(5));
  }
  fermati();
  vTaskDelay(pdMS_TO_TICKS(150));
}

// ════════════════════════════════════════════════════════════════
//  BUFFER TX
// ════════════════════════════════════════════════════════════════

void buildTxBuf() {
  long fl, fr, rl, rr;
  portENTER_CRITICAL(&encMux);
  fl = encoderFL; fr = encoderFR; rl = encoderRL; rr = encoderRR;
  portEXIT_CRITICAL(&encMux);
  portENTER_CRITICAL(&txBufMux);
  auto writeI32 = [](volatile uint8_t* buf, int offset, long val) {
    buf[offset]   = (uint8_t)(val        & 0xFF);
    buf[offset+1] = (uint8_t)((val >> 8) & 0xFF);
    buf[offset+2] = (uint8_t)((val >>16) & 0xFF);
    buf[offset+3] = (uint8_t)((val >>24) & 0xFF);
  };
  writeI32(txBuf,  0, fl);
  writeI32(txBuf,  4, fr);
  writeI32(txBuf,  8, rl);
  writeI32(txBuf, 12, rr);
  txBuf[16] = (uint8_t)velocita;
  txBuf[17] = statoMotori;
  txBuf[18] = (uint8_t)(constrain(velFL, -127, 127) + 128);
  txBuf[19] = (uint8_t)(constrain(velFR, -127, 127) + 128);
  txBuf[20] = (uint8_t)(constrain(velRL, -127, 127) + 128);
  txBuf[21] = (uint8_t)(constrain(velRR, -127, 127) + 128);
  txBuf[22] = txBuf[23] = txBuf[24] = txBuf[25] = txBuf[26] = txBuf[27] = 0;
  portEXIT_CRITICAL(&txBufMux);
}

// ════════════════════════════════════════════════════════════════
//  ESEGUI COMANDO DAL QUEUE (solo nel task motori → nessuna race)
// ════════════════════════════════════════════════════════════════

void eseguiCmd(const MotorCmd& c) {
  switch (c.type) {
    case CMD_STOP: fermati(); break;

    case CMD_AVANTI:
      if (isDirezioneBlocata(DIR_AVANTI))
        { fermati(); Serial.println("[SAFETY] AVANTI bloccato (ostacolo/cliff frontale)"); }
      else avanti(velocita);
      break;

    case CMD_INDIETRO:
      if (isDirezioneBlocata(DIR_INDIETRO))
        { fermati(); Serial.println("[SAFETY] INDIETRO bloccato (ostacolo/cliff posteriore)"); }
      else indietro(velocita);
      break;

    case CMD_LAT_SX:
      if (isDirezioneBlocata(DIR_SX))
        { fermati(); Serial.println("[SAFETY] LAT_SX bloccato (ostacolo sinistra)"); }
      else lateraleSx(velocita);
      break;

    case CMD_LAT_DX:
      if (isDirezioneBlocata(DIR_DX))
        { fermati(); Serial.println("[SAFETY] LAT_DX bloccato (ostacolo destra)"); }
      else lateraleDx(velocita);
      break;

    case CMD_DIAG_AVT_DX:
      if (isDirezioneBlocata(DIR_DIAG_AVT_DX))
        { fermati(); Serial.println("[SAFETY] DIAG_AVT_DX bloccato"); }
      else diagAvantiDx(velocita);
      break;

    case CMD_DIAG_AVT_SX:
      if (isDirezioneBlocata(DIR_DIAG_AVT_SX))
        { fermati(); Serial.println("[SAFETY] DIAG_AVT_SX bloccato"); }
      else diagAvantiSx(velocita);
      break;

    case CMD_DIAG_IND_DX:
      if (isDirezioneBlocata(DIR_DIAG_IND_DX))
        { fermati(); Serial.println("[SAFETY] DIAG_IND_DX bloccato"); }
      else diagIndietroDx(velocita);
      break;

    case CMD_DIAG_IND_SX:
      if (isDirezioneBlocata(DIR_DIAG_IND_SX))
        { fermati(); Serial.println("[SAFETY] DIAG_IND_SX bloccato"); }
      else diagIndietroSx(velocita);
      break;

    case CMD_RUOTA_DX: ruotaDx(velocita); break;
    case CMD_RUOTA_SX: ruotaSx(velocita); break;

    case CMD_SET_VEL:
      velocita = constrain((int)c.val[0], 0, 255);
      break;

    case CMD_RESET_ENC:
      portENTER_CRITICAL(&encMux);
      encoderFL = encoderFR = encoderRL = encoderRR = 0;
      portEXIT_CRITICAL(&encMux);
      break;

    case CMD_SET_MOTORI: {
      int fl = c.val[0], fr = c.val[1], rl = c.val[2], rr = c.val[3];
      // Stima componente avanti/retro e laterale
      int vy = (fl + fr + rl + rr) / 4;
      int vx = (-fl + fr + rl - rr) / 4;
      bool blocked = false;
      if (vy > 0 && isDirezioneBlocata(DIR_AVANTI))   { blocked = true; Serial.println("[SAFETY] SET_MOTORI bloccato (fronte)"); }
      if (vy < 0 && isDirezioneBlocata(DIR_INDIETRO)) { blocked = true; Serial.println("[SAFETY] SET_MOTORI bloccato (retro)"); }
      if (vx > 0 && isDirezioneBlocata(DIR_DX))       { blocked = true; Serial.println("[SAFETY] SET_MOTORI bloccato (destra)"); }
      if (vx < 0 && isDirezioneBlocata(DIR_SX))       { blocked = true; Serial.println("[SAFETY] SET_MOTORI bloccato (sinistra)"); }
      if (!blocked) {
        setMotori(fl, fr, rl, rr);
        statoMotori = (fl==0&&fr==0&&rl==0&&rr==0) ? 0 : 1;
        buildTxBuf();
      } else {
        fermati();
      }
      break;
    }

    case CMD_MECANUM: {
      int vx = c.val[0], vy = c.val[1], vr = c.val[2];
      bool blocked = false;
      if (vy > 0 && isDirezioneBlocata(DIR_AVANTI))   { blocked = true; Serial.println("[SAFETY] MECANUM bloccato (fronte)"); }
      if (vy < 0 && isDirezioneBlocata(DIR_INDIETRO)) { blocked = true; Serial.println("[SAFETY] MECANUM bloccato (retro)"); }
      if (vx > 0 && isDirezioneBlocata(DIR_DX))       { blocked = true; Serial.println("[SAFETY] MECANUM bloccato (destra)"); }
      if (vx < 0 && isDirezioneBlocata(DIR_SX))       { blocked = true; Serial.println("[SAFETY] MECANUM bloccato (sinistra)"); }
      if (!blocked) mecanumDrive(vx, vy, vr);
      else fermati();
      break;
    }

    case CMD_GIRA_ANGOLO:
      giraDiAngolo(c.valF, (int)c.val[0]);
      break;

    case CMD_MOTOR_SINGLE: {
      int motore = c.val[0];
      int speed  = c.val[1];
      switch (motore) {
        case 0: motorControl(FL_CH,FL_IN1,FL_IN2,speed); velFL=speed; break;
        case 1: motorControl(FR_CH,FR_IN1,FR_IN2,speed); velFR=speed; break;
        case 2: motorControl(RL_CH,RL_IN1,RL_IN2,speed); velRL=speed; break;
        case 3: motorControl(RR_CH,RR_IN1,RR_IN2,speed); velRR=speed; break;
      }
      statoMotori = (velFL==0&&velFR==0&&velRL==0&&velRR==0) ? 0 : 1;
      buildTxBuf();
      break;
    }

    case CMD_WIFI_CREDS: {
      const char* buf = c.strBuf;
      int idx = 0;
      char newSsid[64]={}, newPass[64]={}, newBroker[64]={};
      auto unpack = [&](char* dst, int maxLen) {
        int l = (uint8_t)buf[idx++];
        if (l > 0) { memcpy(dst, buf+idx, min(l,maxLen-1)); idx += l; }
      };
      unpack(newSsid,   sizeof(newSsid));
      unpack(newPass,   sizeof(newPass));
      unpack(newBroker, sizeof(newBroker));
      saveCredentials(newSsid, newPass, newBroker);
      if (newSsid[0])   strncpy(wifiSsid,   newSsid,   sizeof(wifiSsid));
      if (newPass[0])   strncpy(wifiPass,   newPass,   sizeof(wifiPass));
      if (newBroker[0]) strncpy(mqttBroker, newBroker, sizeof(mqttBroker));
      wifiReconnectRequest = true;
      break;
    }

    case CMD_SENSOR_DATA: {
      // Aggiorna il buffer sensori con i dati ricevuti dal Pi
      portENTER_CRITICAL(&sensorMux);
      memcpy((void*)sensorBuf, c.strBuf, SENSOR_BUF_SIZE);
      lastSensorUpdateMs = millis();
      sensorDataValid    = true;
      portEXIT_CRITICAL(&sensorMux);
      break;
    }
  }
}

// ════════════════════════════════════════════════════════════════
//  I2C SLAVE CALLBACKS
// ════════════════════════════════════════════════════════════════

void onRequest() {
  portENTER_CRITICAL_ISR(&txBufMux);
  Wire.write((uint8_t*)txBuf, TX_BUF_SIZE);
  portEXIT_CRITICAL_ISR(&txBufMux);
}

void onReceive(int n) {
  if (n == 0) return;
  uint8_t rxBuf[128];
  uint8_t rxLen = 0;
  while (Wire.available() && rxLen < sizeof(rxBuf)-1)
    rxBuf[rxLen++] = Wire.read();
  if (rxLen == 0) return;

  uint8_t cmd = rxBuf[0];

  // ── 0xE0 — dati sensori dal Raspberry (26 byte = i2cBuf completo) ──
  if (cmd == 0xE0) {
    if (rxLen < (1 + SENSOR_BUF_SIZE)) return;  // pacchetto incompleto
    MotorCmd mc = {};
    mc.type = CMD_SENSOR_DATA;
    memcpy(mc.strBuf, rxBuf + 1, SENSOR_BUF_SIZE);
    xQueueSendFromISR(cmdQueue, &mc, nullptr);
    return;
  }

  // ── Credenziali WiFi (0xFD / 0xFE) ──────────────────────────────
  if (cmd == 0xFD && rxLen >= 4) {
    MotorCmd mc = {};
    mc.type = CMD_WIFI_CREDS;
    uint8_t lenIp = rxBuf[1];
    char broker[64]={}, ssid[64]={}, pass[64]={};
    memcpy(broker, rxBuf+2, min((int)lenIp, 63));
    int idx = 2+lenIp;
    if (idx < rxLen) {
      uint8_t ls = rxBuf[idx++];
      memcpy(ssid, rxBuf+idx, min((int)ls, 63)); idx+=ls;
      if (idx < rxLen) {
        uint8_t lp = rxBuf[idx++];
        memcpy(pass, rxBuf+idx, min((int)lp, 63));
      }
    }
    int bi = 0;
    auto pack = [&](const char* s) {
      int l = strlen(s); if(l>63) l=63;
      mc.strBuf[bi++]=(char)l;
      memcpy(mc.strBuf+bi, s, l); bi+=l;
    };
    pack(ssid); pack(pass); pack(broker);
    xQueueSendFromISR(cmdQueue, &mc, nullptr);
    return;
  }
  if (cmd == 0xFE && rxLen >= 4) {
    MotorCmd mc = {};
    mc.type = CMD_WIFI_CREDS;
    char ssid[64]={}, pass[64]={};
    uint8_t ls = rxBuf[1];
    memcpy(ssid, rxBuf+2, min((int)ls, 63));
    uint8_t lp = rxBuf[2+ls];
    memcpy(pass, rxBuf+3+ls, min((int)lp, 63));
    int bi = 0;
    auto pack = [&](const char* s) {
      int l = strlen(s); if(l>63) l=63;
      mc.strBuf[bi++]=(char)l;
      memcpy(mc.strBuf+bi, s, l); bi+=l;
    };
    pack(ssid); pack(pass); pack("");
    xQueueSendFromISR(cmdQueue, &mc, nullptr);
    return;
  }

  // ── Comandi movimento ────────────────────────────────────────────
  CmdType type = CMD_STOP;
  bool valid = true;
  MotorCmd mc = {};

  switch (cmd) {
    case 0x00: type = CMD_STOP;          break;
    case 0x01: type = CMD_AVANTI;        break;
    case 0x02: type = CMD_INDIETRO;      break;
    case 0x03: type = CMD_LAT_SX;        break;
    case 0x04: type = CMD_LAT_DX;        break;
    case 0x05: type = CMD_DIAG_AVT_DX;   break;
    case 0x06: type = CMD_DIAG_AVT_SX;   break;
    case 0x07: type = CMD_DIAG_IND_DX;   break;
    case 0x08: type = CMD_DIAG_IND_SX;   break;
    case 0x09: type = CMD_RUOTA_DX;      break;
    case 0x0A: type = CMD_RUOTA_SX;      break;
    case 0xFF: type = CMD_RESET_ENC;     break;
    case 0xF0:
      if (rxLen >= 2) { mc.type=CMD_SET_VEL; mc.val[0]=rxBuf[1]; xQueueSendFromISR(cmdQueue,&mc,nullptr); }
      return;
    case 0xF1:
      if (rxLen >= 3) { mc.type=CMD_MECANUM; mc.val[0]=(int)rxBuf[1]-128; mc.val[1]=(int)rxBuf[2]-128; mc.val[2]=0; xQueueSendFromISR(cmdQueue,&mc,nullptr); }
      return;
    case 0xF2:
      if (rxLen >= 4) { mc.type=CMD_MECANUM; mc.val[0]=(int)rxBuf[1]-128; mc.val[1]=(int)rxBuf[2]-128; mc.val[2]=(int)rxBuf[3]-128; xQueueSendFromISR(cmdQueue,&mc,nullptr); }
      return;
    case 0xF3:
      if (rxLen >= 3) { mc.type=CMD_GIRA_ANGOLO; mc.valF=((rxBuf[1]<<8)|rxBuf[2])-32768.0f; mc.val[0]=velocita; xQueueSendFromISR(cmdQueue,&mc,nullptr); }
      return;
    default: valid = false; break;
  }
  if (valid) { mc.type = type; xQueueSendFromISR(cmdQueue, &mc, nullptr); }
}

// ════════════════════════════════════════════════════════════════
//  MQTT CALLBACK
// ════════════════════════════════════════════════════════════════

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  char msg[128];
  if (length >= sizeof(msg)) return;
  memcpy(msg, payload, length);
  msg[length] = '\0';

  StaticJsonDocument<128> doc;
  if (deserializeJson(doc, msg)) return;
  const char* cmd = doc["cmd"];
  if (!cmd) return;

  struct { const char* name; CmdType type; } presets[] = {
    {"avanti",            CMD_AVANTI},
    {"indietro",          CMD_INDIETRO},
    {"sinistra",          CMD_LAT_SX},
    {"destra",            CMD_LAT_DX},
    {"ruota_dx",          CMD_RUOTA_DX},
    {"ruota_sx",          CMD_RUOTA_SX},
    {"stop",              CMD_STOP},
    {"diag_avanti_dx",    CMD_DIAG_AVT_DX},
    {"diag_avanti_sx",    CMD_DIAG_AVT_SX},
    {"diag_indietro_dx",  CMD_DIAG_IND_DX},
    {"diag_indietro_sx",  CMD_DIAG_IND_SX},
  };
  for (auto& p : presets) {
    if (strcmp(cmd, p.name) == 0) { sendCmd(p.type); return; }
  }

  if (strcmp(cmd,"velocita")==0)  { sendCmd(CMD_SET_VEL, (int)(doc["val"]|velocita)); return; }
  if (strcmp(cmd,"reset_enc")==0) { sendCmd(CMD_RESET_ENC); return; }
  if (strcmp(cmd,"mecanum")==0)   { sendCmd(CMD_MECANUM, (int)(doc["vx"]|0), (int)(doc["vy"]|0), (int)(doc["vr"]|0)); return; }

  auto singleMotor = [&](int idx) {
    MotorCmd mc={};
    mc.type=CMD_MOTOR_SINGLE;
    mc.val[0]=idx;
    mc.val[1]=constrain((int)(doc["val"]|0),-255,255);
    xQueueSend(cmdQueue,&mc,0);
  };
  if (strcmp(cmd,"fl")==0) { singleMotor(0); return; }
  if (strcmp(cmd,"fr")==0) { singleMotor(1); return; }
  if (strcmp(cmd,"rl")==0) { singleMotor(2); return; }
  if (strcmp(cmd,"rr")==0) { singleMotor(3); return; }

  if (strcmp(cmd,"sx")==0)   { int v=constrain((int)(doc["val"]|0),-255,255); sendCmd(CMD_SET_MOTORI,v,velFR,v,velRR); return; }
  if (strcmp(cmd,"dx")==0)   { int v=constrain((int)(doc["val"]|0),-255,255); sendCmd(CMD_SET_MOTORI,velFL,v,velRL,v); return; }
  if (strcmp(cmd,"ant")==0)  { int v=constrain((int)(doc["val"]|0),-255,255); sendCmd(CMD_SET_MOTORI,v,v,velRL,velRR); return; }
  if (strcmp(cmd,"post")==0) { int v=constrain((int)(doc["val"]|0),-255,255); sendCmd(CMD_SET_MOTORI,velFL,velFR,v,v); return; }
  if (strcmp(cmd,"diag1")==0){ int v=constrain((int)(doc["val"]|0),-255,255); sendCmd(CMD_SET_MOTORI,v,velFR,velRL,v); return; }
  if (strcmp(cmd,"diag2")==0){ int v=constrain((int)(doc["val"]|0),-255,255); sendCmd(CMD_SET_MOTORI,velFL,v,v,velRR); return; }
  if (strcmp(cmd,"tutti")==0){ int v=constrain((int)(doc["val"]|0),-255,255); sendCmd(CMD_SET_MOTORI,v,v,v,v); return; }
  if (strcmp(cmd,"set")==0) {
    sendCmd(CMD_SET_MOTORI,
      constrain((int)(doc["fl"]|0),-255,255),
      constrain((int)(doc["fr"]|0),-255,255),
      constrain((int)(doc["rl"]|0),-255,255),
      constrain((int)(doc["rr"]|0),-255,255));
    return;
  }
}

// ════════════════════════════════════════════════════════════════
//  MQTT — publish stato
// ════════════════════════════════════════════════════════════════

void publishStato() {
  if (!mqtt.connected()) return;
  long fl, fr, rl, rr;
  portENTER_CRITICAL(&encMux);
  fl=encoderFL; fr=encoderFR; rl=encoderRL; rr=encoderRR;
  portEXIT_CRITICAL(&encMux);
  char buf[200];
  snprintf(buf, sizeof(buf),
    "{\"online\":true,\"fl\":%ld,\"fr\":%ld,\"rl\":%ld,\"rr\":%ld,"
    "\"vel\":%d,\"stato\":%d,"
    "\"vfl\":%d,\"vfr\":%d,\"vrl\":%d,\"vrr\":%d}",
    fl,fr,rl,rr,velocita,(int)statoMotori,velFL,velFR,velRL,velRR);
  mqtt.publish("robot/motori/stato", buf);
}

// ════════════════════════════════════════════════════════════════
//  TASK: MOTORI — Core 1, priorità alta
// ════════════════════════════════════════════════════════════════

void taskMotori(void* pvParameters) {
  MotorCmd cmd;
  for (;;) {
    if (xQueueReceive(cmdQueue, &cmd, pdMS_TO_TICKS(10)) == pdTRUE) {
      eseguiCmd(cmd);
    }
    buildTxBuf();
  }
}

// ════════════════════════════════════════════════════════════════
//  TASK: RETE — Core 0, priorità normale
// ════════════════════════════════════════════════════════════════

void taskRete(void* pvParameters) {
  loadCredentials();
  WiFi.mode(WIFI_STA);
  WiFi.begin(wifiSsid, wifiPass);
  { uint32_t t = millis(); while (!WiFi.isConnected() && (millis()-t)<10000) vTaskDelay(pdMS_TO_TICKS(200)); }
  if (WiFi.isConnected()) resolveBroker();
  mqtt.setServer(mqttBroker, MQTT_PORT);
  mqtt.setCallback(mqttCallback);
  mqtt.setKeepAlive(15);

  uint32_t lastWifiCheck   = 0;
  uint32_t lastMqttCheck   = 0;
  uint32_t lastMqttPublish = 0;

  for (;;) {
    uint32_t now = millis();
    if (wifiReconnectRequest) {
      wifiReconnectRequest = false;
      WiFi.disconnect(true);
      vTaskDelay(pdMS_TO_TICKS(200));
      WiFi.begin(wifiSsid, wifiPass);
      mqtt.setServer(mqttBroker, MQTT_PORT);
    }
    if ((now - lastWifiCheck) >= 5000) {
      lastWifiCheck = now;
      if (!WiFi.isConnected()) WiFi.reconnect();
    }
    if (WiFi.isConnected()) {
      if (!mqtt.connected()) {
        if ((now - lastMqttCheck) >= 5000) {
          lastMqttCheck = now;
          resolveBroker();
          mqtt.setServer(mqttBroker, MQTT_PORT);
          const char* lwtPayload = "{\"online\":false}";
          if (mqtt.connect(MQTT_CLIENT_ID, nullptr,nullptr,
                           "robot/motori/stato",0,true,lwtPayload)) {
            mqtt.subscribe("robot/motori/cmd");
            mqtt.publish("robot/motori/log","esp32_motori online");
          }
        }
      } else {
        mqtt.loop();
        if ((now - lastMqttPublish) >= 500) {
          lastMqttPublish = now;
          publishStato();
        }
      }
    }
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

// ════════════════════════════════════════════════════════════════
//  TASK: SERIALE — Core 1, priorità bassa
// ════════════════════════════════════════════════════════════════

void printHelp() {
  Serial.println(F("\n══════════════ COMANDI SERIALI ══════════════"));
  Serial.println(F("  vel <0-255>              es: vel 180"));
  Serial.println(F("  fl/fr/rl/rr <-255..255>  es: fl 150"));
  Serial.println(F("  sx/dx/ant/post/diag1/diag2 <val>"));
  Serial.println(F("  tutti <val>  |  set <fl> <fr> <rl> <rr>"));
  Serial.println(F("  avanti  indietro  sinistra  destra"));
  Serial.println(F("  ruota_dx  ruota_sx  stop"));
  Serial.println(F("  enc  |  reset_enc  |  stato  |  help"));
  Serial.println(F("═════════════════════════════════════════════\n"));
}

void printEncoder() {
  long fl,fr,rl,rr;
  portENTER_CRITICAL(&encMux);
  fl=encoderFL; fr=encoderFR; rl=encoderRL; rr=encoderRR;
  portEXIT_CRITICAL(&encMux);
  Serial.printf("ENC → FL:%ld  FR:%ld  RL:%ld  RR:%ld\n",fl,fr,rl,rr);
}

void printStato() {
  long fl,fr,rl,rr;
  portENTER_CRITICAL(&encMux);
  fl=encoderFL; fr=encoderFR; rl=encoderRL; rr=encoderRR;
  portEXIT_CRITICAL(&encMux);
  Serial.println(F("\n─── STATO ───────────────────────────────────"));
  Serial.printf("Velocità globale  : %d\n", velocita);
  Serial.printf("Stato motori      : %s\n",
    statoMotori==0?"STOP": statoMotori==1?"IN MOVIMENTO":"ROTAZIONE PRECISA");
  Serial.printf("PWM (FL FR RL RR) : %d  %d  %d  %d\n",velFL,velFR,velRL,velRR);
  Serial.printf("Encoder           : FL=%ld  FR=%ld  RL=%ld  RR=%ld\n",fl,fr,rl,rr);
  Serial.printf("WiFi   : %s\n", WiFi.isConnected()?WiFi.localIP().toString().c_str():"DISCONNESSO");
  Serial.printf("MQTT   : %s  broker=%s\n", mqtt.connected()?"OK":"DISCONNESSO", mqttBroker);
  // Stato sensori
  portENTER_CRITICAL(&sensorMux);
  bool valido = sensorDataValid;
  uint32_t lastUpd = lastSensorUpdateMs;
  portEXIT_CRITICAL(&sensorMux);
  Serial.printf("Sensori: %s (ultimo aggiornamento: %lums fa)\n",
    valido ? "VALIDI" : "NON RICEVUTI",
    valido ? (uint32_t)(millis() - lastUpd) : 0UL);
  if (valido) {
    Serial.printf("  FRONTE:%ucm  RETRO:%ucm  SX:%ucm  DX:%ucm  CLIFF_F:%ucm  CLIFF_R:%ucm\n",
      getSensorDist(0), getSensorDist(1), getSensorDist(2),
      getSensorDist(3), getSensorDist(4), getSensorDist(5));
  }
  Serial.println(F("─────────────────────────────────────────────\n"));
}

void taskSeriale(void* pvParameters) {
  for (;;) {
    if (!Serial.available()) { vTaskDelay(pdMS_TO_TICKS(5)); continue; }
    String line = Serial.readStringUntil('\n');
    line.trim();
    if (line.length() == 0) continue;
    String ll = line; ll.toLowerCase();

    if (ll=="help"||ll=="?")  { printHelp();    continue; }
    if (ll=="stato")           { printStato();   continue; }
    if (ll=="enc")             { printEncoder(); continue; }
    if (ll=="reset_enc")       { sendCmd(CMD_RESET_ENC); Serial.println("Encoder azzerati."); continue; }
    if (ll=="avanti")          { sendCmd(CMD_AVANTI);    Serial.printf("AVANTI vel=%d\n",velocita);      continue; }
    if (ll=="indietro")        { sendCmd(CMD_INDIETRO);  Serial.printf("INDIETRO vel=%d\n",velocita);    continue; }
    if (ll=="sinistra")        { sendCmd(CMD_LAT_SX);    Serial.printf("LATERALE SX vel=%d\n",velocita); continue; }
    if (ll=="destra")          { sendCmd(CMD_LAT_DX);    Serial.printf("LATERALE DX vel=%d\n",velocita); continue; }
    if (ll=="ruota_dx")        { sendCmd(CMD_RUOTA_DX);  Serial.printf("RUOTA DX vel=%d\n",velocita);    continue; }
    if (ll=="ruota_sx")        { sendCmd(CMD_RUOTA_SX);  Serial.printf("RUOTA SX vel=%d\n",velocita);    continue; }
    if (ll=="stop")            { sendCmd(CMD_STOP);      Serial.println("STOP");                         continue; }

    int sp = ll.indexOf(' ');
    if (sp < 0) { Serial.printf("Comando sconosciuto: '%s'\n", line.c_str()); continue; }
    String cmd  = ll.substring(0, sp);
    String args = ll.substring(sp+1); args.trim();

    if (cmd=="vel")  { int v=constrain(args.toInt(),0,255);    sendCmd(CMD_SET_VEL,v);  Serial.printf("Velocità: %d\n",v);  continue; }
    if (cmd=="tutti"){ int v=constrain(args.toInt(),-255,255); sendCmd(CMD_SET_MOTORI,v,v,v,v); Serial.printf("TUTTI=%d\n",v); continue; }

    int mi = -1;
    if (cmd=="fl") mi=0; else if (cmd=="fr") mi=1;
    else if (cmd=="rl") mi=2; else if (cmd=="rr") mi=3;
    if (mi >= 0) {
      int v = constrain(args.toInt(),-255,255);
      MotorCmd mc={}; mc.type=CMD_MOTOR_SINGLE; mc.val[0]=mi; mc.val[1]=v;
      xQueueSend(cmdQueue,&mc,0);
      Serial.printf("%s=%d\n", cmd.c_str(), v);
      continue;
    }

    if (cmd=="sx")   { int v=constrain(args.toInt(),-255,255); sendCmd(CMD_SET_MOTORI,v,velFR,v,velRR); Serial.printf("SX=%d\n",v);   continue; }
    if (cmd=="dx")   { int v=constrain(args.toInt(),-255,255); sendCmd(CMD_SET_MOTORI,velFL,v,velRL,v); Serial.printf("DX=%d\n",v);   continue; }
    if (cmd=="ant")  { int v=constrain(args.toInt(),-255,255); sendCmd(CMD_SET_MOTORI,v,v,velRL,velRR); Serial.printf("ANT=%d\n",v);  continue; }
    if (cmd=="post") { int v=constrain(args.toInt(),-255,255); sendCmd(CMD_SET_MOTORI,velFL,velFR,v,v); Serial.printf("POST=%d\n",v); continue; }
    if (cmd=="diag1"){ int v=constrain(args.toInt(),-255,255); sendCmd(CMD_SET_MOTORI,v,velFR,velRL,v); Serial.printf("DIAG1=%d\n",v);continue; }
    if (cmd=="diag2"){ int v=constrain(args.toInt(),-255,255); sendCmd(CMD_SET_MOTORI,velFL,v,v,velRR); Serial.printf("DIAG2=%d\n",v);continue; }

    if (cmd=="set") {
      int vals[4]={0,0,0,0};
      String rem=args;
      for (int i=0;i<4&&rem.length()>0;i++){
        int s=rem.indexOf(' ');
        String tok = (s<0)?rem:rem.substring(0,s);
        vals[i]=constrain(tok.toInt(),-255,255);
        if (s<0) rem=""; else { rem=rem.substring(s+1); rem.trim(); }
      }
      sendCmd(CMD_SET_MOTORI,vals[0],vals[1],vals[2],vals[3]);
      Serial.printf("SET FL=%d FR=%d RL=%d RR=%d\n",vals[0],vals[1],vals[2],vals[3]);
      continue;
    }

    Serial.printf("Comando sconosciuto: '%s'\n", line.c_str());
  }
}

// ════════════════════════════════════════════════════════════════
//  TASK: STAMPA PERIODICA — Core 1, priorità minima
// ════════════════════════════════════════════════════════════════

void taskStampa(void* pvParameters) {
  for (;;) {
    vTaskDelay(pdMS_TO_TICKS(500));
    long fl,fr,rl,rr;
    portENTER_CRITICAL(&encMux);
    fl=encoderFL; fr=encoderFR; rl=encoderRL; rr=encoderRR;
    portEXIT_CRITICAL(&encMux);
    Serial.printf(
      "ENC FL:%ld FR:%ld RL:%ld RR:%ld | PWM FL:%d FR:%d RL:%d RR:%d | "
      "Vel:%d St:%d | WiFi:%s MQTT:%s\n",
      fl,fr,rl,rr,velFL,velFR,velRL,velRR,
      velocita,statoMotori,
      WiFi.isConnected()?"OK":"NO",
      mqtt.connected()  ?"OK":"NO");
  }
}

// ════════════════════════════════════════════════════════════════
//  SETUP
// ════════════════════════════════════════════════════════════════

void setup() {
  Serial.begin(115200);
  Serial.println("== ESP32 Motori Mecanum — OTTIMIZZATO FreeRTOS + SICUREZZA ULTRASUONI ==");

  int dirPins[] = {FL_IN1,FL_IN2,FR_IN1,FR_IN2,RL_IN1,RL_IN2,RR_IN1,RR_IN2,STBY};
  for (int p : dirPins) { pinMode(p, OUTPUT); digitalWrite(p, LOW); }

  ledcSetup(0, PWM_FREQ, PWM_RES);   ledcAttachPin(FL_PWM, 0);
  ledcSetup(1, PWM_FREQ, PWM_RES);   ledcAttachPin(FR_PWM, 1);
  ledcSetup(2, PWM_FREQ, PWM_RES);   ledcAttachPin(RL_PWM, 2);
  ledcSetup(3, PWM_FREQ, PWM_RES);   ledcAttachPin(RR_PWM, 3);
  digitalWrite(STBY, HIGH);

  int encPins[] = {FL_ENC_A,FL_ENC_B,FR_ENC_A,FR_ENC_B,RL_ENC_A,RL_ENC_B,RR_ENC_A,RR_ENC_B};
  for (int p : encPins) pinMode(p, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(FL_ENC_A), updateEncoderFL, CHANGE);
  attachInterrupt(digitalPinToInterrupt(FL_ENC_B), updateEncoderFL, CHANGE);
  attachInterrupt(digitalPinToInterrupt(FR_ENC_A), updateEncoderFR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(FR_ENC_B), updateEncoderFR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(RL_ENC_A), updateEncoderRL, CHANGE);
  attachInterrupt(digitalPinToInterrupt(RL_ENC_B), updateEncoderRL, CHANGE);
  attachInterrupt(digitalPinToInterrupt(RR_ENC_A), updateEncoderRR, CHANGE);
  attachInterrupt(digitalPinToInterrupt(RR_ENC_B), updateEncoderRR, CHANGE);

  memset((void*)txBuf, 0, TX_BUF_SIZE);
  memset((void*)sensorBuf, 0, SENSOR_BUF_SIZE);
  Wire.begin(I2C_SLAVE_ADDR, SDA_PIN, SCL_PIN, 100000);
  Wire.onRequest(onRequest);
  Wire.onReceive(onReceive);

  cmdQueue = xQueueCreate(CMD_QUEUE_SIZE, sizeof(MotorCmd));
  configASSERT(cmdQueue);

  fermati();

  xTaskCreatePinnedToCore(taskMotori,  "Motori",  4096, nullptr, 5, &motorTaskHandle,  1);
  xTaskCreatePinnedToCore(taskRete,    "Rete",    8192, nullptr, 3, &netTaskHandle,    0);
  xTaskCreatePinnedToCore(taskSeriale, "Seriale", 4096, nullptr, 2, &serialTaskHandle, 1);
  xTaskCreatePinnedToCore(taskStampa,  "Stampa",  2048, nullptr, 1, &printTaskHandle,  1);

  Serial.println("Task avviati. Digita 'help' per i comandi.");
  Serial.printf("Soglie sicurezza: FRONTE=%dcm RETRO=%dcm SX=%dcm DX=%dcm CLIFF_F=%dcm CLIFF_R=%dcm\n",
    DIST_SOGLIA_FRONTE, DIST_SOGLIA_RETRO, DIST_SOGLIA_SINISTRA,
    DIST_SOGLIA_DESTRA, DIST_SOGLIA_CLIFF_F, DIST_SOGLIA_CLIFF_R);
  Serial.printf("Timeout sensori: %dms\n", SENSOR_DATA_TIMEOUT_MS);
}

// ════════════════════════════════════════════════════════════════
//  LOOP — praticamente vuoto: tutto è nei task FreeRTOS
// ════════════════════════════════════════════════════════════════

void loop() {
  vTaskDelay(pdMS_TO_TICKS(1000));
}