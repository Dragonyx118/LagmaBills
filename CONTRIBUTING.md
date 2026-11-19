# Contributing to LagmaBills

Thanks for your interest in LagmaBills! This document explains how to propose
changes to the ESP32 firmware, the Raspberry Pi software, the app, or the
website.

## Before You Start
- Read the [Code of Conduct](./CODE_OF_CONDUCT.md) and the
  [Security Policy](./SECURITY.md).
- The project is distributed under the **Hippocratic License 3.0**: every
  contribution (code, firmware, documentation) will be released under the
  same license (see sec. 5.2–5.3 and 8.3 "Copyleft" of the license). Do not
  propose contributions intended for uses prohibited by the license
  (military, mass surveillance, law enforcement, etc.).

## Project Structure
- `esp32_motori_seriale2.ino` — Mecanum motor firmware (I2C slave 0x08, serial
  commands, WiFi/MQTT).
- `esp32_sensori_seriale.ino` — sensor/arm servo firmware (I2C slave 0x09,
  PCA9685, MPU6050, ultrasonic sensors).
- Python scripts on the Raspberry Pi — odometry, occupancy grid, navigation,
  web viewer, drone bridge, GPS, wakeword.
- app/website — see separate repos linked in the project.

## How to Contribute

### Reporting Bugs
Open an issue with:
- affected component (motor/sensor firmware, Pi scripts, app, website),
- expected vs. observed behavior,
- serial/MQTT logs if available,
- hardware/version (e.g. ESP32 dev board, Raspberry Pi model).

### Proposing Changes (Pull Request)
1. Fork the repo and create a descriptive branch (`fix/encoder-fl`,
   `feat/cliff-sensor-tuning`, etc.).
2. For **ESP32 firmware**: test on real hardware before the PR whenever
   possible; if you touch the I2C buffers (TX_BUF_SIZE, offsets), document the
   new layout in the header comment of the file, as already done for the
   existing buffers.
3. For **Python scripts on the Pi**: keep the existing MQTT topic naming
   conventions (`robot/motori/cmd`, `robot/sensori/distanze`,
   `robot/odometria`, etc.) — do not rename them without discussing it first,
   other modules depend on these names.
4. **Never** commit real credentials (WiFi SSID/password, MQTT broker with
   public IPs, tokens). Use placeholders as already done in the firmware
   defaults.
5. Write clear commit messages (Italian is fine too, as in the rest of the
   codebase).
6. Open the PR describing what changes and why; link the related issue if
   there is one.

### Code Style
- ESP32 firmware (.ino): follow the existing style — blocks commented with
  `════...` headers, prototypes declared at the top, constants as `#define`.
- Python: follow PEP8 where reasonable; comments/docstrings can stay in
  Italian as in the existing scripts (e.g. `navigator.py`,
  `occupancyGrid.py`).
- Keep the sensor/topic names already used in the system consistent (e.g.
  `FRONTE`, `RETRO`, `SINISTRA`, `DESTRA`, `CLIFF_F`, `CLIFF_R`).

### Security
If the change touches security-related aspects (credentials, network
exposure, camera streaming, drone bridge), read
[SECURITY.md](./SECURITY.md) first and follow the guidance there (no broker
exposed without a VPN, drone watchdog always active, etc.).

## License of Contributions
By contributing to this repository you agree that your contribution will be
distributed under the Hippocratic License 3.0, under the same terms as the
rest of the project.
