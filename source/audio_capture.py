"""Microphone capture using sounddevice.

Captures 16 kHz mono int16 audio in 30 ms frames — the exact format that both
webrtcvad (the segmenter) and faster-whisper (the transcriber) expect.

The PortAudio callback runs on its own thread; we hand off to the rest of the
pipeline through a thread-safe ``queue.Queue`` of raw frame bytes.
"""
import logging
import queue

import sounddevice as sd

logger = logging.getLogger(__name__)

# ---- Audio constants shared across the pipeline ----------------------------
# webrtcvad accepts 8/16/32/48 kHz; Whisper ingests 16 kHz; 16 kHz is the only
# rate that satisfies both, so this is fixed across all stages.
SAMPLE_RATE = 16_000
CHANNELS = 1
DTYPE = "int16"

# webrtcvad accepts 10, 20, or 30 ms frames. 30 ms gives the lowest CPU cost
# without making segmentation feel laggy.
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480 samples
FRAME_BYTES = FRAME_SAMPLES * 2                 # 2 bytes per int16 sample


class AudioCapture:
    """Open the default input device and stream frames into a shared queue."""

    def __init__(self, frame_queue: "queue.Queue[bytes]") -> None:
        self._queue = frame_queue
        self._stream: sd.RawInputStream | None = None

    def start(self) -> None:
        """Open the microphone. Idempotent — calling twice is a no-op."""
        if self._stream is not None:
            return
        logger.info(
            "Opening audio input stream (%d Hz, %d ms frames, mono int16)",
            SAMPLE_RATE,
            FRAME_MS,
        )
        self._stream = sd.RawInputStream(
            samplerate=SAMPLE_RATE,
            blocksize=FRAME_SAMPLES,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=self._on_audio,
        )
        self._stream.start()

    def stop(self) -> None:
        """Close the microphone. Idempotent."""
        if self._stream is None:
            return
        logger.info("Closing audio input stream")
        try:
            self._stream.stop()
            self._stream.close()
        finally:
            self._stream = None

    def _on_audio(self, indata, frames, time_info, status) -> None:
        # PortAudio invokes this on its own real-time thread. Do *no* heavy work
        # here — just copy the buffer into our queue and return.
        if status:
            logger.warning("Audio input status flag: %s", status)
        try:
            self._queue.put_nowait(bytes(indata))
        except queue.Full:
            # Downstream is too slow; drop this frame rather than blocking the
            # audio thread (which would cause an underrun click on the mic).
            logger.warning("Audio queue full — dropping frame")
