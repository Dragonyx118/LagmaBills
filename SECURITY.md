# SECURITY.md — LagmaBills

## Project Scope
LagmaBills is an open-source home rescue/surveillance robot, distributed under
the **Hippocratic License 3.0**. This policy describes how to report
vulnerabilities and what ethical/security limits apply to the use of the
software and firmware in this repository.

## Supported Versions
| Component                | Supported |
|---------------------------|:---------:|
| ESP32 firmware (motors)   | ✅ latest release on `main` |
| ESP32 firmware (sensors)  | ✅ latest release on `main` |
| Raspberry Pi software     | ✅ latest release on `main` |
| MAUI app / website         | ✅ latest release on `main` |
| Older versions              | ❌ not patched |

## Reporting a Vulnerability
If you find a vulnerability (e.g. plaintext MQTT/WiFi credentials, unauthenticated
access to I2C/MQTT bridges, an exploit in the web viewer, a flaw in the drone
bridge):

1. **Do not open a public issue.**
2. Write directly to: `[insert team/maintainer contact]`.
3. Include: affected component, steps to reproduce, potential impact.
4. You will receive a response within 7 days; fixes are prioritized by
   severity (unauthorized remote access to motors/arm > local data leaks >
   minor bugs).

## Usage Limits Imposed by the License
This project is licensed **exclusively** for uses compatible with the
Hippocratic License 3.0 (clause 3.1). In particular, anyone who forks,
distributes, or integrates this code **may not**:

- use it for military activities (3.1.13);
- supply it to law enforcement agencies or entities that enter into contracts
  with them (3.1.14);
- use it for mass surveillance by government agencies or multinational
  corporations (3.1.12);
- use it to violate the privacy, property, or fundamental rights of people
  monitored by the robot's camera/microphones (3.1.5, 3.1.8, 3.1.9);
- use it to discriminate, harm the environment, or violate workers' rights
  along the supply chain (3.1.5, 3.1.11, 3.1.15, 3.1.16).

Failure to comply with these points results in automatic termination of the
license (sec. 7.1 and 7.3) and the possibility for harmed parties to take
legal action (sec. 4).

## Security Best Practices for Repo Users/Forkers
- **WiFi/MQTT credentials**: never commit real SSIDs/passwords (see the
  hardcoded defaults in the ESP32 firmware — these must be replaced via NVS
  before deployment, not left in the code).
- **MQTT broker**: expose the broker only on the local network/VPN (e.g.
  Tailscale), never directly on the internet without authentication/TLS.
- **Camera streaming (MJPEG)**: the development Flask server
  (`codiceRaspCam.txt`) must not be exposed publicly — consider authentication
  or a VPN tunnel, since the video feed directly touches the privacy of people
  being filmed (see constraint 3.1.8 above).
- **Drone bridge (`testDroneMQTTsecure.py`)**: the automatic landing watchdog
  must always stay active; do not disable it in production.
- **I2C/serial**: motor commands over serial/I2C are not authenticated —
  physical/network access to the bus must be restricted.

## Responsible Disclosure
Vulnerabilities will be made public (changelog/release notes) only after a
patch has been released, unless otherwise agreed with the reporter.
