import math

import numpy as np
import pytest

from voice_dictation.audio import Recorder, loudest_frame_dbfs
from voice_dictation.config import SAMPLE_RATE


class FakeStream:
    def __init__(self, sample_rate, callback):
        self.sample_rate = sample_rate
        self.callback = callback
        self.started = self.stopped = self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


def make_recorder():
    streams = []

    def factory(sample_rate, callback):
        streams.append(FakeStream(sample_rate, callback))
        return streams[-1]

    return Recorder(stream_factory=factory), streams


def test_records_between_start_and_stop():
    recorder, streams = make_recorder()
    recorder.start()
    assert recorder.recording
    stream = streams[0]
    assert stream.started and stream.sample_rate == SAMPLE_RATE

    block = np.arange(6, dtype=np.float32).reshape(3, 2)  # (frames, channels)
    stream.callback(block, 3, None, None)
    block[:] = -1  # PortAudio reuses its buffer; the recorder must have copied it
    stream.callback(np.full((2, 1), 9, dtype=np.float32), 2, None, None)

    audio = recorder.stop()
    assert not recorder.recording
    assert stream.stopped and stream.closed
    assert audio.dtype == np.float32
    assert audio.tolist() == [0, 2, 4, 9, 9]


def test_each_recording_starts_fresh():
    recorder, streams = make_recorder()
    recorder.start()
    streams[0].callback(np.ones((4, 1), dtype=np.float32), 4, None, None)
    recorder.stop()
    recorder.start()
    recorder.start()  # already recording: no second stream
    assert len(streams) == 2
    assert recorder.stop().size == 0


def test_stop_without_start_returns_empty():
    recorder, _ = make_recorder()
    assert recorder.stop().size == 0


@pytest.mark.parametrize(
    ("audio", "expected"),
    [
        (np.zeros(0, dtype=np.float32), -math.inf),
        (np.zeros(SAMPLE_RATE, dtype=np.float32), -math.inf),
        (np.ones(SAMPLE_RATE, dtype=np.float32), 0.0),
        (np.full(SAMPLE_RATE, 0.01, dtype=np.float32), -40.0),
        (np.full(100, 0.1, dtype=np.float32), -20.0),  # shorter than one frame
    ],
)
def test_loudest_frame_dbfs(audio, expected):
    assert loudest_frame_dbfs(audio) == pytest.approx(expected, abs=0.01)


def test_loudest_frame_finds_a_short_loud_burst():
    audio = np.full(SAMPLE_RATE * 2, 0.001, dtype=np.float32)
    audio[SAMPLE_RATE : SAMPLE_RATE + 800] = 0.5
    assert loudest_frame_dbfs(audio) == pytest.approx(20 * math.log10(0.5), abs=0.01)


def test_failed_start_closes_stream_and_stays_idle():
    class FailingStream(FakeStream):
        def start(self):
            raise OSError("device busy")

    streams = []

    def factory(sample_rate, callback):
        streams.append(FailingStream(sample_rate, callback))
        return streams[-1]

    recorder = Recorder(stream_factory=factory)
    with pytest.raises(OSError):
        recorder.start()
    assert streams[0].closed
    assert not recorder.recording
