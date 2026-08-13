"""End-to-end test against a real frame.

Skipped unless AURA_LIVE_TEST=1. It uploads a synthetic test card to the
configured frame and removes it again, asserting the frame returns to its
starting state. Requires a stored session (`aura-upload login`).
"""

import io
import os
from datetime import datetime

import pytest
import requests
from PIL import Image, ImageDraw

from aura_upload.backends.api import ApiBackend
from aura_upload.client import AuraClient
from aura_upload.config import load_config
from aura_upload.images import PreparedImage, prepare

pytestmark = pytest.mark.skipif(
    os.environ.get("AURA_LIVE_TEST") != "1",
    reason="live test writes to a real frame; set AURA_LIVE_TEST=1 to run",
)

LOCAL_ID = "aura-upload-selftest.jpg"


@pytest.fixture(scope="module")
def setup():
    cfg = load_config()
    frame_id = cfg.resolve_frame(None)
    client = AuraClient.from_keyring()
    return cfg, client, frame_id


@pytest.fixture(scope="module")
def testcard(tmp_path_factory):
    path = tmp_path_factory.mktemp("live") / "testcard.jpg"
    img = Image.new("RGB", (1600, 1200), (200, 30, 40))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, 1560, 1160], outline="white", width=8)
    d.text((760, 560), "aura-upload self test", fill="white")
    d.text((760, 620), datetime.now().strftime("%Y-%m-%d %H:%M:%S"), fill="white")
    d.text((740, 700), "this photo deletes itself", fill="white")
    img.save(path, "JPEG", quality=90)
    return path


def listed_count(client, frame_id):
    return len(client.all_assets(frame_id))


def test_upload_appears_on_the_frame(setup, testcard):
    cfg, client, frame_id = setup
    baseline = listed_count(client, frame_id)

    image = prepare(testcard, cfg.max_long_edge, cfg.jpeg_quality)
    ref = ApiBackend(client).upload(image, LOCAL_ID, frame_id)
    assert ref.asset_id

    assets = client.all_assets(frame_id)
    mine = [a for a in assets if a.get("local_identifier") == LOCAL_ID]
    assert len(mine) == 1, "the uploaded photo is not listed on the frame"
    assert len(assets) == baseline + 1

    pytest.shared = {"asset_id": ref.asset_id, "baseline": baseline,
                     "file_name": mine[0]["file_name"], "image": image}


def test_aura_ingested_the_actual_pixels(setup):
    """Fetch the image back through Aura's render proxy.

    A 200 from the upload calls only proves the metadata was accepted; this
    proves the bytes arrived and are being served.
    """
    _, client, _ = setup
    file_name = pytest.shared["file_name"]
    url = (
        f"https://imgproxy.pushd.com/{client.user_id}/"
        f"rotate_0__width_600__height_450__rt_fill__gravity_sm__quality_95__{file_name}"
    )
    r = requests.get(url, timeout=30)
    assert r.status_code == 200
    assert Image.open(io.BytesIO(r.content)).size == (600, 450)


def test_reupload_upserts_instead_of_duplicating(setup):
    """The guarantee the whole design rests on."""
    _, client, frame_id = setup
    before = client.all_assets(frame_id)
    image: PreparedImage = pytest.shared["image"]

    ref = ApiBackend(client).upload(image, LOCAL_ID, frame_id)

    assert ref.asset_id == pytest.shared["asset_id"], "a second asset id was issued"
    after = client.all_assets(frame_id)
    assert len(after) == len(before), "re-uploading added an asset"
    assert len([a for a in after if a.get("local_identifier") == LOCAL_ID]) == 1


def test_show_puts_it_on_the_panel(setup):
    _, client, frame_id = setup
    assert client.show_asset(frame_id, pytest.shared["asset_id"])


def test_remove_restores_the_frame(setup):
    _, client, frame_id = setup
    assert client.remove_asset(frame_id, local_identifier=LOCAL_ID) == 0

    assets = client.all_assets(frame_id)
    assert not [a for a in assets if a.get("local_identifier") == LOCAL_ID]
    assert len(assets) == pytest.shared["baseline"], "frame did not return to baseline"

    # A removed asset still resolves, so the lookup must report it as gone.
    assert client.asset_for_local_identifier(LOCAL_ID) is None
