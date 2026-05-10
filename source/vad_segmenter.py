"""Voice-activity-detection-driven utterance segmentation.

Strategy:
  * Each incoming 30 ms frame is classified speech / non-speech by webrtcvad.
  * We watch a small rolling window for speech onset (avoids cutting off the
    first phoneme) and a longer silence run for end-of-utterance.
  * When the speaker pauses long enough we emit the buffered audio as a single
    utterance for the transcriber to process.

Why segment at all? faster-whisper is most accurate on natural speech units
(a clause, a sentence). Sending fixed-length windows would split words; sending
the whole session would never produce intermediate results. VAD-driven
segmentation is the standard middle ground.
"""
import logging
from collections import deque

import webrtcvad

from .audio_capture import FRAME_BYTES, SAMPLE_RATE

logger = logging.getLogger(__name__)


class VadSegmenter:
    """Stateful segmenter — feed it 30 ms frames, get utterances back."""

    # ~150 ms of speech in the rolling window before we declare an utterance has
    # started. Short enough to feel responsive, long enough to ignore mic clicks.
    MIN_VOICED_FRAMES = 5

    # ~750 ms of silence before we declare an utterance has ended. Doctors
    # typically pause longer between thoughts than within them.
    SILENCE_FRAMES = 25

    # Hard ceiling so a long monologue still produces intermediate results
    # (~30 s). Otherwise the user would see nothing on screen for ages.
    MAX_UTTERANCE_FRAMES = 1000

    def __init__(self, aggressiveness: int = 3) -> None:
        # webrtcvad aggressiveness 0..3 — higher = more aggressive at marking
        # frames as non-speech. We use 3 (the strictest) because the
        # transcriber's hallucination cost from accepting silence as speech is
        # much higher than the (small) risk of clipping the start of a soft
        # word — the segmenter's pre-utterance ring buffer offsets the latter.
        self._vad = webrtcvad.Vad(aggressiveness)

        # Rolling window of recent (frame, is_speech) pairs while we wait for
        # speech onset. Sized to the speech-onset threshold so we can pre-pend
        # those frames once an utterance starts (saving the first syllable).
        self._ring: deque[tuple[bytes, bool]] = deque(maxlen=self.MIN_VOICED_FRAMES)

        # Frames belonging to the current in-flight utterance.
        self._utterance: list[bytes] = []
        self._silence_run = 0

    def push(self, frame: bytes) -> bytes | None:
        """Feed a single frame. Returns finished utterance bytes, or None."""
        if len(frame) != FRAME_BYTES:
            logger.warning("Unexpected frame size: %d bytes (want %d)", len(frame), FRAME_BYTES)
            return None
        is_speech = self._vad.is_speech(frame, SAMPLE_RATE)

        if not self._utterance:
            # Pre-utterance state: looking for speech onset.
            self._ring.append((frame, is_speech))
            voiced = sum(1 for _, s in self._ring if s)
            if voiced >= self.MIN_VOICED_FRAMES:
                # Speech detected — start an utterance, including the buffered
                # frames so the onset isn't clipped.
                self._utterance = [f for f, _ in self._ring]
                self._ring.clear()
                self._silence_run = 0
            return None

        # In-utterance state: append every frame, watch for trailing silence.
        self._utterance.append(frame)
        if is_speech:
            self._silence_run = 0
        else:
            self._silence_run += 1

        end_of_utterance = (
            self._silence_run >= self.SILENCE_FRAMES
            or len(self._utterance) >= self.MAX_UTTERANCE_FRAMES
        )
        if end_of_utterance:
            return self._finalize()
        return None

    def flush(self) -> bytes | None:
        """Force-finalize the current utterance, e.g. when the user stops."""
        if not self._utterance:
            return None
        return self._finalize()

    def _finalize(self) -> bytes:
        data = b"".join(self._utterance)
        self._utterance = []
        self._silence_run = 0
        self._ring.clear()
        return data
