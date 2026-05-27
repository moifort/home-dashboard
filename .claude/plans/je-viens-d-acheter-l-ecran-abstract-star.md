# Plan : Hello World — XIAO ESP32-S3 + Waveshare e-Paper 10.85"

## Contexte

Avant de coder le dashboard complet, on valide le hardware : afficher "Hello World" sur l'écran Waveshare e-Paper 10.85" (1360x480) piloté par un XIAO ESP32-S3 via dual SPI. Si ça marche → le hardware est validé et on enchaîne sur le projet complet.

## Ce qu'on fait

Un firmware PlatformIO minimal (~300 lignes) qui :
1. Initialise le bus SPI avec les 2 chip selects (CS_M + CS_S)
2. Exécute la séquence d'init du contrôleur e-ink (portée depuis `epd10in85.py`)
3. Remplit l'écran en blanc
4. Affiche "Hello World" au centre

Pas de WiFi, pas de HTTP, pas de Flask — juste ESP32 → SPI → écran.

## Câblage XIAO ESP32-S3 → Waveshare 10.85" HAT

Le HAT Waveshare a un header 40 pins compatible RPi. On connecte 8 signaux + alimentation :

| Signal | Fonction | HAT Pin (RPi) | XIAO Pin | ESP32-S3 GPIO |
|--------|----------|:---:|:---:|:---:|
| MOSI | SPI data | 19 | D10 | 9 |
| SCLK | SPI clock | 23 | D8 | 7 |
| CS_M | Chip select gauche | 24 (CE0) | D1 | 2 |
| CS_S | Chip select droite | 26 (CE1) | D2 | 3 |
| DC | Data/Command | 22 | D3 | 4 |
| RST | Reset | 11 | D0 | 1 |
| BUSY | Busy (input) | 18 | D7 | 44 |
| PWR | Power enable | 12 | D6 | 43 |
| 3.3V | Alimentation | 1 ou 17 | 3V3 | — |
| GND | Masse | 6, 9, 14, 20, 25 | GND | — |

**Important** : le HAT Waveshare s'alimente en 3.3V. Le XIAO ESP32-S3 sort du 3.3V sur sa broche 3V3.

## Structure du projet

```
esp32-display/
├── platformio.ini
├── src/
│   └── main.cpp          # tout dans un seul fichier pour le hello world
```

## Implémentation

### `platformio.ini`

```ini
[env:xiao_esp32s3]
platform = espressif32
board = seeed_xiao_esp32s3
framework = arduino
monitor_speed = 115200
board_build.arduino.memory_type = qio_opi  ; active PSRAM
build_flags = -DBOARD_HAS_PSRAM
```

### `main.cpp` — contenu

**1. Pins + constantes** — le tableau de câblage ci-dessus

**2. Fonctions SPI bas niveau** — portées de `epdconfig.py` :
- `spi_send_M(data, len)` : CS_M LOW → SPI write → CS_M HIGH
- `spi_send_S(data, len)` : CS_S LOW → SPI write → CS_S HIGH
- `send_command_ALL(cmd)` : DC LOW → envoie cmd aux deux contrôleurs
- `send_data_ALL(data)` : DC HIGH → envoie data aux deux contrôleurs

**3. Séquence d'init** — portée de `epd10in85.py` `init()` (l.127-195) :
```
reset() → ReadBusy()
0x4D/0x55, 0xA6/0x38, 0xB4/0x5D, 0xB6/0x80, 0xB7/0x00,
0xF7/0x02, 0xAE/0xA0, 0xE0/0x01, 0x00/[0x9F,0x0D],
0x06/[0x57,0x24,0x28,0x32,0x08,0x48],
0x61/[0x02,0xA8,0x01,0xE0], 0x62/[0x00,0x00,0x00,0x00],
0x60/0x31, 0x50/0x97, 0xE8/0x01,
0x04 → delay 200ms → ReadBusy()
```

**4. `display_full(buf)`** — portée de `epd10in85.py` `display()` (l.410-425) :
```
Pour chaque ligne (0..479) :
  Envoyer buf[ligne*170 .. ligne*170+85] au Master (85 octets = 680 pixels / 8)
  Envoyer buf[ligne*170+85 .. ligne*170+170] au Slave
Puis TurnOnDisplay (cmd 0x12 → delay → ReadBusy)
```

**5. Hello World** :
- Créer un buffer de 81 600 octets (tout à 0xFF = blanc)
- Dessiner "HELLO WORLD" en pixels (font bitmap simple 8x8 ou 16x16 hardcodée)
- Appeler `display_full(buffer)`

**Alternative plus simple pour le texte** : au lieu de coder un font renderer, on peut juste dessiner un rectangle noir ou un pattern de test (damier, barres) pour valider que les deux moitiés de l'écran fonctionnent. Le texte "Hello World" c'est du bonus.

## Vérification

1. **Serial monitor** : logs de chaque étape (init SPI, reset, busy wait, sending data)
2. **Écran blanc** : si l'écran passe au blanc après init → SPI fonctionne
3. **Pattern de test** : moitié gauche = noir, moitié droite = blanc → dual CS fonctionne
4. **Hello World** : texte lisible au centre → tout est validé

## Dépannage courant

- **Écran ne répond pas** : vérifier BUSY pin (doit passer HIGH après init), vérifier PWR (doit être HIGH)
- **Une seule moitié fonctionne** : mauvais câblage CS_M ou CS_S, ou inversion des deux
- **Image décalée/corrompue** : vitesse SPI trop haute (baisser de 4 MHz à 2 MHz) ou mode SPI incorrect

## Suite

Une fois le Hello World validé → on enchaîne sur le plan complet :
1. `server.py` Docker (heure + météo)
2. Firmware WiFi + HTTP fetch du bitmap
3. Plus tard : crypto bot via GraphQL
