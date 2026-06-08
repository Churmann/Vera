from app.scoring.nutrition_scorer import NutritionScorer


def test_nutriscore_a_maps_to_100(make_product):
    result = NutritionScorer().score(make_product(nutriscore_grade="A"))
    assert result.score == 100
    assert result.input_value == 100
    assert result.input_label == "Nutri-Score A"


def test_nutriscore_e_maps_to_20(make_product):
    result = NutritionScorer().score(make_product(nutriscore_grade="E"))
    assert result.score == 20


def test_nutriscore_c_maps_to_60(make_product):
    result = NutritionScorer().score(make_product(nutriscore_grade="C"))
    assert result.score == 60


def test_missing_nutriscore_gives_50(make_product):
    result = NutritionScorer().score(make_product(nutriscore_grade=None))
    assert result.score == 50
    assert "unavailable" in result.input_label.lower()


def test_good_grade_has_positive(make_product):
    result = NutritionScorer().score(make_product(nutriscore_grade="A"))
    assert len(result.positives) > 0


def test_dimension_metadata(make_product):
    result = NutritionScorer().score(make_product(nutriscore_grade="B"))
    assert result.id == "nutrition"
    assert result.weight_default == 0.5
    assert len(result.summary) > 0


def test_plain_band_leads_with_plain_language(make_product):
    assert NutritionScorer().score(make_product(nutriscore_grade="E")).plain_band == "Poor"
    assert NutritionScorer().score(make_product(nutriscore_grade="A")).plain_band == "Excellent"
    assert NutritionScorer().score(make_product(nutriscore_grade="C")).plain_band == "Average"


def test_missing_nutriscore_has_unknown_plain_band(make_product):
    assert "unknown" in NutritionScorer().score(make_product(nutriscore_grade=None)).plain_band.lower()


def test_meaning_explains_nutriscore_in_plain_terms(make_product):
    meaning = NutritionScorer().score(make_product(nutriscore_grade="E")).meaning.lower()
    assert "nutri-score" in meaning
    # Names the plain inputs an ordinary reader recognises.
    assert "sugar" in meaning and "salt" in meaning
    assert "fibre" in meaning
