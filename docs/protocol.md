# The Gicisky BLE protocol

What this project knows about the protocol, from reading [hass-gicisky](https://github.com/eigger/hass-gicisky) and checking it against a 4.2" tag. Implementations: `src/epaper_studio/gicisky/` (Python, Bleak) and `src/epaper_studio/web/static/js/webble.js` (browser, Web Bluetooth). Both must stay in step.

## Advertisement

Tags sleep most of the time and wake briefly to advertise. The advert carries manufacturer data with company id **`0x5053`** and 5 bytes:

| Byte | Meaning |
|---|---|
| 0 | model id, low byte |
| 1 | battery voltage × 10 (`0x1e` = 3.0 V) |
| 2–3 | firmware, big endian (`81 01` = `0x8101`) |
| 4 | model id, high byte |

`model_id = ((b4 << 8) | b0) & 0x3FFF`; `hardware = (b4 << 8) | b0`.

## GATT

Service **`fef0`** with two characteristics, sorted by UUID:

- **`fef1`**: commands are written here; replies arrive as notifications on the same characteristic.
- **`fef2`**: image data.

All writes are *write without response*. A block is 4 + 240 bytes, so the ATT MTU must be at least **247** (BlueZ negotiates it automatically).

## Upload

| Step | Written | Reply (notification on `fef1`) |
|---|---|---|
| Ready? | `01` → `fef1` | `01 f4 00` |
| Size | `02 <size u32 LE> 00 00 00` → `fef1` | `02 …` |
| Start | `03` → `fef1` | `05 00 <part u32 LE>` (part 0) |
| Block | `<part u32 LE><240 bytes>` → `fef2` | `05 00 <next u32 LE>` |

The tag drives the transfer: it may ask for the same block again if it was corrupted. The upload is complete when the requested part satisfies `part × 240 ≥ size`, or when the reply is anything other than `05 00 …`. After disconnecting, the tag refreshes the panel (about 15 s on panels with red) and goes back to sleep.

The client waits about a second after subscribing to notifications before sending `01`; the tag needs the time.

## Image format

For the black/white/red panels without compression (e.g. `0x004B`):

1. Apply the model's transform (rotation, mirroring; TFT models halve the width and double the height).
2. **Plane 1**, black/white: one bit per pixel, rows top to bottom, MSB = leftmost pixel, **`1` = white**, `0` = ink.
3. **Plane 2**, red: same layout, **`1` = red**. Red pixels are `0` in plane 1.
4. Concatenate. A 400×300 panel gives 15,000 + 15,000 = 30,000 bytes = 125 blocks.

Four-colour panels use 2 bits per pixel (`00` black, `01` white, `10` yellow, `11` red). Some models compress the planes; the 7.5" and 10.2" panels use QuickLZ, which is not implemented here.

## Web Bluetooth notes

- `requestDevice` filters on manufacturer data `0x5053` (and the `NEMR` name prefix) and asks for the optional service `0xfef0`.
- The browser does not expose the MTU; Chrome on Android negotiates a large one by itself. If a 244-byte write is rejected, the error says so.
- The model is read with `watchAdvertisements()` where the browser offers it; otherwise the user picks it once and it is saved with the device.
- `navigator.bluetooth.getDevices()` lets the page reuse a tag the user already allowed without showing the chooser again.
