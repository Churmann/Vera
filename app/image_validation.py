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
