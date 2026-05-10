"""Left-hand panel: a read-only, append-only view of the transcript.

Each finalized utterance is appended on its own line so the user can visually
distinguish pauses. The view auto-scrolls to keep the latest text in sight.
"""
from PySide6.QtWidgets import QPlainTextEdit


class TranscriptView(QPlainTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setPlaceholderText("Press Talk and start dictating — your speech will appear here…")
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)

    def append_segment(self, text: str) -> None:
        """Append one utterance, separated from the previous by a blank line."""
        if not text:
            return
        if self.toPlainText():
            self.appendPlainText("")  # Visual separator between utterances.
        self.appendPlainText(text)
        # Scroll to bottom so the latest line is always visible.
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def full_text(self) -> str:
        """Return the entire transcript joined into a single string."""
        return self.toPlainText().strip()

    def clear_all(self) -> None:
        self.clear()
