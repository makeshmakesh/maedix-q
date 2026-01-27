"""
S3 utility functions for file uploads
"""
import logging
import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from .models import Configuration

logger = logging.getLogger(__name__)


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


def upload_to_s3(content, s3_key, content_type='application/octet-stream'):
    """
    Upload content to S3 and return the public URL, S3 key, and any error.

    Args:
        content: Bytes content to upload
        s3_key: S3 object key (path in bucket)
        content_type: MIME type of the file

    Returns:
        tuple: (url, s3_key, error_message)
    """
    bucket_name = Configuration.get_value('aws_s3_bucket', '')
    if not bucket_name:
        logger.error("AWS S3 bucket not configured in Configuration table")
        return None, None, "AWS S3 bucket not configured"

    logger.info(f"Uploading to S3: bucket={bucket_name}, key={s3_key}, content_type={content_type}, size={len(content)}")

    try:
        s3_client = get_s3_client()

        # Upload with public-read ACL
        try:
            s3_client.put_object(
                Bucket=bucket_name,
                Key=s3_key,
                Body=content,
                ContentType=content_type,
                ACL='public-read'
            )
            logger.info(f"S3 upload with ACL successful: {s3_key}")
        except Exception as acl_error:
            # If ACL fails, try without ACL
            logger.warning(f"S3 ACL upload failed ({acl_error}), trying without ACL")
            s3_client.put_object(
                Bucket=bucket_name,
                Key=s3_key,
                Body=content,
                ContentType=content_type
            )
            logger.info(f"S3 upload without ACL successful: {s3_key}")

        # Generate public URL
        aws_region = Configuration.get_value('aws_region', 'ap-south-1')
        url = f"https://{bucket_name}.s3.{aws_region}.amazonaws.com/{s3_key}"

        return url, s3_key, None

    except ValueError as e:
        # Missing AWS credentials
        logger.error(f"S3 configuration error: {e}")
        return None, None, str(e)
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_msg = e.response.get('Error', {}).get('Message', str(e))
        logger.error(f"S3 ClientError: {error_code} - {error_msg}")
        return None, None, f"S3 error ({error_code}): {error_msg}"
    except Exception as e:
        logger.exception(f"Unexpected S3 upload error")
        return None, None, str(e)


def upload_image_to_s3(uploaded_file, folder='images'):
    """
    Upload a Django uploaded file (image) to S3.

    Args:
        uploaded_file: Django UploadedFile object
        folder: S3 folder/prefix for the upload

    Returns:
        tuple: (url, s3_key, error_message)
    """
    import uuid
    import os

    # Validate file type
    allowed_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
    content_type = uploaded_file.content_type

    if content_type not in allowed_types:
        return None, None, f"Invalid file type: {content_type}. Allowed: JPEG, PNG, GIF, WebP"

    # Validate file size (max 5MB)
    max_size = 5 * 1024 * 1024
    if uploaded_file.size > max_size:
        return None, None, "File too large. Maximum size is 5MB"

    # Generate unique filename
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    if not ext:
        ext = '.jpg' if content_type == 'image/jpeg' else '.png'
    unique_filename = f"{uuid.uuid4().hex}{ext}"
    s3_key = f"{folder}/{unique_filename}"

    # Read file content
    content = uploaded_file.read()

    return upload_to_s3(content, s3_key, content_type)
