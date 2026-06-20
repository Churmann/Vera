# Photo-based add-product flow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the manual text-entry add-product form with a guided three-photo capture flow that uploads front/ingredients/nutrition images to Open Food Facts, landing the user on a real product page with an honest, time-bounded pending state.

**Architecture:** Reuse the existing OFF SDK wrapper, auth, environment flag, and trust-store setup. A new `OFFWriter.add_product_photos` uploads each photo via `product.upload_image(..., selected=...)`. `POST /add` validates uploads server-side and redirects to `/product/{barcode}?submitted=1`. The product page resolves pending vs final statelessly from OFF's `created_t`.

**Tech Stack:** FastAPI, Jinja2, `python-multipart` (already installed), `openfoodfacts==5.2.0` SDK, pytest + respx. No new dependencies.

## Global Constraints

- **No new dependencies.** Type detection is by magic bytes only (no Pillow). `python-multipart` is already present.
- **Defaults (configurable via env):** max image size **12 MB** (`off_max_image_bytes`), pending window **900 s / 15 min** (`off_pending_window_seconds`), image language **`en`** (`off_image_lang`).
- **OFF SDK upload signature (verified, v5.2.0):** `api.product.upload_image(code, image_path=None, image_data_base64=None, selected=None)`; `selected={field: {lang: {}}}`; valid fields `front|ingredients|nutrition|packaging`; requires username+password; forces API v3; `code` must be digits; synchronous (run in threadpool).
- **Image type is decided by magic bytes only** — never filename, extension, or client `Content-Type`.
- **Commits:** plain Conventional-Commits messages, **no AI attribution trailer**, no push (the maintainer pushes).
- **All commits must leave the full test suite green** (`pytest -q`).

## Refinement vs spec (flagged)

The spec's Files-changed table lists `templates/product.html` ("guard score blocks"). This plan instead realises the pending/partial UI as a **new `templates/product_pending.html`** and leaves `product.html` **unchanged**. Same behaviour (score suppressed, partial content + banner, "Check again"), but cleaner decomposition and zero regression risk to the complex complete-product render path. Note: because `_is_awaiting_extraction` requires *no nutriments*, the partial view is image + name + brand only — there are no nutrient bars to show in that state by definition.

## File structure

| File | Responsibility |
|---|---|
| `app/config.py` | Add the three configurable settings. |
| `app/image_validation.py` (new) | Pure functions: magic-byte sniff + friendly validation. |
| `app/models.py` | Add `created_t` to `NormalisedProduct`. |
| `app/off_client.py` | Fetch + parse `created_t`. |
| `app/off_writer.py` | Replace text submission with `add_product_photos`. |
| `app/main.py` | Rewrite `POST /add`; pending-aware `GET /product`; `_is_awaiting_extraction`. |
| `templates/add.html` | Guided photo capture (replaces text form). |
| `templates/product_pending.html` (new) | Pending / final-incomplete view. |
| `static/css/style.css` | Capture UI + pending styles. |
| `tests/test_config.py` | Defaults test. |
| `tests/test_image_validation.py` (new) | Sniff/validation unit tests incl. renamed non-image. |
| `tests/test_off_client.py` | `created_t` parse test. |
| `tests/test_off_writer.py` | Replace text-update tests with upload tests. |
| `tests/test_routes.py` | Replace text-add tests with photo-flow + pending tests. |

---

### Task 1: Config settings

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.off_max_image_bytes: int`, `Settings.off_pending_window_seconds: int`, `Settings.off_image_lang: str`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_image_and_pending_defaults():
    from app.config import Settings
    s = Settings(_env_file=None)
    assert s.off_max_image_bytes == 12 * 1024 * 1024
    assert s.off_pending_window_seconds == 900
    assert s.off_image_lang == "en"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_image_and_pending_defaults -v`
Expected: FAIL (`AttributeError` / unknown attribute).

- [ ] **Step 3: Add the settings**

In `app/config.py`, after the `off_password` field:

```python
    # Photo-upload + pending-state tuning (all overridable via env).
    off_max_image_bytes: int = 12 * 1024 * 1024   # 12 MB per photo
    off_pending_window_seconds: int = 900          # 15 min: pending -> final cutoff
    off_image_lang: str = "en"                     # language code for selected images
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: add image-upload and pending-window settings"
```

---

### Task 2: Image validation module

**Files:**
- Create: `app/image_validation.py`
- Test: `tests/test_image_validation.py`

**Interfaces:**
- Produces:
  - `sniff_image_type(data: bytes) -> str | None` — returns `"jpeg" | "png" | "webp"` or `None`.
  - `validate_image(data: bytes, *, max_bytes: int) -> str | None` — returns a friendly error string, or `None` if acceptable.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_image_validation.py`:

```python
from app.image_validation import sniff_image_type, validate_image

_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 8
_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
_WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 8
_PDF = b"%PDF-1.4\n%%EOF\n"

def test_sniff_recognises_each_type():
    assert sniff_image_type(_JPEG) == "jpeg"
    assert sniff_image_type(_PNG) == "png"
    assert sniff_image_type(_WEBP) == "webp"

def test_sniff_rejects_non_image():
    assert sniff_image_type(_PDF) is None
    assert sniff_image_type(b"") is None

def test_validate_accepts_good_image():
    assert validate_image(_PNG, max_bytes=1024) is None

def test_validate_rejects_empty():
    assert "empty" in validate_image(b"", max_bytes=1024).lower()

def test_validate_rejects_oversize():
    msg = validate_image(_PNG, max_bytes=4)
    assert "too large" in msg.lower()

def test_validate_rejects_renamed_pdf():
    # A PDF whose bytes are unmistakably not an image. Filename/Content-Type are
    # irrelevant here — validation only sees the bytes.
    msg = validate_image(_PDF, max_bytes=1024)
    assert "JPG, PNG, or WEBP" in msg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_image_validation.py -v`
Expected: FAIL (`ModuleNotFoundError: app.image_validation`).

- [ ] **Step 3: Implement the module**

Create `app/image_validation.py`:

```python
"""Server-side validation for uploaded product photos.

The image type is determined from the leading magic bytes only — never the
filename, extension, or the client-declared Content-Type. A non-image renamed to
.jpg (or sent with a spoofed image/* content type) therefore fails."""

_JPEG = b"\xff\xd8\xff"
_PNG = b"\x89PNG\r\n\x1a\n"


def sniff_image_type(data: bytes) -> str | None:
    """Return 'jpeg' | 'png' | 'webp' from the leading magic bytes, else None."""
    if data.startswith(_JPEG):
        return "jpeg"
    if data.startswith(_PNG):
        return "png"
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def validate_image(data: bytes, *, max_bytes: int) -> str | None:
    """Return a friendly error string, or None if the image is acceptable."""
    if not data:
        return "That file is empty — please choose a photo."
    if len(data) > max_bytes:
        return f"That image is too large (max {max_bytes // (1024 * 1024)} MB). Try again."
    if sniff_image_type(data) is None:
        return "That file must be a JPG, PNG, or WEBP image."
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_image_validation.py -v`
Expected: PASS (all 6).

- [ ] **Step 5: Commit**

```bash
git add app/image_validation.py tests/test_image_validation.py
git commit -m "feat: add magic-byte image validation for uploads"
```

---

### Task 3: `created_t` plumbing

**Files:**
- Modify: `app/models.py`, `app/off_client.py`
- Test: `tests/test_off_client.py`

**Interfaces:**
- Produces: `NormalisedProduct.created_t: int | None` (defaults `None`), populated by `OFFClient.fetch_product`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_off_client.py` (it already uses `httpx` + `respx`; match its async style):

```python
@respx.mock
async def test_fetch_product_parses_created_t():
    respx.get("https://world.openfoodfacts.org/api/v2/product/123.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "X", "created_t": 1700000000,
        }})
    )
    from app.config import Settings
    from app.off_client import OFFClient
    client = OFFClient(Settings(_env_file=None))
    try:
        product = await client.fetch_product("123")
    finally:
        await client.aclose()
    assert product.created_t == 1700000000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_off_client.py::test_fetch_product_parses_created_t -v`
Expected: FAIL (`created_t` is `None` / attribute missing).

- [ ] **Step 3: Add the model field**

In `app/models.py`, in `NormalisedProduct`, after `is_beverage: bool = False`:

```python
    # OFF created_t (unix seconds) — when the product was first added. Used to
    # time-bound the post-submission "still reading the label" pending state.
    created_t: int | None = None
```

- [ ] **Step 4: Fetch and parse it**

In `app/off_client.py`, add `created_t` to `_PRODUCT_FIELDS`:

```python
_PRODUCT_FIELDS = "code,product_name,brands,image_url,nutriscore_grade,nova_group,additives_tags,ingredients_text,categories_tags,countries_tags,nutriments,created_t"
```

In `_normalise`, just before the `return NormalisedProduct(...)`, add:

```python
    raw_created = p.get("created_t")
    created_t = int(raw_created) if isinstance(raw_created, (int, float)) else None
```

and add to the constructor call:

```python
        created_t=created_t,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_off_client.py -v`
Expected: PASS (new test + existing ones).

- [ ] **Step 6: Commit**

```bash
git add app/models.py app/off_client.py tests/test_off_client.py
git commit -m "feat: parse OFF created_t for pending-state timing"
```

---

### Task 4: `OFFWriter.add_product_photos` (additive)

Adds the new upload method alongside the existing text `add_product` (removed later in Task 6) so the suite stays green.

**Files:**
- Modify: `app/off_writer.py`
- Test: `tests/test_off_writer.py`

**Interfaces:**
- Produces: `async OFFWriter.add_product_photos(*, barcode: str, images: dict[str, bytes]) -> None`. `images` keys are `"front" | "ingredients" | "nutrition"`. Raises `OFFError(kind="no_credentials")` or `OFFError(kind="write_failed")`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_off_writer.py`:

```python
import base64

class _RecordingProductResource:
    def __init__(self):
        self.calls = []
    def upload_image(self, code, image_data_base64=None, selected=None):
        self.calls.append({"code": code, "b64": image_data_base64, "selected": selected})
        class _R:
            ok = True
            status_code = 200
        return _R()

class _RecordingAPI:
    def __init__(self):
        self.product = _RecordingProductResource()

def _images():
    return {"front": b"\xff\xd8\xfffront", "ingredients": b"\xff\xd8\xffing", "nutrition": b"\xff\xd8\xffnut"}

async def test_add_product_photos_uploads_three_selected_fields():
    api = _RecordingAPI()
    writer = OFFWriter(_settings(off_image_lang="en"), api_factory=lambda: api)
    await writer.add_product_photos(barcode="3017620422003", images=_images())
    selected = [c["selected"] for c in api.product.calls]
    assert {"front": {"en": {}}} in selected
    assert {"ingredients": {"en": {}}} in selected
    assert {"nutrition": {"en": {}}} in selected
    front_call = next(c for c in api.product.calls if c["selected"] == {"front": {"en": {}}})
    assert front_call["code"] == "3017620422003"
    assert front_call["b64"] == base64.b64encode(b"\xff\xd8\xfffront").decode("utf-8")

async def test_add_product_photos_without_credentials_raises():
    writer = OFFWriter(_settings(off_username=None, off_password=None), api_factory=lambda: None)
    with pytest.raises(OFFError) as exc:
        await writer.add_product_photos(barcode="12345678", images=_images())
    assert exc.value.kind == "no_credentials"

async def test_add_product_photos_request_error_is_write_failed():
    class _BoomResource:
        def upload_image(self, **kw):
            raise requests.ConnectionError("down")
    class _BoomAPI:
        product = _BoomResource()
    writer = OFFWriter(_settings(), api_factory=lambda: _BoomAPI())
    with pytest.raises(OFFError) as exc:
        await writer.add_product_photos(barcode="12345678", images=_images())
    assert exc.value.kind == "write_failed"

async def test_add_product_photos_non_ok_response_is_write_failed():
    class _NotOkResource:
        def upload_image(self, **kw):
            class _R:
                ok = False
                status_code = 400
            return _R()
    class _NotOkAPI:
        product = _NotOkResource()
    writer = OFFWriter(_settings(), api_factory=lambda: _NotOkAPI())
    with pytest.raises(OFFError) as exc:
        await writer.add_product_photos(barcode="12345678", images=_images())
    assert exc.value.kind == "write_failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_off_writer.py -k add_product_photos -v`
Expected: FAIL (`AttributeError: add_product_photos`).

- [ ] **Step 3: Implement the method**

In `app/off_writer.py`, add `import base64` at the top, and add to the `OFFWriter` class:

```python
    _IMAGE_FIELDS = ("front", "ingredients", "nutrition")

    async def add_product_photos(self, *, barcode, images):
        """Upload front/ingredients/nutrition photos for ``barcode``.

        ``images`` maps field name -> raw bytes. Each is base64-encoded and
        uploaded via ``product.upload_image(..., selected={field: {lang: {}}})``
        in a threadpool (the SDK is synchronous). Uploading an image to a barcode
        creates the product in OFF, so no separate text write is needed."""
        if not self._settings.off_username or not self._settings.off_password:
            raise OFFError("Open Food Facts credentials are not configured", "no_credentials")
        try:
            await asyncio.to_thread(self._upload_all, barcode, images)
        except requests.RequestException as e:
            raise OFFError(f"Failed to upload product photos to Open Food Facts: {e}", "write_failed")

    def _upload_all(self, barcode, images):
        api = self._api_factory()
        lang = self._settings.off_image_lang
        for field in self._IMAGE_FIELDS:
            b64 = base64.b64encode(images[field]).decode("utf-8")
            resp = api.product.upload_image(
                code=barcode,
                image_data_base64=b64,
                selected={field: {lang: {}}},
            )
            if not getattr(resp, "ok", True):
                raise OFFError(
                    f"Open Food Facts rejected the image upload "
                    f"({getattr(resp, 'status_code', '?')})",
                    "write_failed",
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_off_writer.py -v`
Expected: PASS (new upload tests + existing text tests both green).

- [ ] **Step 5: Commit**

```bash
git add app/off_writer.py tests/test_off_writer.py
git commit -m "feat: add OFFWriter.add_product_photos image upload"
```

---

### Task 5: Switch the add flow to photos

Rewrites the route + template + styles and replaces the add-route tests in one coherent, green commit.

**Files:**
- Modify: `app/main.py` (`POST /add`), `templates/add.html`, `static/css/style.css`, `tests/test_routes.py`

**Interfaces:**
- Consumes: `validate_image` (Task 2), `OFFWriter.add_product_photos` (Task 4), `Settings.off_max_image_bytes` (Task 1), existing `_clean_barcode`, `_refetch_after_write`.
- Produces: `POST /add` accepting multipart `barcode` + `front_photo`/`ingredients_photo`/`nutrition_photo`, redirecting `303 -> /product/{barcode}?submitted=1`.

- [ ] **Step 1: Replace the add-route tests**

In `tests/test_routes.py`: delete `test_add_page_renders_form`, `test_add_submit_rejects_invalid_barcode_and_keeps_values`, `test_add_submit_requires_name`, `test_add_submit_trims_whitespace_from_barcode_before_validating`, `test_add_submit_missing_credentials_shows_friendly_message`, `test_add_submit_write_failure_shows_friendly_message`, `test_add_submit_success_redirects_to_product`, `test_add_submit_not_yet_queryable_shows_refresh_notice`, and the old text `_StubWriter` class. Keep `test_add_page_prefills_barcode_from_query`, `test_empty_search_results_offer_add_product`, `test_product_not_found_shows_add_form_prefilled`. Add:

```python
def _img(prefix=b"\xff\xd8\xff"):
    return ("p.jpg", prefix + b"imagedata", "image/jpeg")

def _photo_files():
    return {"front_photo": _img(), "ingredients_photo": _img(), "nutrition_photo": _img()}

class _StubPhotoWriter:
    def __init__(self, raise_kind=None):
        self.calls = []
        self._raise_kind = raise_kind
    async def add_product_photos(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise_kind:
            from app.models import OFFError
            raise OFFError("boom", self._raise_kind)

def test_add_page_renders_photo_capture():
    with TestClient(app) as client:
        body = client.get("/add").text
    assert 'enctype="multipart/form-data"' in body
    assert 'name="barcode"' in body
    assert 'name="front_photo"' in body
    assert 'name="ingredients_photo"' in body
    assert 'name="nutrition_photo"' in body
    assert 'type="file"' in body
    # The text fields are gone.
    assert 'name="name"' not in body
    assert 'name="brand"' not in body
    assert 'name="category"' not in body

@respx.mock
def test_add_submit_uploads_photos_and_redirects_with_submitted_flag():
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(404, json={"status": 0})
    )
    with TestClient(app) as client:
        app.state.off_writer = _StubPhotoWriter()
        app.state.settings.off_retry_backoff = 0.0
        response = client.post(
            "/add", data={"barcode": "3017620422003"},
            files=_photo_files(), follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"] == "/product/3017620422003?submitted=1"
    call = app.state.off_writer.calls[0]
    assert call["barcode"] == "3017620422003"
    assert set(call["images"]) == {"front", "ingredients", "nutrition"}

def test_add_submit_missing_nutrition_photo_blocks_with_message():
    with TestClient(app) as client:
        app.state.off_writer = _StubPhotoWriter()
        files = {"front_photo": _img(), "ingredients_photo": _img()}
        response = client.post("/add", data={"barcode": "3017620422003"}, files=files)
    assert response.status_code == 400
    assert "Nutrition photo needed" in response.text
    assert app.state.off_writer.calls == []

def test_add_submit_rejects_renamed_non_image():
    with TestClient(app) as client:
        app.state.off_writer = _StubPhotoWriter()
        files = {
            "front_photo": ("evil.jpg", b"%PDF-1.4 not an image", "image/jpeg"),
            "ingredients_photo": _img(),
            "nutrition_photo": _img(),
        }
        response = client.post("/add", data={"barcode": "3017620422003"}, files=files)
    assert response.status_code == 400
    assert "JPG, PNG, or WEBP" in response.text
    assert app.state.off_writer.calls == []

def test_add_submit_rejects_invalid_barcode():
    with TestClient(app) as client:
        app.state.off_writer = _StubPhotoWriter()
        response = client.post("/add", data={"barcode": "12"}, files=_photo_files())
    assert response.status_code == 400
    assert "8" in response.text and "14" in response.text
    assert app.state.off_writer.calls == []

def test_add_submit_missing_credentials_message():
    with TestClient(app) as client:
        app.state.off_writer = _StubPhotoWriter(raise_kind="no_credentials")
        response = client.post("/add", data={"barcode": "3017620422003"}, files=_photo_files())
    assert response.status_code == 503
    assert "configured" in response.text.lower()

def test_add_submit_write_failure_message():
    with TestClient(app) as client:
        app.state.off_writer = _StubPhotoWriter(raise_kind="write_failed")
        response = client.post("/add", data={"barcode": "3017620422003"}, files=_photo_files())
    assert response.status_code == 502
    assert "couldn't save" in response.text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routes.py -k add -v`
Expected: FAIL (route still text-based: no file handling, wrong redirect, missing template fields).

- [ ] **Step 3: Rewrite the template**

Replace the entire contents of `templates/add.html`:

```html
{% extends "base.html" %}
{% block title %}Add this product — Vera{% endblock %}
{% block content %}
<section class="search-hero add-product">
  <a href="/" class="back-link">← Back to search</a>
  <h1>Add this product</h1>
  <p class="tagline">It isn't in Open Food Facts yet. Photograph the pack and we'll read it and score it — and it stays in the open database for everyone.</p>

  <div class="photo-requirements">
    <p class="photo-requirements-title">You'll need three clear photos:</p>
    <ul>
      <li><strong>Front of pack</strong> — the product name and brand</li>
      <li><strong>Ingredients list</strong> — the full list, in focus</li>
      <li><strong>Nutrition table</strong> — the per-100g values</li>
    </ul>
    <p class="photo-requirements-note">All three are required so we can score it accurately.</p>
  </div>

  {% if notice %}<p class="form-notice">{{ notice }}</p>{% endif %}
  {% if error %}<p class="form-error">{{ error }}</p>{% endif %}

  <form action="/add" method="post" enctype="multipart/form-data" class="add-form">
    <label class="add-field">Barcode
      <input name="barcode" inputmode="numeric" autocomplete="off"
             placeholder="e.g. 3017620422003" value="{{ barcode or '' }}" required>
    </label>

    <label class="add-field photo-field">Front of pack
      <span class="photo-guidance">Fill the frame; make the name and brand readable.</span>
      <input type="file" name="front_photo" accept="image/jpeg,image/png,image/webp" capture="environment" required>
    </label>

    <label class="add-field photo-field">Ingredients list
      <span class="photo-guidance">Get the whole list in focus, avoid glare.</span>
      <input type="file" name="ingredients_photo" accept="image/jpeg,image/png,image/webp" capture="environment" required>
    </label>

    <label class="add-field photo-field">Nutrition table
      <span class="photo-guidance">Capture all the per-100g values clearly.</span>
      <input type="file" name="nutrition_photo" accept="image/jpeg,image/png,image/webp" capture="environment" required>
    </label>

    <button type="submit">Upload &amp; score</button>
  </form>
</section>
{% endblock %}
```

- [ ] **Step 4: Rewrite the route**

In `app/main.py`, update the FastAPI import to add `File, UploadFile`:

```python
from fastapi import FastAPI, File, Form, Request, UploadFile
```

Add the validation import near the other app imports:

```python
from app.image_validation import validate_image
```

Add module-level constants near the top (after `BASE_DIR`):

```python
_PHOTO_LABELS = {"front": "Front-of-pack", "ingredients": "Ingredients", "nutrition": "Nutrition"}
```

Replace the entire `add_product_submit` function (the `@app.post("/add")` handler) with:

```python
    @app.post("/add", response_class=HTMLResponse)
    async def add_product_submit(
        request: Request,
        barcode: str = Form(""),
        front_photo: UploadFile | None = File(None),
        ingredients_photo: UploadFile | None = File(None),
        nutrition_photo: UploadFile | None = File(None),
    ):
        settings = request.app.state.settings
        ctx = {"barcode": barcode.strip()}
        clean = _clean_barcode(barcode)
        if clean is None:
            return templates.TemplateResponse(
                request, "add.html",
                {**ctx, "error": "Enter a valid barcode — 8 to 14 digits."},
                status_code=400,
            )

        uploads = {"front": front_photo, "ingredients": ingredients_photo, "nutrition": nutrition_photo}
        images: dict[str, bytes] = {}
        for field, upload in uploads.items():
            if upload is None or not upload.filename:
                return templates.TemplateResponse(
                    request, "add.html",
                    {**ctx, "error": f"{_PHOTO_LABELS[field]} photo needed."},
                    status_code=400,
                )
            data = await upload.read()
            err = validate_image(data, max_bytes=settings.off_max_image_bytes)
            if err:
                return templates.TemplateResponse(
                    request, "add.html",
                    {**ctx, "error": f"{_PHOTO_LABELS[field]} photo: {err}"},
                    status_code=400,
                )
            images[field] = data

        try:
            await request.app.state.off_writer.add_product_photos(barcode=clean, images=images)
        except OFFError as e:
            if e.kind == "no_credentials":
                message = Markup("Submitting products isn't configured on this server yet.")
                status = 503
            else:
                message = Markup("Couldn't save to Open Food Facts — please try again.")
                status = 502
            return templates.TemplateResponse(
                request, "add.html", {**ctx, "error": message}, status_code=status,
            )

        # One immediate bounded attempt; the product page owns the pending UI.
        await _refetch_after_write(
            request.app.state.off_client, clean, base_backoff=settings.off_retry_backoff,
        )
        return RedirectResponse(url=f"/product/{clean}?submitted=1", status_code=303)
```

- [ ] **Step 5: Add the capture styles**

Append to `static/css/style.css`:

```css
/* Photo-capture add form */
.photo-requirements { max-width: 28rem; margin: 1.25rem auto 0; text-align: left; background: var(--color-unknown-bg); border: 1px solid var(--color-border); border-radius: var(--radius); padding: 0.85rem 1rem; }
.photo-requirements-title { font-weight: 600; margin: 0 0 0.4rem; }
.photo-requirements ul { margin: 0; padding-left: 1.1rem; display: flex; flex-direction: column; gap: 0.25rem; }
.photo-requirements-note { color: var(--color-text-muted); font-size: .85rem; margin: 0.5rem 0 0; }
.photo-field { gap: 0.35rem; }
.photo-guidance { font-weight: 400; font-size: .82rem; color: var(--color-text-muted); }
.photo-field input[type="file"] { font: inherit; font-weight: 400; }
.add-form button { margin-top: 0.5rem; padding: 0.7rem 1rem; background: var(--color-accent); color: #fff; border: none; border-radius: 8px; font: inherit; font-weight: 600; cursor: pointer; }
.add-form button:hover { opacity: .88; }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_routes.py -v`
Expected: PASS (new add tests + all unchanged route tests).

- [ ] **Step 7: Commit**

```bash
git add app/main.py templates/add.html static/css/style.css tests/test_routes.py
git commit -m "feat: replace text add-product form with guided photo capture"
```

---

### Task 6: Remove the dead text-submission path

**Files:**
- Modify: `app/off_writer.py`, `tests/test_off_writer.py`

**Interfaces:**
- Removes: `OFFWriter.add_product`, `OFFWriter._write`. (No caller remains after Task 5.)

- [ ] **Step 1: Confirm there are no remaining callers**

Run: `grep -rn "add_product\b\|\._write\b" app/ tests/`
Expected: only `add_product_photos` references remain (no bare `add_product(`/`_write` in `app/`). If `app/main.py` still references `add_product`, stop — Task 5 is incomplete.

- [ ] **Step 2: Delete the dead methods**

In `app/off_writer.py`, remove the `add_product` method and the `_write` method (the text `product.update` path). Leave `add_product_photos` and `_upload_all`.

- [ ] **Step 3: Delete the obsolete tests**

In `tests/test_off_writer.py`, delete the four text-update tests: `test_add_product_builds_minimal_body_and_omits_empty_optionals`, `test_add_product_includes_all_fields_when_present`, `test_add_product_without_credentials_raises_no_credentials`, `test_add_product_maps_write_failure_to_offerror`, and the `_FakeProductResource`/`_FakeAPI` helpers they used. Keep the `add_product_photos` tests and the shared `_settings` helper.

- [ ] **Step 4: Run the suite to verify nothing broke**

Run: `pytest tests/test_off_writer.py -v && pytest -q`
Expected: PASS; no import errors; no reference to removed methods.

- [ ] **Step 5: Commit**

```bash
git add app/off_writer.py tests/test_off_writer.py
git commit -m "refactor: remove dead text add-product write path"
```

---

### Task 7: Product-page pending state

**Files:**
- Modify: `app/main.py` (`GET /product/{off_id}`, add `_is_awaiting_extraction`), `static/css/style.css`
- Create: `templates/product_pending.html`
- Test: `tests/test_routes.py`

**Interfaces:**
- Consumes: `NormalisedProduct.created_t` (Task 3), `Settings.off_pending_window_seconds` (Task 1).
- Produces: `_is_awaiting_extraction(product) -> bool`; `GET /product/{off_id}` accepts `submitted: bool = False`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_routes.py` (add `import time` at the top if absent):

```python
@respx.mock
def test_product_pending_when_incomplete_and_fresh():
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "New Snack", "created_t": int(time.time()),
        }})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    assert response.status_code == 200
    assert "still reading the label" in response.text.lower()
    assert "Check again" in response.text

@respx.mock
def test_product_final_when_incomplete_and_stale():
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(200, json={"product": {
            "product_name": "Old Snack", "created_t": int(time.time()) - 86400,
        }})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003")
    assert response.status_code == 200
    assert "couldn't read enough" in response.text.lower()
    assert "Check again" not in response.text

@respx.mock
def test_product_pending_shell_when_submitted_but_not_found():
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json").mock(
        return_value=httpx.Response(404, json={"status": 0})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422003?submitted=1")
    assert response.status_code == 200
    assert "photos received" in response.text.lower()
    assert "Check again" in response.text

@respx.mock
def test_product_not_found_not_submitted_shows_capture_page():
    respx.get("https://world.openfoodfacts.org/api/v2/product/3017620422000.json").mock(
        return_value=httpx.Response(404, json={"status": 0})
    )
    with TestClient(app) as client:
        response = client.get("/product/3017620422000")
    assert 'name="front_photo"' in response.text
    assert 'value="3017620422000"' in response.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_routes.py -k "pending or final or capture_page" -v`
Expected: FAIL (no pending template / param; incomplete product currently goes through scoring).

- [ ] **Step 3: Add the helper**

In `app/main.py`, after `_refetch_after_write`:

```python
def _is_awaiting_extraction(product) -> bool:
    """True when Robotoff hasn't extracted enough to produce a meaningful score:
    no Nutri-Score AND no nutriments. (When True, nutriments is empty by
    definition, so the partial view shows image + name only.)"""
    return product.nutriscore_grade is None and not product.nutriments
```

- [ ] **Step 4: Make the route pending-aware**

In `app/main.py`, replace the `product_score` handler with:

```python
    @app.get("/product/{off_id}", response_class=HTMLResponse)
    async def product_score(request: Request, off_id: str, submitted: bool = False):
        settings = request.app.state.settings
        try:
            product = await request.app.state.off_client.fetch_product(off_id)
        except OFFError as e:
            if e.kind == "not_found":
                if submitted:
                    # Photos just uploaded; OFF may not have materialised the
                    # product record yet. Show a pending shell, not the capture
                    # page (which would loop the user back to re-uploading).
                    return templates.TemplateResponse(request, "product_pending.html", {
                        "barcode": off_id, "product": None, "state": "pending", "submitted": True,
                        "off_url": f"https://{settings.off_product_host}/product/{off_id}/",
                    })
                return templates.TemplateResponse(request, "add.html", {
                    "barcode": off_id,
                    "notice": "We don't have this product yet — add its photos below "
                              "and we'll score it once they're read.",
                })
            return templates.TemplateResponse(
                request, "error.html",
                {"message": "Couldn't reach Open Food Facts — please try again."},
            )

        if _is_awaiting_extraction(product):
            fresh = (
                product.created_t is not None
                and (time.time() - product.created_t) < settings.off_pending_window_seconds
            )
            return templates.TemplateResponse(request, "product_pending.html", {
                "barcode": off_id, "product": product,
                "state": "pending" if fresh else "final", "submitted": submitted,
                "off_url": product.raw_off_url,
            })

        result = request.app.state.scoring_engine.score(product)
        overall_score = weighted_overall(result)

        try:
            alternatives = await find_better_alternatives(
                request.app.state.off_client,
                request.app.state.scoring_engine,
                product,
                uncapped_overall(result),
            )
        except OFFError:
            alternatives = []

        return templates.TemplateResponse(request, "product.html", {
            "product": product,
            "result": result,
            "overall_score": overall_score,
            "alternatives": alternatives,
            "factors": group_factors(result),
        })
```

- [ ] **Step 5: Create the pending template**

Create `templates/product_pending.html`:

```html
{% extends "base.html" %}
{% block title %}{% if product %}{{ product.name }}{% else %}Reading your photos{% endif %} — Vera{% endblock %}
{% block content %}
<section class="product-pending">
  <a href="/" class="back-link">← Back to search</a>
  {% if product and product.image_url %}
  <img src="{{ product.image_url }}" alt="{{ product.name }}" class="product-hero-img">
  {% endif %}
  <h1>{% if product %}{{ product.name }}{% else %}Thanks — photos received{% endif %}</h1>
  {% if product and product.brand %}<p class="brand">{{ product.brand }}</p>{% endif %}

  {% if state == "pending" %}
  <div class="pending-banner">
    <p><strong>We're still reading the label.</strong> Your photos are with Open Food Facts and the score will fill in shortly — this can take a few minutes.</p>
  </div>
  <div class="pending-actions">
    <a class="check-again" href="/product/{{ barcode }}?submitted=1">Check again</a>
    <a class="off-link" href="{{ off_url }}" target="_blank" rel="noopener">View on Open Food Facts ↗</a>
  </div>
  {% else %}
  <div class="pending-banner pending-banner--final">
    <p><strong>We couldn't read enough from the photos to score this yet.</strong> The product is now in Open Food Facts and its details may be completed over time.</p>
  </div>
  <div class="pending-actions">
    <a class="off-link" href="{{ off_url }}" target="_blank" rel="noopener">View on Open Food Facts ↗</a>
  </div>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 6: Add the pending styles**

Append to `static/css/style.css`:

```css
/* Pending / partial product state */
.product-pending { max-width: 32rem; margin: 0 auto; text-align: center; }
.pending-banner { background: var(--color-moderate-bg); border: 1px solid var(--color-moderate); color: var(--color-text); border-radius: var(--radius); padding: 0.85rem 1rem; margin: 1rem 0; text-align: left; }
.pending-banner--final { background: var(--color-unknown-bg); border-color: var(--color-border); }
.pending-actions { display: flex; gap: 0.75rem; justify-content: center; flex-wrap: wrap; }
.check-again { display: inline-block; padding: 0.6rem 1rem; background: var(--color-accent); color: #fff; text-decoration: none; border-radius: 8px; font-weight: 600; }
.check-again:hover { opacity: .88; }
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_routes.py -v`
Expected: PASS — the four new tests plus all existing complete-product tests (they carry `nutriscore_grade`, so they are not awaiting extraction and render normally — regression guard).

- [ ] **Step 8: Commit**

```bash
git add app/main.py templates/product_pending.html static/css/style.css tests/test_routes.py
git commit -m "feat: honest pending/partial state on product page after photo upload"
```

---

### Task 8: Full verification

**Files:** none (verification only).

- [ ] **Step 1: Run the entire suite**

Run: `pytest -q`
Expected: all tests pass, no warnings about unraised/!skipped add-product tests.

- [ ] **Step 2: Confirm the app imports and routes register**

Run: `python -c "from app.main import create_app; create_app(); print('OK')"`
Expected: `OK` (catches template/route wiring errors `pytest` might miss).

- [ ] **Step 3: Manual smoke (staging) — optional but recommended**

With `OFF_ENVIRONMENT=staging` and staging credentials set, run `uvicorn app.main:app --reload`, then:
- Visit `/product/<unknown-barcode>` → photo-capture page with the barcode prefilled and the three-photo requirement shown up front.
- Submit with only two photos → blocked with "Nutrition photo needed."
- Submit a `.jpg`-renamed PDF → blocked with the JPG/PNG/WEBP message.
- Submit three real photos → redirect to `/product/<barcode>?submitted=1` showing the pending banner + "Check again."
- Confirm the three images appear on the staging product (front/ingredients/nutrition).

- [ ] **Step 4: Confirm no dead references remain**

Run: `grep -rn "name=\"name\"\|name=\"brand\"\|name=\"category\"\|name=\"quantity\"" templates/ ; grep -rn "\.add_product\b" app/`
Expected: no matches.

---

## Self-review

**Spec coverage:**
- Guided capture, all three required, up-front requirement → Task 5 (template + route validation). ✓
- File inputs with `capture` → Task 5 template. ✓
- Upload via SDK `upload_image(selected=...)` → Task 4. ✓
- Honest pending + real content, `created_t` three-state resolution → Tasks 3 + 7. ✓
- Server-side validation (jpg/png/webp + 12 MB), friendly errors → Tasks 1 + 2 + 5. ✓
- Renamed non-image rejected + tested → Task 2 (unit) + Task 5 (route). ✓
- Reuse auth/environment/trust-store → Task 4 (existing `_build_api`/`api_factory`). ✓
- Clean removal of text path + tests → Tasks 5 (tests) + 6 (code/tests). ✓
- 12 MB / 15 min / `en` configurable defaults → Task 1. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; every test step shows real assertions. ✓

**Type consistency:** `add_product_photos(*, barcode, images: dict[str,bytes])` used identically in Tasks 4 and 5. `created_t` (Task 3) consumed in Task 7. `validate_image(data, *, max_bytes=...)` defined in Task 2, called in Task 5. `_is_awaiting_extraction` defined and used in Task 7. Pending template context keys (`barcode`, `product`, `state`, `submitted`, `off_url`) match between route (Task 7 step 4) and template (Task 7 step 5). ✓

**Deviation from spec:** pending UI realised as new `product_pending.html` rather than inline guards in `product.html` (flagged above). Behaviour-equivalent.
