# Contributing a LagmaBills

Grazie per l'interesse verso LagmaBills! Questo documento spiega come proporre
modifiche al firmware ESP32, al software del Raspberry Pi, all'app o al sito.

## Prima di iniziare
- Leggi il [Code of Conduct](./CODE_OF_CONDUCT.md) e la [Security Policy](./SECURITY.md).
- Il progetto è distribuito sotto **Hippocratic License 3.0**: ogni contributo
  (codice, firmware, documentazione) sarà rilasciato sotto la stessa licenza
  (vedi sez. 5.2–5.3 e 8.3 "Copyleft" della licenza). Non proporre contributi
  pensati per usi vietati dalla licenza (militare, sorveglianza di massa, law
  enforcement, ecc.).

## Struttura del progetto
- `esp32_motori_seriale2.ino` — firmware motori Mecanum (I2C slave 0x08, seriale
  comandi, WiFi/MQTT).
- `esp32_sensori_seriale.ino` — firmware sensori/servo braccio (I2C slave 0x09,
  PCA9685, MPU6050, ultrasuoni).
- script Python sul Raspberry Pi — odometria, occupancy grid, navigazione,
  viewer web, bridge drone, GPS, wakeword.
- app/sito — vedi repo separati collegati nel progetto.

## Come contribuire

### Segnalare bug
Apri una issue con:
- componente coinvolto (firmware motori/sensori, script Pi, app, sito),
- comportamento atteso vs osservato,
- log seriali/MQTT se disponibili,
- hardware/versione (es. ESP32 dev board, Raspberry Pi model).

### Proporre modifiche (Pull Request)
1. Fai fork del repo e crea un branch descrittivo (`fix/encoder-fl`,
   `feat/cliff-sensor-tuning`, ecc.).
2. Per il **firmware ESP32**: testa su hardware reale prima della PR quando
   possibile; se tocchi i buffer I2C (TX_BUF_SIZE, offset), documenta il nuovo
   layout nel commento in testa al file, come già fatto per i buffer esistenti.
3. Per gli **script Python sul Pi**: mantieni la convenzione dei topic MQTT già
   in uso (`robot/motori/cmd`, `robot/sensori/distanze`, `robot/odometria`,
   ecc.) — non rinominarli senza discuterne prima, altri moduli dipendono da
   questi nomi.
4. Non committare **mai** credenziali reali (SSID/password WiFi, broker MQTT
   con IP pubblici, token). Usa placeholder come già fatto nei default del
   firmware.
5. Scrivi commit message chiari (va bene anche in italiano, come nel resto del
   codice).
6. Apri la PR descrivendo cosa cambia e perché; linka la issue correlata se c'è.

### Stile del codice
- Firmware ESP32 (.ino): segui lo stile esistente — blocchi commentati con
  intestazioni `════...`, prototipi dichiarati in cima, costanti in `#define`.
- Python: PEP8 dove ragionevole, commenti/docstring in italiano come negli
  script esistenti (es. `navigator.py`, `occupancyGrid.py`).
- Mantieni coerenti i nomi dei sensori/topic già usati nel sistema (es.
  `FRONTE`, `RETRO`, `SINISTRA`, `DESTRA`, `CLIFF_F`, `CLIFF_R`).

### Sicurezza
Se la modifica tocca aspetti di sicurezza (credenziali, esposizione di rete,
streaming camera, bridge drone), leggi prima [SECURITY.md](./SECURITY.md) e
segui le indicazioni lì riportate (no broker esposti senza VPN, watchdog drone
sempre attivo, ecc.).

## Licenza dei contributi
Contribuendo a questo repository accetti che il tuo contributo sia distribuito
sotto Hippocratic License 3.0, alle stesse condizioni del resto del progetto.
