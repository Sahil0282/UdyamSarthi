"""Low confidence must be audible, not just present in the JSON.

The dairy verdict is `low` confidence because yield, opex and capex are
national benchmarks (MILK_YIELD_OPEX_SOURCE.md) and the milk price is a
Kolhapur proxy. A user who is told "borrow 756,665 rupees" in a confident
voice has been misled even if the JSON is scrupulous.
"""
import yaml
import pytest

from core.narrate import narrate, render_template
from core.pipeline import advise

Q = dict(village="nimgaon jali", capital_inr=100_000, sector="dairy")
DAIRY = yaml.safe_load(open("data/sectors/dairy.yaml"))["monthly"]


@pytest.fixture(scope="module")
def env():
    return advise(**Q)


# ------------------------------------------------ the three sourced Facts
@pytest.mark.parametrize("key,value", [
    ("yield", 10.0),
    ("monthly_opex_per_animal", 3483),
    ("capex_per_animal", 65400),
])
def test_source_facts_are_national_and_low(key, value):
    f = DAIRY[key]
    assert f["value"] == value
    assert f["geo_level"] == "national"
    assert f["confidence"] == "low"
    assert f["note"]


def test_the_420_vs_365_mismatch_note_is_intact():
    note = DAIRY["monthly_opex_per_animal"]["note"]
    assert "420" in note and "365" in note
    assert "270" in note and "150" in note


def test_the_shared_labour_note_is_intact():
    note = DAIRY["monthly_opex_per_animal"]["note"]
    assert "10-animal" in note
    assert "unpaid time" in note


# ------------------------------------------------ survival into the JSON
def test_low_confidence_reaches_the_envelope(env):
    assert env["decision"]["confidence"] == "low"
    y = env["affordability"]["yield_per_animal_per_day"]
    assert y.geo_level == "national" and y.confidence == "low"
    assert y.value == 10.0
    o = env["affordability"]["opex_per_animal"]
    assert o.geo_level == "national" and o.confidence == "low"
    assert o.value == 3483


def test_yield_note_survives_verbatim(env):
    assert env["affordability"]["yield_per_animal_per_day"].note == \
        DAIRY["yield"]["note"]


def test_opex_note_survives_verbatim(env):
    assert env["affordability"]["opex_per_animal"].note == \
        DAIRY["monthly_opex_per_animal"]["note"]


def test_annualisation_is_disclosed_not_hidden(env):
    """The engine converts 10 L/day lactation to ~7.4 L/day annual. That
    conversion must be visible, and must carry the day-count discrepancy."""
    a = env["affordability"]["yield_annualised"]
    assert abs(float(a.value) - 10.0 * 270 / 365) < 0.01
    assert "270" in a.note and "150" in a.note and "420" in a.note
    assert "365" in a.note


def test_provenance_panel_carries_the_notes(env):
    paths = {p["path"]: p for p in env["provenance"]}
    for key in ("affordability.yield_per_animal_per_day",
                "affordability.opex_per_animal"):
        assert key in paths, f"{key} missing from provenance"
        assert paths[key]["confidence"] == "low"
        assert paths[key]["geo_level"] == "national"


# ------------------------------------------------ survival into the PROSE
def test_english_narration_says_confidence_is_low(env):
    text = render_template(env, "en")
    assert "LOW" in text
    assert "national benchmark" in text.lower()
    assert "not measured in ahmadnagar" in text.lower()


def test_marathi_narration_says_confidence_is_low(env):
    text = render_template(env, "mr")
    assert "विश्वासार्हता कमी आहे" in text
    assert "राष्ट्रीय सरासरी" in text
    assert "अहमदनगर" in text


def test_confidence_statement_survives_the_llm_path(env):
    """Even on the LLM path the confidence sentence is in the payload the
    model is given, so it cannot silently drop it without us noticing."""
    from core.narrate import _envelope_for_llm
    payload = _envelope_for_llm(env)
    assert payload["confidence"] == "low"
    assert "LOW" in payload["confidence_explanation"]
    assert "national benchmark" in payload["confidence_explanation"].lower()


def test_narrate_wrapper_keeps_confidence_in_both_langs(env):
    for lang, needle in (("en", "LOW"), ("mr", "विश्वासार्हता कमी आहे")):
        r = narrate(env, use_llm=False, lang=lang)
        assert needle in r["text"]
