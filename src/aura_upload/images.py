"""Reading capture time and rendering an upload-ready JPEG."""

import base64
import hashlib
import io
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

from .config import MAX_UPLOAD_BYTES
from .errors import ImageError

log = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}

EXIF_IFD = 0x8769
DATETIME_ORIGINAL = 0x9003
OFFSET_TIME_ORIGINAL = 0x9011
SUBSEC_TIME_ORIGINAL = 0x9291


@dataclass
class PreparedImage:
    data: bytes
    width: int
    height: int
    taken_at: datetime
    taken_at_source: str
    source_path: Path

    @property
    def md5_b64(self) -> str:
        """Aura wants base64 of the digest, not the usual hex."""
        return base64.b64encode(hashlib.md5(self.data).digest()).decode()

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


def read_taken_at(path: Path, img: Image.Image | None = None):
    """Return (datetime_utc, source).

    Aura ignores EXIF inside the uploaded file and displays whatever `taken_at`
    the upload call supplies, so getting this right here is the only chance to
    date a photo correctly.
    """
    try:
        img = img or Image.open(path)
        exif = img.getexif()
        sub = exif.get_ifd(EXIF_IFD) if exif else {}
    except Exception:
        sub = {}

    raw = (sub or {}).get(DATETIME_ORIGINAL)
    if raw:
        try:
            dt = datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
            subsec = str(sub.get(SUBSEC_TIME_ORIGINAL) or "").strip()
            if subsec.isdigit():
                dt = dt.replace(microsecond=int(subsec.ljust(3, "0")[:3]) * 1000)

            offset = str(sub.get(OFFSET_TIME_ORIGINAL) or "").strip()
            if offset:
                dt = dt.replace(tzinfo=datetime.strptime(offset, "%z").tzinfo)
            else:
                dt = dt.astimezone()
            return dt.astimezone(timezone.utc), "exif"
        except ValueError:
            pass

    log.warning(
        "%s has no usable EXIF DateTimeOriginal; falling back to file mtime, "
        "so the frame will show the file's date rather than the capture date.",
        path.name,
    )
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc), "mtime"


def prepare(path: Path, max_long_edge: int = 2048, quality: int = 90) -> PreparedImage:
    try:
        img = Image.open(path)
    except Exception as e:
        raise ImageError(f"{path.name}: not a readable image ({e})") from e

    taken_at, source = read_taken_at(path, img)

    # Bake the EXIF rotation into the pixels and declare orientation 1, rather
    # than trusting Aura to honour the tag.
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")

    if max(img.size) > max_long_edge:
        img.thumbnail((max_long_edge, max_long_edge), Image.LANCZOS)

    data = _encode(img, quality)
    if len(data) > MAX_UPLOAD_BYTES:
        for lower in (80, 70, 60):
            data = _encode(img, lower)
            if len(data) <= MAX_UPLOAD_BYTES:
                break
        else:
            raise ImageError(
                f"{path.name}: still {len(data) / 1e6:.1f} MB at quality 60, "
                f"above Aura's {MAX_UPLOAD_BYTES / 1e6:.1f} MB limit."
            )

    return PreparedImage(
        data=data,
        width=img.width,
        height=img.height,
        taken_at=taken_at,
        taken_at_source=source,
        source_path=path,
    )


def _encode(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def content_identifier(path: Path) -> str:
    """Fallback identity for files with no external id, from the source bytes."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return f"aura-{digest}.jpg"


def collect(target: Path, recursive: bool = False) -> list[Path]:
    if target.is_file():
        return [target]
    if not target.is_dir():
        raise ImageError(f"{target} is neither a file nor a directory.")
    it = target.rglob("*") if recursive else target.iterdir()
    return sorted(
        p for p in it if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )
