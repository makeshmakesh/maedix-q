"""
Custom S3 storage backend for blog uploads using Configuration model
"""
import uuid
import os
from django.core.files.storage import Storage
from django.core.files.base import ContentFile
from core.s3_utils import upload_to_s3, delete_from_s3, get_s3_client
from core.models import Configuration


class BlogS3Storage(Storage):
    """
    Custom storage backend for CKEditor uploads.
    Uses AWS credentials from Configuration model.
    """

    def __init__(self, location='blog/uploads'):
        self.location = location

    def _get_s3_url_base(self):
        """Get the base URL for S3 files"""
        bucket_name = Configuration.get_value('aws_s3_bucket', '')
        aws_region = Configuration.get_value('aws_region', 'ap-south-1')
        return f"https://{bucket_name}.s3.{aws_region}.amazonaws.com"

    def _save(self, name, content):
        """Save file to S3"""
        # Generate unique filename to avoid collisions
        ext = os.path.splitext(name)[1].lower()
        unique_name = f"{uuid.uuid4().hex}{ext}"
        s3_key = f"{self.location}/{unique_name}"

        # Determine content type
        content_type = getattr(content, 'content_type', 'application/octet-stream')
        if ext in ['.jpg', '.jpeg']:
            content_type = 'image/jpeg'
        elif ext == '.png':
            content_type = 'image/png'
        elif ext == '.gif':
            content_type = 'image/gif'
        elif ext == '.webp':
            content_type = 'image/webp'

        # Read content
        file_content = content.read()

        # Upload to S3
        url, key, error = upload_to_s3(file_content, s3_key, content_type)

        if error:
            raise Exception(f"S3 upload failed: {error}")

        return s3_key

    def url(self, name):
        """Return the URL for the file"""
        return f"{self._get_s3_url_base()}/{name}"

    def exists(self, name):
        """Check if file exists in S3"""
        try:
            s3_client = get_s3_client()
            bucket_name = Configuration.get_value('aws_s3_bucket', '')
            s3_client.head_object(Bucket=bucket_name, Key=name)
            return True
        except:
            return False

    def delete(self, name):
        """Delete file from S3"""
        delete_from_s3(name)

    def size(self, name):
        """Get file size from S3"""
        try:
            s3_client = get_s3_client()
            bucket_name = Configuration.get_value('aws_s3_bucket', '')
            response = s3_client.head_object(Bucket=bucket_name, Key=name)
            return response.get('ContentLength', 0)
        except:
            return 0
