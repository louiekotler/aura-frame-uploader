"""Upload via Aura's private API.

There is no REST endpoint that accepts image bytes — the app puts the file in
S3 itself and then registers it. Three steps:

  1. select_asset   reserve the slot on the frame under our chosen identifier
  2. S3 PutObject   the actual transfer, with temporary Cognito credentials
  3. batch_update   register the object as an asset, with its metadata

The `local_identifier` we choose in step 1 is an idempotency key: uploading the
same one twice updates the existing asset instead of adding a second copy.
"""

import uuid

import boto3
import botocore
from botocore import UNSIGNED

from ..client import AuraClient, aura_timestamp
from ..errors import UploadError
from ..images import PreparedImage
from .base import AssetRef, Backend

S3_BUCKET = "images.senseapp.co"
COGNITO_POOL_ID = "us-east-1:b92826c0-8274-43db-abff-136977c13598"
AWS_REGION = "us-east-1"


def _s3_client():
    """Credentials from the app's unauthenticated Cognito pool.

    The pool is public by design and the role it grants is write-only, so a 403
    from a read call against this bucket is expected rather than a fault.
    """
    cognito = boto3.client(
        "cognito-identity",
        region_name=AWS_REGION,
        config=botocore.config.Config(signature_version=UNSIGNED),
    )
    identity = cognito.get_id(IdentityPoolId=COGNITO_POOL_ID)
    creds = cognito.get_credentials_for_identity(IdentityId=identity["IdentityId"])[
        "Credentials"
    ]
    return boto3.client(
        "s3",
        region_name=AWS_REGION,
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretKey"],
        aws_session_token=creds["SessionToken"],
    )


class ApiBackend(Backend):
    name = "api"

    def __init__(self, client: AuraClient):
        self.client = client

    def upload(self, image: PreparedImage, local_identifier: str, frame_id: str) -> AssetRef:
        failed = self.client.select_asset(frame_id, local_identifier)
        if failed:
            raise UploadError(
                f"{image.source_path.name}: frame refused the asset "
                f"(number_failed={failed})."
            )

        file_name = f"{uuid.uuid4()}.jpg"
        try:
            _s3_client().put_object(Body=image.data, Bucket=S3_BUCKET, Key=file_name)
        except Exception as e:
            raise UploadError(f"{image.source_path.name}: S3 upload failed ({e})") from e

        success = self.client.batch_update(
            {
                "data_uti": "public.jpeg",
                "favorite": False,
                "file_name": file_name,
                "md5_hash": image.md5_b64,
                "width": image.width,
                "height": image.height,
                "orientation": 1,
                "local_identifier": local_identifier,
                "selected": True,
                "upload_priority": 0,
                "taken_at": aura_timestamp(image.taken_at),
                "modified_at": aura_timestamp(),
            }
        )
        return AssetRef(
            asset_id=success["id"],
            local_identifier=success.get("local_identifier", local_identifier),
            file_name=file_name,
        )
