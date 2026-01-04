"""
S3 utility functions for file uploads
"""
import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from .models import Configuration


def get_s3_client():
    """Get S3 client using Configuration model settings"""
    aws_access_key = Configuration.get_value('aws_access_key_id', '')
    aws_secret_key = Configuration.get_value('aws_secret_access_key', '')
    aws_region = Configuration.get_value('aws_region', 'ap-south-1')

    if not aws_access_key or not aws_secret_key:
        raise ValueError("AWS credentials not configured. Set aws_access_key_id and aws_secret_access_key in Configuration.")

    return boto3.client(
        's3',
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=aws_region
    )


def upload_file_to_s3(file_path, s3_key, content_type='video/mp4'):
    """
    Upload a file to S3 and return the public URL

    Args:
        file_path: Local path to the file
        s3_key: S3 object key (path in bucket)
        content_type: MIME type of the file

    Returns:
        str: Public URL of the uploaded file
    """
    bucket_name = Configuration.get_value('aws_s3_bucket', '')
    if not bucket_name:
        raise ValueError("AWS S3 bucket not configured. Set aws_s3_bucket in Configuration.")

    s3_client = get_s3_client()

    # Upload file (public access should be configured via bucket policy)
    try:
        s3_client.upload_file(
            file_path,
            bucket_name,
            s3_key,
            ExtraArgs={
                'ContentType': content_type,
                'ACL': 'public-read'
            }
        )
    except Exception as acl_error:
        # If ACL fails (bucket might block public ACLs), try without ACL
        s3_client.upload_file(
            file_path,
            bucket_name,
            s3_key,
            ExtraArgs={
                'ContentType': content_type
            }
        )

    # Generate public URL
    aws_region = Configuration.get_value('aws_region', 'ap-south-1')
    url = f"https://{bucket_name}.s3.{aws_region}.amazonaws.com/{s3_key}"

    return url


def upload_bytes_to_s3(content, s3_key, content_type='video/mp4'):
    """
    Upload bytes content to S3 and return the public URL

    Args:
        content: Bytes content to upload
        s3_key: S3 object key (path in bucket)
        content_type: MIME type of the file

    Returns:
        str: Public URL of the uploaded file
    """
    bucket_name = Configuration.get_value('aws_s3_bucket', '')
    if not bucket_name:
        raise ValueError("AWS S3 bucket not configured. Set aws_s3_bucket in Configuration.")

    s3_client = get_s3_client()

    # Upload with public-read ACL for Instagram API access
    s3_client.put_object(
        Bucket=bucket_name,
        Key=s3_key,
        Body=content,
        ContentType=content_type,
        ACL='public-read'
    )

    # Generate public URL
    aws_region = Configuration.get_value('aws_region', 'ap-south-1')
    url = f"https://{bucket_name}.s3.{aws_region}.amazonaws.com/{s3_key}"

    return url


def delete_from_s3(s3_key):
    """Delete a file from S3"""
    bucket_name = Configuration.get_value('aws_s3_bucket', '')
    if not bucket_name:
        return False

    try:
        s3_client = get_s3_client()
        s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
        return True
    except ClientError:
        return False
