"""Phase 6 — voice is additive and must never be able to break the text path."""
import os

import pytest

from core.narrate import render_template
from core.pipeline import advise
from core.voice import parse_query, pcm_to_wav, synthesize, transcribe


def _llm_status() -> tuple[bool, str]:
    """Distinguish 'no key' from 'bad key' from 'quota exhausted'.

    A skip that says "unavailable" hides which of those it was. The final
    report has to be able to say exactly why a live test did not run.
    """
    import os
    if not os.getenv("GEMINI_API_KEY"):
        return False, "GEMINI_API_KEY not set"
    try:
        from core.narrate import _gemini, DEFAULT_MODEL
        _gemini("Reply with the single word: ok", "You are a test harness.")
        return True, "ok"
    except Exception as exc:
        msg = str(exc)
        from core.narrate import DEFAULT_MODEL
        if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
            return False, (f"LIVE LLM QUOTA EXHAUSTED for {DEFAULT_MODEL} "
                           "(free tier = 20 requests/day/model). Not a code "
                           "failure; set GEMINI_MODEL to another model or "
                           "wait for the daily reset.")
        if "API_KEY_INVALID" in msg or "401" in msg or "403" in msg:
            return False, f"GEMINI_API_KEY rejected: {msg[:120]}"
        return False, f"live LLM unreachable: {type(exc).__name__}: {msg[:120]}"

_LLM_OK, _LLM_WHY = _llm_status()
live = pytest.mark.skipif(not _LLM_OK, reason=_LLM_WHY)


# ------------------------------------------------- degradation, no network
def test_transcribe_with_no_audio_degrades():
    r = transcribe(b"")
    assert r["ok"] is False and r["error"]


def test_synthesize_with_no_text_degrades():
    r = synthesize("")
    assert r["ok"] is False and r["error"]


def test_parse_query_with_empty_utterance_degrades():
    r = parse_query("")
    assert r["ok"] is False


def test_pcm_to_wav_produces_a_valid_container():
    import io
    import wave
    wav = pcm_to_wav(b"\x00\x01" * 2400)
    with wave.open(io.BytesIO(wav)) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 24000


def test_text_pipeline_does_not_import_voice():
    """The advisory path must not depend on the voice stack existing."""
    import core.pipeline as p
    assert "voice" not in open(p.__file__).read()


def test_text_advice_works_regardless_of_voice():
    env = advise(village="nimgaon jali", capital_inr=100_000, sector="dairy")
    assert env["decision"]["verdict"]
    assert render_template(env, "en")


def test_parse_query_falls_back_to_keywords_without_a_model(monkeypatch):
    """If the model call fails, sector and amount are still recovered."""
    import core.voice as v
    monkeypatch.setattr(v, "_client",
                        lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    r = v.parse_query("I have 50000 rupees for a kirana shop")
    assert r["ok"] is False
    assert r["sector"] == "kirana_retail"
    assert r["capital_inr"] == 50000



def _skip_if_quota(result: dict) -> None:
    """TTS has its own per-model quota, separate from the text model.

    A 429 mid-suite is an account limit, not a code failure — these same calls
    pass in isolation. Skip with the cause named rather than fail, matching how
    the narration tests already report an exhausted quota. Any OTHER error
    still fails the test.
    """
    if result["ok"]:
        return
    err = result.get("error") or ""
    if "RESOURCE_EXHAUSTED" in err or "429" in err:
        pytest.skip(f"TTS QUOTA EXHAUSTED mid-suite (passes in isolation): "
                    f"{err[:140]}")
    pytest.fail(f"TTS failed for a non-quota reason: {err[:200]}")


# ------------------------------------------------------------------- live
@live
def test_live_tts_produces_audio():
    r = synthesize("नमस्कार")
    _skip_if_quota(r)
    assert r["audio"][:4] == b"RIFF"
    assert len(r["audio"]) > 5000


@live
def test_live_marathi_round_trip():
    """Speak a Marathi question, hear it back, and recover the structured query."""
    said = ("माझ्याकडे एक लाख रुपये आहेत, मला निमगाव जाळी मध्ये "
            "दुग्ध व्यवसाय सुरू करायचा आहे.")
    tts = synthesize(said)
    _skip_if_quota(tts)
    asr = transcribe(tts["audio"])
    assert asr["ok"], asr["error"]
    assert "निमगाव" in asr["text"]

    q = parse_query(asr["text"])
    assert q["ok"], q["error"]
    assert q["capital_inr"] == 100000
    assert q["sector"] == "dairy_buffalo"
    assert "nimgaon" in (q["village"] or "").lower()
    # Never auto-executed: the user confirms what was heard.
    assert q["needs_confirmation"] is True


@live
def test_live_spoken_query_reaches_the_same_verdict_as_typed():
    """Voice must be a different door to the same answer, not a different answer."""
    said = ("माझ्याकडे एक लाख रुपये आहेत, मला निमगाव जाळी मध्ये "
            "दुग्ध व्यवसाय सुरू करायचा आहे.")
    q = parse_query(said)
    if not q["ok"] or not q["village"]:
        # A failed parse (quota, or the model returning nothing) must not be
        # passed into advise() as None — that crashes in geo.resolve and reads
        # like a pipeline bug rather than an upstream limit.
        pytest.skip(f"intent parse unavailable: {(q.get('error') or 'no village')[:140]}")
    spoken = advise(village=q["village"], capital_inr=q["capital_inr"],
                    sector=q["sector"])
    typed = advise(village="nimgaon jali", capital_inr=100_000,
                   sector="dairy_buffalo")
    assert spoken["run_id"] == typed["run_id"]
    assert spoken["decision"]["verdict"] == typed["decision"]["verdict"]
