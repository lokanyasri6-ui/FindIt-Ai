import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import settings

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ImageError(ValueError):
    """Raised for uploads we refuse to store; the message is safe to show to the user."""


def process_image(raw: bytes) -> bytes:
    """Validate an upload and re-encode it as a clean JPEG.

    Re-encoding drops EXIF metadata (GPS position, device info), which matters for privacy,
    applies the camera orientation and caps the pixel size.
    """
    if not raw:
        raise ImageError("The uploaded image is empty")
    if len(raw) > settings.max_upload_mb * 1024 * 1024:
        raise ImageError(f"Image is too large (max {settings.max_upload_mb} MB)")
    try:
        im = Image.open(io.BytesIO(raw))
        fmt = im.format
        im.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ImageError("That file isn't a valid image") from None
    if fmt not in ALLOWED_FORMATS:
        raise ImageError("Only JPEG, PNG or WebP images are supported")

    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        im = background
    else:
        im = im.convert("RGB")
    im.thumbnail((1280, 1280))

    out = io.BytesIO()
    im.save(out, "JPEG", quality=85, optimize=True)
    return out.getvalue()


def save_image(data: bytes) -> str:
    """Persist processed image bytes and return a URL (relative for local, absolute for S3)."""
    name = f"{uuid.uuid4().hex}.jpg"

    if settings.storage_backend == "s3":
        import boto3  # optional dependency (requirements-ml.txt)

        boto3.client("s3", region_name=settings.s3_region or None).put_object(
            Bucket=settings.s3_bucket, Key=f"items/{name}", Body=data, ContentType="image/jpeg"
        )
        base = settings.s3_public_base_url or f"https://{settings.s3_bucket}.s3.{settings.s3_region}.amazonaws.com"
        return f"{base.rstrip('/')}/items/{name}"

    folder = Path(settings.upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)
    return f"/uploads/{name}"
