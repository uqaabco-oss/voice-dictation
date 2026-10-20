import threading

import numpy as np

from voice_dictation.config import SAMPLE_RATE, Settings
from voice_dictation.controller import DictationController, DictationPipeline, Worker
from voice_dictation.transcriber import Transcript


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class FakeRecorder:
    def __init__(self, audio=None, fail=False):
        self.audio = np.ones(SAMPLE_RATE, dtype=np.float32) if audio is None else audio
        self.fail = fail
        self.starts = 0
        self.stops = 0

    def start(self):
        if self.fail:
            raise OSError("no input device")
        self.starts += 1

    def stop(self):
        self.stops += 1
        return self.audio


class FakeSounds:
    def __init__(self):
        self.played = []

    def start(self):
        self.played.append("start")

    def stop(self):
        self.played.append("stop")

    def error(self):
        self.played.append("error")


class FakeTranscriber:
    def __init__(self, text="um, hello there"):
        self.result = Transcript(text)
        self.calls = 0
        self.loaded = False

    def load(self):
        self.loaded = True

    def transcribe(self, audio):
        self.calls += 1
        return self.result


class FakePaster:
    def __init__(self, ok=True):
        self.ok = ok
        self.pasted = []

    def paste(self, text):
        self.pasted.append(text)
        return self.ok


def speech(seconds=1.0, amplitude=0.1):
    t = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


# --- DictationController -------------------------------------------------------


def make_controller(recorder=None, settings=None):
    clock = FakeClock()
    sounds = FakeSounds()
    submitted = []
    recorder = recorder or FakeRecorder()
    controller = DictationController(
        recorder, submitted.append, sounds, settings or Settings(), clock=clock
    )
    return controller, recorder, sounds, submitted, clock


def test_hold_and_release_submits_audio():
    controller, recorder, sounds, submitted, clock = make_controller()
    controller.press()
    assert controller.recording
    clock.now += 1.5
    controller.release()
    assert not controller.recording
    assert len(submitted) == 1 and submitted[0] is recorder.audio
    assert sounds.played == ["start", "stop"]


def test_short_tap_is_ignored():
    controller, recorder, sounds, submitted, clock = make_controller()
    controller.press()
    clock.now += 0.2
    controller.release()
    assert submitted == []
    assert recorder.stops == 1  # the microphone is still closed
    assert sounds.played == ["start"]


def test_repeated_press_and_stray_release_are_harmless():
    controller, recorder, sounds, submitted, clock = make_controller()
    controller.release()
    controller.press()
    controller.press()
    clock.now += 1
    controller.release()
    controller.release()
    assert recorder.starts == 1 and recorder.stops == 1
    assert len(submitted) == 1


def test_cancel_discards_recording():
    controller, recorder, sounds, submitted, clock = make_controller()
    controller.press()
    clock.now += 2
    controller.cancel()
    controller.release()
    assert submitted == []
    assert recorder.stops == 1
    assert sounds.played == ["start"]


def test_recorder_failure_plays_error_and_stays_idle():
    controller, recorder, sounds, submitted, clock = make_controller(FakeRecorder(fail=True))
    controller.press()
    assert not controller.recording
    assert sounds.played == ["error"]


def test_tick_stops_overlong_recording():
    settings = Settings(max_record_seconds=10)
    controller, recorder, sounds, submitted, clock = make_controller(settings=settings)
    controller.press()
    clock.now += 5
    controller.tick()
    assert controller.recording
    clock.now += 5
    controller.tick()
    assert not controller.recording
    assert len(submitted) == 1


# --- DictationPipeline ---------------------------------------------------------


def make_pipeline(transcriber=None, paster=None, settings=None):
    transcriber = transcriber or FakeTranscriber()
    paster = paster or FakePaster()
    sounds = FakeSounds()
    pipeline = DictationPipeline(transcriber, paster, sounds, settings or Settings())
    return pipeline, transcriber, paster, sounds


def test_pipeline_pastes_cleaned_text():
    pipeline, transcriber, paster, sounds = make_pipeline()
    assert pipeline.process(speech()) == "Hello there."
    assert paster.pasted == ["Hello there."]
    assert sounds.played == []


def test_pipeline_skips_digital_silence_with_error_sound():
    pipeline, transcriber, paster, sounds = make_pipeline()
    assert pipeline.process(np.zeros(SAMPLE_RATE, dtype=np.float32)) is None
    assert transcriber.calls == 0
    assert sounds.played == ["error"]


def test_pipeline_skips_quiet_audio():
    pipeline, transcriber, paster, sounds = make_pipeline()
    assert pipeline.process(speech(amplitude=0.0005)) is None
    assert transcriber.calls == 0
    assert sounds.played == []


def test_start_sound_bleed_does_not_count_as_speech():
    audio = speech(amplitude=0.0005)
    audio[: SAMPLE_RATE // 10] = 0.5  # loud click in the first 100 ms only
    pipeline, transcriber, paster, sounds = make_pipeline()
    assert pipeline.process(audio) is None
    assert transcriber.calls == 0


def test_pipeline_skips_empty_transcript():
    pipeline, transcriber, paster, sounds = make_pipeline(FakeTranscriber(text=" Um. "))
    assert pipeline.process(speech()) is None
    assert paster.pasted == []


def test_pipeline_signals_paste_failure():
    pipeline, transcriber, paster, sounds = make_pipeline(paster=FakePaster(ok=False))
    pipeline.process(speech())
    assert sounds.played == ["error"]


# --- Worker --------------------------------------------------------------------


def test_worker_loads_model_then_processes_in_order():
    transcriber = FakeTranscriber()
    done = threading.Event()
    seen = []

    class RecordingPipeline:
        def process(self, audio):
            seen.append(float(audio[0]))
            if len(seen) == 2:
                done.set()

    worker = Worker(transcriber, RecordingPipeline())
    worker.start()
    assert worker.ready.wait(5)
    assert transcriber.loaded and worker.load_error is None
    worker.submit(np.full(4, 1.0, dtype=np.float32))
    worker.submit(np.full(4, 2.0, dtype=np.float32))
    assert done.wait(5)
    worker.stop()
    assert seen == [1.0, 2.0]


def test_worker_reports_load_error():
    class BrokenTranscriber(FakeTranscriber):
        def load(self):
            raise RuntimeError("download failed")

    worker = Worker(BrokenTranscriber(), None)
    worker.start()
    assert worker.ready.wait(5)
    assert isinstance(worker.load_error, RuntimeError)


def test_worker_survives_a_failing_dictation():
    done = threading.Event()
    calls = []

    class FlakyPipeline:
        def process(self, audio):
            calls.append(1)
            if len(calls) == 1:
                raise ValueError("boom")
            done.set()

    worker = Worker(FakeTranscriber(), FlakyPipeline())
    worker.start()
    worker.submit(np.zeros(1, dtype=np.float32))
    worker.submit(np.zeros(1, dtype=np.float32))
    assert done.wait(5)
    worker.stop()
    assert len(calls) == 2
