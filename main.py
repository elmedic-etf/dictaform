"""Application entry point — see PLAN.md for the high-level design.

Start with:
    pip install -r requirements.txt
    cp .env.example .env  # edit and add your OpenRouter API key
    python main.py
"""
import os

# Disable HuggingFace tokenizer parallelism BEFORE any import that might pull
# tokenizers in (faster-whisper does, transitively). Without this, macOS prints
# "leaked semaphore objects" at shutdown because the tokenizer worker pool's
# multiprocessing semaphores aren't reaped cleanly when Python exits.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import sys
from pathlib import Path

from dotenv import load_dotenv
from PySide6.QtWidgets import QApplication

from source.config_loader import load_config
from source.logging_setup import setup_logging
from source.main_window import MainWindow
from source.theme import apply_theme


def main() -> int:
    # Load OPENROUTER_API_KEY (and any other env vars) from a local .env file
    # before anything else looks at os.environ.
    load_dotenv()

    setup_logging()

    config_path = Path(__file__).parent / "config.json"
    config = load_config(config_path)

    app = QApplication(sys.argv)
    app.setApplicationName("Medical Dictation Transcriber")
    apply_theme(app)

    window = MainWindow(config)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
