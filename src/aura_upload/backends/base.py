from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..images import PreparedImage


@dataclass
class AssetRef:
    asset_id: str
    local_identifier: str
    file_name: str | None = None


class Backend(ABC):
    """How photos reach a frame.

    Only the API backend exists today. The interface is here so a second
    transport (email-to-frame, or another vendor's) can be added as a module
    rather than a refactor.
    """

    name = "base"

    @abstractmethod
    def upload(self, image: PreparedImage, local_identifier: str, frame_id: str) -> AssetRef:
        ...
