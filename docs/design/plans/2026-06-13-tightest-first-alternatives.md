# Tightest-First Alternatives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make better-alternatives prefer the tightest kind level (cola→colas, aloe vera→aloe-vera-drinks) for *every* category, returning only matches from that level, and broaden one level at a time only when the tighter level has no healthier match — never empty when a healthier option exists at a reasonable level.

**Architecture:** A single change to the `find_better_alternatives` loop in `app/alternatives.py`. Today it searches most-specific-first but (a) accepts a candidate that shares *any* of the current product's specific tags and (b) only stops once a level yields ≥2, otherwise broadening and keeping a running "best". Both let a looser sibling (a soda matched to a cola) slip in. New behaviour: at each level require the candidate to share *that level's* kind tag, and return the first (tightest) level that yields ≥1 healthier same-kind match; broaden through every reasonable (specific, non-generic) level; return empty only if no level had one.

**Tech Stack:** Python, pytest, respx (HTTP mocking). Pure-async function; no new dependencies.

---

## Background: the four rules

1. Search the tightest kind level first. If it yields any better-scoring same-kind matches, show ONLY those.
2. If the tightest level yields zero better matches, broaden one level and try again — still requiring a genuine healthier match.
3. Keep broadening as needed so the section is never empty when a healthier option exists at any reasonable level — but always prefer the tightest available.
4. Candidates must share the kind tag at whatever level is currently being used (no cross-cutting property tags — already excluded from `_ordered_category_tags`/`_specific_tags`).

## File Structure

- Modify: `app/alternatives.py` — `find_better_alternatives` (currently lines ~90-169): the loop body and signature default for `max_levels`; docstring.
- Modify/Add tests: `tests/test_alternatives.py` — rewrite 2 tests that encode the old `≥2`/broaden-on-`<2` behaviour; add 4 new tests for the rules above.

No other files change. `_ordered_category_tags`, `_specific_tags`, `_could_beat`, `_fetch_many`, `_reason`, `_band` are unchanged.

---

## Task 1: Tighten the alternatives selection loop (TDD)

**Files:**
- Modify: `app/alternatives.py:90-169`
- Test: `tests/test_alternatives.py`

### Step 1 — Rewrite the two tests that assert the OLD semantics

- [ ] **1a. Replace `test_broadens_when_specific_category_too_sparse`** (it asserted "broaden when the tightest level has <2"). New rule: one match at the tightest level is shown alone, no broaden.

```python
@respx.mock
async def test_tightest_level_with_one_match_shows_only_it_no_broaden(engine, client):
    """One healthier match at the tightest level is enough — show only it and do NOT
    broaden to a looser level (that's how a sibling soda reached a cola)."""
    searched = []

    def handler(request):
        q = request.url.params.get("q")
        searched.append(q)
        if "chocolate-spreads" in q:
            return httpx.Response(200, json={"hits": [_hit("x1", "a", 1)]})
        return httpx.Response(200, json={"hits": [_hit("x2", "a", 1), _hit("x3", "a", 1)]})

    respx.get(SEARCH_URL).mock(side_effect=handler)
    _mock_product("x1", "a", 1)  # 100, in the tightest level
    _mock_product("x2", "a", 1)
    _mock_product("x3", "a", 1)
    alts = await find_better_alternatives(
        client, engine, _current(["en:spreads", "en:chocolate-spreads"]), current_score=50)
    await client.aclose()
    assert [a.off_id for a in alts] == ["x1"]            # only the tightest-level match
    assert all("chocolate-spreads" in q for q in searched)  # never broadened to en:spreads
```

- [ ] **1b. Replace `test_pepsi_rejects_property_tag_cross_kinds_keeps_real_sodas`** with the tightest-first Pepsi behaviour (a sibling soda no longer rides along when a better cola exists).

```python
@respx.mock
async def test_pepsi_shows_only_colas_when_a_better_cola_exists(engine, client):
    """The Pepsi case: a better cola (Coke Zero) exists at the tightest level (en:colas),
    so ONLY colas are shown. The blood-orange spritz / Fanta (sodas, not colas) and the
    sparkling water / energy drink (property-only) never appear."""
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [
        _hit("cokezero", "a", 1), _hit("fanta", "a", 1), _hit("spritz", "a", 1),
        _hit("water", "a", 1), _hit("energy", "a", 1),
    ]}))
    _mock_product("cokezero", "a", 1,
                  cats=["en:beverages", "en:carbonated-drinks", "en:sodas", "en:colas", "en:diet-sodas"])
    _mock_product("fanta", "a", 1,
                  cats=["en:beverages", "en:carbonated-drinks", "en:sodas", "en:orange-sodas"])
    _mock_product("spritz", "a", 1,
                  cats=["en:beverages", "en:carbonated-drinks", "en:sodas", "en:sweetened-beverages"])
    _mock_product("water", "a", 1,
                  cats=["en:beverages", "en:carbonated-drinks", "en:carbonated-waters", "en:waters"])
    _mock_product("energy", "a", 1,
                  cats=["en:beverages", "en:sweetened-beverages", "en:carbonated-drinks", "en:energy-drinks"])
    pepsi = _current(
        ["en:beverages-and-beverages-preparations", "en:beverages", "en:carbonated-drinks",
         "en:non-alcoholic-beverages", "en:sodas", "en:colas", "en:sweetened-beverages"],
        nutri="E", nova=4)
    alts = await find_better_alternatives(client, engine, pepsi, current_score=40)
    await client.aclose()
    ids = [a.off_id for a in alts]
    assert ids == ["cokezero"]                 # only the cola
    assert route.call_count == 1               # returned at en:colas, never broadened to en:sodas
    for absent in ("spritz", "fanta", "water", "energy"):
        assert absent not in ids
```

### Step 2 — Add the four new behaviour tests

- [ ] **2a. Pepsi falls back to a better soda ONLY when no better cola exists.**

```python
@respx.mock
async def test_pepsi_falls_back_to_better_soda_only_when_no_better_cola(engine, client):
    """If the tightest level (en:colas) has no HEALTHIER cola — only a worse one — broaden
    one level to en:sodas and offer the genuinely healthier sodas instead of nothing."""
    searched = []

    def handler(request):
        q = request.url.params.get("q")
        searched.append(q)
        if "colas" in q:
            return httpx.Response(200, json={"hits": [_hit("cola_e", "e", 4)]})  # a cola, but worse
        if "sodas" in q:
            return httpx.Response(200, json={"hits": [_hit("fanta", "a", 1), _hit("spritz", "a", 1)]})
        return httpx.Response(200, json={"hits": []})

    respx.get(SEARCH_URL).mock(side_effect=handler)
    _mock_product("cola_e", "e", 4, cats=["en:colas", "en:sodas"])      # not healthier -> pruned
    _mock_product("fanta", "a", 1, cats=["en:sodas", "en:orange-sodas"])
    _mock_product("spritz", "a", 1, cats=["en:sodas", "en:sweetened-beverages"])
    pepsi = _current(["en:beverages", "en:carbonated-drinks", "en:sodas", "en:colas"],
                     nutri="E", nova=4)
    alts = await find_better_alternatives(client, engine, pepsi, current_score=40)
    await client.aclose()
    ids = [a.off_id for a in alts]
    assert ids == ["fanta", "spritz"]                       # honest soda fallback (tie -> off_id order)
    assert searched[0] == 'categories_tags:"en:colas"'      # tightest tried first
    assert any("sodas" in q for q in searched)              # broadened only after colas had no healthier cola
```

- [ ] **2b. A narrow category falls back to a close sibling rather than nothing.**

```python
@respx.mock
async def test_narrow_category_falls_back_to_close_sibling(engine, client):
    """A cocoa-hazelnut spread with no healthier option in its exact niche broadens to the
    parent kind (chocolate spreads) and offers a close sibling — not an empty section."""
    searched = []

    def handler(request):
        q = request.url.params.get("q")
        searched.append(q)
        if "cocoa-and-hazelnuts-spreads" in q:
            return httpx.Response(200, json={"hits": []})            # nothing healthier in the niche
        if "chocolate-spreads" in q:
            return httpx.Response(200, json={"hits": [_hit("sibling", "a", 1)]})
        return httpx.Response(200, json={"hits": []})

    respx.get(SEARCH_URL).mock(side_effect=handler)
    _mock_product("sibling", "a", 1, cats=["en:spreads", "en:sweet-spreads", "en:chocolate-spreads"])
    current = _current(
        ["en:spreads", "en:sweet-spreads", "en:chocolate-spreads", "en:cocoa-and-hazelnuts-spreads"],
        nutri="C", nova=2)
    alts = await find_better_alternatives(client, engine, current, current_score=50)
    await client.aclose()
    assert [a.off_id for a in alts] == ["sibling"]                    # a close sibling, not empty
    assert searched[0] == 'categories_tags:"en:cocoa-and-hazelnuts-spreads"'  # tightest first
    assert any("chocolate-spreads" in q for q in searched)           # broadened one level
```

- [ ] **2c. Always show at least one when a healthier option exists somewhere reasonable.**

```python
@respx.mock
async def test_shows_at_least_one_when_a_healthier_option_exists_somewhere(engine, client):
    """The non-empty guarantee: the tightest level is barren but a healthier option exists
    at a broader (still specific, non-generic) level — surface it rather than nothing."""
    def handler(request):
        q = request.url.params.get("q")
        if "chocolate-spreads" in q:
            return httpx.Response(200, json={"hits": []})
        return httpx.Response(200, json={"hits": [_hit("betterspread", "a", 1)]})

    respx.get(SEARCH_URL).mock(side_effect=handler)
    _mock_product("betterspread", "a", 1, cats=["en:spreads"])
    alts = await find_better_alternatives(
        client, engine, _current(["en:spreads", "en:chocolate-spreads"]), current_score=50)
    await client.aclose()
    assert len(alts) >= 1
    assert alts[0].off_id == "betterspread"
```

- [ ] **2d. Keep the existing "honest empty" guarantees** — these still pass unchanged and must be re-run as regression:
  `test_niche_category_with_no_same_kind_options_returns_empty`,
  `test_only_property_grouping_tags_returns_empty_without_searching`,
  `test_only_generic_categories_returns_empty_without_searching`,
  `test_rate_limited_specific_search_stops_instead_of_broadening`.

### Step 3 — Run the new/changed tests to confirm they FAIL against current code

- [ ] Run: `python -m pytest tests/test_alternatives.py -q`
  Expected: the rewritten + new tests FAIL (current code returns `["cokezero","fanta"]` for Pepsi, broadens on `<2`, and accepts any shared specific tag).

### Step 4 — Implement the loop change

- [ ] Replace the `find_better_alternatives` docstring + loop (`app/alternatives.py:100-169`) with:

```python
    """Same-category products that are genuinely better than ``product``.

    ``current_score`` is the current product's *uncapped* weighted score. Candidates are
    ranked and compared on their uncapped score too, so the cap doesn't flatten the
    comparison — but the score *displayed* on each card stays the capped one. Candidates
    missing NOVA or Nutri-Score data are skipped.

    Tightest-first, like Yuka: the most-specific kind level is searched first and a
    candidate counts only if it shares *that level's* kind tag. The first (tightest) level
    that yields one or more healthier same-kind matches wins and is returned alone — looser
    levels never dilute it. If a level has none, broaden one level and try again, through
    every reasonable (specific, non-generic) level, so the section is empty only when no
    healthier option exists at any of them.
    """
    tags = _ordered_category_tags(product.categories)
    if not tags:
        return []

    # No specific kind tag at all -> we can't establish kinship. Honest empty.
    if not _specific_tags(product.categories):
        return []

    current_dims = engine.score(product).dimensions

    levels = tags if max_levels is None else tags[:max_levels]
    for tag in levels:
        try:
            candidates = await off_client.search_category(tag, page_size=candidate_pool)
        except OFFError:
            # A rate-limited/failed search is NOT an empty level. Stop rather than
            # broadening into a looser tag and recommending unrelated products.
            break

        seen: set[str] = {product.off_id}
        unique = [c for c in candidates if not (c.code in seen or seen.add(c.code))]

        # Pre-filter on the Nutri-Score + NOVA the search already gave us: only fetch
        # candidates that *could* beat the current score even with a perfect additive
        # profile (an upper bound, so this never prunes a genuine improvement).
        to_fetch = [c.code for c in unique if _could_beat(engine, c, current_score)]

        ranked: list[tuple[int, Alternative]] = []
        for p in await _fetch_many(off_client, to_fetch):
            if p.nova_group is None or p.nutriscore_grade is None:
                continue  # don't recommend products with missing data
            if tag not in _specific_tags(p.categories):
                continue  # must be the same KIND at this level (rule 4)
            result = engine.score(p)
            rank = uncapped_overall(result)
            if rank > current_score:
                display = weighted_overall(result)
                reason = _reason(product, current_dims, p, result.dimensions)
                ranked.append((rank, Alternative(p.off_id, p.name, p.brand, p.image_url, display, _band(display), reason)))

        if ranked:
            # Tightest non-empty level wins; show only its matches, best first.
            ranked.sort(key=lambda t: (-t[0], t[1].off_id))
            return [a for _, a in ranked][:max_results]
        # Nothing healthier here -> broaden to the next (looser) reasonable level.

    return []
```

- [ ] Change the signature default so broadening covers every reasonable level (`app/alternatives.py:98`):

```python
    max_levels: int | None = None,
```

### Step 5 — Run the full alternatives suite

- [ ] Run: `python -m pytest tests/test_alternatives.py -q`
  Expected: PASS (all, including the unchanged honest-empty regressions).

### Step 6 — Run the whole suite

- [ ] Run: `python -m pytest tests/ -q`
  Expected: PASS.

### Step 7 — Live sanity check (optional, read-only)

- [ ] Fetch Pepsi `87156836`, run `find_better_alternatives`; confirm only colas appear and no spritz/soda when a better cola exists.

### Step 8 — Commit

- [ ] `git add app/alternatives.py tests/test_alternatives.py docs/design/plans/2026-06-13-tightest-first-alternatives.md`
- [ ] Commit (attribution-free) describing tightest-first selection.

---

## Self-Review

- **Rule 1** (tightest level wins, show only those) → loop returns on first non-empty `ranked`; tests 1b, 2c.
- **Rule 2** (broaden when tightest has zero) → `for` continues when `ranked` empty; tests 2a, 2b.
- **Rule 3** (never empty when a healthier option exists at a reasonable level; all levels iterated) → `levels = tags` when `max_levels is None`; tests 2b, 2c.
- **Rule 4** (share the current level's kind tag) → `if tag not in _specific_tags(p.categories): continue`; tests 1b, 2a.
- **Honest empty preserved** → `return []` when no level qualifies; OFFError breaks instead of broadening; test 2d set.
- **Placeholder scan:** none. (test 1a asserts only on `searched` for the no-broaden check.)
