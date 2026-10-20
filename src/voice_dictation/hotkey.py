"""Global Right Option hold/release detection with a macOS event tap."""

from __future__ import annotations

import logging
from collections.abc import Callable
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)

RIGHT_OPTION_KEYCODE = 61  # kVK_RightOption
# Device-dependent modifier bits from IOKit's NX_DEVICE*ALTKEYMASK; they tell
# the left and right Option keys apart.
DEVICE_LEFT_ALT = 0x00000020
DEVICE_RIGHT_ALT = 0x00000040
FLAG_MASK_ALTERNATE = 0x00080000  # kCGEventFlagMaskAlternate
# kCGEventSourceUserData value on the events this app posts itself (its Cmd+V),
# so they are never mistaken for the user pressing a key.
SYNTHETIC_EVENT_TAG = 0x766F6963  # "voic"

# CGEventType values.
EVENT_LEFT_MOUSE_DOWN = 1
EVENT_RIGHT_MOUSE_DOWN = 3
EVENT_KEY_DOWN = 10
EVENT_FLAGS_CHANGED = 12
EVENT_OTHER_MOUSE_DOWN = 25
EVENT_TAP_DISABLED_BY_TIMEOUT = 0xFFFFFFFE
EVENT_TAP_DISABLED_BY_USER_INPUT = 0xFFFFFFFF

_CHORD_EVENTS = frozenset(
    {EVENT_KEY_DOWN, EVENT_LEFT_MOUSE_DOWN, EVENT_RIGHT_MOUSE_DOWN, EVENT_OTHER_MOUSE_DOWN}
)


class KeyAction(Enum):
    PRESS = "press"
    RELEASE = "release"
    CHORD = "chord"  # another key or click while Right Option is held


def right_option_down(flags: int) -> bool:
    """Whether Right Option is held, given CGEvent modifier flags."""
    if flags & (DEVICE_LEFT_ALT | DEVICE_RIGHT_ALT):
        return bool(flags & DEVICE_RIGHT_ALT)
    # Some virtual keyboards only set the generic Option flag.
    return bool(flags & FLAG_MASK_ALTERNATE)


def classify(event_type: int, keycode: int, flags: int, held: bool) -> KeyAction | None:
    """Turn a raw event into a Right Option action, given whether it is held."""
    if event_type == EVENT_FLAGS_CHANGED and keycode == RIGHT_OPTION_KEYCODE:
        down = right_option_down(flags)
        if down and not held:
            return KeyAction.PRESS
        if held and not down:
            return KeyAction.RELEASE
        return None
    if held and event_type in _CHORD_EVENTS:
        return KeyAction.CHORD
    return None


class RightOptionTap:
    """Listen-only event tap that reports Right Option press/release.

    Holding Right Option together with another key or a mouse click (typing an
    accented character, Option-click) cancels the dictation instead.
    Callbacks run on the thread that runs the CFRunLoop (the main thread).
    """

    def __init__(
        self,
        on_press: Callable[[], None],
        on_release: Callable[[], None],
        on_chord: Callable[[], None],
    ) -> None:
        self._handlers = {
            KeyAction.PRESS: on_press,
            KeyAction.RELEASE: on_release,
            KeyAction.CHORD: on_chord,
        }
        self._held = False
        self._tap: Any = None
        self._source: Any = None

    def start(self) -> bool:
        """Install the tap on the current run loop; False if permission is missing."""
        import Quartz

        mask = 0
        for event_type in (EVENT_FLAGS_CHANGED, *_CHORD_EVENTS):
            mask |= Quartz.CGEventMaskBit(event_type)
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            self._callback,
            None,
        )
        if tap is None:
            return False
        self._tap = tap
        self._source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        Quartz.CFRunLoopAddSource(
            Quartz.CFRunLoopGetCurrent(), self._source, Quartz.kCFRunLoopCommonModes
        )
        Quartz.CGEventTapEnable(tap, True)
        return True

    def stop(self) -> None:
        import Quartz

        if self._tap is not None:
            Quartz.CGEventTapEnable(self._tap, False)
            Quartz.CFRunLoopRemoveSource(
                Quartz.CFRunLoopGetCurrent(), self._source, Quartz.kCFRunLoopCommonModes
            )
            self._tap = self._source = None

    def _callback(self, proxy: Any, event_type: int, event: Any, refcon: Any) -> Any:
        try:
            self._handle(event_type, event)
        except Exception:  # never let an exception escape into the event tap
            log.exception("Error handling keyboard event")
        return event

    def feed(self, event_type: int, keycode: int, flags: int) -> None:
        """Process one keyboard/mouse event."""
        action = classify(event_type, keycode, flags, self._held)
        if action is not None:
            self._dispatch(action)

    def resync(self, flags: int) -> None:
        """Catch up with the current modifier state after events may have been missed."""
        if self._held and not right_option_down(flags):
            self._dispatch(KeyAction.RELEASE)

    def _handle(self, event_type: int, event: Any) -> None:
        import Quartz

        if event_type in (EVENT_TAP_DISABLED_BY_TIMEOUT, EVENT_TAP_DISABLED_BY_USER_INPUT):
            # macOS disables taps that are slow or interrupted; turn it back on and
            # catch up on a release we may have missed meanwhile.
            log.info("Keyboard listener was paused by macOS; re-enabling it.")
            Quartz.CGEventTapEnable(self._tap, True)
            self.resync(
                Quartz.CGEventSourceFlagsState(Quartz.kCGEventSourceStateCombinedSessionState)
            )
            return
        if (
            Quartz.CGEventGetIntegerValueField(event, Quartz.kCGEventSourceUserData)
            == SYNTHETIC_EVENT_TAG
        ):
            return
        keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        self.feed(event_type, keycode, Quartz.CGEventGetFlags(event))

    def _dispatch(self, action: KeyAction) -> None:
        if action is KeyAction.PRESS:
            self._held = True
        elif action is KeyAction.RELEASE:
            self._held = False
        self._handlers[action]()


def input_monitoring_granted(prompt: bool = False) -> bool:
    """Whether this process may listen to the keyboard; optionally show the system prompt."""
    import Quartz

    if Quartz.CGPreflightListenEventAccess():
        return True
    if prompt:
        Quartz.CGRequestListenEventAccess()
    return False
