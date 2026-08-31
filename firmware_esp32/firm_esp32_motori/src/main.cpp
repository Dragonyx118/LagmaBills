/*
 * ================================================================
 *  ESP32 MOTORI — FIRMWARE SOLO I2C (WiFi/MQTT rimossi)
 *  Latenza comando→motore: < 2ms (tipico) / < 5ms (peggiore)
 *
 *  Il Raspberry Pi è l'UNICO punto di comunicazione con l'esterno.
 *  Questo ESP32 parla SOLO via I2C slave (0x08) col Pi — nessun WiFi,
 *  nessun MQTT, nessuna gestione credenziali/broker. Tutto il traffico
 *  verso controller esterni/dashboard passa dal Pi, che poi scrive
 *  qui via I2C con lo stesso protocollo di sempre (opcode invariati).
 *
 *  ARCHITETTURA (invariata rispetto a prima, solo networking rimosso):
 *
 *  1. DUAL-CORE FreeRTOS
 *     - Core 0: libero (nessun task di rete più necessario)
 *     - Core 1: Motori + Encoder + I2C + Seriale (real-time)
 *
 *  2. CODA COMANDI (xQueueSend/Receive)
 *     - I2C ISR → coda → task motori: latenza < 1ms
 *     - Seriale → coda → task motori: latenza < 2ms
 *
 *  3. SICUREZZA ULTRASUONI (invariata)
 *     - Il Raspberry invia periodicamente i dati sensori via I2C
 *       con comando 0xE0 seguito da 26 byte (buffer ESP32 sensori)
 *     - Se un sensore scende sotto la soglia DIST_SOGLIA_*, i movimenti
 *       nella direzione corrispondente vengono bloccati
 *
 * ────────────────────────────────────────────────────────────────
 *  LATENZE ATTESE (misurate su ESP32 240MHz):
 *  I2C     → motore: < 1ms
 *  Seriale → motore: < 2ms
 * ════════════════════════════════════════════════════════════════
 */

#include <Arduino.h>
#include <Wire.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

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
//  TIPI
// ════════════════════════════════════════════════════════════════

enum DirezioneCmd {
  DIR_AVANTI, DIR_INDIETRO, DIR_SX, DIR_DX,
  DIR_DIAG_AVT_DX, DIR_DIAG_AVT_SX, DIR_DIAG_IND_DX, DIR_DIAG_IND_SX,
  DIR_RUOTA, DIR_NESSUNA
};

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
  CMD_SET_MOTORI,
  CMD_MECANUM,
  CMD_GIRA_ANGOLO,
  CMD_SET_VEL,
  CMD_RESET_ENC,
  CMD_MOTOR_SINGLE,
  CMD_SENSOR_DATA,      // dati sensori dal Pi via I2C 0xE0
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

// ── DATI SENSORI RICEVUTI DAL RASPBERRY (via I2C, non WiFi) ──────
#define SENSOR_BUF_SIZE 26
volatile uint8_t  sensorBuf[SENSOR_BUF_SIZE];
volatile uint32_t lastSensorUpdateMs = 0;
volatile bool     sensorDataValid    = false;

// ── HANDLE RTOS ──────────────────────────────────────────────────
QueueHandle_t cmdQueue;
TaskHandle_t  motorTaskHandle  = nullptr;
TaskHandle_t  serialTaskHandle = nullptr;
TaskHandle_t  printTaskHandle  = nullptr;

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
void printHelp();
void printEncoder();
void printStato();
uint16_t getSensorDist(int idx);
bool distanzaBloccante(uint16_t dist, uint16_t soglia);
bool isDirezioneBlocata(DirezioneCmd dir);

// ════════════════════════════════════════════════════════════════
//  SICUREZZA ULTRASUONI — lettura buffer e logica blocco
// ════════════════════════════════════════════════════════════════

inline uint16_t getSensorDist(int idx) {
  int o = idx * 2;
  portENTER_CRITICAL(&sensorMux);
  uint16_t v = sensorBuf[o] | ((uint16_t)sensorBuf[o+1] << 8);
  portEXIT_CRITICAL(&sensorMux);
  return v;
}

inline bool distanzaBloccante(uint16_t dist, uint16_t soglia) {
  if (soglia == 0)    return false;
  if (dist == 9999)   return false;
  return dist < soglia;
}

bool isDirezioneBlocata(DirezioneCmd dir) {
  if (SENSOR_DATA_TIMEOUT_MS > 0) {
    uint32_t now = millis();
    portENTER_CRITICAL(&sensorMux);
    bool     valido  = sensorDataValid;
    uint32_t lastUpd = lastSensorUpdateMs;
    portEXIT_CRITICAL(&sensorMux);
    if (!valido || (now - lastUpd) > SENSOR_DATA_TIMEOUT_MS) {
      return true;
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
//  HELPER — invio comando alla coda
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

void fermati() { setMotori(0,0,0,0); statoMotori=0; buildTxBuf(); }

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
  setMotoriCorrected(fl,fr,rl,rr);
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
//  ESEGUI COMANDO DAL QUEUE
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

    case CMD_SENSOR_DATA: {
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
//  I2C SLAVE CALLBACKS — UNICO canale di comunicazione col Pi
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

  // ── 0xE0 — dati sensori dal Raspberry (26 byte = buffer sensori) ──
  if (cmd == 0xE0) {
    if (rxLen < (1 + SENSOR_BUF_SIZE)) return;
    MotorCmd mc = {};
    mc.type = CMD_SENSOR_DATA;
    memcpy(mc.strBuf, rxBuf + 1, SENSOR_BUF_SIZE);
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
//  TASK: SERIALE — Core 1, priorità bassa (debug via USB)
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
  portENTER_CRITICAL(&sensorMux);
  bool valido = sensorDataValid;
  uint32_t lastUpd = lastSensorUpdateMs;
  portEXIT_CRITICAL(&sensorMux);
  Serial.printf("Sensori (via I2C dal Pi): %s (ultimo aggiornamento: %lums fa)\n",
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
      "ENC FL:%ld FR:%ld RL:%ld RR:%ld | PWM FL:%d FR:%d RL:%d RR:%d | Vel:%d St:%d\n",
      fl,fr,rl,rr,velFL,velFR,velRL,velRR,
      velocita,statoMotori);
  }
}

// ════════════════════════════════════════════════════════════════
//  SETUP
// ════════════════════════════════════════════════════════════════

void setup() {
  Serial.begin(115200);
  Serial.println("== ESP32 Motori Mecanum — SOLO I2C (WiFi/MQTT rimossi) ==");

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
  xTaskCreatePinnedToCore(taskSeriale, "Seriale", 4096, nullptr, 2, &serialTaskHandle, 1);
  xTaskCreatePinnedToCore(taskStampa,  "Stampa",  2048, nullptr, 1, &printTaskHandle,  1);

  Serial.println("Task avviati. Digita 'help' per i comandi.");
  Serial.printf("Soglie sicurezza: FRONTE=%dcm RETRO=%dcm SX=%dcm DX=%dcm CLIFF_F=%dcm CLIFF_R=%dcm\n",
    DIST_SOGLIA_FRONTE, DIST_SOGLIA_RETRO, DIST_SOGLIA_SINISTRA,
    DIST_SOGLIA_DESTRA, DIST_SOGLIA_CLIFF_F, DIST_SOGLIA_CLIFF_R);
  Serial.printf("Timeout sensori: %dms\n", SENSOR_DATA_TIMEOUT_MS);
  Serial.println("Comunicazione: SOLO I2C 0x08 col Raspberry Pi. Nessun WiFi/MQTT.");
}

// ════════════════════════════════════════════════════════════════
//  LOOP — vuoto, tutto è nei task FreeRTOS
// ════════════════════════════════════════════════════════════════

void loop() {
  vTaskDelay(pdMS_TO_TICKS(1000));
}
