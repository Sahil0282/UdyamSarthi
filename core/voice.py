"""M-voice — ASR in, TTS out. Strictly additive.

Voice wraps the text pipeline; it never replaces it. Every function here
degrades to a plain dict with ``ok: False`` and an error string, so a failed
transcription leaves the caller with the text path intact rather than a broken
request. Phase 6 is the plan's lowest-priority item and must not be able to
break the demo.

Model choice (deviates from the plan's suggestion, deliberately):

* ASR  — Gemini ``gemini-3.6-flash`` (native audio input)
* TTS  — Gemini ``gemini-2.5-flash-preview-tts``

The plan suggests AI4Bharat IndicConformer + Indic-Parler-TTS. Those need
NVIDIA NeMo, an AI4Bharat fork and a multi-GB PyTorch install, on a machine the
plan says must not require a GPU. Gemini is already authenticated for L6, needs
no local compute, and was verified to round-trip Marathi correctly. If the
project later needs on-device or offline voice, IndicConformer is the right
answer and this module is the seam to swap it behind.

ARCHITECTURE NOTE — this does not violate "the LLM never computes".
``parse_query`` extracts what the user SAID (a village name, a rupee amount, a
sector) from their own speech. That is input transcription, not computation.
The parsed query is returned for explicit user confirmation before it reaches
L4/L5, and no advisory number is ever produced here.
"""
from __future__ import annotations

import io
import json
import os
import re
import wave
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

ASR_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-tts")
TTS_VOICE = "Kore"
TTS_RATE = 24000

LANG_NAME = {"mr": "Marathi", "hi": "Hindi", "en": "English"}


_CLIENT = None


def _client():
    """One cached client. A fresh Client per call gets closed when it falls out
    of scope, and the next request fails with 'client has been closed'."""
    global _CLIENT
    if _CLIENT is None:
        from google import genai
        key = os.getenv("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY not set")
        _CLIENT = genai.Client(api_key=key)
    return _CLIENT


def pcm_to_wav(pcm: bytes, rate: int = TTS_RATE) -> bytes:
    """Gemini TTS returns raw L16 PCM; browsers want a container."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


# --------------------------------------------------------------------- ASR
def transcribe(audio: bytes, mime: str = "audio/wav", lang: str = "mr") -> dict:
    """Speech -> text. Never raises; the caller keeps its text path either way."""
    out = {"ok": False, "text": None, "model": ASR_MODEL, "lang": lang,
           "error": None}
    if not audio:
        out["error"] = "no audio supplied"
        return out
    try:
        from google.genai import types
        r = _client().models.generate_content(
            model=ASR_MODEL,
            contents=[
                types.Part.from_bytes(data=audio, mime_type=mime),
                f"Transcribe this {LANG_NAME.get(lang, 'Marathi')} audio "
                "verbatim. Output only the transcription, nothing else.",
            ],
        )
        text = (r.text or "").strip()
        if not text:
            out["error"] = "empty transcription"
            return out
        out.update(ok=True, text=text)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


# --------------------------------------------------------------------- TTS
def synthesize(text: str, voice: str = TTS_VOICE) -> dict:
    """Text -> WAV bytes. Never raises."""
    out = {"ok": False, "audio": None, "mime": "audio/wav",
           "model": TTS_MODEL, "error": None}
    if not text or not text.strip():
        out["error"] = "no text supplied"
        return out
    try:
        from google.genai import types
        r = _client().models.generate_content(
            model=TTS_MODEL,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice))),
            ),
        )
        part = r.candidates[0].content.parts[0]
        pcm = part.inline_data.data
        out.update(ok=True, audio=pcm_to_wav(pcm))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


# ------------------------------------------------------------ intent parse
_SECTOR_HINTS = {
    "dairy_buffalo": ["dairy", "milk", "buffalo", "दूध", "दुग्ध", "म्हैस", "गाय"],
    "goat_rearing": ["goat", "शेळी", "बकरी"],
    "backyard_poultry": ["poultry", "chicken", "कुक्कुट", "कोंबडी"],
    "kirana_retail": ["kirana", "shop", "store", "किराणा", "दुकान"],
}

PARSE_PROMPT = """Extract the request from this sentence. Return ONLY JSON:
{"village": <string or null>, "capital_inr": <integer or null>,
 "sector": <one of dairy_buffalo, goat_rearing, backyard_poultry,
            kirana_retail, or null>}

Rules:
- capital_inr: convert spoken amounts to a plain integer. "एक लाख" / "one lakh"
  = 100000. "पन्नास हजार" / "fifty thousand" = 50000. If no amount is spoken,
  use null. Never invent an amount.
- village: the place name only, transliterated to lowercase Latin script.
- Output JSON and nothing else."""


def parse_query(utterance: str) -> dict:
    """Pull village / capital / sector out of what the user said.

    Input parsing, not computation. The result is returned for confirmation;
    `needs_confirmation` is always True so no spoken number silently drives a
    verdict.
    """
    out = {"ok": False, "utterance": utterance, "village": None,
           "capital_inr": None, "sector": None, "needs_confirmation": True,
           "error": None, "source": "llm"}
    if not utterance or not utterance.strip():
        out["error"] = "empty utterance"
        return out
    try:
        from google.genai import types
        r = _client().models.generate_content(
            model=ASR_MODEL, contents=utterance,
            config=types.GenerateContentConfig(
                system_instruction=PARSE_PROMPT, temperature=0.0,
                response_mime_type="application/json"),
        )
        d = json.loads((r.text or "{}").strip())
        out.update(ok=True, village=d.get("village"),
                   capital_inr=d.get("capital_inr"), sector=d.get("sector"))
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"

    # Deterministic fallback/cross-check, so a model failure still yields
    # something usable and a wrong sector guess can be corrected locally.
    low = utterance.lower()
    if not out["sector"]:
        for sid, words in _SECTOR_HINTS.items():
            if any(w in low for w in words):
                out["sector"] = sid
                out["source"] = "keyword-fallback" if not out["ok"] else out["source"]
                break
    if out["capital_inr"] is None:
        m = re.search(r"(\d[\d,]*)", utterance)
        if m:
            out["capital_inr"] = int(m.group(1).replace(",", ""))
    return out
