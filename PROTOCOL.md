# Flitsmeister DOT BLE protocol

Based on the Flitsmeister Android app 15.1.1 and the Dot firmware
1.0.14 bundled inside it.

## Device

- Nordic nRF54L15 (board `nrf54l15dk`), Zephyr 4.0.99, MCUboot, C++ application
- 8 LEDs, 1 W speaker, two buttons (firmware calls them left and right), accelerometer
- Advertises as `FM DOT` with a random static Bluetooth address
- A retail device reports model number `nrf54l15` and firmware and software
  revision `2.9.0`, newer than the 1.0.14 bundled in the app
- Firmware version string in 1.0.14: `1.0.14-HEAD+20260130.162802.f6db73e`

## GATT services and characteristics

All custom UUIDs share the base `2783xxxx-33ee-9b9c-124d-109d6b0c0a91`.

| Service | UUID | Characteristic | UUID | Properties |
|---|---|---|---|---|
| FM DOT | `27831530-33ee-9b9c-124d-109d6b0c0a91` | Animation | `27831001-33ee-9b9c-124d-109d6b0c0a91` | write |
| | | Button events | `27831002-33ee-9b9c-124d-109d6b0c0a91` | indicate |
| | | Speech language | `27831003-33ee-9b9c-124d-109d6b0c0a91` | read |
| | | Volume | `27831004-33ee-9b9c-124d-109d6b0c0a91` | read, write |
| | | Brightness | `27831005-33ee-9b9c-124d-109d6b0c0a91` | read, write |
| | | LED rotation | `27831006-33ee-9b9c-124d-109d6b0c0a91` | read, write |
| | | Motion | `27831580-33ee-9b9c-124d-109d6b0c0a91` | read, notify |
| Battery | `0x180F` | Battery level | `0x2A19` | read, notify |
| | | Charging state | `0x2BED` | read, notify |
| Device information | `0x180A` | Manufacturer name | `0x2A29` | read |
| | | Model number | `0x2A24` | read |
| | | Serial number | `0x2A25` | read |
| | | Firmware revision | `0x2A26` | read |
| | | Software revision | `0x2A28` | read |
| SMP | `8D53DC1D-1DB7-4CD3-868B-8A527460AA84` | SMP | `DA2E7828-FBCE-4E01-AE9E-261174997C48` | write, notify |

Every UUID above also appears in the firmware binary's GATT table, so the device side matches the app.

The SMP characteristic UUID differs from stock Zephyr (`DA2E988E-F315-4E01-AE9E-261174997C48`). The Nordic Secure DFU service `0xFE59` appears in the app too, but only for the older FM One and FM Two devices.

## Advertising and discovery

- Advertised device name: `FM DOT`
- Advertised service UUID: `27831530-33ee-9b9c-124d-109d6b0c0a91`
- Manufacturer specific data with company ID 4012 (`0x0FAC`) and an empty
  payload, purpose unknown
- The app accepts the Dot for connection at RSSI above -85 dBm
- Manufacturer specific data, company ID 871 (`0x0367`), identifies the other devices: bytes 1-2 equal `04 04` for FM One, `0C 28` for FM Two. The Dot is matched on name instead
- The Dot sleeps while parked and advertises only in bursts after
  accelerometer motion, so a scanner must keep scanning while it connects
- The firmware also builds an iBeacon advertisement set. The app ignores it for the Dot. Its purpose is unknown, possibly in-car presence detection

## Animation characteristic

Write to `27831001-33ee-9b9c-124d-109d6b0c0a91`, 10 bytes, write with response. The app queues writes and sends them one at a time. It skips a write when the new packet is identical to the previous one and the type is progression top to bottom.

### Packet layout

| Offset | Size | Field | Meaning |
|---|---|---|---|
| 0 | 1 | type | animation type, see below |
| 1 | 4 | color | ARGB, big-endian, `00 00 00 00` when the animation has no color |
| 5 | 1 | value | number of LEDs to light, 1 to 8, for progression types. Alert packets from the app carry 0 to 4 here, purpose unconfirmed |
| 6 | 1 | primary sound | sound ID, 0 for none |
| 7 | 1 | secondary sound | sound ID, 0 for none |
| 8 | 1 | end behavior | what happens after the alert, see below |
| 9 | 1 | cut off | 0 stops the running animation, 1 lets it continue |

### Types

| Value | Name | Behavior |
|---|---|---|
| 0 | none | |
| 1 | mid to outward and breathe | LEDs light from the middle outward, then pulse |
| 2 | wave | |
| 3 | progression top to bottom | value LEDs light in sequence, shows approach progress |
| 4 | fade out | clears the current animation |
| 5 | progression blink | like 3 but blinking, used for overspeed |
| 6 | blink down up and mid to out | |
| 7 | flash and static | |
| 8 | reporting | shown while a button is held to file a report |
| 9 | bluetooth connected | |
| 10 | waiting to drive | |
| 11 | start driving | startup animation |

### Colors

`Color.parseColor` semantics, so alpha is always `FF`.

| Name | RGB hex | Bytes 1-4 |
|---|---|---|
| DANGER | `#FF0505` | `FF FF 05 05` |
| AVG_SPEED_CHECK | `#0000CE` | `FF 00 00 CE` |
| SPEED_TRAP | `#00284A` | `FF 00 28 4A` |
| SPEED_CAM | `#02F2FF` | `FF 02 F2 FF` |
| WHITE | `#FFFFFF` | `FF FF FF FF` |
| PRO | `#8000FF` | `FF 80 00 FF` |
| SUCCESS | `#003B09` | `FF 00 3B 09` |
| WARNING | `#FF3000` | `FF FF 30 00` |

### End behavior

| Value | Name | Meaning |
|---|---|---|
| 0 | fade out | LEDs fade out when the alert ends |
| 1 | rate | a button press rates the alert and ends it |
| 2 | progression | |

### Sound IDs

The speech IDs play from the voice in the firmware image. A live DOT on firmware 2.9.0 with the Dutch voice plays nothing for 48, 51, 52, 53, 55, 56, 57, 58, 59 and 61 and reports no error. Every other ID in the table plays.

| ID | Sound | ID | Sound |
|---|---|---|---|
| 0 | none | 38 | speech: accident |
| 1 | sfx: error | 39 | speech: stationary vehicle |
| 2 | sfx: exit | 40 | speech: object on road |
| 3 | sfx: sound logo short | 41 | speech: emergency vehicle |
| 4 | sfx: confirm | 42 | speech: ambulance |
| 5 | sfx: ambulance | 43 | speech: fire truck |
| 6 | sfx: emergency vehicle | 44 | speech: slippery road |
| 7 | sfx: end of report | 45 | speech: bumpy road |
| 8 | sfx: police hotspot | 46 | speech: animal on the road |
| 9 | sfx: reduce speed | 47 | speech: person on the road |
| 10 | sfx: avg speed check start | 48 | speech: dangerous situation 2 |
| 11 | sfx: safety notification | 49 | speech: impact attenuator |
| 12 | sfx: speed camera | 50 | speech: text car |
| 13 | sfx: avg speed check end | 51 | speech: dangerous situation 3 |
| 15 | sfx: wrong direction | 52 | speech: reindeer on road |
| 16 | sfx: wrong way driver | 53 | speech: moose nearby |
| 30 | speech: traffic jam | 54 | speech: poor visibility |
| 31 | speech: roadworks | 55 | speech: snow on road |
| 32 | speech: speed trap | 56 | speech: strong wind |
| 33 | speech: speed cam | 57 | speech: ice on road |
| 34 | speech: avg speed check | 58 | speech: reindeer near road |
| 35 | speech: end of avg speed check | 59 | speech: railway crossing |
| 36 | speech: hotspot | 60 | speech: wrong way driver |
| 37 | speech: dangerous situation 1 | 61 | speech: wrong way driving |
| | | 62 | speech: bridge open |
| | | 63 | speech: traffic camera |
| | | 64 | speech: lane closed |
| | | 65 | speech: left lane closed |
| | | 66 | speech: right lane closed |

Sound slots 14 and 17 to 29 are unused.

### Packets the app sends

Layout per row: type, color, value, primary, secondary, end, cut off.

| Situation | Packet |
|---|---|
| Startup after connect | `0B FF 00 28 4A 00 00 00 00 00` |
| Fade out, stop everything | `04 00 00 00 00 00 00 00 00 00` |
| Fade out, keep prior state | `04 00 00 00 00 00 00 00 00 01` |
| Speed trap alert | `01 FF 00 28 4A 03 0C 20 01 00` |
| Speed camera alert | `01 FF 02 F2 FF 03 0C 21 01 00` |
| Traffic camera alert | `01 FF 02 F2 FF 03 3F 00 01 00` |
| Average speed check start | `01 FF 00 00 CE 02 0A 22 01 00` |
| Average speed check end | `02 FF 00 00 CE 00 0D 23 00 00` |
| Traffic jam start | `01 FF FF 30 00 02 0B 1E 00 00` |
| Traffic jam end | `02 FF FF 30 00 00 07 00 00 00` |
| Police hotspot | `01 FF 80 00 FF 03 08 24 01 00` |
| Roadworks | `01 FF FF 30 00 02 0B 1F 01 00` |
| Incident, general | `01 FF FF 05 05 02 0B <speech> 01 00` |
| Lane closure | `01 FF FF 05 05 03 0B <speech> 00 00` |
| Ambulance | `06 FF 00 28 4A 04 05 2A 00 00` |
| Fire truck | `06 FF 00 28 4A 04 06 2B 00 00` |
| Police | `01 FF 00 28 4A 04 06 00 00 00` |
| Emergency vehicle | `01 FF FF 05 05 04 06 29 00 00` |
| Railway crossing | `01 FF FF 05 05 00 0B 3B 00 00` |
| Wrong way driving | `07 FF FF 05 05 00 0F 00 00 00` |
| Wrong way driver | `01 FF FF 05 05 02 10 3C 01 00` |
| Approach progress | `03 <color> <leds 1-8> 00 00 00 01` |
| Overspeed | `05 FF FF 05 05 <leds 1-8> 09 00 00 00` |
| Reporting, button held | `08 00 00 00 00 00 04 00 00 00` |
| Brightness sample | `03 FF FF FF FF 08 00 00 00 01` |
| Orientation sample | `01 FF 00 28 4A 00 00 00 00 01` |
| Firmware updating | `02 FF FF FF FF 00 00 00 00 00` |

When an alert is not rateable, byte 8 is `00` instead of `01`.

## Button events

Indication on `27831002-33ee-9b9c-124d-109d6b0c0a91`, 2 bytes. Byte 0 holds the state of the red button, byte 1 the blue button. Values: 0 idle, 1 pushed, 2 released. The device sends one indication per event and sets the other button's byte to 0.

| Event | Payload |
|---|---|
| Red pushed | `01 00` |
| Red released | `02 00` |
| Blue pushed | `00 01` |
| Blue released | `00 02` |

The LED rotation setting also swaps the buttons. Seen from the front with the USB-C port at the bottom, the right button reports as red and the left as blue with rotation 0 (normal). With rotation 1 (upside down) the left button reports as red and the right as blue.

App behavior on a push, timed from the pushed indication:

1. At 250 ms it writes the reporting animation, so the driver sees that the hold registers
2. At 1000 ms total it sends the report to the Flitsmeister backend: red button files a speed trap, blue button files a dangerous situation
3. A release before 1000 ms cancels the report
4. A release before 250 ms counts as a short press: the app shows the battery level as a progress animation in green above 38 percent, orange above 13 percent, red below, and emits a button event to rate or dismiss an active alert

## Settings characteristics

All writes are 1 byte, write with response.

| Characteristic | Values |
|---|---|
| Volume `...1004` | 0 silent, 1 low, 2 normal, 3 hard |
| Brightness `...1005` | 10 to 100 in steps of 10. The app maps unknown values to 100 on read |
| LED rotation `...1006` | 0 normal, 1 upside down. Flips the LED ring so mounting orientation does not invert the patterns |

After a brightness or rotation write the app reads the characteristic back and plays the matching sample animation for 2 seconds.

### Speech language

The speech language characteristic `...1003` is read only on firmware 2.9.0. A write with response fails with the GATT error Write Not Permitted (`0x03`) and the link stays up. A DOT with the Dutch voice reads `01 01`.

| Byte | Meaning |
|---|---|
| 0 | Language: 0 English, 1 Dutch, 2 German, 3 French |
| 1 | Unconfirmed, likely the voice. Compare the value after flashing the other voice to confirm |

The voice is part of the firmware image. To change the language or the voice (male or female) the app downloads `{device}-{version}-{language}-{voice}-dfu.zip`, built from the `firmware_template` and `voices` of the update manifest, and flashes it over MCUmgr. The app offers Dutch, English, French, German and Spanish.

## Status characteristics

| Characteristic | Format |
|---|---|
| Battery level `0x2A19` | 1 byte, 0 to 100 percent |
| Charging state `0x2BED` | 3 or more bytes, the app reads byte 2: 0 consuming, 1 charging, 2 charging done |
| Motion `...1580` | 1 byte: 0 parked, any other value driving. Driven by the accelerometer. The device sleeps while parked and wakes on motion |
| Serial number `0x2A25` | raw bytes, redacted in captures. The app hashes them with `UUID.nameUUIDFromBytes` (MD5) and uppercases the result |

Bytes 0 and 1 of the charging state are unknown. A device on USB power
at 69 percent sends `00 a3 02` for charging done.

## Connection sequence

1. Connect without autoConnect
2. Discover services
3. Subscribe: button events as indication (CCCD `00 02`), battery, charging and motion as notifications (CCCD `01 00`)
4. Write the volume stored in the app preferences
5. Read battery level, charging state, manufacturer name, model number, serial number, firmware revision, software revision, motion
6. Write the startup animation

The device drops a client that only subscribes and reads after about
4 seconds. Writes keep the link up, which is why the app writes the
volume and the startup animation right after connecting. The device
notifies the battery level periodically while connected.

## Firmware update

The Dot updates over MCUmgr image upload, not Nordic DFU. The app connects to the SMP service, uploads `build.signed.bin` from the update zip, and the device reboots into the new MCUboot image. The update zips contain a `manifest.json` with the board and SoC and the signed binary.

The app bundles three versions: `dot_log_106.zip` (1.0.6), `dot_fw_1012.zip` (1.0.12), `dot_fw_1014.zip` (1.0.14), stored in the APK at `res/raw/`. The update manifest is fetched from `https://cdn.flitsmeister.app/firmware/android` in an app-specific encrypted format. Firmware packages carry per-language voice options. The selected speech language and gender decide which package the app downloads.
