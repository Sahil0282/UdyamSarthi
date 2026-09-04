"""The Kolhapur proxy must stay visible in every dairy output.

MILK_PRICE_SOURCE.md is explicit: this is a Kolhapur union rate used as a
Maharashtra proxy, not an Ahmadnagar rate. If the note, the geo_level or the
confidence is lost or upgraded on the way through the engines, a user in
Ahmadnagar is shown a local-looking price that is not local.
"""
import yaml
import pytest

from core.pipeline import advise

Q = dict(village="nimgaon jali", capital_inr=100_000, sector="dairy")
SRC = yaml.safe_load(open("data/sectors/dairy.yaml"))["monthly"]["milk_price"]["buffalo"]


@pytest.fixture(scope="module")
def env():
    return advise(**Q)


def test_milk_price_reaches_the_envelope(env):
    assert "milk_price" in env["affordability"]


def test_milk_price_fields_are_unchanged(env):
    f = env["affordability"]["milk_price"]
    assert f.value == SRC["value"] == 62.18
    assert f.unit == SRC["unit"]
    assert f.year == SRC["year"] == 2026
    assert f.geo_level == SRC["geo_level"] == "state"
    assert f.confidence == SRC["confidence"] == "medium"
    assert f.note == SRC["note"]


def test_confidence_is_not_upgraded(env):
    assert env["affordability"]["milk_price"].confidence == "medium"


def test_note_names_kolhapur_and_the_nearer_union(env):
    note = env["affordability"]["milk_price"].note.lower()
    assert "kolhapur" in note
    assert "sangamner" in note
    assert "not ahmadnagar" in note or "not an ahmadnagar" in note


def test_note_survives_into_the_provenance_panel(env):
    hits = [p for p in env["provenance"] if p["path"].endswith("milk_price")]
    assert hits, "milk_price missing from the provenance panel"
    p = hits[0]
    assert p["geo_level"] == "state"
    assert p["confidence"] == "medium"
    assert "Kolhapur" in p["note"]


def test_revenue_inherits_no_better_than_state_level(env):
    """Revenue is computed FROM the state-level price, so it cannot claim
    village-level provenance."""
    rev = env["affordability"]["monthly_revenue"]
    assert rev.geo_level in {"state", "national"}
    assert rev.confidence in {"low", "medium"}
