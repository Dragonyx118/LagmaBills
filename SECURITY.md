# Security Policy — LagmaBills

## Ambito del progetto
LagmaBills è un robot di salvataggio/sorveglianza domestica open source, distribuito
sotto **Hippocratic License 3.0**. Questa policy descrive come segnalare
vulnerabilità e quali limiti etici/di sicurezza si applicano all'uso del software
e del firmware in questo repository.

## Versioni supportate
| Componente              | Supportato |
|--------------------------|:----------:|
| Firmware ESP32 (motori)  | ✅ ultima release su `main` |
| Firmware ESP32 (sensori) | ✅ ultima release su `main` |
| Software Raspberry Pi    | ✅ ultima release su `main` |
| App MAUI / sito web       | ✅ ultima release su `main` |
| Versioni precedenti       | ❌ non patchate |

## Segnalazione di una vulnerabilità
Se trovi una vulnerabilità (es. credenziali MQTT/WiFi in chiaro, accesso non
autenticato ai bridge I2C/MQTT, exploit sul web viewer, falla nel bridge del drone):

1. **Non aprire una issue pubblica.**
2. Scrivi direttamente a: `[inserire email/contatto del team]`.
3. Includi: componente coinvolto, passi per riprodurre, impatto potenziale.
4. Riceverai un riscontro entro 7 giorni; la correzione viene prioritizzata in
   base alla gravità (accesso remoto non autorizzato ai motori/braccio > fughe di
   dati locali > bug minori).

## Limiti d'uso previsti dalla licenza
Questo progetto è concesso in licenza **esclusivamente** per usi compatibili con
la Hippocratic License 3.0 (clausola 3.1). In particolare, chiunque forka,
distribuisce o integra questo codice **non può**:

- impiegarlo per attività militari (3.1.13);
- fornirlo a forze dell'ordine o enti che stipulano contratti con esse (3.1.14);
- usarlo per sorveglianza di massa da parte di enti governativi o multinazionali (3.1.12);
- utilizzarlo per violare privacy, proprietà o diritti fondamentali delle persone
  monitorate dalla telecamera/microfoni del robot (3.1.5, 3.1.8, 3.1.9);
- impiegarlo per discriminare, danneggiare l'ambiente o violare i diritti dei
  lavoratori lungo la filiera (3.1.5, 3.1.11, 3.1.15, 3.1.16).

Il mancato rispetto di questi punti comporta la decadenza automatica della
licenza (sez. 7.1 e 7.3) e la possibilità per le parti lese di agire legalmente
(sez. 4).

## Buone pratiche di sicurezza per chi usa/clona il repo
- **Credenziali WiFi/MQTT**: non committare mai SSID/password reali (vedi i
  default hardcoded nel firmware ESP32 — vanno sostituiti tramite NVS prima del
  deploy, non lasciati nel codice).
- **MQTT broker**: esporre il broker solo su rete locale/VPN (es. Tailscale),
  mai direttamente su internet senza autenticazione/TLS.
- **Streaming camera (MJPEG)**: il server Flask di sviluppo (`codiceRaspCam.txt`)
  non va esposto pubblicamente — valutare autenticazione o tunnel VPN, dato che
  il feed video tocca direttamente la privacy delle persone riprese (vedi
  vincolo 3.1.8 sopra).
- **Bridge drone (`testDroneMQTTsecure.py`)**: il watchdog di atterraggio
  automatico va sempre mantenuto attivo; non disabilitarlo in produzione.
- **I2C/seriale**: i comandi motori via seriale/I2C non sono autenticati — va
  limitato l'accesso fisico/di rete al bus.

## Divulgazione responsabile
Le vulnerabilità saranno rese pubbliche (changelog/release notes) solo dopo il
rilascio di una patch, salvo diverso accordo con chi segnala.
