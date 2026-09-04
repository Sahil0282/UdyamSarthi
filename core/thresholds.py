"""Every verdict threshold and weight in the system, in one auditable file.

PART 10: "keep verdict thresholds as named constants in one auditable file".
Nothing in decision.py may hardcode a number — if a figure influences a
verdict, it is defined here, with the reasoning for its value written down.

Changing any value here changes what the system advises. That is the point:
a government-facing tool must be able to show exactly which line moved.
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# Component weights. Must sum to 1.0 (asserted at import).
# --------------------------------------------------------------------------
WEIGHT_MARKET = 0.30
WEIGHT_AFFORDABILITY = 0.45   # heaviest: the PS's stated gap is viability,
                              # and affordability is where loans actually fail
WEIGHT_RISK = 0.25

# --------------------------------------------------------------------------
# Verdict bands on the overall score (0..1).
# --------------------------------------------------------------------------
PROCEED_MIN = 0.62            # at or above -> PROCEED
RECONSIDER_MAX = 0.40         # strictly below -> RECONSIDER
# between the two -> PROCEED_WITH_CHANGES

# --------------------------------------------------------------------------
# Hard gates. Any one of these forces RECONSIDER regardless of the score.
# A weighted average can otherwise average away a fatal condition.
# --------------------------------------------------------------------------
MIN_SURVIVAL_AT_RECOMMENDED = 0.50   # a coin-flip business is not advice
MIN_RECOMMENDED_LOAN_INR = 25_000    # below this the loan cannot buy the unit
MIN_RECOMMENDED_FRACTION = 0.15      # recommended/eligible under this means
                                     # the scheme and the business disagree
                                     # so completely that the plan is wrong
BLOCKING_FLAGS = frozenset({
    "NO_BUYER_IN_CATCHMENT",         # nothing to sell to
    "NO_ALL_WEATHER_ROAD",           # only blocking for daily-collection sectors
})

# --------------------------------------------------------------------------
# Risk scoring.
# --------------------------------------------------------------------------
SURVIVAL_WEIGHT_IN_RISK = 0.60       # rest comes from the computed flags
FLAG_PENALTY = {"high": 0.34, "medium": 0.16, "low": 0.05}
MAX_FLAG_PENALTY = 1.0

# --------------------------------------------------------------------------
# Affordability scoring.
# --------------------------------------------------------------------------
# How much of the eligible-loan EMI the business can safely cover. 1.0 means
# the business can service everything the scheme would lend.
AFFORDABILITY_FULL_COVER = 1.0

# --------------------------------------------------------------------------
# Alternatives ranking.
# --------------------------------------------------------------------------
N_ALTERNATIVES = 3
ALTERNATIVE_MIN_SCORE = 0.0   # report the best available even if all are poor,
                              # but never present a poor one as good

# --------------------------------------------------------------------------
# Confidence aggregation: the verdict is only as good as its weakest inputs.
# --------------------------------------------------------------------------
CONFIDENCE_FROM_UNVERIFIED_TEMPLATE = "low"

assert abs(WEIGHT_MARKET + WEIGHT_AFFORDABILITY + WEIGHT_RISK - 1.0) < 1e-9, \
    "component weights must sum to 1.0"
