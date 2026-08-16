# Supported devices

`sdcx` recognises 196 USB IDs across 32 vendor IDs. That list is not guesswork: it is the exact
device filter the vendor's own WebHID configurator at `sdcx-tech.com` uses, extracted from its
JavaScript bundle and shipped inside the package as [`sdcx/devices.json`](../sdcx/devices.json).
Every one of them is a HID device on usage page `0xFF00` / usage `0x02`, the vendor configuration
interface this driver talks to.

These keypads are sold unbranded, under dozens of shop names, on AliExpress, Amazon, Temu and
elsewhere. The silicon and the protocol are shared; what differs between them is the key layout
and which lighting modes the firmware implements.

---

## Verified vs. generic fallback

`sdcx list` marks each device it finds, and the distinction matters:

| | verified | generic fallback |
|---|---|---|
| meaning | the key layout has been transcribed and checked against real hardware | the USB ID is recognised, but the key map has not been confirmed |
| global lighting (`light off`, `mode`, `brightness`, `speed`, `colour`) | works | works (identical across the family) |
| `sdcx keys`, `key color`, host effects | works | reports that the layout is unknown |
| shown by `sdcx list` as | model name, e.g. `HCY-K006` | `Unknown (vvvv:pppp)  (layout unverified)` |

The fallback deliberately refuses to guess key indices rather than writing colours to addresses
that might mean something else on a given device.

### Hardware-verified

| model | USB ID | strings | hardware |
|---|---|---|---|
| **HCY-K006** | `0816:246f` | product `SIDE-KEYBOARD`, manufacturer `SDINNOVATION`, MCU `951` | 6 keys plus a clickable rotary encoder. Sold by Shenzhen HCY (szhcykb.com). |

That is the complete verified list: one device, because it is the one the maintainer owns.
Everything else below is recognised and expected to work, but untested.

---

## Reporting a device

If a keypad works, or is recognised but the keys are wrong, or is not recognised at all, open an
issue using the [new device report](../.github/ISSUE_TEMPLATE/new-device.md) template. Useful
information:

```bash
lsusb                      # the full line for the keypad
sdcx list                  # what the driver thinks it is
sdcx info                  # firmware and serial
sdcx modes                 # what the firmware says it supports
```

plus the product string, whatever model number is printed on the device or its box, and what
does and does not work. To also contribute a transcribed key layout, see
[CONTRIBUTING.md](../CONTRIBUTING.md).

If the USB ID is genuinely absent from the list, it is likely a newer product than the bundle
that was extracted; note that in the issue and include the `lsusb -v` interface descriptors if
available.

---

## The full list

Grouped by vendor ID. Counts are IDs, not distinct products; one product often ships several IDs.

| vendor ID | IDs |
|---|---|
| `0461` | 3 |
| `0483` | 1 |
| `05ac` | 5 |
| `0816` | 27 |
| `0817` | 2 |
| `0818` | 3 |
| `0819` | 1 |
| `08a1` | 1 |
| `08a3` | 3 |
| `08a5` | 1 |
| `08ae` | 1 |
| `3151` | 2 |
| `35ae` | 11 |
| `36ae` | 107 |
| `5566` | 1 |
| `68bd` | 1 |
| `6d02` | 1 |
| `6d03` | 1 |
| `6d04` | 1 |
| `6d05` | 1 |
| `6d06` | 1 |
| `6d07` | 1 |
| `6d7b` | 1 |
| `6d7c` | 1 |
| `6d7d` | 1 |
| `6d7e` | 1 |
| `6d7f` | 1 |
| `6d80` | 1 |
| `6d81` | 1 |
| `6d82` | 1 |
| `6d83` | 3 |
| `7dfa` | 9 |

<details>
<summary>Every recognised vid:pid pair (196 entries)</summary>

**`0461`** (3 IDs)

```text
0461:4001 0461:4002 0461:4003
```

**`0483`** (1 ID)

```text
0483:0010
```

**`05ac`** (5 IDs)

```text
05ac:021d 05ac:021e 05ac:024f 05ac:0250 05ac:0255
```

**`0816`** (27 IDs)

```text
0816:021d 0816:021f 0816:0220 0816:024c 0816:0600 0816:0601 0816:0605
0816:060a 0816:060b 0816:060c 0816:060d 0816:06a0 0816:06a1 0816:06ab
0816:246d 0816:246e 0816:246f 0816:2470 0816:2471 0816:2472 0816:2473
0816:2474 0816:2475 0816:2476 0816:2477 0816:2478 0816:2479
```

**`0817`** (2 IDs)

```text
0817:d18a 0817:dcfb
```

**`0818`** (3 IDs)

```text
0818:d18a 0818:dcfa 0818:dcfb
```

**`0819`** (1 ID)

```text
0819:d18a
```

**`08a1`** (1 ID)

```text
08a1:dcfc
```

**`08a3`** (3 IDs)

```text
08a3:1cfc 08a3:2cfc 08a3:3cfc
```

**`08a5`** (1 ID)

```text
08a5:dcfc
```

**`08ae`** (1 ID)

```text
08ae:dcfb
```

**`3151`** (2 IDs)

```text
3151:4010 3151:6000
```

**`35ae`** (11 IDs)

```text
35ae:0250 35ae:0251 35ae:0252 35ae:0253 35ae:0254 35ae:0255 35ae:0256
35ae:0257 35ae:0258 35ae:02a4 35ae:dcfc
```

**`36ae`** (107 IDs)

```text
36ae:021d 36ae:021e 36ae:021f 36ae:0220 36ae:0221 36ae:0222 36ae:0223
36ae:0224 36ae:0225 36ae:0227 36ae:0230 36ae:0250 36ae:0252 36ae:0257
36ae:0258 36ae:0259 36ae:0260 36ae:0261 36ae:0262 36ae:0263 36ae:0264
36ae:0265 36ae:0266 36ae:0267 36ae:0268 36ae:0269 36ae:0270 36ae:0355
36ae:03ff 36ae:060e 36ae:060f 36ae:0610 36ae:0634 36ae:0635 36ae:06f3
36ae:06f6 36ae:1433 36ae:1434 36ae:1435 36ae:1437 36ae:1438 36ae:1439
36ae:1440 36ae:1903 36ae:1904 36ae:1905 36ae:2231 36ae:2232 36ae:2233
36ae:246d 36ae:246e 36ae:246f 36ae:2471 36ae:2472 36ae:2473 36ae:2474
36ae:2475 36ae:4001 36ae:4002 36ae:4003 36ae:4004 36ae:4005 36ae:4006
36ae:4007 36ae:f021 36ae:f024 36ae:f031 36ae:f041 36ae:f042 36ae:f043
36ae:f051 36ae:f069 36ae:f070 36ae:f100 36ae:f101 36ae:f2ff 36ae:fc1b
36ae:fc1c 36ae:fda4 36ae:fda8 36ae:fe12 36ae:fe61 36ae:fe62 36ae:fe63
36ae:fe68 36ae:fe70 36ae:fe71 36ae:fe81 36ae:fe83 36ae:fe98 36ae:fe9c
36ae:fe9d 36ae:fea3 36ae:feab 36ae:feac 36ae:fead 36ae:feae 36ae:feb1
36ae:feb2 36ae:febb 36ae:febc 36ae:febd 36ae:febe 36ae:feec 36ae:feed
36ae:ff01 36ae:ff61
```

**`5566`** (1 ID)

```text
5566:0009
```

**`68bd`** (1 ID)

```text
68bd:dcfc
```

**`6d02`** (1 ID)

```text
6d02:dcfc
```

**`6d03`** (1 ID)

```text
6d03:dcfc
```

**`6d04`** (1 ID)

```text
6d04:dcfc
```

**`6d05`** (1 ID)

```text
6d05:dcfc
```

**`6d06`** (1 ID)

```text
6d06:dcfc
```

**`6d07`** (1 ID)

```text
6d07:dcfc
```

**`6d7b`** (1 ID)

```text
6d7b:dcfa
```

**`6d7c`** (1 ID)

```text
6d7c:dcfb
```

**`6d7d`** (1 ID)

```text
6d7d:dcfc
```

**`6d7e`** (1 ID)

```text
6d7e:dcfd
```

**`6d7f`** (1 ID)

```text
6d7f:dcfe
```

**`6d80`** (1 ID)

```text
6d80:dc81
```

**`6d81`** (1 ID)

```text
6d81:dc82
```

**`6d82`** (1 ID)

```text
6d82:dc83
```

**`6d83`** (3 IDs)

```text
6d83:dc84 6d83:dc85 6d83:dcfa
```

**`7dfa`** (9 IDs)

```text
7dfa:37a1 7dfa:dcfa 7dfa:dcfb 7dfa:dcfc 7dfa:dcfd 7dfa:dcfe 7dfa:dcff
7dfa:ddfc 7dfa:defa
```

</details>

The authoritative copy is [`sdcx/devices.json`](../sdcx/devices.json); this page is a rendering
of it. To check a single ID without reading either:

```bash
python3 -c "from sdcx.layouts import is_supported; print(is_supported(0x0816, 0x246f))"
```
