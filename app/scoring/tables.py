# Deliberate v1 simplification — easy to find and adjust here.
# Refine mappings in a later iteration based on user feedback.

NUTRISCORE_TO_SCORE: dict[str, int] = {
    "A": 100,
    "B": 80,
    "C": 60,
    "D": 40,
    "E": 20,
}

NOVA_TO_SCORE: dict[int, int] = {
    1: 100,
    2: 75,
    3: 40,
    4: 0,
}

# Core-dimension floor: when a product is nutritionally very poor OR ultra-processed,
# its overall score is capped at this value so a clean additives profile can't lift
# it into "Mixed" or "Good" territory.
#
# POOR_SCORE_CAP      — the ceiling applied when any trigger fires (tune here).
# NUTRITION_CAP_THRESHOLD — nutrition scores at or below this value trigger the cap.
#                           20 = Nutri-Score E only. Set to 40 to also include D.
POOR_SCORE_CAP: int = 35
NUTRITION_CAP_THRESHOLD: int = 20
