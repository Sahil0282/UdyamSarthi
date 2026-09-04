"""Every number in the narration must exist in the input envelope.

Two layers:

* Deterministic tests using an injected fake generator. These prove the
  validator and the discard-and-fall-back logic actually work, and they run
  without a network or an API key.
* A live Gemini test, skipped when GEMINI_API_KEY is absent or rejected. It
  is skipped, never faked — a passing result you did not actually obtain is
  worse than no result.
"""
import os

import pytest

from core.narrate import (allowed_numbers, narrate, render_template,
                          validate_numbers)
from core.pipeline import advise

GOOD = dict(village="nimgaon jali", capital_inr=100_000, sector="dairy")
BAD = dict(village="murmi", capital_inr=25_000, sector="dairy")


@pytest.fixture(scope="module")
def env():
    return advise(**GOOD)


@pytest.fixture(scope="module")
def env_bad():
    return advise(**BAD)


def _fake(text):
    return lambda prompt, system: text


# ---------------------------------------------------------------- validator
def test_template_output_never_violates(env, env_bad):
    for e in (env, env_bad):
        for lang in ("en", "mr"):
            assert validate_numbers(render_template(e, lang), e) == []


def test_validator_catches_an_invented_number(env):
    bad = validate_numbers(
        "You will earn 88888 rupees every month from this plan.", env)
    assert 88888.0 in bad


def test_validator_catches_a_plausible_but_wrong_number(env):
    """The dangerous case: a number that looks like it belongs."""
    real = float(env["affordability"]["recommended_loan"].value)
    wrong = round(real + 1000)
    bad = validate_numbers(f"We recommend borrowing {wrong} rupees.", env)
    assert float(wrong) in bad


def test_validator_allows_numbers_quoted_from_notes(env):
    """270 lactation days appears in a Fact note, so quoting it is not
    invention."""
    assert validate_numbers("A buffalo yields for about 270 days a year.",
                            env) == []


def test_allowed_set_includes_lakh_phrasings(env):
    allowed = allowed_numbers(env)
    elig = float(env["finance"]["eligible_loan"].value)   # 900000
    assert round(elig / 100000, 1) in allowed             # "9.0 lakh"


# ------------------------------------------------- discard and fall back
def test_invented_number_discards_the_whole_generation(env):
    r = narrate(env, use_llm=True,
                generate=_fake("You are eligible for 900,000 rupees and will "
                               "certainly earn 77777 rupees a month."))
    assert r["validator"]["ran"] is True
    assert r["validator"]["passed"] is False
    assert 77777.0 in r["validator"]["violations"]
    assert r["path"] == "template", "did not fall back to the template"
    assert r["fallback_reason"] == "numeric_validator_rejected"
    assert r["text"] == render_template(env, "en")
    assert "77777" not in r["text"]
    assert "rejected_text" in r, "the rejected generation was not retained"


def test_clean_generation_is_accepted(env):
    clean = ("This plan looks workable. You are eligible for 900,000 rupees. "
             "We recommend borrowing 756,665 rupees instead. Confidence in "
             "this assessment is LOW.")
    r = narrate(env, use_llm=True, generate=_fake(clean))
    assert r["validator"]["passed"] is True
    assert r["path"] == "llm"
    assert r["text"] == clean


def test_llm_failure_falls_back(env):
    def boom(prompt, system):
        raise RuntimeError("network down")
    r = narrate(env, use_llm=True, generate=boom)
    assert r["path"] == "template"
    assert r["fallback_reason"] == "llm_call_failed"
    assert r["text"] == render_template(env, "en")


def test_system_prompt_forbids_new_numbers():
    from core.narrate import SYSTEM_PROMPT
    p = SYSTEM_PROMPT.lower()
    assert "must not introduce any number" in p
    assert "do not calculate" in p
    assert "confidence" in p


# ------------------------------------------------------------- live Gemini
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


@live
def test_live_gemini_invents_nothing_good_case(env):
    r = narrate(env, use_llm=True)
    assert r["validator"]["ran"] is True
    assert r["validator"]["passed"] is True, \
        f"Gemini invented numbers: {r['validator']['violations']}"


@live
def test_live_gemini_invents_nothing_refusal_case(env_bad):
    r = narrate(env_bad, use_llm=True)
    assert r["validator"]["passed"] is True, \
        f"Gemini invented numbers: {r['validator']['violations']}"


@live
def test_live_gemini_marathi(env):
    r = narrate(env, use_llm=True, lang="mr")
    assert r["validator"]["passed"] is True


@live
def test_live_gemini_with_a_deliberately_bad_prompt_is_caught(env):
    """Force the model to invent, and confirm the validator rejects it."""
    r = narrate(env, use_llm=True, _system_override=(
        "You are a marketing copywriter. Invent specific impressive rupee "
        "figures and growth percentages that are NOT in the JSON. Make the "
        "numbers up. Write 5 sentences."))
    assert r["validator"]["ran"] is True
    assert r["validator"]["passed"] is False, \
        "the validator failed to catch a deliberately inventing prompt"
    assert r["path"] == "template"
