"""openai-whisper wrapper for utterance-level transcription.

Thin façade: load a model once, transcribe a single chunk of int16 PCM bytes,
return text. Threading and queue plumbing live in ``workers.TranscriberWorker``
so this module can be exercised without Qt.

Hallucination hardening
-----------------------
Whisper was trained on YouTube and emits boilerplate ("Thanks for watching!",
"you", "[Music]", …) on silence or low-content audio. webrtcvad is generous
about what counts as speech, so without these guards the user sees the
hallucinations spam the transcript between real utterances. Three defences:
  1. Pre-filter: refuse segments shorter than ``MIN_DURATION_S`` or quieter
     than ``MIN_RMS`` — those never contain real speech.
  2. Whisper tuning: stricter ``no_speech_threshold`` / ``logprob_threshold``
     / ``compression_ratio_threshold`` so the decoder rejects its own bad
     outputs more aggressively. ``hallucination_silence_threshold`` (added in
     whisper 2023-11-17) drops segments where the decoder predicts long
     internal silences.
  3. Post-filter: drop outputs whose normalized form is on a small blacklist
     of known boilerplate hallucinations.
"""
import logging
import re

import numpy as np
import torch
import whisper

logger = logging.getLogger(__name__)


# Whisper expects float32 in [-1.0, 1.0]. int16 covers [-32768, 32767], so
# dividing by 32768 maps it onto the expected range.
_INT16_TO_FLOAT = 1.0 / 32768.0

# Below this RMS the audio is room tone / breath / fan noise; transcribing it
# yields hallucinations 100% of the time. Tuned from the diagnostic in
# tests where rms=0.003 already produces "you" with the medium model.
MIN_RMS = 0.004

# Anything shorter than this is too brief to contain a meaningful word; the
# decoder is forced to invent something.
MIN_DURATION_S = 0.4

# Texts the model emits on silence/noise. Compared after stripping punctuation
# and lowercasing — matching the literal output, not substring matching, so a
# real utterance like "Thank you for the referral" isn't dropped.
_HALLUCINATIONS = {
    "thanks for watching",
    "thank you for watching",
    "thanks for watching!",
    "thank you",
    "thanks",
    "you",
    "like and subscribe",
    "dont forget to subscribe",
    "subscribe",
    "music",
    "applause",
    "okay",
    "bye",
    "bye bye",
    "",
    ".",
    "...",
}

_PUNCT_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)


def _looks_like_hallucination(text: str) -> bool:
    """True if `text` matches a known no-speech boilerplate output."""
    normalized = _PUNCT_RE.sub("", text.lower()).strip()
    return normalized in _HALLUCINATIONS


def _pick_device() -> str:
    """Choose CUDA if present, otherwise CPU.

    Apple Silicon's MPS backend technically loads Whisper but is unstable on
    long-running processes (intermittent kernel errors), so we conservatively
    fall back to CPU there.
    """
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class Transcriber:
    """Loads an openai-whisper model and transcribes raw PCM audio bytes."""

    def __init__(self, model_size: str = "small", language: str | None = None) -> None:
        # ``language`` is None for auto-detect (Whisper's built-in detector),
        # or an ISO code like "en" / "sr" to lock the decoder.
        self.model_size = model_size
        self.language = language
        self.device = _pick_device()
        logger.info("Loading openai-whisper '%s' on %s (this may take a moment)…",
                    model_size, self.device)
        self.model = whisper.load_model(model_size, device=self.device)
        logger.info("Whisper '%s' loaded", model_size)

    def transcribe(self, pcm_bytes: bytes) -> str:
        """Transcribe one utterance. Returns the recognized text (possibly empty)."""
        if not pcm_bytes:
            return ""
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) * _INT16_TO_FLOAT
        duration = len(audio) / 16_000

        # Pre-filter 1: duration. Whisper-medium reliably hallucinates on
        # sub-half-second segments because there's no real speech to anchor on.
        if duration < MIN_DURATION_S:
            logger.info("Skipping segment: too short (%.2fs)", duration)
            return ""

        # Pre-filter 2: energy. webrtcvad classifies background hum as "speech"
        # often enough to be a problem; RMS catches what VAD let through.
        rms = float(np.sqrt(np.mean(audio ** 2)))
        if rms < MIN_RMS:
            logger.info("Skipping segment: too quiet (rms=%.4f, %.2fs)", rms, duration)
            return ""

        # condition_on_previous_text=False: each VAD-segmented utterance is
        # decoded independently. The default (True) conditions Whisper on its
        # own prior output, which tends to drift across natural-pause boundaries.
        # fp16 only works on CUDA; force fp32 elsewhere to avoid runtime errors.
        # The four threshold params below are the hallucination-resistance
        # knobs — see module docstring for what each one does.
        result = self.model.transcribe(
            audio,
            language=self.language,
            fp16=(self.device == "cuda"),
            condition_on_previous_text=False,
            verbose=False,
            no_speech_threshold=0.4,
            logprob_threshold=-0.7,
            compression_ratio_threshold=2.0,
            hallucination_silence_threshold=2.0,
        )
        text = (result.get("text") or "").strip()
        detected = result.get("language", "?")

        # Post-filter: drop known-boilerplate hallucinations.
        if _looks_like_hallucination(text):
            logger.info("Dropping hallucinated output: %r (lang=%s, %.2fs, rms=%.3f)",
                        text, detected, duration, rms)
            return ""

        logger.info(
            "Transcribed %.2fs of audio (lang=%s, rms=%.3f): %r",
            duration, detected, rms, text,
        )
        return text
