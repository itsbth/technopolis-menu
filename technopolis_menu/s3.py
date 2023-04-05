import os

import boto3


def get_s3_resource():
    s3 = boto3.resource(
        "s3",
        endpoint_url=S3_ENDPOINT,
        region_name=S3_REGION,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
    )
    return s3


S3_REGION = os.environ.get("S3_REGION", "nl-ams")
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", None)
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY_ID", None)
S3_SECRET_KEY = os.environ.get("S3_SECRET_ACCESS_KEY", None)
