"""Device discovery and the raw 64-byte hidraw transport.

The vendor config channel is a plain HID interface with usage page 0xFF00 and
usage 0x02, carrying one 64-byte input report and one 64-byte output report,
both with report ID 0. That needs no HID library at all: on Linux the interface
shows up as its own /dev/hidrawN and a read()/write() pair is the whole
transport. Staying dependency-free keeps the package installable anywhere a
Python interpreter already exists, including minimal images and environments
where adding a compiled HID binding is impractical.

See docs/PROTOCOL.md §1.
"""

from __future__ import annotations

import errno
import os
import select
import time
from dataclasses import dataclass
from pathlib import Path

REPORT_SIZE = 64

# The config interface's report descriptor always begins with:
#   06 00 ff   Usage Page (Vendor-Defined 0xFF00)
#   09 02      Usage (0x02)
# Matching on this is what distinguishes the config interface from the two
# keyboard interfaces, which share the same VID:PID.
_CONFIG_DESCRIPTOR_PREFIX = bytes([0x06, 0x00, 0xFF, 0x09, 0x02])

HIDRAW_CLASS = Path("/sys/class/hidraw")


class SdcxError(Exception):
    """Base class for every error this package raises."""


class DeviceNotFound(SdcxError):
    pass


class PermissionDenied(SdcxError):
    """Raised with an actionable message; this is the common first-run failure."""


@dataclass(frozen=True)
class DeviceInfo:
    """A discovered config interface."""

    path: str  # /dev/hidrawN
    vendor_id: int
    product_id: int
    name: str
    uevent_path: str

    @property
    def usb_id(self) -> str:
        return f"{self.vendor_id:04x}:{self.product_id:04x}"

    def describe(self) -> str:
        return f"{self.name} ({self.usb_id}) at {self.path}"


def _parse_hid_id(uevent: str) -> tuple[int, int] | None:
    """Pull (vendor, product) out of a hidraw uevent's HID_ID line.

    HID_ID has the form BUS:VVVVVVVV:PPPPPPPP with 8 hex digits each.
    """
    for line in uevent.splitlines():
        if line.startswith("HID_ID="):
            parts = line.split("=", 1)[1].split(":")
            if len(parts) == 3:
                try:
                    return int(parts[1], 16), int(parts[2], 16)
                except ValueError:
                    return None
    return None


def _hid_name(uevent: str) -> str:
    for line in uevent.splitlines():
        if line.startswith("HID_NAME="):
            return line.split("=", 1)[1].strip()
    return "unknown"


def enumerate_devices(
    vendor_id: int | None = None,
    product_id: int | None = None,
    include_unsupported: bool = False,
) -> list[DeviceInfo]:
    """Return every SDCX config interface present on the system.

    A device with N HID interfaces produces N hidraw nodes sharing one VID:PID;
    only the one whose report descriptor starts with the vendor-defined prefix
    is the config channel. Filtering on the descriptor rather than on an
    interface number keeps this correct if a firmware revision reorders them.

    `include_unsupported` keeps devices whose USB ID is not in the recognised
    list. Normal operation wants them excluded, but `sdcx report` needs them:
    a keypad this driver has never heard of is exactly the one worth reporting,
    and it still announces itself with the same vendor-defined descriptor.
    """
    from .layouts import is_supported

    found: list[DeviceInfo] = []
    if not HIDRAW_CLASS.is_dir():
        return found

    for node in sorted(HIDRAW_CLASS.iterdir()):
        device_dir = node / "device"
        try:
            uevent = (device_dir / "uevent").read_text()
            descriptor = (device_dir / "report_descriptor").read_bytes()
        except OSError:
            continue

        ids = _parse_hid_id(uevent)
        if ids is None:
            continue
        vid, pid = ids

        if not descriptor.startswith(_CONFIG_DESCRIPTOR_PREFIX):
            continue
        if not include_unsupported and not is_supported(vid, pid):
            continue
        if vendor_id is not None and vid != vendor_id:
            continue
        if product_id is not None and pid != product_id:
            continue

        found.append(
            DeviceInfo(
                path=f"/dev/{node.name}",
                vendor_id=vid,
                product_id=pid,
                name=_hid_name(uevent),
                uevent_path=str(device_dir / "uevent"),
            )
        )
    return found


def _permission_help(path: str) -> str:
    return (
        f"cannot open {path}: permission denied.\n\n"
        f"The config interface is root-only by default. Either run once as root:\n"
        f"    sudo chmod 666 {path}\n"
        f"or install the udev rule for a permanent fix:\n"
        f"    sdcx install-udev-rule --print   # see what it does\n"
        f"    sudo sdcx install-udev-rule      # write and reload it"
    )


class Transport:
    """A 64-byte request/response channel over one hidraw node.

    The device pushes unsolicited lighting notifications (frames beginning
    AA FA) whenever lighting changes, including changes made from the keypad
    itself. Those can arrive between a write and its response, so the read path
    skips them rather than mistaking one for a reply. See docs/PROTOCOL.md §1.
    """

    LIGHT_EVENT_PREFIX = (0xAA, 0xFA)

    def __init__(self, path: str, timeout: float = 1.0):
        self.path = path
        self.timeout = timeout
        try:
            self._fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError as exc:
            raise PermissionDenied(_permission_help(path)) from exc
        except FileNotFoundError as exc:
            raise DeviceNotFound(f"{path} does not exist") from exc

    def close(self) -> None:
        if getattr(self, "_fd", None) is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "Transport":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _drain(self) -> None:
        """Discard anything already queued so a stale frame can't answer a new write."""
        while True:
            ready, _, _ = select.select([self._fd], [], [], 0)
            if not ready:
                return
            try:
                if not os.read(self._fd, REPORT_SIZE):
                    return
            except OSError:
                return

    def write(self, payload: bytes | list[int]) -> None:
        """Send one 64-byte report. Shorter payloads are zero-padded."""
        data = bytes(payload)
        if len(data) > REPORT_SIZE:
            raise SdcxError(f"payload of {len(data)} bytes exceeds the {REPORT_SIZE}-byte report")
        data = data.ljust(REPORT_SIZE, b"\0")
        try:
            os.write(self._fd, data)
        except OSError as exc:
            if exc.errno == errno.EACCES:
                raise PermissionDenied(_permission_help(self.path)) from exc
            raise SdcxError(f"write to {self.path} failed: {exc}") from exc

    def read(self, timeout: float | None = None) -> bytes:
        """Read one 64-byte report, skipping asynchronous light-event frames."""
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SdcxError(
                    f"timed out waiting for a response from {self.path}. "
                    "The device may be in an unexpected state. Try replugging it."
                )
            ready, _, _ = select.select([self._fd], [], [], remaining)
            if not ready:
                continue
            try:
                data = os.read(self._fd, REPORT_SIZE)
            except BlockingIOError:
                continue
            except OSError as exc:
                raise SdcxError(f"read from {self.path} failed: {exc}") from exc
            if len(data) >= 2 and tuple(data[:2]) == self.LIGHT_EVENT_PREFIX:
                continue  # unsolicited lighting notification, not our reply
            return data

    def request(self, payload: bytes | list[int]) -> bytes:
        """Write a command and return its 64-byte response."""
        self._drain()
        self.write(payload)
        return self.read()
