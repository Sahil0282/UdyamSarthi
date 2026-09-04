"""Same input, same output, twice. Non-negotiable for a government tool."""
from core.pipeline import advise, to_json

Q = dict(village="nimgaon jali", capital_inr=100_000, sector="dairy")


def test_determinism_full_envelope():
    a = to_json(advise(**Q))
    b = to_json(advise(**Q))
    assert a == b, "two identical runs produced different envelopes"


def test_determinism_run_id_is_not_a_timestamp():
    assert advise(**Q)["run_id"] == advise(**Q)["run_id"]


def test_determinism_monte_carlo_is_seeded():
    a = advise(**Q)["risk"]["survival_at_recommended"].value
    b = advise(**Q)["risk"]["survival_at_recommended"].value
    assert a == b, "Monte Carlo is not seeded; survival probability drifts"


def test_different_input_gives_different_run_id():
    a = advise(**Q)["run_id"]
    b = advise(village="nimgaon jali", capital_inr=200_000, sector="dairy")["run_id"]
    assert a != b
