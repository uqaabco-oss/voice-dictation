import sys

import pytest

from voice_dictation.paste import TEXT_TYPE, TRANSIENT_TYPE, ClipboardPaster


class FakeItem:
    def __init__(self):
        self.data = {}

    def types(self):
        return list(self.data)

    def dataForType_(self, kind):
        return self.data.get(kind)

    def setData_forType_(self, data, kind):
        self.data[kind] = data

    def setString_forType_(self, text, kind):
        self.data[kind] = text


class FakePasteboard:
    """Mimics the parts of NSPasteboard the paster uses."""

    def __init__(self, items=()):
        self.items = list(items)
        self.count = 0

    def pasteboardItems(self):
        return list(self.items)

    def clearContents(self):
        self.items = []
        self.count += 1

    def writeObjects_(self, items):
        self.items.extend(items)
        return True

    def changeCount(self):
        return self.count

    def text(self):
        return self.items[0].data.get(TEXT_TYPE) if self.items else None


def item(**types):
    it = FakeItem()
    it.data.update(types)
    return it


def make_paster(pasteboard, *, on_paste=None, can_paste=True):
    sent = []

    def send():
        sent.append(pasteboard.text())
        if on_paste:
            on_paste()

    paster = ClipboardPaster(
        pasteboard=pasteboard,
        new_item=FakeItem,
        send_paste=send,
        can_paste=lambda: can_paste,
        sleep=lambda seconds: None,
    )
    return paster, sent


def test_pastes_text_and_restores_previous_clipboard():
    original = [item(**{TEXT_TYPE: "old", "public.html": "<b>old</b>"}), item(**{"x": "2nd"})]
    pasteboard = FakePasteboard(original)
    paster, sent = make_paster(pasteboard)

    assert paster.paste("Hello there.") is True

    assert sent == ["Hello there."]
    restored = [it.data for it in pasteboard.items]
    assert restored == [{TEXT_TYPE: "old", "public.html": "<b>old</b>"}, {"x": "2nd"}]


def test_marks_dictation_as_transient_for_clipboard_managers():
    pasteboard = FakePasteboard()
    seen_types = []
    paster, _ = make_paster(
        pasteboard, on_paste=lambda: seen_types.extend(pasteboard.items[0].types())
    )
    paster.paste("hi")
    assert set(seen_types) == {TEXT_TYPE, TRANSIENT_TYPE}


def test_empty_clipboard_is_restored_empty():
    pasteboard = FakePasteboard()
    paster, sent = make_paster(pasteboard)
    paster.paste("hi")
    assert sent == ["hi"]
    assert pasteboard.items == []


def test_does_not_clobber_a_newer_copy():
    pasteboard = FakePasteboard([item(**{TEXT_TYPE: "old"})])

    def user_copies_something():
        pasteboard.clearContents()
        pasteboard.writeObjects_([item(**{TEXT_TYPE: "newer"})])

    paster, _ = make_paster(pasteboard, on_paste=user_copies_something)
    paster.paste("dictated")
    assert pasteboard.text() == "newer"


def test_without_accessibility_text_is_left_on_clipboard():
    pasteboard = FakePasteboard([item(**{TEXT_TYPE: "old"})])
    paster, sent = make_paster(pasteboard, can_paste=False)
    assert paster.paste("dictated") is False
    assert sent == []
    assert pasteboard.text() == "dictated"


@pytest.mark.skipif(sys.platform != "darwin", reason="needs macOS AppKit")
def test_round_trip_on_a_real_private_pasteboard():
    """Exercise the real NSPasteboard API on a throwaway pasteboard, not the user's."""
    appkit = pytest.importorskip("AppKit")
    pasteboard = appkit.NSPasteboard.pasteboardWithUniqueName()
    html = appkit.NSPasteboardTypeHTML
    try:
        original = appkit.NSPasteboardItem.alloc().init()
        original.setString_forType_("original", TEXT_TYPE)
        original.setString_forType_("<b>original</b>", html)
        pasteboard.clearContents()
        if not pasteboard.writeObjects_([original]):
            pytest.skip("pasteboard server unavailable")

        sent = []
        paster = ClipboardPaster(
            pasteboard=pasteboard,
            send_paste=lambda: sent.append(
                (pasteboard.stringForType_(TEXT_TYPE), set(pasteboard.types()))
            ),
            can_paste=lambda: True,
            sleep=lambda seconds: None,
        )
        assert paster.paste("dictated text") is True

        text, types = sent[0]
        assert text == "dictated text"
        assert TRANSIENT_TYPE in types
        assert pasteboard.stringForType_(TEXT_TYPE) == "original"
        assert pasteboard.stringForType_(html) == "<b>original</b>"
    finally:
        pasteboard.releaseGlobally()
