"""Offline tests for the byte packing and the keycode parser.

Run with: python3 -m sdcx._selftest

Nothing here touches hardware. Everything the driver writes to the device is
built by a pure function first, so the packing can be checked against the wire
formats in docs/PROTOCOL.md §3.3 and §3.5 without a keypad plugged in.
"""

from __future__ import annotations

import unittest

from .device import SdcxError
from .keycodes import (
    TYPE_CONSUMER,
    TYPE_CONTROL,
    TYPE_MACRO,
    TYPE_STANDARD,
    describe,
    lookup,
    parse_keycode,
)
from .protocol import (
    MACRO_AREA_SIZE,
    MACRO_INDEX_SIZE,
    STEP_FLAG_LAST,
    STEP_FLAG_PRESS,
    STEP_KEYBOARD,
    Macro,
    MacroStep,
    decode_macros,
    encode_macros,
    macro_from_sequence,
    u16le,
)


class TestKeycodeParsing(unittest.TestCase):
    def test_plain_key(self):
        self.assertEqual(parse_keycode("f5").wire, (TYPE_STANDARD, 0, 62, 0))

    def test_case_and_separator_tolerance(self):
        for text in ("ctrl+c", "Ctrl + C", "ctrl-c", "CONTROL_C", "  ctrl  +  C  "):
            with self.subTest(text=text):
                self.assertEqual(parse_keycode(text).wire, (TYPE_STANDARD, 0x01, 6, 0))

    def test_multiple_modifiers(self):
        # LCTRL | LSHIFT = 0x03, "s" is usage 22.
        self.assertEqual(parse_keycode("ctrl+shift+s").wire, (TYPE_STANDARD, 0x03, 22, 0))

    def test_right_hand_modifiers(self):
        self.assertEqual(parse_keycode("ralt+a").wire, (TYPE_STANDARD, 0x40, 4, 0))

    def test_aliases(self):
        self.assertEqual(parse_keycode("esc"), lookup("escape"))
        self.assertEqual(parse_keycode("super+l").wire, (TYPE_STANDARD, 0x08, 15, 0))

    def test_consumer_and_control(self):
        self.assertEqual(parse_keycode("volume_up").wire, (TYPE_CONSUMER, 233, 0, 0))
        self.assertEqual(parse_keycode("light_switch").wire, (TYPE_CONTROL, 0, 0, 0))

    def test_macro_forms(self):
        for text in ("macro:3", "macro3", "M3", "m3"):
            with self.subTest(text=text):
                self.assertEqual(parse_keycode(text).wire, (TYPE_MACRO, 3, 1, 0))

    def test_raw_escape_hatch(self):
        self.assertEqual(parse_keycode("raw:32,1,6,0").wire, (TYPE_STANDARD, 1, 6, 0))
        self.assertEqual(parse_keycode("raw:0x20,0x01,0x06,0").wire, (TYPE_STANDARD, 1, 6, 0))

    def test_trailing_separator_is_a_key(self):
        self.assertEqual(parse_keycode("ctrl+-").wire, (TYPE_STANDARD, 0x01, 45, 0))

    def test_refusals_are_actionable(self):
        for text in ("", "nonsense", "ctrl+nonsense", "ctrl+shift", "ctrl+volume_up", "raw:1,2"):
            with self.subTest(text=text):
                with self.assertRaises(SdcxError):
                    parse_keycode(text)


class TestDescribe(unittest.TestCase):
    def test_round_trip(self):
        for text in ("f5", "ctrl+c", "volume_up", "macro:3", "mouse_left", "light_switch"):
            with self.subTest(text=text):
                code = parse_keycode(text)
                rendered = describe(*code.wire)
                self.assertEqual(parse_keycode(rendered).wire, code.wire)

    def test_unset_and_unknown(self):
        self.assertEqual(describe(0, 0, 0, 0), "unset")
        self.assertEqual(describe(200, 1, 2, 3), "raw:200,1,2,3")


class TestWireHelpers(unittest.TestCase):
    def test_u16le(self):
        self.assertEqual(u16le(0), [0, 0])
        self.assertEqual(u16le(56), [56, 0])
        self.assertEqual(u16le(300), [44, 1])


class _FakeTransport:
    """Records what would have gone to the device, and replays canned reads."""

    def __init__(self, responses: list[bytes] | None = None):
        self.written: list[list[int]] = []
        self.responses = responses or []

    def write(self, payload):
        self.written.append(list(payload))

    def request(self, payload):
        self.written.append(list(payload))
        return self.responses.pop(0) if self.responses else bytes(64)

    def close(self):
        pass


def _fake_pad():
    from .layouts import get_layout
    from .protocol import Keypad

    pad = Keypad.__new__(Keypad)
    pad.transport = _FakeTransport()
    pad.info = None
    pad.layout = get_layout(0x0816, 0x246F)
    return pad


class TestKeymapPacking(unittest.TestCase):
    def test_set_key_frame(self):
        pad = _fake_pad()
        pad.set_key(0, "ctrl+c")
        # [group, 16, 7, off_lo, off_hi, 0, layer, 0, type, c1, c2, c3]
        self.assertEqual(
            pad.transport.written[0],
            [0x06, 16, 7, 0, 0, 0, 0, 0, 32, 1, 6, 0],
        )

    def test_set_key_offset_is_index_times_four(self):
        pad = _fake_pad()
        pad.set_key(18, "volume_up")
        frame = pad.transport.written[0]
        self.assertEqual(frame[2:5], [7, 18 * 4, 0])
        self.assertEqual(frame[8:12], [48, 233, 0, 0])

    def test_set_key_rejects_indices_the_pad_does_not_have(self):
        pad = _fake_pad()
        with self.assertRaises(SdcxError):
            pad.set_key(7, "a")

    def test_get_keymap_command(self):
        pad = _fake_pad()
        pad.transport.responses = [bytes(64)]
        pad.get_keymap(layer=1)
        # Span is (18 + 1) * 4 = 76 bytes, so two 56-byte reads.
        self.assertEqual(pad.transport.written[0], [0x06, 8, 58, 0, 0, 0, 1])

    def test_get_keymap_indexes_by_key_index(self):
        pad = _fake_pad()
        first = bytearray(64)
        first[8:12] = bytes([32, 1, 6, 0])  # key_index 0 -> ctrl+c
        second = bytearray(64)
        # key_index 18 sits at byte 72, which is byte 16 of the second chunk.
        second[8 + 16 : 8 + 20] = bytes([48, 233, 0, 0])
        pad.transport.responses = [bytes(first), bytes(second)]
        keymap = pad.get_keymap()
        self.assertEqual(keymap[0].name, "lctrl+c")
        self.assertEqual(keymap[18].name, "volume_up")

    def test_bulk_keymap_chunking(self):
        pad = _fake_pad()
        pad.transport.responses = [bytes(64), bytes(64)]
        pad.set_keymap({0: __import__("sdcx.protocol", fromlist=["x"]).KeyAssignment(0, 32, 1, 6, 0)})
        writes = [w for w in pad.transport.written if w[1] == 9]
        self.assertEqual(len(writes), 2)
        self.assertEqual(writes[0][1:6], [9, 59, 0, 0, 0])
        # 76 bytes total, so the tail is 20 bytes and declares 20 + 3.
        self.assertEqual(writes[1][1:6], [9, 76 % 56 + 3, 56, 0, 0])
        self.assertEqual(writes[0][7:11], [32, 1, 6, 0])


class TestMacroCodec(unittest.TestCase):
    def test_empty_area_decodes_to_empty_slots(self):
        blob = b"\xff" * MACRO_INDEX_SIZE + b"\x00" * (MACRO_AREA_SIZE - MACRO_INDEX_SIZE)
        self.assertTrue(all(not m.steps for m in decode_macros(blob)))

    def test_encode_layout(self):
        macro = Macro(0, [MacroStep(STEP_KEYBOARD, 6, True, 10), MacroStep(STEP_KEYBOARD, 6, False, 0)])
        blob = encode_macros([macro])
        self.assertEqual(len(blob), MACRO_AREA_SIZE)
        self.assertEqual(list(blob[0:2]), [MACRO_INDEX_SIZE, 0])  # pointer to 64
        self.assertEqual(list(blob[2:4]), [0xFF, 0xFF])  # slot 1 still empty
        self.assertEqual(list(blob[64:68]), [10, 0, STEP_KEYBOARD | STEP_FLAG_PRESS, 6])
        self.assertEqual(list(blob[68:72]), [0, 0, STEP_KEYBOARD | STEP_FLAG_LAST, 6])

    def test_round_trip(self):
        macros = [
            Macro(0, macro_from_sequence("ctrl+c, a", delay=5)),
            Macro(3, macro_from_sequence("enter")),
        ]
        decoded = decode_macros(encode_macros(macros))
        self.assertEqual(
            [s.to_dict() for s in decoded[0].steps],
            [s.to_dict() for s in macros[0].steps],
        )
        self.assertEqual(len(decoded[3].steps), 2)
        self.assertFalse(decoded[1].steps)

    def test_sequence_expands_modifiers(self):
        steps = macro_from_sequence("ctrl+c", delay=7)
        self.assertEqual(
            [(s.code, s.press) for s in steps],
            [(224, True), (6, True), (6, False), (224, False)],
        )
        self.assertTrue(all(s.delay == 7 for s in steps))

    def test_sequence_refuses_non_key_codes(self):
        with self.assertRaises(SdcxError):
            macro_from_sequence("volume_up")

    def test_overflow_is_reported(self):
        huge = Macro(0, [MacroStep(STEP_KEYBOARD, 4, True, 0)] * 2000)
        with self.assertRaises(SdcxError):
            encode_macros([huge])


class TestMacroTransfer(unittest.TestCase):
    def test_write_chunks_at_59(self):
        pad = _fake_pad()
        pad.set_macro_data(bytes(MACRO_AREA_SIZE))
        first = pad.transport.written[0]
        self.assertEqual(first[1:5], [13, 59, 0, 0])
        self.assertEqual(len(first) - 5, 59)
        second = pad.transport.written[1]
        self.assertEqual(second[3:5], [59, 0])

    def test_read_chunks_at_56(self):
        pad = _fake_pad()
        pad.transport.responses = [bytes(64)] * 80
        blob = pad.get_macro_data()
        self.assertEqual(len(blob), MACRO_AREA_SIZE)
        self.assertEqual(pad.transport.written[0], [0x06, 12, 56, 0, 0])
        self.assertEqual(pad.transport.written[1][2:5], [56, 56, 0])


if __name__ == "__main__":
    unittest.main()
