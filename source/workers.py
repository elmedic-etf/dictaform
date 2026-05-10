"""QThread workers that drive the audio→transcription→structuring pipeline.

Two long-lived workers run for the lifetime of a session:

  TranscriberWorker
    * Pulls audio frames off a shared queue (filled by AudioCapture).
    * Feeds them through VadSegmenter and Transcriber.
    * Emits ``segment_ready(text)`` for each finalized utterance, and
      ``flushed()`` after a requested flush completes — used by the main
      window to know when it's safe to save.

  StructurerWorker
    * Receives full-transcript snapshots via ``submit(transcript)``.
    * Coalesces aggressively: if a new transcript arrives while another is
      pending, the older one is dropped — only the latest matters because
      a later transcript is always a superset of the earlier one.
    * Emits ``form_ready(dict)`` with the extracted fields, and ``idle()``
      when its inbox drains (so the main window can save once structuring
      has caught up to the final transcript).

Why one extraction call per VAD segment, not per word? Calling the LLM on
every partial would burn through free-tier rate limits in seconds and produce
flickering form values. Per-utterance is the right grain.
"""
import gc
import logging
import queue

from PySide6.QtCore import QThread, Signal

from .audio_capture import FRAME_BYTES
from .config_loader import FormConfig
from .structurer import Structurer
from .transcriber import Transcriber
from .vad_segmenter import VadSegmenter

logger = logging.getLogger(__name__)


class TranscriberWorker(QThread):
    """Background thread: audio frames → VAD segments → Whisper text."""

    segment_ready = Signal(str)        # One finalized utterance.
    status_changed = Signal(str)       # Free-form status text for the UI.
    flushed = Signal()                 # Emitted after a successful flush().

    def __init__(
        self,
        frame_queue: "queue.Queue[bytes]",
        model_size: str,
        language: str | None,
    ) -> None:
        super().__init__()
        self._queue = frame_queue
        self.model_size = model_size      # Public so MainWindow can detect changes.
        self.language = language
        self._stop_requested = False
        self._flush_requested = False

    # ---- External commands (called from the main thread) -------------------

    def request_stop(self) -> None:
        """Ask the worker to exit at its next loop iteration."""
        self._stop_requested = True

    def request_flush(self) -> None:
        """Force-finalize the current utterance (e.g. on user pressing Stop)."""
        self._flush_requested = True

    # ---- Worker body --------------------------------------------------------

    def run(self) -> None:
        try:
            self.status_changed.emit(f"Loading Whisper '{self.model_size}'…")
            transcriber = Transcriber(self.model_size, self.language)
            segmenter = VadSegmenter()
            self.status_changed.emit("Ready — press Talk to start")
        except Exception as exc:
            logger.exception("Failed to initialize transcription pipeline")
            self.status_changed.emit(f"Init failed: {exc}")
            return

        try:
            while not self._stop_requested:
                try:
                    frame = self._queue.get(timeout=0.1)
                except queue.Empty:
                    # No audio currently flowing — handle pending flush, then loop.
                    if self._flush_requested:
                        self._do_flush(segmenter, transcriber)
                    continue

                utterance = segmenter.push(frame)
                if utterance is not None:
                    self._transcribe_and_emit(transcriber, utterance)

                # If a flush was requested mid-stream, finalize buffered audio.
                if self._flush_requested:
                    self._do_flush(segmenter, transcriber)

            # On stop, drain any in-flight utterance so we don't lose final speech.
            self._do_flush(segmenter, transcriber)
        finally:
            # Drop refs to the Whisper model before the thread exits and force
            # GC. torch's tensor allocators (CUDA caching allocator, etc.) are
            # better released here than during interpreter shutdown.
            del transcriber
            del segmenter
            gc.collect()
            logger.info("TranscriberWorker stopped")

    # ---- Helpers ------------------------------------------------------------

    def _do_flush(self, segmenter: VadSegmenter, transcriber: Transcriber) -> None:
        # Reset the flag *before* doing the work — otherwise a flush mid-loop
        # could be triggered twice.
        self._flush_requested = False
        residual = segmenter.flush()
        # Skip flushes that contain less than ~150 ms of audio: too short to be
        # speech, almost certainly trailing silence the segmenter was holding.
        if residual is not None and len(residual) >= FRAME_BYTES * 5:
            self._transcribe_and_emit(transcriber, residual)
        self.flushed.emit()

    def _transcribe_and_emit(self, transcriber: Transcriber, audio: bytes) -> None:
        try:
            text = transcriber.transcribe(audio)
        except Exception:
            logger.exception("Transcription failed for one segment — skipping")
            return
        if text:
            self.segment_ready.emit(text)


class StructurerWorker(QThread):
    """Background thread: transcript snapshot → OpenRouter → form fields."""

    form_ready = Signal(dict)
    idle = Signal()

    def __init__(self, config: FormConfig) -> None:
        super().__init__()
        self._config = config
        # Use ``None`` as a sentinel to wake the loop on stop.
        self._inbox: "queue.Queue[str | None]" = queue.Queue()
        self._stop_requested = False

    # ---- External commands -------------------------------------------------

    def submit(self, transcript: str) -> None:
        """Queue a transcript for extraction. Drops any older pending work."""
        # Coalesce: only the most recent snapshot matters. This prevents a
        # backlog from forming when LLM responses are slower than utterances.
        try:
            while True:
                self._inbox.get_nowait()
        except queue.Empty:
            pass
        self._inbox.put(transcript)

    def request_stop(self) -> None:
        self._stop_requested = True
        self._inbox.put(None)  # Wake any blocked get().

    # ---- Worker body --------------------------------------------------------

    def run(self) -> None:
        structurer = Structurer(self._config)
        try:
            was_busy = False
            while not self._stop_requested:
                try:
                    transcript = self._inbox.get(timeout=0.2)
                except queue.Empty:
                    # Transition busy→idle exactly once per quiet period.
                    if was_busy:
                        self.idle.emit()
                        was_busy = False
                    continue

                if transcript is None or self._stop_requested:
                    break

                was_busy = True
                fields = structurer.extract(transcript)
                if fields:
                    self.form_ready.emit(fields)
        finally:
            structurer.close()
            logger.info("StructurerWorker stopped")
