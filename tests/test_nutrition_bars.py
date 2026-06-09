import pytest

from app.nutrition_bars import build


def _bars(make_product, **kw):
    return {b.key: b for b in build(make_product(**kw))}


def test_food_sugar_bands(make_product):
    assert _bars(make_product, nutriments={"sugars": 2.4})["sugars"].band_label == "Low"
    assert _bars(make_product, nutriments={"sugars": 12.0})["sugars"].band_label == "Medium"
    assert _bars(make_product, nutriments={"sugars": 30.0})["sugars"].band_label == "High"


def test_food_sugar_boundaries_inclusive_low_and_high(make_product):
    # 5.0 is the documented top of Low; 22.5 the top of Medium.
    assert _bars(make_product, nutriments={"sugars": 5.0})["sugars"].band_label == "Low"
    assert _bars(make_product, nutriments={"sugars": 22.5})["sugars"].band_label == "Medium"


def test_salt_and_satfat_food_bands(make_product):
    assert _bars(make_product, nutriments={"salt": 0.18})["salt"].band_label == "Low"
    assert _bars(make_product, nutriments={"salt": 2.0})["salt"].band_label == "High"
    assert _bars(make_product, nutriments={"saturated_fat": 2.1})["saturated_fat"].band_label == "Medium"


def test_drink_column_switches_band(make_product):
    # 4.0 g sugar is Low as a food (<=5) but Medium as a drink (>2.5).
    assert _bars(make_product, nutriments={"sugars": 4.0})["sugars"].band_label == "Low"
    drink = _bars(make_product, nutriments={"sugars": 4.0}, is_beverage=True)
    assert drink["sugars"].band_label == "Medium"


def test_drink_satfat_high_threshold_is_2_5_not_8_75(make_product):
    # Regression guard: drink saturated-fat HIGH is >2.5 g/100 ml (8.75 is total fat).
    b = _bars(make_product, nutriments={"saturated_fat": 3.0}, is_beverage=True)["saturated_fat"]
    assert b.band_label == "High"
    b2 = _bars(make_product, nutriments={"saturated_fat": 2.0}, is_beverage=True)["saturated_fat"]
    assert b2.band_label == "Medium"


def test_marker_piecewise_and_clamped(make_product):
    # Each zone is a third. value at low_max sits at ~33%; far over high_min clamps to 100.
    at_lowmax = _bars(make_product, nutriments={"sugars": 5.0})["sugars"].marker_pct
    assert 32.0 <= at_lowmax <= 34.0
    huge = _bars(make_product, nutriments={"sugars": 90.0})["sugars"].marker_pct
    assert huge == 100.0


def test_fibre_higher_better_bands_and_tone(make_product):
    low = _bars(make_product, nutriments={"fibre": 2.0})["fibre"]
    src = _bars(make_product, nutriments={"fibre": 4.0})["fibre"]
    high = _bars(make_product, nutriments={"fibre": 7.0})["fibre"]
    assert (low.band_label, low.band) == ("Low", "high")        # little fibre -> red tone
    assert (src.band_label, src.band) == ("Source", "moderate")
    assert (high.band_label, high.band) == ("High", "low")      # lots of fibre -> sage tone
    assert high.kind == "higher_better"
    assert high.source_key == "eu_fibre"


def test_protein_and_energy_are_neutral(make_product):
    bars = _bars(make_product, nutriments={"protein": 9.2, "energy_kcal": 432})
    assert bars["protein"].kind == "neutral"
    assert bars["protein"].band == "none"
    assert bars["protein"].band_label == ""
    assert "no official" in bars["protein"].caption
    assert bars["energy_kcal"].kind == "neutral"
    assert bars["energy_kcal"].unit == "kcal"


def test_missing_nutrient_emits_missing_bar(make_product):
    bars = _bars(make_product, nutriments={"sugars": 2.0})
    assert bars["salt"].kind == "missing"
    assert bars["salt"].present is False


def test_all_missing_returns_empty_list(make_product):
    assert build(make_product(nutriments={})) == []


def test_order_is_fixed(make_product):
    keys = [b.key for b in build(make_product(nutriments={
        "sugars": 1, "salt": 1, "saturated_fat": 1, "fibre": 1, "protein": 1, "energy_kcal": 1,
    }))]
    assert keys == ["sugars", "salt", "saturated_fat", "fibre", "protein", "energy_kcal"]
