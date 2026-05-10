"""Right-hand panel: the structured form, dynamically built from FormConfig.

User-edit protection
--------------------
If the user manually edits a field, we mark it ``dirty`` and the LLM is no
longer allowed to overwrite it for the rest of the session. Without this, an
LLM call triggered after the user fixed a transcription error would clobber
the correction. The dirty flag is reset only when ``clear_all()`` runs at the
start of a new session.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .config_loader import Field, FormConfig

# Type alias for any editor widget the form can hold.
Editor = QLineEdit | QSpinBox | QPlainTextEdit

# Minimum height for multi-line text editors (~4 lines on default fonts).
TEXT_FIELD_MIN_HEIGHT = 110


class FormView(QWidget):
    def __init__(self, config: FormConfig) -> None:
        super().__init__()
        self.config = config
        # Editor widget per field, indexed by field key.
        self._editors: dict[str, Editor] = {}
        # True if the user has typed in this field manually (and we should not
        # let the LLM overwrite it).
        self._user_dirty: dict[str, bool] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(14)
        for group in config.groups:
            box = QGroupBox(group.name)
            form = QFormLayout(box)
            # Roomy form rows so the cards don't feel cramped.
            form.setHorizontalSpacing(14)
            form.setVerticalSpacing(10)
            form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
            form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
            for field in group.fields:
                editor = self._make_editor(field)
                self._editors[field.key] = editor
                self._user_dirty[field.key] = False
                form.addRow(field.label, editor)
            outer.addWidget(box)
        outer.addStretch(1)

    # ---------- Editor construction -----------------------------------------

    def _make_editor(self, field: Field) -> Editor:
        if field.type == "integer":
            spin = QSpinBox()
            # 0..9999 covers any plausible year of birth or count. Keep a
            # field's "no value" as 0 — see _silent_set / clear_all.
            spin.setRange(0, 9999)
            spin.valueChanged.connect(lambda _v, k=field.key: self._mark_dirty(k))
            return spin

        if field.type == "text":
            # Multi-line narrative editor for things like diagnosis / treatment.
            # textChanged fires on programmatic edits too, but _silent_set wraps
            # those in blockSignals(True), so we never spuriously set dirty.
            box = QPlainTextEdit()
            box.setMinimumHeight(TEXT_FIELD_MIN_HEIGHT)
            box.textChanged.connect(lambda k=field.key: self._mark_dirty(k))
            return box

        line = QLineEdit()
        # textEdited (not textChanged) only fires on user input, never on
        # programmatic setText — exactly what we want for the dirty flag.
        line.textEdited.connect(lambda _t, k=field.key: self._mark_dirty(k))
        return line

    def _mark_dirty(self, key: str) -> None:
        self._user_dirty[key] = True

    # ---------- Public API ---------------------------------------------------

    def apply_update(self, fields: dict) -> None:
        """Apply LLM-extracted values, skipping any field the user has edited."""
        for key, value in fields.items():
            if key not in self._editors:
                continue
            if self._user_dirty.get(key, False):
                continue
            self._silent_set(key, value)

    def current_values(self) -> dict:
        """Snapshot of all field values, ready to serialize."""
        out: dict = {}
        for key, editor in self._editors.items():
            if isinstance(editor, QSpinBox):
                # 0 is our "unset" sentinel — represent it as None on output so
                # the saved JSON doesn't claim a year of 0 was dictated.
                out[key] = editor.value() if editor.value() != 0 else None
            elif isinstance(editor, QPlainTextEdit):
                text = editor.toPlainText().strip()
                out[key] = text if text else None
            else:
                text = editor.text().strip()
                out[key] = text if text else None
        return out

    def clear_all(self) -> None:
        """Reset every editor and the dirty flags — call at session start."""
        for key, editor in self._editors.items():
            self._silent_set(key, 0 if isinstance(editor, QSpinBox) else "")
            self._user_dirty[key] = False

    # ---------- Internals ----------------------------------------------------

    def _silent_set(self, key: str, value) -> None:
        """Set an editor's value without triggering its change signals."""
        editor = self._editors[key]
        editor.blockSignals(True)
        try:
            if isinstance(editor, QSpinBox):
                try:
                    editor.setValue(int(value))
                except (TypeError, ValueError):
                    editor.setValue(0)
            elif isinstance(editor, QPlainTextEdit):
                editor.setPlainText(str(value))
            else:
                editor.setText(str(value))
        finally:
            editor.blockSignals(False)
