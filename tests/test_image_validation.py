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
