import pytest

from app.nutrition_bars import build


def _bars(make_product, **kw):
    return {b.key: b for b in build(make_product(**kw)).bars}


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


def test_order_is_fixed(make_product):
    keys = [b.key for b in build(make_product(nutriments={
        "sugars": 1, "salt": 1, "saturated_fat": 1, "fibre": 1, "protein": 1, "energy_kcal": 1,
    })).bars]
    assert keys == ["sugars", "salt", "saturated_fat", "fibre", "protein", "energy_kcal"]


def test_complete_product_has_no_missing_note_or_summary(make_product):
    panel = build(make_product(nutriments={
        "sugars": 1, "salt": 1, "saturated_fat": 1, "fibre": 1, "protein": 1, "energy_kcal": 1,
    }))
    assert all(b.present for b in panel.bars)
    assert panel.note == ""
    assert panel.missing_summary == ""


def test_a_few_missing_keeps_individual_no_data_rows_and_adds_note(make_product):
    # The Wrigley's gum shape: sugar/protein/energy reported, salt/sat fat/fibre absent.
    panel = build(make_product(nutriments={"sugars": 0, "protein": 0, "energy_kcal": 23.9}))
    by_key = {b.key: b for b in panel.bars}
    # All six still appear, in fixed order, the three gaps as explicit no-data rows.
    assert [b.key for b in panel.bars] == [
        "sugars", "salt", "saturated_fat", "fibre", "protein", "energy_kcal"]
    assert by_key["salt"].kind == "missing" and by_key["salt"].present is False
    assert by_key["fibre"].present is False
    # An honest note explains the gap; no collapsed summary in the partial case.
    assert "Open Food Facts" in panel.note
    assert panel.missing_summary == ""


def test_three_missing_is_the_partial_boundary_not_collapsed(make_product):
    panel = build(make_product(nutriments={"sugars": 1, "protein": 1, "energy_kcal": 1}))
    assert any(b.kind == "missing" for b in panel.bars)
    assert panel.missing_summary == ""
    assert panel.note != ""


def test_most_missing_collapses_to_one_summary_naming_the_gaps(make_product):
    # Four of six absent -> the section is mostly empty, so collapse the gaps.
    panel = build(make_product(nutriments={"sugars": 1, "protein": 1}))
    assert all(b.present for b in panel.bars)          # only the two real bars remain
    assert not any(b.kind == "missing" for b in panel.bars)
    assert panel.note == ""
    summary = panel.missing_summary
    assert summary and summary.endswith("Open Food Facts.")
    for word in ("salt", "saturated fat", "fibre", "energy"):
        assert word in summary.lower()
    # Reads as a sentence: the first nutrient is capitalised.
    assert summary[0].isupper()


def test_all_missing_collapses_to_summary_with_no_bars(make_product):
    panel = build(make_product(nutriments={}))
    assert panel.bars == []
    assert panel.missing_summary != ""
    assert panel.note == ""
