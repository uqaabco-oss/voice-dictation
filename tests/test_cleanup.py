import pytest

from voice_dictation.cleanup import clean_transcript


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Leading fillers, with and without punctuation.
        ("Um, I think we should ship it.", "I think we should ship it."),
        ("um I think we should ship it", "I think we should ship it."),
        ("Uh, uh, what time is it?", "What time is it?"),
        ("Umm... let me check.", "Let me check."),
        ("Erm, okay.", "Okay."),
        # Mid-sentence fillers take their commas with them.
        ("I was, um, thinking about it.", "I was thinking about it."),
        ("Can you, uh, refactor this function?", "Can you refactor this function?"),
        ("I think um we should go.", "I think we should go."),
        ("I think, um we should go.", "I think we should go."),
        ("I think um, we should go.", "I think we should go."),
        ("It was, uhm... fine.", "It was fine."),
        ("I was um— thinking.", "I was thinking."),
        # ...except after a sentence-opening word, where the comma is normal style.
        ("So, um, what do you think?", "So, what do you think?"),
        ("Okay um, let's go.", "Okay, let's go."),
        ("Done. Well, uh, maybe not.", "Done. Well, maybe not."),
        # Trailing fillers hand their sentence punctuation to the previous word.
        ("I like it, um.", "I like it."),
        ("Is that right, uh?", "Is that right?"),
        ("Ship it um", "Ship it."),
        # A filler opening a later sentence: the next word becomes the sentence start.
        ("That works. Um, so what's next?", "That works. So what's next?"),
        ("That works. Uh. Next one.", "That works. Next one."),
        ("Okay. um, so", "Okay. So."),
        # "you know" as a filler.
        ("You know, I think it's fine.", "I think it's fine."),
        ("It was, you know, really hard.", "It was really hard."),
        ("It's hard, you know.", "It's hard."),
        ("It's hard, you know", "It's hard."),
        ("Well, you know, I tried.", "Well, I tried."),
        ("Fine. You know, whatever.", "Fine. Whatever."),
    ],
)
def test_removes_fillers(raw, expected):
    assert clean_transcript(raw) == expected


@pytest.mark.parametrize(
    "text",
    [
        # "you know" carrying meaning is kept.
        "You know what I mean.",
        "As you know, the build is green.",
        "Do you know where it is?",
        "Ask the people you know.",
        "If you know the answer, tell me.",
        "It's hard, you know?",
        "Did you know, the API changed?",
        # Hyphenated words and acronyms that look like fillers are kept.
        "Uh-huh, that's right.",
        "Uh-oh, the build failed.",
        "She studied at UM and UH.",
        # Words that merely contain filler letters are kept.
        "The umbrella is under the drum.",
        "Uhura was the communications officer.",
        "Hummus is great, er... I mean, fine.",
        "Ah, I see. Hmm, interesting.",
    ],
)
def test_keeps_real_words(text):
    assert clean_transcript(text) == text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  hello   world  ", "Hello world."),
        ("hello\n\tworld", "Hello world."),
        ("hello , world .", "Hello, world."),
        ("wait ... what", "Wait... what."),
    ],
)
def test_collapses_whitespace(raw, expected):
    assert clean_transcript(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("this is a test", "This is a test."),
        ("is this a test?", "Is this a test?"),
        ("this is great!", "This is great!"),
        ("and then...", "And then..."),
        ("and then…", "And then…"),
        ("here is the list:", "Here is the list:"),
        ("trailing comma,", "Trailing comma."),
        ("trailing semicolon;", "Trailing semicolon."),
        ('he said "hello"', 'He said "hello."'),
        ('he said "hello."', 'He said "hello."'),
        ("(see the docs)", "(See the docs.)"),
        ('"quoted start', '"Quoted start.'),
        ("version 3.12", "Version 3.12."),
    ],
)
def test_terminal_punctuation_and_capitalization(raw, expected):
    assert clean_transcript(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("iPhone sales are up", "iPhone sales are up."),
        ("macOS is updated.", "macOS is updated."),
        ("Um, iPhone sales are up.", "iPhone sales are up."),
        ("42 is the answer", "42 is the answer."),
        ("i think so", "I think so."),
    ],
)
def test_capitalization_respects_existing_casing(raw, expected):
    assert clean_transcript(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "Um.", "uh, um...", "You know.", "...", " . "])
def test_empty_after_cleanup(raw):
    assert clean_transcript(raw) == ""


def test_is_idempotent():
    samples = [
        "Um, so, uh, I was, you know, thinking we could, um, ship it?",
        "That works. Um, so what's next",
        'he said "hello" um, then left',
    ]
    for raw in samples:
        once = clean_transcript(raw)
        assert clean_transcript(once) == once
