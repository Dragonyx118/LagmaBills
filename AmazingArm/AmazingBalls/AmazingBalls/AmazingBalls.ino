#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_PWMServoDriver pca = Adafruit_PWMServoDriver(0x40);

// Calibrazione pulse width in tick (a 50Hz)
// SG90:    min~150, max~600
// MG996R:  min~150, max~600  (quasi uguale)
#define SERVO_MIN  150
#define SERVO_MAX  600

// Posizioni correnti di ogni servo (in gradi)
int pos[6] = {90, 90, 90, 90, 90, 120};

// Converte gradi in tick PCA9685
int degreesToTick(int degrees) {
  return map(degrees, 0, 180, SERVO_MIN, SERVO_MAX);
}

// Muove un servo a una posizione assoluta
void setServo(uint8_t channel, int degrees) {
  degrees = constrain(degrees, 0, 180);
  pos[channel] = degrees;
  pca.setPWM(channel, 0, degreesToTick(degrees));
}

// Muove un servo di un delta rispetto alla posizione attuale
void moveServo(uint8_t channel, int delta) {
  setServo(channel, pos[channel] + delta);
}

void setup() {
  Serial.begin(9600);
  Wire.begin(21, 22);  // SDA, SCL su ESP32
  pca.begin();
  pca.setOscillatorFrequency(27000000);
  pca.setPWMFreq(50);  // 50Hz per tutti i servo

  delay(100);

  // Posizioni iniziali
  setServo(0, 90);
  setServo(1, 90);
  setServo(2, 90);
  setServo(3, 90);
  setServo(4, 90);
  setServo(5, 120);
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    /* Formato comando: "C0+10" -> canale 0, avanti 10 gradi
                        "C3-5"  -> canale 3, indietro 5 gradi
                        "C1=45" -> canale 1, vai a 45 gradi (assoluto)
    */
    if (cmd.startsWith("C") && cmd.length() >= 4) {
      int channel = cmd.substring(1, 2).toInt();

      if (channel >= 0 && channel <= 5) {
        char type = cmd.charAt(2);  // '+', '-' o '='
        int value = cmd.substring(3).toInt();

        if (type == '+') {
          moveServo(channel, +value);
        } else if (type == '-') {
          moveServo(channel, -value);
        } else if (type == '=') {
          setServo(channel, value);
        }

        Serial.print("CH");
        Serial.print(channel);
        Serial.print(" -> ");
        Serial.println(pos[channel]);
      }
    }
  }
}