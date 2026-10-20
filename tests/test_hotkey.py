import sys

import pytest

from voice_dictation import hotkey
from voice_dictation.hotkey import (
    DEVICE_LEFT_ALT,
    DEVICE_RIGHT_ALT,
    EVENT_FLAGS_CHANGED,
    EVENT_KEY_DOWN,
    EVENT_LEFT_MOUSE_DOWN,
    FLAG_MASK_ALTERNATE,
    RIGHT_OPTION_KEYCODE,
    KeyAction,
    RightOptionTap,
    classify,
    right_option_down,
)

LEFT_OPTION_KEYCODE = 58
RIGHT = FLAG_MASK_ALTERNATE | DEVICE_RIGHT_ALT
LEFT = FLAG_MASK_ALTERNATE | DEVICE_LEFT_ALT


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        (0, False),
        (RIGHT, True),
        (LEFT, False),
        (LEFT | RIGHT, True),
        # Virtual keyboards may only set the generic Option bit.
        (FLAG_MASK_ALTERNATE, True),
    ],
)
def test_right_option_down(flags, expected):
    assert right_option_down(flags) is expected


@pytest.mark.parametrize(
    ("event_type", "keycode", "flags", "held", "expected"),
    [
        (EVENT_FLAGS_CHANGED, RIGHT_OPTION_KEYCODE, RIGHT, False, KeyAction.PRESS),
        (EVENT_FLAGS_CHANGED, RIGHT_OPTION_KEYCODE, RIGHT, True, None),
        (EVENT_FLAGS_CHANGED, RIGHT_OPTION_KEYCODE, 0, True, KeyAction.RELEASE),
        (EVENT_FLAGS_CHANGED, RIGHT_OPTION_KEYCODE, 0, False, None),
        # Right Option released while Left Option stays down.
        (EVENT_FLAGS_CHANGED, RIGHT_OPTION_KEYCODE, LEFT, True, KeyAction.RELEASE),
        # Left Option is ignored.
        (EVENT_FLAGS_CHANGED, LEFT_OPTION_KEYCODE, LEFT, False, None),
        # Another key or a click while held turns the hold into a shortcut.
        (EVENT_KEY_DOWN, 14, RIGHT, True, KeyAction.CHORD),
        (EVENT_LEFT_MOUSE_DOWN, 0, RIGHT, True, KeyAction.CHORD),
        (EVENT_KEY_DOWN, 14, 0, False, None),
    ],
)
def test_classify(event_type, keycode, flags, held, expected):
    assert classify(event_type, keycode, flags, held) is expected


def make_tap():
    calls = []
    tap = RightOptionTap(
        on_press=lambda: calls.append("press"),
        on_release=lambda: calls.append("release"),
        on_chord=lambda: calls.append("chord"),
    )
    return tap, calls


def test_tap_reports_hold_and_release():
    tap, calls = make_tap()
    tap.feed(EVENT_FLAGS_CHANGED, RIGHT_OPTION_KEYCODE, RIGHT)
    tap.feed(EVENT_FLAGS_CHANGED, RIGHT_OPTION_KEYCODE, RIGHT)  # duplicate down
    tap.feed(EVENT_FLAGS_CHANGED, RIGHT_OPTION_KEYCODE, 0)
    assert calls == ["press", "release"]


def test_tap_reports_chord_then_release():
    tap, calls = make_tap()
    tap.feed(EVENT_FLAGS_CHANGED, RIGHT_OPTION_KEYCODE, RIGHT)
    tap.feed(EVENT_KEY_DOWN, 14, RIGHT)
    tap.feed(EVENT_FLAGS_CHANGED, RIGHT_OPTION_KEYCODE, 0)
    tap.feed(EVENT_KEY_DOWN, 14, 0)  # typing after release is ignored
    assert calls == ["press", "chord", "release"]


def test_resync_releases_after_missed_key_up():
    tap, calls = make_tap()
    tap.feed(EVENT_FLAGS_CHANGED, RIGHT_OPTION_KEYCODE, RIGHT)
    tap.resync(RIGHT)  # still held: nothing to do
    tap.resync(0)
    tap.resync(0)
    assert calls == ["press", "release"]


@pytest.mark.skipif(sys.platform != "darwin", reason="needs macOS Quartz")
def test_constants_match_quartz():
    quartz = pytest.importorskip("Quartz")
    assert hotkey.EVENT_FLAGS_CHANGED == quartz.kCGEventFlagsChanged
    assert hotkey.EVENT_KEY_DOWN == quartz.kCGEventKeyDown
    assert hotkey.EVENT_LEFT_MOUSE_DOWN == quartz.kCGEventLeftMouseDown
    assert hotkey.EVENT_RIGHT_MOUSE_DOWN == quartz.kCGEventRightMouseDown
    assert hotkey.EVENT_OTHER_MOUSE_DOWN == quartz.kCGEventOtherMouseDown
    assert hotkey.EVENT_TAP_DISABLED_BY_TIMEOUT == quartz.kCGEventTapDisabledByTimeout
    assert hotkey.EVENT_TAP_DISABLED_BY_USER_INPUT == quartz.kCGEventTapDisabledByUserInput
    assert hotkey.FLAG_MASK_ALTERNATE == quartz.kCGEventFlagMaskAlternate


@pytest.mark.skipif(sys.platform != "darwin", reason="needs macOS Quartz")
def test_callback_reads_real_cgevents():
    """Feed synthetic CGEvents through the tap callback (no tap or permission needed)."""
    quartz = pytest.importorskip("Quartz")

    def event(event_type, keycode, flags):
        ev = quartz.CGEventCreateKeyboardEvent(None, keycode, True)
        quartz.CGEventSetType(ev, event_type)
        quartz.CGEventSetFlags(ev, flags)
        return ev

    tap, calls = make_tap()
    for ev_type, keycode, flags in [
        (EVENT_FLAGS_CHANGED, RIGHT_OPTION_KEYCODE, RIGHT),
        (EVENT_FLAGS_CHANGED, RIGHT_OPTION_KEYCODE, 0),
        (EVENT_FLAGS_CHANGED, LEFT_OPTION_KEYCODE, LEFT),
        (EVENT_FLAGS_CHANGED, RIGHT_OPTION_KEYCODE, RIGHT),
        (EVENT_KEY_DOWN, 14, RIGHT),
    ]:
        ev = event(ev_type, keycode, flags)
        assert tap._callback(None, ev_type, ev, None) is ev
    assert calls == ["press", "release", "press", "chord"]
