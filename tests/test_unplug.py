"""THE test. Disabling the LLM must not change a single number.

The LLM is not merely switched off in the --no-llm path; it is absent from the
computation call graph entirely. `advise()` takes no model client and imports
no SDK, so these assertions are structural, not behavioural.
"""
import json

from core.facts import encode
from core.narrate import narrate, render_template
from core.pipeline import advise, to_json

Q = dict(village="nimgaon jali", capital_inr=100_000, sector="dairy")


def _fake_llm(text):
    return lambda prompt, system: text


def test_advise_takes_no_llm_argument():
    import inspect
    params = set(inspect.signature(advise).parameters)
    assert not {"use_llm", "llm", "model", "client"} & params, (
        "advise() accepts an LLM parameter — the LLM can reach the numbers")


def test_pipeline_imports_no_llm_sdk():
    import core.pipeline as p
    src = open(p.__file__).read()
    for banned in ("google.genai", "import genai", "anthropic", "openai"):
        assert banned not in src, f"{banned} imported into the pipeline"


def test_unplug_numbers_are_byte_identical():
    """LLM on vs off: the envelope must be identical, only prose differs."""
    env_off = advise(**Q)
    env_on = advise(**Q)

    n_off = narrate(env_off, use_llm=False)
    n_on = narrate(env_on, use_llm=True,
                   generate=_fake_llm(
                       "This plan looks workable. You are eligible for 900,000 "
                       "rupees but we recommend 756,665 rupees. Confidence is "
                       "LOW because the cost figures are national benchmarks."))

    assert to_json(env_off) == to_json(env_on), \
        "the envelope changed when the LLM was enabled"
    assert n_on["path"] == "llm"
    assert n_off["path"] == "template"
    assert n_on["text"] != n_off["text"], "prose should differ"


def test_unplug_decision_and_facts_identical():
    a, b = advise(**Q), advise(**Q)
    assert a["decision"]["verdict"] == b["decision"]["verdict"]
    assert encode(a["provenance"]) == encode(b["provenance"])


def test_narration_is_downstream_of_the_envelope():
    """Narration receives a finished envelope; mutating prose cannot alter it."""
    env = advise(**Q)
    before = to_json(env)
    narrate(env, use_llm=True, generate=_fake_llm("Completely unrelated text."))
    assert to_json(env) == before
