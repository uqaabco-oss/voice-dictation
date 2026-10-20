"""Paste text into the focused app through the clipboard, then restore it."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

TEXT_TYPE = "public.utf8-plain-text"  # NSPasteboardTypeString
# nspasteboard.org convention: clipboard managers skip transient content, so
# dictations do not pile up in clipboard history.
TRANSIENT_TYPE = "org.nspasteboard.TransientType"
KEYCODE_V = 9  # kVK_ANSI_V

# One clipboard item: {type identifier: NSData}.
SavedItem = dict[str, Any]


def snapshot_clipboard(pasteboard: Any) -> list[SavedItem]:
    """Copy every item and type currently on ``pasteboard``."""
    saved: list[SavedItem] = []
    for item in pasteboard.pasteboardItems() or []:
        types: SavedItem = {}
        for kind in item.types() or []:
            data = item.dataForType_(kind)
            if data is not None:
                types[str(kind)] = data
        if types:
            saved.append(types)
    return saved


def restore_clipboard(pasteboard: Any, saved: list[SavedItem], new_item: Callable[[], Any]) -> None:
    pasteboard.clearContents()
    items = []
    for types in saved:
        item = new_item()
        for kind, data in types.items():
            item.setData_forType_(data, kind)
        items.append(item)
    if items:
        pasteboard.writeObjects_(items)


class ClipboardPaster:
    """Puts text on the clipboard, presses Cmd+V and restores the old clipboard.

    The previous contents are only restored if nothing else has written to the
    clipboard in the meantime, so a copy you make right after dictating wins.
    """

    def __init__(
        self,
        *,
        restore_delay: float = 0.5,
        pasteboard: Any = None,
        new_item: Callable[[], Any] | None = None,
        send_paste: Callable[[], None] | None = None,
        can_paste: Callable[[], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if pasteboard is None or new_item is None:
            from AppKit import NSPasteboard, NSPasteboardItem

            if pasteboard is None:
                pasteboard = NSPasteboard.generalPasteboard()
            if new_item is None:
                new_item = lambda: NSPasteboardItem.alloc().init()  # noqa: E731
        self._pasteboard = pasteboard
        self._new_item = new_item
        self._send_paste = send_paste or post_cmd_v
        self._can_paste = can_paste or accessibility_trusted
        self._restore_delay = restore_delay
        self._sleep = sleep

    def paste(self, text: str) -> bool:
        """Paste ``text``; returns False if it could only be left on the clipboard."""
        pasteboard = self._pasteboard
        saved = snapshot_clipboard(pasteboard)
        pasteboard.clearContents()
        item = self._new_item()
        item.setString_forType_(text, TEXT_TYPE)
        item.setData_forType_(_empty_data(), TRANSIENT_TYPE)
        pasteboard.writeObjects_([item])
        ours = pasteboard.changeCount()

        if not self._can_paste():
            log.warning(
                "Accessibility permission is missing, so the text could not be pasted. "
                "It is on the clipboard: press Cmd+V. See the README for granting access."
            )
            return False

        self._send_paste()
        # The target app reads the clipboard asynchronously when it handles Cmd+V.
        self._sleep(self._restore_delay)
        if pasteboard.changeCount() == ours:
            restore_clipboard(pasteboard, saved, self._new_item)
        else:
            log.info("Clipboard changed while pasting; leaving the new contents in place.")
        return True


def _empty_data() -> Any:
    try:
        from Foundation import NSData
    except ImportError:  # tests on non-macOS use fakes that accept bytes
        return b""
    return NSData.data()


def post_cmd_v() -> None:
    """Send Cmd+V to the focused app (needs Accessibility permission)."""
    import Quartz

    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for key_down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(source, KEYCODE_V, key_down)
        # Set the flags explicitly so modifiers still held (e.g. Shift) don't turn
        # this into a different shortcut.
        Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def accessibility_trusted(prompt: bool = False) -> bool:
    """Whether this process may send keystrokes; optionally show the system prompt."""
    import ApplicationServices as AS

    if prompt:
        return bool(AS.AXIsProcessTrustedWithOptions({AS.kAXTrustedCheckOptionPrompt: True}))
    return bool(AS.AXIsProcessTrusted())
