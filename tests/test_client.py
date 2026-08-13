from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import responses

from aura_upload.auth import BASE_URL
from aura_upload.backends.api import ApiBackend
from aura_upload.client import AuraClient
from aura_upload.errors import ApiError, UploadError
from aura_upload.images import PreparedImage

FRAME = "aaaaaaaa-0000-0000-0000-000000000000"


@pytest.fixture
def client():
    return AuraClient("user-1", "token-1")


@pytest.fixture
def image(tmp_path):
    return PreparedImage(
        data=b"\xff\xd8\xff\xe0 fake jpeg bytes",
        width=2400,
        height=1600,
        taken_at=datetime(2019, 7, 4, 12, 0, 0, tzinfo=timezone.utc),
        taken_at_source="exif",
        source_path=tmp_path / "photo.jpg",
    )


@responses.activate
def test_expired_token_gives_actionable_error(client):
    responses.get(f"{BASE_URL}/frames.json", json={"error": "unauthorized"}, status=401)
    with pytest.raises(ApiError) as e:
        client.frames()
    assert "login" in str(e.value).lower()


@responses.activate
def test_removed_asset_lookup_returns_none(client):
    """A removed asset still resolves, but with its file cleared.

    Treating that stub as 'present' would make the tool believe a photo is on a
    frame after it was deleted.
    """
    responses.get(
        f"{BASE_URL}/assets/asset_for_local_identifier.json",
        json={"asset": {"id": "a1", "local_identifier": "x.jpg", "file_name": None}},
    )
    assert client.asset_for_local_identifier("x.jpg") is None


@responses.activate
def test_live_asset_lookup_returns_asset(client):
    responses.get(
        f"{BASE_URL}/assets/asset_for_local_identifier.json",
        json={"asset": {"id": "a1", "local_identifier": "x.jpg", "file_name": "f.jpg"}},
    )
    assert client.asset_for_local_identifier("x.jpg")["id"] == "a1"


@responses.activate
def test_all_assets_follows_the_cursor(client):
    responses.get(
        f"{BASE_URL}/frames/{FRAME}/assets.json",
        json={"assets": [{"id": "1"}, {"id": "2"}], "next_page_cursor": "c1"},
    )
    responses.get(
        f"{BASE_URL}/frames/{FRAME}/assets.json",
        json={"assets": [{"id": "3"}], "next_page_cursor": None},
    )
    assert [a["id"] for a in client.all_assets(FRAME)] == ["1", "2", "3"]


@responses.activate
def test_upload_sends_the_metadata_aura_requires(client, image):
    responses.post(f"{BASE_URL}/frames/{FRAME}/select_asset.json",
                   json={"number_failed": 0})
    responses.put(
        f"{BASE_URL}/assets/batch_update.json",
        json={"ids": ["asset-9"],
              "successes": [{"id": "asset-9", "local_identifier": "lrpub-x.jpg"}]},
    )

    with patch("aura_upload.backends.api._s3_client") as s3:
        ref = ApiBackend(client).upload(image, "lrpub-x.jpg", FRAME)
        s3.return_value.put_object.assert_called_once()

    assert ref.asset_id == "asset-9"

    sent = responses.calls[-1].request.body
    import json as _json
    asset = _json.loads(sent)["assets"][0]

    assert asset["md5_hash"] == image.md5_b64
    assert asset["taken_at"] == "2019-07-04T12:00:00.000Z"
    assert asset["orientation"] == 1
    assert asset["local_identifier"] == "lrpub-x.jpg"
    assert (asset["width"], asset["height"]) == (2400, 1600)


@responses.activate
def test_upload_stops_when_the_frame_refuses_the_slot(client, image):
    responses.post(f"{BASE_URL}/frames/{FRAME}/select_asset.json",
                   json={"number_failed": 1})
    with patch("aura_upload.backends.api._s3_client") as s3:
        with pytest.raises(UploadError):
            ApiBackend(client).upload(image, "x.jpg", FRAME)
        s3.assert_not_called()


@responses.activate
def test_batch_update_with_no_successes_is_an_error(client, image):
    responses.post(f"{BASE_URL}/frames/{FRAME}/select_asset.json",
                   json={"number_failed": 0})
    responses.put(f"{BASE_URL}/assets/batch_update.json", json={"ids": [], "successes": []})
    with patch("aura_upload.backends.api._s3_client"):
        with pytest.raises(ApiError):
            ApiBackend(client).upload(image, "x.jpg", FRAME)


@responses.activate
def test_remove_by_local_identifier(client):
    responses.post(f"{BASE_URL}/frames/{FRAME}/remove_asset.json",
                   json={"number_failed": 0})
    assert client.remove_asset(FRAME, local_identifier="x.jpg") == 0
    import json as _json
    assert _json.loads(responses.calls[-1].request.body)["assets"][0] == {
        "asset_local_identifier": "x.jpg"
    }
