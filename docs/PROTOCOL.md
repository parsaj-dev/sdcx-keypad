# SDCX / SDINNOVATION keypad USB HID protocol

Reverse-engineered from the vendor's WebHID configurator at `https://www.sdcx-tech.com`
(Next.js bundle, `_next/static/chunks/app/page-*.js`). No USB capture was needed — the
web app ships the full protocol in readable JavaScript.

Reference copies of the decisive source are kept alongside this document:

- `reference-classS.js` — the device API class, all 32 methods, as shipped (minified).
- `reference-layout-0816_246f.js` — the per-device layout/capability JSON for the HCY-K006.

Verified against: **HCY-K006**, USB `0816:246f`, product string `SIDE-KEYBOARD`,
manufacturer `SDINNOVATION`, MCU type `951`.

---

## 1. Transport

The device exposes three USB interfaces. Interface 2 is the config channel:

| interface | usage page | usage | purpose |
|---|---|---|---|
| 0 | `0x0001` | `0x06` | keyboard / consumer / system input |
| 1 | `0x0001` | `0x06` | boot keyboard + LED output |
| **2** | **`0xFF00`** | **`0x02`** | **vendor config channel** |

Interface 2 declares one 64-byte input report and one 64-byte output report, both
with report ID 0. On Linux it appears as its own `/dev/hidrawN`.

The vendor usage page is deliberate: WebHID refuses to hand a page-`0x01` keyboard
collection to a web page, but allows vendor-defined collections. The same split is
what lets an unprivileged Linux process drive the device without touching the
keyboard interfaces.

### Framing

There is **no checksum, no magic header, and no sequence number.** From the bundle:

```js
webhid_write_command(e, a, l = []) {
  let u = [0, a, ...l],            // [reportId, cmd, ...payload]
      v = Array(65).fill(0);       // 65 = 1 report-id byte + 64 data bytes
  u.forEach((e, a) => { v[a] = e });
  await this.getHID().write(v);
  return Array.from(await this.webhid_read_command());
}

// ...and HID.write() drops the leading report-id placeholder:
async write(e) {
  let l = new Uint8Array(e.slice(1));
  await this._device.sendReport(0, l);
}
```

So the wire format is simply:

```
write:  report id 0, exactly 64 bytes = [cmd, ...payload, 0x00 padding]
read:   report id 0, exactly 64 bytes
```

On Linux with `hidraw`, report ID 0 means **do not** prefix a report-ID byte — write
the 64 payload bytes directly:

```python
os.write(fd, bytes([cmd, *payload]).ljust(64, b"\0"))
resp = os.read(fd, 64)
```

Commands are serialised through a queue in the web app; one outstanding
command at a time. Reads are matched to writes in order.

### Command groups

The first wire byte is a group selector:

| byte 0 | group |
|---|---|
| `0x06` | configuration (everything in §3) |
| `0x55` | firmware update / bootloader — **destructive, see §5** |
| `0x5A` | Artery-MCU firmware update — **destructive** |

For group `0x06`, the second wire byte is the sub-command. Throughout this document
`sendDeviceData(6, [sub, ...])` therefore means wire bytes `[0x06, sub, ...]`.

### Little-endian helper

`T(x)` in the bundle is a 16-bit little-endian split, used for every offset:

```
T(x) = [x & 0xFF, (x >> 8) & 0xFF]
```

### Asynchronous light events

Input reports whose first two bytes are `0xAA 0xFA` are unsolicited lighting
notifications pushed by the device (e.g. when lighting is changed with an on-device
key). They are delivered to a `"light"` listener and are not responses to a command:

```js
if (170 == a[0] && 250 == a[1]) { /* light event */ }
```

A reader must therefore tolerate `AA FA ...` frames arriving between a write and its
real response.

---

## 2. Device capability descriptor

The web app loads a per-device JSON keyed by USB ID: `./{vid:04x}_{pid:04x}.json`.
For the HCY-K006 that is `0816_246f.json`, which defines both the light modes the
firmware supports and the physical key layout.

### Light modes (HCY-K006)

`value` is the wire value written into the `mode` field of `setLightConfig`.
The booleans say which fields the firmware actually honours in that mode — the
UI greys out the rest.

| value | name (zh) | name (en) | brightness | speed | direction | color | palette |
|---|---|---|---|---|---|---|---|
| 0 | 关闭 | Off | – | – | – | – | – |
| 1 | 常亮 | Steady on | ✓ | – | – | ✓ | ✓ |
| 2 | 呼吸 | Breath | ✓ | ✓ | – | ✓ | ✓ |
| 3 | 按亮 | Press-lit (react to keypress) | ✓ | ✓ | – | ✓ | ✓ |
| 4 | 潮汐 | Tidal | ✓ | ✓ | – | ✓ | ✓ |
| 5 | custom | Custom / per-key | ✓ | – | – | – | ✓ |

Mode `5` is the one that hands per-key colour control to the host (§3.4).

### Key layout (HCY-K006)

`key_index_max: 19`, matrix `6 rows × 5 cols`, but only 9 addressable inputs:

| index | position | function as shipped |
|---|---|---|
| 0 | row 0, col 0 | key 1 |
| 1 | row 1, col 0 | key 2 |
| 2 | row 2, col 0 | key 3 |
| 3 | row 3, col 0 | key 4 |
| 4 | row 0, col 1 | key 5 |
| 5 | row 1, col 1 | key 6 |
| 16 | row 1, col 4 | knob press (mute) |
| 17 | row 2, col 4 | knob CW (volume up) |
| 18 | row 0, col 4 | knob CCW (volume down) |

The vendor's layout JSON captions 18 as 音量+ and 17 as 音量-, i.e. the opposite
rotation. That caption is wrong: reading the factory keymap off the device gives
`17 = volume_up, 18 = volume_down`, and louder-clockwise is universal. Trust the
device, not the JSON's labels.

Note the gap: knob actions live at indices **16–18**, not 6–8. Per-key colour and
keymap writes are indexed by this `key_index`, so the addressing is sparse.

---

## 3. Command reference (group `0x06`)

Offsets below are **byte offsets into the 64-byte wire buffer**, i.e. wire byte 0 is
the group byte `0x06` and wire byte 1 is the sub-command.

### 3.1 Device info

#### `[5]` — get keyboard config

Response is parsed as `resp[2]` = length, `resp.slice(5, 43)` = payload `l`:

| field | source | notes |
|---|---|---|
| `version` | `u16le(l[0], l[1])` | |
| `pid` | `u16le(l[2], l[3])` | |
| `firmware` | `u16le(l[4], l[5])` | |
| `workMode` | `l[6]` | |
| `linkStatus` | `l[7]` | |
| `battery` | `l[8]` | wireless models only |
| `charge` | `l[9]` | |
| `profileCnt` | `l[10]` | number of configuration schemes |
| `profile` | `l[11]` | currently active scheme |
| `layerCnt` | `l[12]` | |
| `layer` | `l[13]` | |
| `autoSleepTime` | `u16le(l[14], l[15])` | only if `resp[2] >= 16` |
| `serialNumStr` | `resp.slice(21, 43)` as ASCII, NULs dropped | only if `resp[2] >= 40` |

### 3.2 Lighting — global

#### `[10]` — get light config

Response payload is `resp.slice(5, 16)`:

| offset | field | encoding |
|---|---|---|
| 0 | `type` | always 1 in practice |
| 1 | — | reserved |
| 2 | `mode` | see §2 light-mode table |
| 3 | `brightness` | 0–4 on this device |
| 4 | `speed` | 0–4 on this device |
| 5 | `direction` | 0 or 1 |
| 6 | `color` | 0 = rainbow/palette, 1 = single colour |
| 7 | `singleColorIndex` | index into the preset swatch row |
| 8 | `h` | hue, 0–255 → degrees = `floor(h * 360 / 255)` |
| 9 | `s` | saturation, 0–255 → percent = `floor(s * 100 / 255)` |
| 10 | `v` | value, 0–255 → percent = `floor(v * 100 / 255)` |

#### `[11, len, 0, 0, ...cfg]` — set light config

`cfg` is 11 bytes laid out as:

```
[type, 0, mode, brightness, speed, direction, color, 0, h, s, v]
```

with `len = 11`. Two firmware quirks the web app compensates for:

- **If `mode == 0` (Off), `cfg[6]` (`color`) is forced to 0.** Writing Off with a
  non-zero colour flag does not reliably turn the LEDs off.
- Brightness is not a plain scale in the UI: when the brightness slider changes, the
  app also rescales `v` as `floor(v_pct / 100 * 255 / 4 * brightness)`, and sends
  `v = 0` when `brightness == 0`. Brightness and value are therefore coupled;
  a driver that sets `v` directly should keep `brightness` at its maximum (4) to get
  a linear, predictable result.

Turning the lights off is exactly:

```
06 0B 0B 00 00  01 00 00 00 00 00 00 00 00 00 00   (+ zero padding to 64)
        └len┘   └type,─,mode=0,bri=0,spd=0,dir=0,color=0,─,h=0,s=0,v=0┘
```

#### `[22, 0, 0, 0, 1, 0, mode]` — get firmware defaults for a mode

Returns the same 11-byte block as `[10]`, populated with the firmware's preferred
defaults for `mode`. The web app uses this when you pick a new effect: it fetches the
defaults, overwrites `[2]` with the chosen mode, and writes the result back via `[11]`.
Reproducing that sequence is what makes mode switching feel identical to the vendor UI.

### 3.3 Keymap

Key entries are **4 bytes each**: `[type, code1, code2, code3]`.

| command | direction | layout |
|---|---|---|
| `[7, 56, ...T(off)]` | read | raw key info, 576 bytes total, 56 per chunk, data at `resp[8..]` |
| `[8, 58, ...T(off), 0, layer]` | read | per-layer keymap, data at `resp[8..]` |
| `[9, 59, ...T(off), 0, layer, ...data]` | write | bulk keymap; data starts at wire offset 7 |
| `[16, 7, ...T(idx*4), 0, layer, 0, type, c1, c2, c3]` | write | single key |

For the bulk write `[9]`, the final chunk sets wire byte 1 to `(total % 56) + 3`
rather than 59.

Chunking is 56 data bytes per transfer for reads, 56 for keymap writes.

### 3.4 Per-key RGB

Colour entries are **3 bytes each**: `[r, g, b]`, indexed by `key_index`.

| command | direction | layout |
|---|---|---|
| `[19, 58, ...T(off)]` | read | per-key RGB, 3 bytes/key, data at `resp[8..]` |
| `[18, 59, ...T(off), ...data]` | write | bulk per-key RGB; data starts at wire offset 7 |
| `[20, 3, ...T(idx*3), 0, 0, 0, r, g, b]` | write | **single key colour** |

As with the keymap, the last bulk chunk sets wire byte 1 to `(total % 56) + 3`.

`[20]` is the interesting one for a host-driven light show: it sets one key's colour
in a single 64-byte transfer with no read-back, so a host can repaint individual keys
at high rate. Put the device in light mode `5` (custom) first, or the effect engine
will overwrite the table.

### 3.5 Macros

The macro area is a flat 4096-byte blob.

| command | direction | notes |
|---|---|---|
| `[12, len, ...T(off)]` | read | 4096 bytes total, 56 per chunk, data at `resp[8..]` |
| `[13, len, ...T(off), ...data]` | write | **59** data bytes per chunk |
| `[15, 4]` | write | reset macro area |

### 3.6 Miscellaneous

| command | effect |
|---|---|
| `[251, profile]` | select active configuration scheme (profile) |
| `[252, 2, 0, 0, ...T(seconds)]` | set auto-sleep time |
| `[64, len, ...T(off), ...data]` | write the 128-byte URL/OEM string area, 59 bytes/chunk |
| `[65, len, ...T(off)]` | read the 128-byte URL area, 56 bytes/chunk |
| `[15, 255]` | **restore factory settings** |

---

## 4. Deriving the "turn it off" packet

For the common case — kill the RGB and leave the keys working — the whole
interaction is one 64-byte write with no response required:

```
06 0B 0B 00 00 01 00 00 00 00 00 00 00 00 00 00 ...
```

`mode = 0`, `brightness = 0`, `color = 0`, `v = 0`. The setting is stored in the
device's flash and survives unplugging, so it is a one-shot operation.

---

## 5. Commands this driver deliberately does not expose

Group `0x55` and `0x5A` are the firmware-update path:

| command | meaning |
|---|---|
| `06 55 FF 00 00` | `startUpdate` — enter update mode |
| `06 55 FF 01 00` | `connectBootLoader` |
| `06 55 FF 02 04 ...` | `startWriteRom(addr, len)` |
| `06 55 FF 04 00` | `checkRom` |
| `06 55 FF 05 01 01` | `endUpdate` |
| `06 5A A0` | `startUpdateForArtery` |

These write flash. A mistake here bricks the device and there is no recovery path
without hardware. They are documented for completeness and are **not** implemented.

`[15, 255]` (factory reset) is implemented but gated behind an explicit confirmation
flag, because it discards the user's keymap, macros and colours.

---

## 6. Supported devices

The vendor bundle ships WebHID filters for **196 USB IDs across 32 vendor IDs**,
all on usage page `0xFF00` / usage `0x02`:

```
0x0461 0x0483 0x05ac 0x0816 0x0817 0x0818 0x0819 0x08a1 0x08a3 0x08a5 0x08ae
0x3151 0x35ae 0x36ae 0x5566 0x68bd 0x6d02 0x6d03 0x6d04 0x6d05 0x6d06 0x6d07
0x6d7b 0x6d7c 0x6d7d 0x6d7e 0x6d7f 0x6d80 0x6d81 0x6d82 0x6d83 0x7dfa
```

Under vendor `0x0816` alone: `021d 021f 0220 024c 0600 0601 0605 060a 060b 060c
060d 06a0 06a1 06ab 246d 246e 246f 2470 2471 2472 2473 2474 2475 2476 2477 2478 2479`.

The protocol is shared across all of them; what differs per device is the layout JSON
(key count, indices, which light modes the firmware implements). The full ID list as
extracted is in `../sdcx/devices.json`.

Only `0816:246f` has been tested on hardware. Other IDs should work but are unverified.
