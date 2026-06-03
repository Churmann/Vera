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
