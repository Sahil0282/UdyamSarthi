"""A saturated / unviable village must be able to produce RECONSIDER.

`murmi` was found by querying the loaded data for a village with zero dairy
processing employment anywhere in its 8 km catchment, no all-weather road, no
veterinary hospital and a town 97 km away. It is a real place, not a
constructed fixture — PART 9: do not fabricate the scenario, find a real one.
"""
import pytest

from core.pipeline import advise

BAD = dict(village="murmi", capital_inr=25_000, sector="dairy")


@pytest.fixture(scope="module")
def env():
    return advise(**BAD)


def test_refusal_possible(env):
    assert env["decision"]["verdict"] == "RECONSIDER", (
        f"expected RECONSIDER, got {env['decision']['verdict']} — the "
        "thresholds have defaulted to always-PROCEED")


def test_refusal_states_why(env):
    assert env["decision"]["hard_gates_triggered"], \
        "RECONSIDER with no hard gate recorded"
    assert env["decision"]["reasons"]


def test_refusal_ranks_alternatives(env):
    alts = env["decision"]["alternatives"]
    assert len(alts) == 3, f"expected 3 ranked alternatives, got {len(alts)}"
    scores = [float(a["score"].value) for a in alts]
    assert scores == sorted(scores, reverse=True), "alternatives are not ranked"


def test_override_is_honoured_not_blocked():
    env = advise(**BAD, override=True)
    d = env["decision"]
    assert d["override_applied"] is True
    assert d["mode"] == "risk_mitigation"
    # The verdict is NOT softened — that would be lying to the user.
    assert d["verdict"] == "RECONSIDER"
    assert d["original_verdict"] == "RECONSIDER"
    assert d["mitigations"], "override produced no mitigation guidance"


def test_all_three_verdicts_are_reachable():
    """Guards against thresholds that can only ever emit one answer."""
    seen = {
        advise(**BAD)["decision"]["verdict"],
        advise(village="nimgaon jali", capital_inr=100_000,
               sector="dairy")["decision"]["verdict"],
    }
    assert "RECONSIDER" in seen
    assert len(seen) > 1, "every input produced the same verdict"
