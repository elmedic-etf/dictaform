"""Application-wide Qt stylesheet (QSS) + theme helpers.

Visual language: clean clinical, soft slate background, white surfaces, sky-blue
accent, danger red for the recording state. All sizing in pixels — Qt stylesheet
units don't honour DPI scaling well across platforms, so explicit px keeps the
look consistent on Retina + Windows.

The QSS is applied once on the QApplication; widgets that need state-driven
styling expose a dynamic property and the stylesheet's attribute selectors
react to it (see ``QPushButton#talkButton[recording="true"]``). To re-evaluate
the stylesheet after toggling such a property, call ``repolish(widget)``.
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget


# --- Palette ----------------------------------------------------------------
# Slate / sky / red — neutral, calm, with a single saturated accent.
PALETTE = {
    "bg":            "#F1F5F9",   # window background (slate-100)
    "surface":       "#FFFFFF",   # cards, inputs
    "surface_alt":   "#F8FAFC",   # subtle separators
    "border":        "#E2E8F0",   # 1px borders
    "border_strong": "#CBD5E1",   # hovered input borders
    "text":          "#0F172A",   # primary text (slate-900)
    "text_muted":    "#64748B",   # labels, captions (slate-500)
    "text_subtle":   "#94A3B8",   # placeholder (slate-400)
    "accent":        "#0EA5E9",   # sky-500
    "accent_hover":  "#0284C7",   # sky-600
    "accent_press":  "#0369A1",   # sky-700
    "accent_soft":   "#E0F2FE",   # sky-100 — selection bg
    "danger":        "#EF4444",   # red-500 (Stop / recording)
    "danger_hover":  "#DC2626",   # red-600
    "danger_press":  "#B91C1C",   # red-700
}


STYLESHEET = f"""
/* ---------- Global ----------------------------------------------------- */
* {{
    /* Qt doesn't resolve the CSS `-apple-system` alias; list real family
       names in priority order so each platform picks its native UI font. */
    font-family: "SF Pro Text", "Helvetica Neue", "Segoe UI", "Inter",
                 "Roboto", Arial, sans-serif;
}}

QMainWindow, QWidget {{
    background-color: {PALETTE['bg']};
    color: {PALETTE['text']};
}}

QLabel {{
    color: {PALETTE['text']};
    font-size: 13px;
}}

QLabel#sectionLabel {{
    color: {PALETTE['text_muted']};
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 1px;
}}

QLabel#appTitle {{
    color: {PALETTE['text']};
    font-size: 18px;
    font-weight: 700;
}}

QLabel#appSubtitle {{
    color: {PALETTE['text_muted']};
    font-size: 12px;
}}

/* ---------- Group boxes (form sections) -------------------------------- */
QGroupBox {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 12px;
    margin-top: 18px;
    padding: 22px 16px 14px 16px;
    font-weight: 600;
    font-size: 12px;
    color: {PALETTE['text_muted']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 8px;
    background-color: {PALETTE['bg']};
}}

/* ---------- Inputs ----------------------------------------------------- */
QLineEdit, QPlainTextEdit, QSpinBox {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: {PALETTE['accent_soft']};
    selection-color: {PALETTE['text']};
    color: {PALETTE['text']};
    font-size: 13px;
}}
QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover {{
    border: 1px solid {PALETTE['border_strong']};
}}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{
    border: 1px solid {PALETTE['accent']};
}}
QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled {{
    background-color: {PALETTE['surface_alt']};
    color: {PALETTE['text_muted']};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    width: 18px;
    background: transparent;
    border: none;
}}

/* ---------- Transcript view (read-only) -------------------------------- */
QPlainTextEdit#transcriptView {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 12px;
    padding: 18px 20px;
    font-size: 14px;
    color: {PALETTE['text']};
}}

/* ---------- Buttons ---------------------------------------------------- */
QPushButton {{
    background-color: {PALETTE['accent']};
    color: white;
    border: none;
    border-radius: 10px;
    padding: 9px 18px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton:hover    {{ background-color: {PALETTE['accent_hover']}; }}
QPushButton:pressed  {{ background-color: {PALETTE['accent_press']}; }}
QPushButton:disabled {{
    background-color: {PALETTE['text_subtle']};
    color: {PALETTE['surface_alt']};
}}

/* Primary Talk button — larger and reacts to a `recording` dynamic property. */
QPushButton#talkButton {{
    background-color: {PALETTE['accent']};
    padding: 12px 30px;
    font-size: 14px;
    border-radius: 12px;
    min-width: 130px;
    min-height: 24px;
    letter-spacing: 0.4px;
}}
QPushButton#talkButton:hover           {{ background-color: {PALETTE['accent_hover']}; }}
QPushButton#talkButton:pressed         {{ background-color: {PALETTE['accent_press']}; }}
QPushButton#talkButton[recording="true"]         {{ background-color: {PALETTE['danger']}; }}
QPushButton#talkButton[recording="true"]:hover   {{ background-color: {PALETTE['danger_hover']}; }}
QPushButton#talkButton[recording="true"]:pressed {{ background-color: {PALETTE['danger_press']}; }}

/* ---------- Combo boxes ------------------------------------------------ */
QComboBox {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    padding: 6px 10px;
    color: {PALETTE['text']};
    font-size: 13px;
    min-width: 110px;
}}
QComboBox:hover    {{ border: 1px solid {PALETTE['border_strong']}; }}
QComboBox:focus    {{ border: 1px solid {PALETTE['accent']}; }}
QComboBox::drop-down {{
    border: none;
    width: 24px;
    subcontrol-origin: padding;
    subcontrol-position: top right;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0; height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {PALETTE['text_muted']};
    margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: {PALETTE['surface']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    selection-background-color: {PALETTE['accent_soft']};
    selection-color: {PALETTE['text']};
    padding: 4px;
    outline: 0;
}}

/* ---------- Status bar ------------------------------------------------- */
QStatusBar {{
    background-color: {PALETTE['surface']};
    color: {PALETTE['text_muted']};
    border-top: 1px solid {PALETTE['border']};
    padding: 4px 12px;
    font-size: 12px;
}}
QStatusBar::item {{ border: none; }}

/* ---------- Splitter handle ------------------------------------------- */
QSplitter::handle {{
    background-color: transparent;
}}
QSplitter::handle:horizontal {{ width: 10px; }}
QSplitter::handle:vertical   {{ height: 10px; }}
QSplitter::handle:hover {{
    background-color: {PALETTE['border']};
    border-radius: 2px;
}}

/* ---------- Scrollbars ------------------------------------------------- */
QScrollBar:vertical, QScrollBar:horizontal {{
    background: transparent;
    border: none;
    margin: 4px;
}}
QScrollBar:vertical   {{ width: 10px; }}
QScrollBar:horizontal {{ height: 10px; }}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background: {PALETTE['border_strong']};
    border-radius: 5px;
    min-height: 24px;
    min-width: 24px;
}}
QScrollBar::handle:hover {{ background: {PALETTE['text_subtle']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0; width: 0; border: none; background: none;
}}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ---------- Tooltip --------------------------------------------------- */
QToolTip {{
    background-color: {PALETTE['text']};
    color: {PALETTE['surface']};
    border: none;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}
"""


def apply_theme(app: QApplication) -> None:
    """Install the global stylesheet on the application."""
    app.setStyleSheet(STYLESHEET)


def repolish(widget: QWidget) -> None:
    """Re-evaluate the stylesheet for ``widget``.

    Needed after toggling a dynamic property used by an attribute selector,
    e.g. ``btn.setProperty("recording", True)``. Qt doesn't notice these
    changes automatically.
    """
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
