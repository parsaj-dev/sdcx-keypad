---
name: Device report
about: Report a keypad that works, partly works, or isn't recognised at all
title: "Device: VVVV:PPPP — "
labels: device
---

<!--
Thanks — device reports are the most useful thing anyone can send this project.
One device is hardware-verified; everything else is recognised on trust.
Fill in what you can. A partial report is still worth filing.
-->

## USB ID and `lsusb`

<!-- The full line for your keypad. -->

```
$ lsusb

```

## `sdcx list`

<!-- If it prints nothing, say so — that's the interesting case. -->

```
$ sdcx list

```

## `sdcx info`

```
$ sdcx info

```

<details>
<summary>Optional: <code>sdcx modes</code> and <code>sdcx keys</code></summary>

```
$ sdcx modes

$ sdcx keys

```
</details>

## Product string

<!-- Manufacturer and product as reported by USB, e.g. SDINNOVATION / SIDE-KEYBOARD.
     From the lsusb line above, or: cat /sys/class/hidraw/hidrawN/device/uevent -->

- Manufacturer:
- Product:

## Model markings

<!-- Anything printed on the device, the PCB, the box, the listing, or the manual —
     e.g. HCY-K006, a shop name, a vendor site. Rough is fine. -->

- Model / markings:
- Where you bought it:
- Physical layout (number of keys, knobs, screen, etc.):

## What works and what doesn't

<!-- Tick what you tried. Anything you didn't try, leave blank. -->

- [ ] `sdcx light off` — turns the RGB off, and it stays off after a replug
- [ ] `sdcx light mode <name>` — switching effects
- [ ] `sdcx light set --brightness / --speed / --color`
- [ ] `sdcx keys` lists the right number of keys with sensible indices
- [ ] `sdcx key color 0 '#00ff00'` lights the key you expected (in Custom mode)
- [ ] `sdcx effect rainbow` runs

Anything that went wrong — the exact error text, please, not a paraphrase:

```

```

## Environment

- Distro / kernel:
- Python version:
- Installed via (pipx / pip / source / Nix):
- udev rule installed:  yes / no

## Anything else

<!-- Screenshots of the vendor web app, a photo of the pad, or a per-device JSON
     you grabbed from sdcx-tech.com are all welcome. -->
