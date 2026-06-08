from app.scoring.nova_scorer import NovaScorer


def test_nova_1_maps_to_100(make_product):
    result = NovaScorer().score(make_product(nova_group=1))
    assert result.score == 100
    assert result.input_label == "NOVA group 1"
    assert result.input_value == 100


def test_nova_4_maps_to_0(make_product):
    result = NovaScorer().score(make_product(nova_group=4))
    assert result.score == 0


def test_nova_2_maps_to_75(make_product):
    result = NovaScorer().score(make_product(nova_group=2))
    assert result.score == 75


def test_missing_nova_gives_50(make_product):
    result = NovaScorer().score(make_product(nova_group=None))
    assert result.score == 50
    assert "unavailable" in result.input_label.lower()


def test_low_processing_has_positive(make_product):
    result = NovaScorer().score(make_product(nova_group=1))
    assert len(result.positives) > 0


def test_dimension_metadata(make_product):
    result = NovaScorer().score(make_product(nova_group=3))
    assert result.id == "nova"
    assert result.weight_default == 0.2
    assert len(result.summary) > 0


def test_plain_band_leads_with_plain_language(make_product):
    # The prominent label is the plain classification, not the NOVA jargon.
    assert NovaScorer().score(make_product(nova_group=4)).plain_band == "Ultra-processed"
    assert NovaScorer().score(make_product(nova_group=3)).plain_band == "Processed"
    assert NovaScorer().score(make_product(nova_group=1)).plain_band == "Minimally processed"


def test_missing_nova_has_unknown_plain_band(make_product):
    assert "unknown" in NovaScorer().score(make_product(nova_group=None)).plain_band.lower()


def test_meaning_explains_nova_in_plain_terms(make_product):
    meaning = NovaScorer().score(make_product(nova_group=4)).meaning.lower()
    # Explains the scale and the plain-language consequence, jargon expanded.
    assert "nova" in meaning
    assert "ultra-processed" in meaning
    assert "health" in meaning
