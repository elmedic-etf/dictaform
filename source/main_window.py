"""Top-level Qt window — wires the UI to the pipeline workers.

Recording lifecycle
-------------------
The user toggles a single Talk/Stop button. We deliberately avoid restarting
the (slow-loading) Whisper model on every click: the TranscriberWorker stays
alive across sessions and is only rebuilt if the user changes the model size
or language between sessions.

Stop sequence (signal-driven, not blocking the UI thread)
---------------------------------------------------------
  1. User clicks Stop.
  2. We close the microphone and ask the transcriber to flush its buffered audio.
  3. When the transcriber emits ``flushed``, we send the final transcript to
     the structurer for one last extraction pass.
  4. When the structurer emits ``idle``, we save the JSON file and re-enable
     the UI.
  5. A safety timer guarantees we save (and re-enable the UI) within 15 s
     even if a signal goes missing.
"""
import logging
import queue

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .audio_capture import AudioCapture
from .config_loader import FormConfig
from .form_widget import FormView
from .session_saver import save_session
from .theme import repolish
from .transcript_widget import TranscriptView
from .workers import StructurerWorker, TranscriberWorker

logger = logging.getLogger(__name__)


# Whisper model sizes from smallest/fastest to largest/most accurate.
# openai-whisper resolves "large" to the latest large-v3 weights.
WHISPER_MODELS: tuple[str, ...] = ("small", "medium", "large")
DEFAULT_MODEL = "small"

# (UI label, Whisper language code or None for auto-detect).
LANGUAGES: tuple[tuple[str, str | None], ...] = (
    ("Auto-detect", None),
    ("English", "en"),
    ("Serbian", "sr"),
)

# Bound on the audio queue: ~30 s of buffered frames at 30 ms each. If the
# transcriber falls more than half a minute behind, dropping frames is the
# right behavior — the user is likely no longer talking about the same thing.
AUDIO_QUEUE_MAX = 1000

# Hard upper bound on how long we wait for the post-Stop flush + final
# structuring before saving. Real cases finish in ~2–6 s; this is a safety net.
SAVE_DEADLINE_MS = 15_000


class MainWindow(QMainWindow):
    def __init__(self, config: FormConfig) -> None:
        super().__init__()
        self.config = config
        self.setWindowTitle("Medical Dictation Transcriber")
        self.resize(1200, 700)

        # Audio frames flow capture → transcriber via this queue. Bounded so a
        # slow transcriber can't grow memory without limit.
        self._audio_queue: "queue.Queue[bytes]" = queue.Queue(maxsize=AUDIO_QUEUE_MAX)

        self._capture: AudioCapture | None = None
        self._transcriber: TranscriberWorker | None = None
        self._structurer: StructurerWorker | None = None

        # Recording state. ``_finalizing`` is True between Stop click and the
        # final save — we use it to gate which signal events trigger a save.
        self._recording = False
        self._finalizing = False
        self._save_done = False

        self._build_ui()
        self._start_structurer()

    # ---- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        # Generous outer margins so cards float in a calm field of bg colour.
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(16)

        layout.addLayout(self._build_header())

        # Split: transcript on the left, form on the right.
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(10)
        splitter.setChildrenCollapsible(False)
        self.transcript_view = TranscriptView()
        self.transcript_view.setObjectName("transcriptView")
        self.form_view = FormView(self.config)
        splitter.addWidget(self.transcript_view)
        splitter.addWidget(self.form_view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([640, 560])
        layout.addWidget(splitter, stretch=1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Idle — press Talk to start")

    def _build_header(self) -> QHBoxLayout:
        """Top bar: title block on the left, settings + Talk button on the right."""
        bar = QHBoxLayout()
        bar.setSpacing(12)

        # Title block.
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("Medical Dictation")
        title.setObjectName("appTitle")
        subtitle = QLabel("Whisper transcription · OpenRouter structuring")
        subtitle.setObjectName("appSubtitle")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        bar.addLayout(title_col)

        bar.addStretch(1)

        # Settings: language + model.
        lang_label = QLabel("LANGUAGE")
        lang_label.setObjectName("sectionLabel")
        bar.addWidget(lang_label)
        self.language_combo = QComboBox()
        for label, _code in LANGUAGES:
            self.language_combo.addItem(label)
        bar.addWidget(self.language_combo)

        bar.addSpacing(12)
        model_label = QLabel("MODEL")
        model_label.setObjectName("sectionLabel")
        bar.addWidget(model_label)
        self.model_combo = QComboBox()
        for name in WHISPER_MODELS:
            self.model_combo.addItem(name)
        self.model_combo.setCurrentText(DEFAULT_MODEL)
        bar.addWidget(self.model_combo)

        bar.addSpacing(16)
        self.talk_button = QPushButton("Talk")
        self.talk_button.setObjectName("talkButton")
        # The "recording" dynamic property drives the stylesheet's red state.
        self.talk_button.setProperty("recording", False)
        self.talk_button.clicked.connect(self._on_talk_clicked)
        bar.addWidget(self.talk_button)

        return bar

    def _set_talk_recording(self, recording: bool) -> None:
        """Toggle the Talk button's recording state (label + stylesheet colour)."""
        self.talk_button.setText("Stop" if recording else "Talk")
        self.talk_button.setProperty("recording", recording)
        repolish(self.talk_button)

    # ---- Worker lifecycle --------------------------------------------------

    def _start_structurer(self) -> None:
        """Start the long-lived OpenRouter worker once at app startup."""
        self._structurer = StructurerWorker(self.config)
        self._structurer.form_ready.connect(self.form_view.apply_update)
        self._structurer.idle.connect(self._on_structurer_idle)
        self._structurer.start()

    def _ensure_transcriber(self, model_size: str, language: str | None) -> None:
        """Create or recreate the transcriber when settings differ from current."""
        same = (
            self._transcriber is not None
            and self._transcriber.model_size == model_size
            and self._transcriber.language == language
        )
        if same:
            return

        if self._transcriber is not None:
            logger.info("Recreating transcriber (settings changed)")
            self._transcriber.request_stop()
            if not self._transcriber.wait(15_000):
                # Same reasoning as closeEvent: an in-flight transcribe can
                # hold the thread well past a few-second wait. Terminate
                # rather than dereference a still-running QThread.
                logger.warning("Previous transcriber did not exit — terminating")
                self._transcriber.terminate()
                self._transcriber.wait(2000)

        self._transcriber = TranscriberWorker(self._audio_queue, model_size, language)
        self._transcriber.segment_ready.connect(self._on_segment)
        self._transcriber.status_changed.connect(self.statusBar().showMessage)
        self._transcriber.flushed.connect(self._on_transcriber_flushed)
        self._transcriber.start()

    # ---- Talk / Stop -------------------------------------------------------

    def _on_talk_clicked(self) -> None:
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        # Reset prior session state so a new dictation starts clean.
        self.transcript_view.clear_all()
        self.form_view.clear_all()
        self._drain_audio_queue()

        model_size = self.model_combo.currentText()
        language = LANGUAGES[self.language_combo.currentIndex()][1]
        logger.info(
            "Starting recording: whisper=%s lang=%s",
            model_size,
            language or "auto",
        )

        self._ensure_transcriber(model_size, language)

        try:
            self._capture = AudioCapture(self._audio_queue)
            self._capture.start()
        except Exception as exc:
            logger.exception("Failed to open microphone")
            QMessageBox.critical(self, "Microphone error", str(exc))
            return

        self._recording = True
        self._finalizing = False
        self._save_done = False
        self._set_talk_recording(True)
        self.model_combo.setEnabled(False)
        self.language_combo.setEnabled(False)
        self.statusBar().showMessage("Recording — speak now")

    def _stop_recording(self) -> None:
        if not self._recording:
            return
        logger.info("Stopping recording — flushing pipeline")
        self._recording = False
        self._finalizing = True
        self._save_done = False

        # Disable Talk while we finalize so the user can't start a new session
        # before the JSON has been written.
        self.talk_button.setEnabled(False)
        self.statusBar().showMessage("Finalizing — please wait…")

        if self._capture is not None:
            self._capture.stop()
            self._capture = None

        if self._transcriber is not None:
            self._transcriber.request_flush()
        else:
            # No transcriber means nothing to flush; save immediately.
            self._save_and_reset()

        # Safety net: if the chain of signals stalls, save anyway.
        QTimer.singleShot(SAVE_DEADLINE_MS, self._save_and_reset)

    # ---- Pipeline signal handlers ------------------------------------------

    def _on_segment(self, text: str) -> None:
        """A finalized utterance arrived from the transcriber."""
        self.transcript_view.append_segment(text)
        if self._structurer is not None:
            # Send the *cumulative* transcript every time. Free-tier models do
            # better with a full snapshot than with incremental patches.
            self._structurer.submit(self.transcript_view.full_text())

    def _on_transcriber_flushed(self) -> None:
        """The transcriber finished its post-Stop flush — fire one last extract."""
        if not self._finalizing:
            return  # An incidental flush during recording — nothing to do.

        full = self.transcript_view.full_text()
        if full and self._structurer is not None:
            self._structurer.submit(full)
        else:
            # Nothing to extract; save what we have.
            self._save_and_reset()

    def _on_structurer_idle(self) -> None:
        """The structurer finished its work queue."""
        # Only save during the Stop sequence, not after every routine extraction.
        if self._finalizing:
            self._save_and_reset()

    # ---- Save + reset ------------------------------------------------------

    def _save_and_reset(self) -> None:
        """Persist the session and re-enable the UI. Idempotent."""
        if self._save_done:
            return
        self._save_done = True
        self._finalizing = False

        full = self.transcript_view.full_text()
        fields = self.form_view.current_values()
        try:
            path = save_session(full, fields)
            self.statusBar().showMessage(f"Saved: {path}")
        except Exception as exc:
            logger.exception("Failed to save session")
            self.statusBar().showMessage(f"Save failed: {exc}")

        self._set_talk_recording(False)
        self.talk_button.setEnabled(True)
        self.model_combo.setEnabled(True)
        self.language_combo.setEnabled(True)

    # ---- Misc helpers ------------------------------------------------------

    def _drain_audio_queue(self) -> None:
        """Discard any leftover frames from a previous session."""
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

    def closeEvent(self, event) -> None:
        """Tear workers down cleanly on app close. We do NOT auto-save here —
        the user must press Stop explicitly to commit a session.

        Shutdown ordering:
          1. Close the mic immediately so no new audio enters the pipeline.
          2. Signal *both* workers to stop, then wait on them in parallel.
             Sequential waits would compound — and an in-flight Whisper
             ``transcribe()`` call on the medium/large model can hold the
             worker thread for 10+ seconds.
          3. If a worker still hasn't exited after the grace window, call
             ``terminate()``. We can't cancel a running Whisper decode or an
             httpx request cleanly, so for app close that's the only option
             — better than aborting with "QThread destroyed while running".
        """
        logger.info("Window closing — shutting down pipeline")
        if self._capture is not None:
            self._capture.stop()
            self._capture = None

        workers = [
            ("transcriber", self._transcriber),
            ("structurer", self._structurer),
        ]
        for name, worker in workers:
            if worker is not None:
                worker.request_stop()

        # 15 s covers a long medium-model decode plus the 30 s httpx timeout
        # being interrupted by the stop flag; in practice both finish well
        # under it. terminate() catches edge cases (model still loading on
        # quick-close, or a hung HTTP call).
        for name, worker in workers:
            if worker is None:
                continue
            if not worker.wait(15_000):
                logger.warning("%s did not exit within 15s — terminating", name)
                worker.terminate()
                worker.wait(2000)

        self._transcriber = None
        self._structurer = None
        super().closeEvent(event)
