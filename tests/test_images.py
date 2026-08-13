import base64
import hashlib
from datetime import datetime, timezone

import piexif
import pytest
from PIL import Image

from aura_upload import images
from aura_upload.client import aura_timestamp
from aura_upload.config import MAX_UPLOAD_BYTES
from aura_upload.errors import ImageError


def make_jpeg(path, size=(400, 300), exif_bytes=None, color=(120, 60, 30)):
    img = Image.new("RGB", size, color)
    img.save(path, "JPEG", quality=90, **({"exif": exif_bytes} if exif_bytes else {}))
    return path


def exif_with(dt="2019:07:04 12:00:00", offset=None, subsec=None, orientation=1):
    exif = {"0th": {piexif.ImageIFD.Orientation: orientation}, "Exif": {}, "GPS": {},
            "1st": {}, "thumbnail": None}
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = dt.encode()
    if offset:
        exif["Exif"][piexif.ExifIFD.OffsetTimeOriginal] = offset.encode()
    if subsec:
        exif["Exif"][piexif.ExifIFD.SubSecTimeOriginal] = subsec.encode()
    return piexif.dump(exif)


def test_taken_at_read_from_exif(tmp_path):
    p = make_jpeg(tmp_path / "a.jpg", exif_bytes=exif_with(offset="+00:00"))
    dt, source = images.read_taken_at(p)
    assert source == "exif"
    assert (dt.year, dt.month, dt.day, dt.hour) == (2019, 7, 4, 12)


def test_taken_at_honours_utc_offset(tmp_path):
    p = make_jpeg(tmp_path / "b.jpg", exif_bytes=exif_with(offset="-07:00"))
    dt, _ = images.read_taken_at(p)
    assert dt.tzinfo == timezone.utc
    assert (dt.hour, dt.day) == (19, 4)


def test_taken_at_subsecond(tmp_path):
    p = make_jpeg(tmp_path / "c.jpg", exif_bytes=exif_with(offset="+00:00", subsec="25"))
    dt, _ = images.read_taken_at(p)
    assert dt.microsecond == 250000


def test_taken_at_falls_back_to_mtime(tmp_path):
    p = make_jpeg(tmp_path / "d.jpg")
    dt, source = images.read_taken_at(p)
    assert source == "mtime"
    assert dt.tzinfo == timezone.utc


def test_prepare_resizes_to_long_edge(tmp_path):
    p = make_jpeg(tmp_path / "big.jpg", size=(5000, 2500))
    out = images.prepare(p, max_long_edge=2048)
    assert out.width == 2048 and out.height == 1024


def test_prepare_leaves_small_images_alone(tmp_path):
    p = make_jpeg(tmp_path / "small.jpg", size=(800, 600))
    out = images.prepare(p, max_long_edge=2048)
    assert (out.width, out.height) == (800, 600)


def test_prepare_stays_under_the_upload_ceiling(tmp_path):
    p = make_jpeg(tmp_path / "e.jpg", size=(2048, 2048))
    assert len(images.prepare(p).data) <= MAX_UPLOAD_BYTES


def test_md5_is_base64_not_hex(tmp_path):
    """Aura rejects a hex digest here; this catches a silent regression."""
    p = make_jpeg(tmp_path / "f.jpg")
    out = images.prepare(p)
    assert out.md5_b64 == base64.b64encode(hashlib.md5(out.data).digest()).decode()
    assert out.md5_b64.endswith("==") or "+" in out.md5_b64 or "/" in out.md5_b64 or True
    assert len(out.md5_b64) == 24


def test_exif_rotation_is_baked_in(tmp_path):
    """Orientation 6 means 'rotate 90°'; the output must already be rotated."""
    p = make_jpeg(tmp_path / "rot.jpg", size=(400, 300),
                  exif_bytes=exif_with(orientation=6))
    out = images.prepare(p)
    assert (out.width, out.height) == (300, 400)


def test_prepare_rejects_non_images(tmp_path):
    p = tmp_path / "not.jpg"
    p.write_text("hello")
    with pytest.raises(ImageError):
        images.prepare(p)


def test_content_identifier_is_stable_and_prefixed(tmp_path):
    p = make_jpeg(tmp_path / "g.jpg")
    assert images.content_identifier(p) == images.content_identifier(p)
    assert images.content_identifier(p).startswith("aura-")


def test_content_identifier_differs_per_content(tmp_path):
    a = make_jpeg(tmp_path / "h.jpg", color=(1, 2, 3))
    b = make_jpeg(tmp_path / "i.jpg", color=(200, 100, 50))
    assert images.content_identifier(a) != images.content_identifier(b)


def test_collect_single_file(tmp_path):
    p = make_jpeg(tmp_path / "one.jpg")
    assert images.collect(p) == [p]


def test_collect_folder_skips_unsupported_and_subdirs(tmp_path):
    make_jpeg(tmp_path / "a.jpg")
    make_jpeg(tmp_path / "b.png")
    (tmp_path / "notes.txt").write_text("x")
    nested = tmp_path / "sub"
    nested.mkdir()
    make_jpeg(nested / "c.jpg")

    names = [p.name for p in images.collect(tmp_path)]
    assert names == ["a.jpg", "b.png"]

    recursive = [p.name for p in images.collect(tmp_path, recursive=True)]
    assert "c.jpg" in recursive


def test_collect_rejects_missing_path(tmp_path):
    with pytest.raises(ImageError):
        images.collect(tmp_path / "missing")


def test_aura_timestamp_is_milliseconds_utc():
    dt = datetime(2026, 8, 13, 7, 6, 3, 480123, tzinfo=timezone.utc)
    assert aura_timestamp(dt) == "2026-08-13T07:06:03.480Z"


def test_aura_timestamp_converts_to_utc():
    from datetime import timedelta

    tz = timezone(timedelta(hours=-7))
    dt = datetime(2026, 8, 13, 0, 6, 3, 0, tzinfo=tz)
    assert aura_timestamp(dt) == "2026-08-13T07:06:03.000Z"
