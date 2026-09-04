"""M7 — Narration. The ONLY module that may import an LLM SDK.

Three rules, enforced by code below rather than by prompt discipline alone:

1. The template renderer is the primary path. It is built first, it needs no
   network, and `--no-llm` uses it. If the LLM is unavailable, wrong, or
   caught inventing a number, this is what the user gets.
2. The LLM receives a finished envelope and returns prose. It is handed no
   tools, no data access and no arithmetic. It cannot change a number because
   it is not in the computation call graph at all.
3. Every number the LLM emits is checked against the envelope afterwards. One
   number that does not trace back and the whole generation is discarded.

Note on what "the confidence" means in the output: PART 5.1 says a derived
Fact inherits the lowest confidence of its inputs, so the dairy verdict is
`low` because yield and opex are national benchmarks. The renderer says that
out loud. A user should not have to open the JSON to learn it.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from core.facts import Fact

# override=True so the committed .env beats anything stale in the shell.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

# --------------------------------------------------------------------------
# Number handling
# --------------------------------------------------------------------------
# Matches 1234, 1,234, 1,00,000 (Indian grouping), 12.5, .5
_NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{2,3})+|\d+)(\.\d+)?(?![\w])")


def _to_float(tok: str) -> float | None:
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


def extract_numbers(text: str) -> list[float]:
    out = []
    for m in _NUM_RE.finditer(text):
        v = _to_float(m.group(0))
        if v is not None:
            out.append(v)
    return out


def allowed_numbers(obj: Any) -> set[float]:
    """Every number that appears anywhere in the envelope.

    Includes numbers embedded in source and note strings, because those are
    literally present in the input the LLM was given — quoting '270 lactation
    days' from a note is not an invention.
    """
    allowed: set[float] = set()

    def add(v: float, as_pct: bool = False) -> None:
        allowed.add(round(v, 4))
        allowed.add(round(v))
        allowed.add(round(v, 1))
        allowed.add(round(v, 2))
        if abs(v) >= 1000:                      # lakh / thousand phrasings
            allowed.add(round(v / 100000, 2))
            allowed.add(round(v / 100000, 1))
            allowed.add(round(v / 1000, 2))
            allowed.add(round(v / 1000, 1))
        if as_pct and 0 < abs(v) <= 1:
            # Only genuine rates get a percentage form. Expanding EVERY value
            # under 1 was too generous: the 0.45 affordability weight then
            # legitimised an invented "45% growth", which a live model did in
            # fact produce under an adversarial prompt.
            allowed.add(round(v * 100, 1))
            allowed.add(round(v * 100))

    PCT_UNITS = ("probability", "percent", "rate", "ratio", "share")

    def walk(o: Any, pct: bool = False) -> None:
        if isinstance(o, Fact):
            u = (o.unit or "").lower()
            walk(o.to_dict(), any(k in u for k in PCT_UNITS)); return
        if isinstance(o, bool):
            return
        if isinstance(o, (int, float)):
            add(float(o), pct); return
        if isinstance(o, str):
            for v in extract_numbers(o):
                add(v)
            return
        if isinstance(o, dict):
            u = str(o.get("unit") or "").lower()
            sub = pct or any(k in u for k in PCT_UNITS)
            for v in o.values():
                walk(v, sub)
            return
        if isinstance(o, (list, tuple)):
            for v in o:
                walk(v, pct)

    walk(obj)
    return allowed


def validate_numbers(text: str, envelope: dict) -> list[float]:
    """Return the numbers in `text` that do NOT trace back to the envelope."""
    allowed = allowed_numbers(envelope)
    bad = []
    for v in extract_numbers(text):
        if not any(abs(v - a) < 0.011 for a in
                   (round(v, 4), round(v), round(v, 1), round(v, 2))
                   if a in allowed):
            if round(v, 4) not in allowed and round(v) not in allowed \
                    and round(v, 1) not in allowed and round(v, 2) not in allowed:
                bad.append(v)
    return bad


# --------------------------------------------------------------------------
# 1. TEMPLATE RENDERER — the --no-llm path. Built first, no network.
# --------------------------------------------------------------------------
VERDICT_EN = {
    "PROCEED": "This plan looks workable.",
    "PROCEED_WITH_CHANGES": "This plan can work, but not as you have described it.",
    "RECONSIDER": "We advise against this plan in this village.",
}
VERDICT_MR = {
    "PROCEED": "ही योजना व्यवहार्य दिसते.",
    "PROCEED_WITH_CHANGES": "ही योजना चालू शकते, पण तुम्ही सांगितल्याप्रमाणे नाही.",
    "RECONSIDER": "या गावात ही योजना करू नये असा आमचा सल्ला आहे.",
}
CONF_EN = {
    "high": "Confidence in this assessment is HIGH.",
    "medium": "Confidence in this assessment is MEDIUM.",
    "low": ("Confidence in this assessment is LOW. The map, the population and "
            "the loan rules are specific to your village, but the cost and "
            "yield figures behind the cash flow are national benchmarks, not "
            "measured in Ahmadnagar."),
}
CONF_MR = {
    "high": "या मूल्यांकनाची विश्वासार्हता जास्त आहे.",
    "medium": "या मूल्यांकनाची विश्वासार्हता मध्यम आहे.",
    "low": ("या मूल्यांकनाची विश्वासार्हता कमी आहे. नकाशा, लोकसंख्या आणि कर्ज "
            "नियम तुमच्या गावासाठी अचूक आहेत, पण खर्च आणि दूध उत्पादनाचे आकडे "
            "राष्ट्रीय सरासरी आहेत, अहमदनगरमध्ये मोजलेले नाहीत."),
}


def _v(f) -> Any:
    return f.value if isinstance(f, Fact) else (
        f.get("value") if isinstance(f, dict) else f)


def _inr(x) -> str:
    return "n/a" if x is None else f"{float(x):,.0f}"


def render_template(env: dict, lang: str = "en") -> str:
    """Deterministic prose. No LLM, no network, no invention by construction."""
    if "error" in env:
        return env["error"]
    if env.get("resolution", {}).get("needs_confirmation"):
        return env["resolution"]["message"]

    c = env["resolution"]["chosen"]
    d, m, fin, aff = env["decision"], env["market"], env["finance"], env["affordability"]
    risk = env["risk"]
    mr = lang == "mr"
    L: list[str] = []

    place = c["place_name"].title()
    if mr:
        L.append(f"{place} ({c['subdistrict_name'].title()}) साठी सल्ला.")
        L.append(VERDICT_MR[d["verdict"]])
        L.append(
            f"तुमच्या गावाच्या ८ किमी परिसरात {_inr(_v(m['catchment_population']))} "
            f"लोक राहतात ({_v(m['villages_in_catchment'])} गावे).")
        L.append(
            f"या योजनेखाली तुम्ही {_inr(_v(fin['eligible_loan']))} रुपये कर्जास "
            f"पात्र आहात, ज्याचा मासिक हप्ता {_inr(_v(fin['emi']))} रुपये होईल.")
        L.append(
            f"पण हा व्यवसाय दरमहा {_inr(_v(aff['monthly_revenue']))} रुपये कमावतो, "
            f"त्यातून {_inr(_v(aff['monthly_opex']))} रुपये खर्च आणि "
            f"{_inr(_v(aff['household_drawings']))} रुपये घरखर्च वजा जाता "
            f"{_inr(_v(aff['net_available_for_emi']))} रुपये शिल्लक राहतात.")
        L.append(
            f"म्हणून आम्ही {_inr(_v(aff['recommended_loan']))} रुपये कर्ज घेण्याची "
            f"शिफारस करतो.")
        L.append(
            f"कर्जातून {_inr(_v(aff['working_capital_floor']))} रुपये खेळते भांडवल "
            f"म्हणून बाजूला ठेवा.")
        if risk["flags"]:
            L.append("धोक्याचे इशारे: " + "; ".join(
                f["code"].replace("_", " ").lower() for f in risk["flags"]) + ".")
        L.append(CONF_MR[d["confidence"]])
        if d.get("override_applied"):
            L.append("तुम्ही तरीही पुढे जाण्याचे ठरवले आहे. निर्णय बदललेला नाही; "
                     "खालील उपाय धोका कमी करण्यासाठी आहेत.")
    else:
        L.append(f"Advice for {place} ({c['subdistrict_name'].title()}, "
                 f"{c['district_name'].title()}).")
        L.append(VERDICT_EN[d["verdict"]])
        L.append(
            f"Within 8 km of your village there are about "
            f"{_inr(_v(m['catchment_population']))} people across "
            f"{_v(m['villages_in_catchment'])} villages.")
        pc = _v(m.get("procurement_capacity"))
        if pc is not None:
            L.append(
                f"Milk processing within that ring employs {_inr(pc)} people, "
                "which is the buyer capacity for your milk. Note this counts "
                "milk plants, not other dairy farmers — the Economic Census "
                "does not record livestock rearing at all.")
        L.append(
            f"Under this scheme you are eligible for "
            f"{_inr(_v(fin['eligible_loan']))} rupees, which carries a monthly "
            f"instalment of {_inr(_v(fin['emi']))} rupees.")
        L.append(
            f"This business earns about {_inr(_v(aff['monthly_revenue']))} "
            f"rupees a month. After {_inr(_v(aff['monthly_opex']))} rupees of "
            f"running cost and {_inr(_v(aff['household_drawings']))} rupees "
            f"the household needs to live on, "
            f"{_inr(_v(aff['net_available_for_emi']))} rupees are left.")
        L.append(
            f"We recommend borrowing {_inr(_v(aff['recommended_loan']))} rupees, "
            f"not the full amount you are eligible for.")
        L.append(
            f"Set aside {_inr(_v(aff['working_capital_floor']))} rupees from the "
            "loan as working capital before buying anything.")
        sr = _v(risk["survival_at_recommended"])
        se = _v(risk["survival_at_eligible"])
        if sr is not None and se is not None:
            L.append(
                f"Stress testing the cash flow, the plan survives in "
                f"{float(sr) * 100:.0f} out of 100 runs at the recommended "
                f"amount, against {float(se) * 100:.0f} at the full eligible "
                "amount.")
        if risk["flags"]:
            L.append("Risks found: " + "; ".join(
                f["message"] for f in risk["flags"][:3]))
        if d["alternatives"]:
            alts = ", ".join(a["display_name"] for a in d["alternatives"][:3])
            L.append(f"Other options scored for this village: {alts}.")
        L.append(CONF_EN[d["confidence"]])
        if d.get("override_applied"):
            L.append("You chose to proceed anyway. The verdict above has not "
                     "changed; the steps below are to reduce the risk.")
            for x in d.get("mitigations", [])[:3]:
                L.append(x)
    return " ".join(L)


# --------------------------------------------------------------------------
# 2. LLM PATH — Gemini. Translates only.
# --------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a translator and narrator for a rural enterprise
advisory system in Maharashtra, India. You will be given a JSON object that has
ALREADY been computed. Your job is to turn it into clear, plain prose for a
person with limited literacy.

ABSOLUTE RULES — breaking any one of these makes your output unusable:

1. You MUST NOT introduce any number that is not present in the JSON you are
   given. Do not calculate. Do not estimate. Do not round to a "nicer" number.
   Do not convert units. Do not add percentages, totals, averages, ratios or
   dates of your own. If you want to state a number, copy it from the JSON.
2. You MUST NOT change the verdict, soften it, or add optimism the JSON does
   not contain. If the verdict is RECONSIDER, your prose advises against it.
3. You MUST state the confidence level explicitly, in words, including WHY it
   is low if it is low. Never present a low-confidence result as certain.
4. Do not invent risks, causes, benefits, or advice that is not in the JSON.
5. Write in short sentences. Address the reader as "you".

Write %(n)d-%(m)d sentences of flowing prose. No bullet points, no headings,
no markdown. Output the prose only."""

LANG_INSTRUCTION = {
    "en": "Write in simple English.",
    "mr": ("Write in Marathi (Devanagari script). Keep all numerals as "
           "Western digits exactly as they appear in the JSON."),
}


def _envelope_for_llm(env: dict) -> dict:
    """The subset handed to the model. Geometry and candidate lists are
    stripped: they are large, they are not narratable, and every number in
    them would widen the validator's allowed set for no benefit."""
    from core.facts import encode

    d, m, fin, aff, risk = (env["decision"], env["market"], env["finance"],
                            env["affordability"], env["risk"])
    return encode({
        "place": env["resolution"]["chosen"]["place_name"],
        "subdistrict": env["resolution"]["chosen"]["subdistrict_name"],
        "district": env["resolution"]["chosen"]["district_name"],
        "sector": env["query"]["sector"],
        "verdict": d["verdict"],
        "confidence": d["confidence"],
        "confidence_explanation": CONF_EN[d["confidence"]],
        "override_applied": d.get("override_applied", False),
        "mitigations": d.get("mitigations", []),
        "reasons": d["reasons"][:6],
        "market": {k: m[k] for k in (
            "catchment_population", "villages_in_catchment",
            "procurement_capacity", "saturation_percentile") if k in m},
        "finance": {k: fin[k] for k in (
            "eligible_loan", "interest_rate", "emi", "tenure_years") if k in fin},
        "affordability": {k: aff[k] for k in (
            "monthly_revenue", "monthly_opex", "household_drawings",
            "net_available_for_emi", "recommended_loan",
            "working_capital_floor", "emi_at_recommended") if k in aff},
        "risk": {
            "flags": [{"code": f["code"], "severity": f["severity"],
                       "message": f["message"]} for f in risk["flags"]],
            "survival_at_recommended": risk["survival_at_recommended"],
            "survival_at_eligible": risk["survival_at_eligible"],
        },
        "alternatives": [{"sector": a["display_name"], "why": a["why"]}
                         for a in d["alternatives"]],
    })


# Free-tier quota is 20 requests/day PER MODEL, so the model is configurable:
# switching it is the difference between a demo that narrates and one that
# silently falls back to templates all day.
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")


def _gemini(prompt: str, system: str,
            model: str = DEFAULT_MODEL) -> str:
    from google import genai
    from google.genai import types

    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2,
            max_output_tokens=2000,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        ),
    )
    return (resp.text or "").strip()


def narrate(env: dict, use_llm: bool = False, lang: str = "en",
            _system_override: str | None = None,
            model: str = DEFAULT_MODEL,
            generate=None) -> dict:
    """Return prose plus a record of how it was produced and what was checked.

    `generate` is injectable so the validator and the fallback path can be
    tested deterministically, without a network call and without pretending a
    canned string came from the model.
    """
    import json

    template = render_template(env, lang=lang)
    result = {
        "text": template,
        "path": "template",
        "lang": lang,
        "llm_attempted": False,
        "validator": {"ran": False, "violations": [], "passed": None},
    }
    if not use_llm:
        return result

    system = (_system_override or (SYSTEM_PROMPT % {"n": 6, "m": 10})) + \
        "\n\n" + LANG_INSTRUCTION.get(lang, LANG_INSTRUCTION["en"])
    payload = json.dumps(_envelope_for_llm(env), ensure_ascii=False, indent=1,
                         default=str)
    result["llm_attempted"] = True
    gen = generate or (lambda p, sys_: _gemini(p, sys_, model=model))
    try:
        text = gen(payload, system)
    except Exception as exc:
        result["llm_error"] = f"{type(exc).__name__}: {exc}"
        result["fallback_reason"] = "llm_call_failed"
        return result

    if not text:
        result["fallback_reason"] = "llm_returned_empty"
        return result

    bad = validate_numbers(text, env)
    result["validator"] = {"ran": True, "violations": bad, "passed": not bad}
    if bad:
        # Discard the whole generation. A narration with one invented number is
        # not partially usable — the user cannot tell which number was invented.
        result["fallback_reason"] = "numeric_validator_rejected"
        result["rejected_text"] = text
        return result

    result["text"] = text
    result["path"] = "llm"
    return result
