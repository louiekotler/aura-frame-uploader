"""How photo shape maps to presentation on the frame."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import responses

from aura_upload.auth import BASE_URL
from aura_upload.backends.api import ApiBackend
from aura_upload.cli import build_parser
from aura_upload.client import AuraClient
from aura_upload.config import Config, load_config
from aura_upload.errors import ConfigError
from aura_upload.images import PreparedImage

FRAME = "aaaaaaaa-0000-0000-0000-000000000000"


def write(tmp_path, body):
    p = tmp_path / "config.toml"
    p.write_text(body)
    return p


def test_defaults_crop_wide_and_fit_tall():
    """The frame crops to fill, which is wanted for wide photos and not for tall."""
    cfg = Config()
    assert cfg.display_mode(3000, 2000) == "crop"
    assert cfg.display_mode(2000, 3000) == "fit"


def test_square_counts_as_landscape():
    assert Config().display_mode(2000, 2000) == "crop"


def test_display_modes_are_configurable(tmp_path):
    cfg = load_config(write(
        tmp_path,
        'allowed_frame_ids = ["x"]\n\n[display]\nlandscape = "fit"\nportrait = "crop"\n',
    ))
    assert cfg.display_mode(3000, 2000) == "fit"
    assert cfg.display_mode(2000, 3000) == "crop"


def test_invalid_display_mode_is_rejected(tmp_path):
    with pytest.raises(ConfigError) as e:
        load_config(write(tmp_path, '[display]\nportrait = "blurred"\n'))
    assert "portrait" in str(e.value)


@pytest.fixture
def image(tmp_path):
    return PreparedImage(
        data=b"\xff\xd8\xff\xe0 bytes",
        width=1366,
        height=2048,
        taken_at=datetime(2024, 8, 17, 20, 17, tzinfo=timezone.utc),
        taken_at_source="exif",
        source_path=tmp_path / "tall.jpg",
    )


def _stub_upload_calls():
    responses.post(f"{BASE_URL}/frames/{FRAME}/select_asset.json",
                   json={"number_failed": 0})
    responses.put(f"{BASE_URL}/assets/batch_update.json",
                  json={"ids": ["a1"],
                        "successes": [{"id": "a1", "local_identifier": "x.jpg"}]})


@responses.activate
def test_fit_marks_the_whole_image_visible(image):
    _stub_upload_calls()
    responses.post(f"{BASE_URL}/assets/crop.json", json={"asset": {"id": "a1"}})

    with patch("aura_upload.backends.api._s3_client"):
        ApiBackend(AuraClient("u1", "t1")).upload(image, "x.jpg", FRAME, fit=True)

    crop = [c for c in responses.calls if "crop.json" in c.request.url]
    assert len(crop) == 1, "fit did not set the visible area"

    import json as _json
    body = _json.loads(crop[0].request.body)
    # A rect covering the whole image is what stops Aura cropping to fill.
    assert body["user_landscape_rect"] == "0,0,1366,2048"
    assert body["id"] == "a1"


@responses.activate
def test_crop_leaves_the_frame_to_decide(image):
    _stub_upload_calls()

    with patch("aura_upload.backends.api._s3_client"):
        ApiBackend(AuraClient("u1", "t1")).upload(image, "x.jpg", FRAME, fit=False)

    assert not [c for c in responses.calls if "crop.json" in c.request.url]


def test_cli_exposes_per_orientation_overrides():
    args = build_parser().parse_args(
        ["upload", "--landscape", "fit", "--portrait", "crop"]
    )
    assert (args.landscape, args.portrait) == ("fit", "crop")


def test_cli_overrides_default_to_none_so_config_wins():
    args = build_parser().parse_args(["upload"])
    assert args.landscape is None and args.portrait is None


def test_cli_rejects_an_unknown_mode():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["upload", "--portrait", "blurred"])
