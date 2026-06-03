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
