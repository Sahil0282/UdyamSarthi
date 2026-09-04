"""M3 — Finance Engine.

Loads the versioned scheme YAMLs and computes the loan the scheme would
actually give, including the cap collision that the naive arithmetic hides.

PART 10: never hardcode the problem statement's scheme parameters. Everything
here comes from data/rules/schemes/*.yaml, and every Fact carries the
scheme's own source_url and effective_from.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from core.facts import Fact, derive

SCHEMES_DIR = Path(__file__).resolve().parents[1] / "data" / "rules" / "schemes"


def load_schemes(d: Path | None = None) -> list[dict]:
    d = d or SCHEMES_DIR
    return [yaml.safe_load(p.read_text()) for p in sorted(d.glob("*.yaml"))]


def _scheme_source(s: dict) -> str:
    return (f"{s['corporation']} {s.get('scheme_name', s['scheme_id'])} "
            f"(rules file, effective {s['effective_from']})")


def _scheme_note(s: dict) -> str:
    n = (f"From versioned scheme rules {s['scheme_id']}, "
         f"source {s.get('source_url')}, effective {s['effective_from']}. "
         "Scheme terms are national/state-level, not village-level.")
    if not s.get("verified", False):
        n += (" NOT re-verified against the live published scheme document — "
              f"{s.get('notes', '')}").rstrip()
    return n


def eligible_schemes(schemes: list[dict], target_group: str | None,
                     annual_income_inr: float | None) -> list[dict]:
    out = []
    for s in schemes:
        if target_group and s.get("target_group") and \
                s["target_group"].upper() != target_group.upper():
            continue
        if annual_income_inr is not None and \
                annual_income_inr > s.get("income_ceiling_inr", float("inf")):
            continue
        out.append(s)
    return out


def rate_for(scheme: dict, loan_inr: float) -> float:
    """Slabbed interest: the rate is chosen by which slab the loan falls into.

    NBCFDC publishes the slabs as bands on total loan size, not as marginal
    tranches, so a 6 lakh loan is entirely at the 8% rate rather than 5 lakh at
    6% plus 1 lakh at 8%. Stated explicitly because the two readings differ by
    real money.
    """
    slabs = sorted(scheme["interest_slabs"], key=lambda x: x["upto_inr"])
    for slab in slabs:
        if loan_inr <= slab["upto_inr"]:
            return float(slab["annual_rate"])
    return float(slabs[-1]["annual_rate"])


def emi(principal: float, annual_rate: float, years: int,
        moratorium_months: int = 0, per_year: int = 12) -> dict:
    """Instalment on an amortising loan, normalised to a monthly figure.

    Interest during the moratorium is ACCRUED and capitalised — the borrower
    pays nothing during it, and the balance grows. That is the conservative
    reading of "moratorium" and the one that does not flatter the verdict.
    """
    if principal <= 0:
        return {"instalment": 0.0, "monthly_equivalent": 0.0,
                "principal_after_moratorium": 0.0, "n_instalments": 0,
                "total_repayment": 0.0}

    # Capitalise moratorium interest.
    bal = principal * (1 + annual_rate / 12.0) ** moratorium_months

    n = int(years * per_year)
    r = annual_rate / per_year
    if r == 0:
        inst = bal / n
    else:
        inst = bal * r * (1 + r) ** n / ((1 + r) ** n - 1)
    return {
        "instalment": inst,
        "monthly_equivalent": inst * per_year / 12.0,
        "principal_after_moratorium": bal,
        "n_instalments": n,
        "total_repayment": inst * n,
    }


FREQ = {"monthly": 12, "quarterly": 4, "half_yearly": 2, "annual": 1}


def analyse(scheme: dict, capital_inr: float,
            project_cost_override: float | None = None) -> dict[str, Fact]:
    """Compute what this scheme would actually lend against `capital_inr`."""
    src = _scheme_source(scheme)
    note = _scheme_note(scheme)
    yr = int(str(scheme["effective_from"])[:4])
    conf = "high" if scheme.get("verified") else "medium"

    def F(v, unit, extra: str = "") -> Fact:
        return Fact(v, unit, src, yr, "state", conf,
                    note=(note + (" " + extra if extra else "")))

    ltc = float(scheme["loan_to_cost_ratio"])
    cap = float(scheme["per_beneficiary_cap_inr"])

    out: dict[str, Fact] = {"scheme_id": Fact(
        scheme["scheme_id"], None, src, yr, "state", conf, note=note)}
    out["loan_to_cost_ratio"] = F(ltc, "ratio")
    out["per_beneficiary_cap"] = F(cap, "INR")

    # What the borrower's margin money can in theory support.
    theoretical_project = (project_cost_override
                           if project_cost_override is not None
                           else capital_inr / (1 - ltc))
    theoretical_loan = theoretical_project * ltc

    out["theoretical_project_cost"] = F(
        round(theoretical_project, 2), "INR",
        "Project size the borrower's own margin money could support before the "
        "scheme cap is applied.")
    out["theoretical_loan"] = F(round(theoretical_loan, 2), "INR")

    # ---- the cap collision ----
    capped = theoretical_loan > cap
    eligible_loan = min(theoretical_loan, cap)
    workable_project = eligible_loan / ltc
    margin_used = workable_project - eligible_loan
    margin_left = capital_inr - margin_used

    out["eligible_loan"] = F(round(eligible_loan, 2), "INR")
    out["cap_applied"] = Fact(
        capped, None, src, yr, "state", conf,
        note=(note + " Cap collision: the scheme's per-beneficiary ceiling binds "
              "before the borrower's margin money runs out.") if capped
        else note)
    out["workable_project_cost"] = F(round(workable_project, 2), "INR")
    out["margin_money_required"] = F(round(margin_used, 2), "INR")
    out["margin_money_left_over"] = F(
        round(margin_left, 2), "INR",
        "Capital not absorbed by the capped project. Better held as working "
        "capital than forced into capex." if capped else "")

    # ---- repayment ----
    rate = rate_for(scheme, eligible_loan)
    years = int(scheme["repayment_years"])
    mor = int(scheme.get("moratorium_months", 0))
    freq_name = scheme.get("installment_frequency", "monthly")
    per_year = FREQ[freq_name]

    sched = emi(eligible_loan, rate, years, mor, per_year)
    out["interest_rate"] = F(rate, "annual rate")
    out["tenure_years"] = F(years, "years")
    out["moratorium_months"] = F(
        mor, "months",
        "Interest accrues and is capitalised during the moratorium; no payment "
        "is made. The balance therefore grows before repayment starts.")
    out["installment_frequency"] = Fact(
        freq_name, None, src, yr, "state", conf, note=note)
    out["installment"] = F(
        round(sched["instalment"], 2), f"INR per {freq_name[:-2]}"
        if freq_name.endswith("ly") else "INR")
    out["emi"] = F(
        round(sched["monthly_equivalent"], 2), "INR per month",
        f"Normalised to a monthly figure from a {freq_name} instalment of "
        f"INR {sched['instalment']:,.0f}, for comparison against monthly cash "
        "flow. The borrower actually pays {}.".format(
            "monthly" if freq_name == "monthly" else f"{freq_name}"))
    out["principal_after_moratorium"] = F(
        round(sched["principal_after_moratorium"], 2), "INR")
    out["total_repayment"] = F(round(sched["total_repayment"], 2), "INR")
    return out


def emi_for_principal(scheme: dict, principal: float) -> float:
    """Monthly-equivalent EMI for an arbitrary principal under this scheme."""
    return emi(
        principal, rate_for(scheme, principal), int(scheme["repayment_years"]),
        int(scheme.get("moratorium_months", 0)),
        FREQ[scheme.get("installment_frequency", "monthly")],
    )["monthly_equivalent"]
