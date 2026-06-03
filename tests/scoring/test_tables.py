from app.scoring.tables import NUTRISCORE_TO_SCORE, NOVA_TO_SCORE


def test_nutriscore_table_covers_all_grades():
    for grade in ("A", "B", "C", "D", "E"):
        assert grade in NUTRISCORE_TO_SCORE


def test_nutriscore_a_is_highest():
    assert NUTRISCORE_TO_SCORE["A"] > NUTRISCORE_TO_SCORE["E"]


def test_nova_table_covers_all_groups():
    for group in (1, 2, 3, 4):
        assert group in NOVA_TO_SCORE


def test_nova_1_is_highest():
    assert NOVA_TO_SCORE[1] > NOVA_TO_SCORE[4]


def test_all_scores_in_range():
    for v in NUTRISCORE_TO_SCORE.values():
        assert 0 <= v <= 100
    for v in NOVA_TO_SCORE.values():
        assert 0 <= v <= 100
