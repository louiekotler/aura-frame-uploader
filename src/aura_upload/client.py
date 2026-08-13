"""Thin HTTP layer over Aura's private app API.

Aura publishes no official API. Everything here was derived by observing the
app's own traffic and verified against a real frame; it can break whenever Aura
ships a release. Keeping this layer thin is deliberate — re-deriving a changed
endpoint should be a small job.
"""

from datetime import datetime, timezone

import requests

from .auth import BASE_URL, load_session
from .errors import ApiError


def aura_timestamp(dt: datetime | None = None) -> str:
    """Aura's wire format: 2026-08-13T07:06:03.480Z, milliseconds not micros."""
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class AuraClient:
    def __init__(self, user_id: str, auth_token: str):
        self.user_id = user_id
        self.session = requests.Session()
        self.session.headers.update(
            {
                "X-User-Id": user_id,
                "X-Token-Auth": auth_token,
                "Content-Type": "application/json; charset=utf-8",
                "Accept-Language": "en-US",
            }
        )

    @classmethod
    def from_keyring(cls) -> "AuraClient":
        s = load_session()
        return cls(s["user_id"], s["auth_token"])

    def _request(self, method: str, path: str, **kwargs):
        r = self.session.request(method, f"{BASE_URL}{path}", timeout=60, **kwargs)
        try:
            body = r.json()
        except ValueError:
            body = {"raw": r.text[:500]}
        if r.status_code == 401:
            raise ApiError(
                "Aura rejected the stored token. Run `aura-upload login` again.",
                401,
                body,
            )
        if r.status_code >= 400:
            raise ApiError(f"{method} {path} failed ({r.status_code})", r.status_code, body)
        return body

    def frames(self) -> list[dict]:
        return self._request("GET", "/frames.json").get("frames") or []

    def frame(self, frame_id: str) -> dict:
        return self._request("GET", f"/frames/{frame_id}.json").get("frame") or {}

    def assets_page(self, frame_id: str, limit: int = 200, cursor: str | None = None):
        params = {"limit": limit, "side_load_users": "false"}
        if cursor:
            params["cursor"] = cursor
        body = self._request("GET", f"/frames/{frame_id}/assets.json", params=params)
        return body.get("assets") or [], body.get("next_page_cursor")

    def all_assets(self, frame_id: str) -> list[dict]:
        """Page through every asset.

        The frame's `num_assets` field is a denormalised counter that does not
        decrement on removal, so any question about what is actually on a frame
        has to be answered by listing.
        """
        assets, cursor = self.assets_page(frame_id)
        while cursor:
            page, cursor = self.assets_page(frame_id, cursor=cursor)
            if not page:
                break
            assets.extend(page)
        return assets

    def select_asset(self, frame_id: str, local_identifier: str) -> int:
        body = self._request(
            "POST",
            f"/frames/{frame_id}/select_asset.json",
            json={"assets": [{"asset_local_identifier": local_identifier}]},
        )
        return body.get("number_failed", 0)

    def batch_update(self, asset: dict) -> dict:
        body = self._request("PUT", "/assets/batch_update.json", json={"assets": [asset]})
        successes = body.get("successes") or []
        if not successes:
            raise ApiError(f"batch_update registered nothing: {str(body)[:300]}")
        return successes[0]

    def asset_for_local_identifier(self, local_identifier: str) -> dict | None:
        body = self._request(
            "GET",
            "/assets/asset_for_local_identifier.json",
            params={"local_identifier": local_identifier},
        )
        asset = body.get("asset")
        # A removed asset still resolves here, but with its file cleared — so a
        # hit alone does not mean the photo is on a frame.
        if not asset or not asset.get("file_name"):
            return None
        return asset

    def remove_asset(self, frame_id: str, *, local_identifier=None, asset_id=None) -> int:
        entry = {"asset_id": asset_id} if asset_id else {"asset_local_identifier": local_identifier}
        body = self._request(
            "POST", f"/frames/{frame_id}/remove_asset.json", json={"assets": [entry]}
        )
        return body.get("number_failed", 0)

    def show_asset(self, frame_id: str, asset_id: str) -> bool:
        import uuid

        body = self._request(
            "POST",
            f"/frames/{frame_id}/goto.json",
            json={
                "asset_id": asset_id,
                "frame_id": frame_id,
                "goto_time": aura_timestamp(),
                "swipe_direction": 0,
                "impression_id": str(uuid.uuid4()),
                "select_asset": True,
            },
        )
        return bool(body.get("showing"))
