"""Every numeric leaf in the envelope is a Fact with a source."""
import pytest

from core.facts import Fact, encode, iter_bare_numbers
from core.pipeline import advise

Q = dict(village="nimgaon jali", capital_inr=100_000, sector="dairy")


@pytest.fixture(scope="module")
def env():
    return advise(**Q)


def test_no_bare_numbers(env):
    payload = {k: env[k] for k in
               ("market", "finance", "affordability", "risk", "decision")}
    bare = iter_bare_numbers(encode(payload))
    assert bare == [], f"bare numbers with no provenance: {bare}"


def test_every_fact_has_a_source(env):
    for p in env["provenance"]:
        assert p["source"], f"Fact at {p['path']} has no source"
        assert p["geo_level"] in {
            "village", "subdistrict", "district", "state", "national"}
        assert p["confidence"] in {"high", "medium", "low"}


def test_degradation_is_labelled(env):
    """A Fact coarser than village must explain itself."""
    for p in env["provenance"]:
        if p["geo_level"] != "village":
            assert p["note"], (
                f"{p['path']} is {p['geo_level']}-level with no note")


def test_provenance_panel_is_populated(env):
    assert len(env["provenance"]) > 30
