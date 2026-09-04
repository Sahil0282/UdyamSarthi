"""M6 — Decision Engine. Deterministic, explainable, no ML.

The Refusal Engine lives here. A tool that validates every idea cannot reduce
enterprise failure, so RECONSIDER must be genuinely reachable — see the hard
gates in thresholds.py, which exist because a weighted average will otherwise
quietly average away a fatal condition.

PART 10: the user override is always honoured. If someone says "I still want
dairy", the system complies and switches to risk-mitigation mode. It never
blocks.
"""
from __future__ import annotations

from core import thresholds as T
from core.facts import Fact, derive, worst_confidence

VERDICTS = ("PROCEED", "PROCEED_WITH_CHANGES", "RECONSIDER")


def _market_score(market: dict[str, Fact], sector: dict) -> float:
    pct = market.get("saturation_percentile")
    if pct is None or pct.value is None:
        return 0.5
    p = float(pct.value) / 100.0
    role = sector["market_mapping"].get("role")
    # For a procurement sector a high percentile means more buyers -> good.
    # For a competitive sector it means more rivals -> bad. Same number,
    # opposite meaning; getting this backwards inverts the verdict.
    return p if role == "procurement_capacity" else (1.0 - p)


def _affordability_score(afford: dict[str, Fact]) -> float:
    cap = float(afford["safe_emi_capacity"].value or 0.0)
    emi_elig = float(afford["emi_at_eligible"].value or 0.0)
    if emi_elig <= 0:
        return 0.0
    return max(0.0, min(cap / emi_elig, T.AFFORDABILITY_FULL_COVER))


def _risk_score(flags: list[dict], survival: Fact) -> float:
    penalty = sum(T.FLAG_PENALTY.get(f["severity"], 0.0) for f in flags)
    penalty = min(penalty, T.MAX_FLAG_PENALTY)
    surv = float(survival.value) if survival.value is not None else 0.0
    return (T.SURVIVAL_WEIGHT_IN_RISK * surv
            + (1.0 - T.SURVIVAL_WEIGHT_IN_RISK) * (1.0 - penalty))


def score(market: dict[str, Fact], afford: dict[str, Fact],
          flags: list[dict], survival: Fact, sector: dict) -> dict[str, float]:
    m = _market_score(market, sector)
    a = _affordability_score(afford)
    r = _risk_score(flags, survival)
    return {
        "market_fit": round(m, 4),
        "affordability": round(a, 4),
        "risk": round(r, 4),
        "overall": round(T.WEIGHT_MARKET * m + T.WEIGHT_AFFORDABILITY * a
                         + T.WEIGHT_RISK * r, 4),
    }


def _hard_gates(afford: dict[str, Fact], finance: dict[str, Fact],
                flags: list[dict], survival: Fact,
                sector: dict) -> list[str]:
    """Conditions that force RECONSIDER on their own."""
    hits: list[str] = []
    rec = float(afford["recommended_loan"].value or 0.0)
    elig = float(finance["eligible_loan"].value or 0.0)

    if survival.value is not None and \
            float(survival.value) < T.MIN_SURVIVAL_AT_RECOMMENDED:
        hits.append(
            f"Survival probability at the recommended loan is "
            f"{float(survival.value):.0%}, below the "
            f"{T.MIN_SURVIVAL_AT_RECOMMENDED:.0%} floor.")
    if rec < T.MIN_RECOMMENDED_LOAN_INR:
        hits.append(
            f"The business supports a loan of only INR {rec:,.0f}, below the "
            f"INR {T.MIN_RECOMMENDED_LOAN_INR:,} minimum needed to buy the unit.")
    if elig > 0 and (rec / elig) < T.MIN_RECOMMENDED_FRACTION:
        hits.append(
            f"The business can service only {rec / elig:.0%} of what the scheme "
            f"would lend (floor {T.MIN_RECOMMENDED_FRACTION:.0%}) — the plan and "
            "the scheme disagree too far.")
    for f in flags:
        if f["code"] in T.BLOCKING_FLAGS:
            hits.append(f"Blocking risk flag: {f['message']}")
    return hits


def decide(market: dict[str, Fact], finance: dict[str, Fact],
           afford: dict[str, Fact], flags: list[dict], survival: Fact,
           sector: dict, alternatives: list[dict] | None = None,
           override: bool = False) -> dict:
    """Produce the verdict, the reasons behind it, and the ranked alternatives."""
    s = score(market, afford, flags, survival, sector)
    gates = _hard_gates(afford, finance, flags, survival, sector)

    if gates:
        verdict = "RECONSIDER"
    elif s["overall"] >= T.PROCEED_MIN:
        verdict = "PROCEED"
    elif s["overall"] < T.RECONSIDER_MAX:
        verdict = "RECONSIDER"
    else:
        verdict = "PROCEED_WITH_CHANGES"

    # ---- confidence: no better than the weakest Fact behind it ----
    inputs = [f for f in list(market.values()) + list(finance.values())
              + list(afford.values()) if isinstance(f, Fact)]
    inputs.append(survival)
    conf = worst_confidence(inputs)

    reasons: list[str] = list(gates)
    rec = float(afford["recommended_loan"].value or 0.0)
    elig = float(finance["eligible_loan"].value or 0.0)
    if rec < elig:
        reasons.append(
            f"Eligible for INR {elig:,.0f}, but this business supports "
            f"INR {rec:,.0f}. EMI on the eligible loan is INR "
            f"{float(afford['emi_at_eligible'].value):,.0f}/month against "
            f"INR {float(afford['net_available_for_emi'].value):,.0f} available.")
    wc = afford.get("working_capital_floor")
    if wc is not None and wc.value:
        reasons.append(
            f"INR {float(wc.value):,.0f} must be reserved as working capital "
            "before any capex is approved.")
    for f in flags:
        if f["severity"] in ("high", "medium"):
            reasons.append(f["message"])

    # The four scores are computed numbers the user is shown, so they carry
    # provenance like any other derived figure and inherit the weakest inputs.
    score_facts = {
        k: derive(v, "score 0-1",
                  f"deterministic weighted score component '{k}' "
                  f"(weights market {T.WEIGHT_MARKET}, affordability "
                  f"{T.WEIGHT_AFFORDABILITY}, risk {T.WEIGHT_RISK}; "
                  "thresholds in core/thresholds.py)",
                  *[f for f in inputs if isinstance(f, Fact)])
        for k, v in s.items()
    }

    out = {
        "verdict": verdict,
        "score": score_facts,
        "thresholds": {
            "_policy": True,
            "proceed_min": T.PROCEED_MIN,
            "reconsider_max": T.RECONSIDER_MAX,
            "min_survival_at_recommended": T.MIN_SURVIVAL_AT_RECOMMENDED,
            "min_recommended_fraction": T.MIN_RECOMMENDED_FRACTION,
            "weights": {"market": T.WEIGHT_MARKET,
                        "affordability": T.WEIGHT_AFFORDABILITY,
                        "risk": T.WEIGHT_RISK},
        },
        "hard_gates_triggered": gates,
        "reasons": reasons,
        "alternatives": alternatives or [],
        "confidence": conf,
        "override_applied": False,
        "mode": "advisory",
    }

    if override:
        out = apply_override(out)
    return out


def apply_override(decision: dict) -> dict:
    """The user insists. Comply — never block — and switch to mitigation mode.

    The verdict is NOT rewritten to something rosier: that would be lying. It
    is kept, marked as overridden, and the output reframes around how to make
    the plan survivable instead of whether to attempt it.
    """
    d = dict(decision)
    d["override_applied"] = True
    d["mode"] = "risk_mitigation"
    d["original_verdict"] = decision["verdict"]
    d["mitigations"] = _mitigations(decision)
    d["override_note"] = (
        "You chose to proceed despite the assessment. The verdict above is "
        "unchanged and still stands — what follows is how to make this plan "
        "as survivable as possible, not an endorsement of it.")
    return d


def _mitigations(decision: dict) -> list[str]:
    out = [
        "Borrow the recommended amount, not the eligible amount. The gap "
        "between them is the month you default.",
        "Reserve the working-capital floor in a separate account before "
        "buying the asset.",
    ]
    for g in decision.get("hard_gates_triggered", []):
        if "Survival probability" in g:
            out.append("Line up a second income source for the first year — "
                       "the cash-flow model does not survive on its own.")
        if "Blocking risk flag" in g and "buyer" in g.lower():
            out.append("Secure a written offtake commitment from a buyer "
                       "BEFORE drawing the loan.")
        if "road" in g.lower():
            out.append("Confirm a monsoon-season collection route in writing, "
                       "or plan for storage.")
    for r in decision.get("reasons", []):
        if "veterinary" in r.lower():
            out.append("Budget for veterinary call-out costs from the nearest "
                       "town and identify the vet before purchase.")
    seen, uniq = set(), []
    for m in out:
        if m not in seen:
            seen.add(m); uniq.append(m)
    return uniq
