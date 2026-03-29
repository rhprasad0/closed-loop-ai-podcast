from __future__ import annotations

import boto3

# Module-level cached S3 client — reused across Lambda warm starts.
_s3_client = boto3.client("s3")


def upload_bytes(bucket: str, key: str, data: bytes, content_type: str) -> None:
    """Upload raw bytes to S3 via put_object."""
    _s3_client.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)


def upload_file(bucket: str, key: str, filepath: str, content_type: str) -> None:
    """Upload a local file to S3 via upload_file."""
    _s3_client.upload_file(filepath, bucket, key, ExtraArgs={"ContentType": content_type})


def download_file(bucket: str, key: str, local_path: str) -> None:
    """Download an S3 object to a local file path via download_file."""
    _s3_client.download_file(bucket, key, local_path)


def generate_presigned_url(bucket: str, key: str, expiry: int = 3600) -> str:
    """Generate a presigned GET URL for an S3 object.

    Default expiry is 3600 seconds (1 hour).
    """
    url: str = _s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expiry,
    )
    return url
