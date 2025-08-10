import boto3
from botocore.exceptions import ClientError
from minio import Minio
from minio.error import S3Error
import hashlib
import os
from typing import Optional, BinaryIO
import logging

logger = logging.getLogger(__name__)

class S3StorageService:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket_name: str, secure: bool = True):
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure
        )
        self.bucket_name = bucket_name
        self._ensure_bucket_exists()
    
    def _ensure_bucket_exists(self):
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logger.info(f"Created bucket: {self.bucket_name}")
        except S3Error as e:
            logger.error(f"Error creating bucket: {e}")
            raise
    
    def upload_file(self, file_obj: BinaryIO, object_name: str, content_type: str = None) -> tuple[str, str, int]:
        try:
            # Calculate file size and checksum
            file_obj.seek(0, 2)  # Seek to end
            file_size = file_obj.tell()
            file_obj.seek(0)  # Seek to beginning
            
            # Calculate MD5 checksum
            md5_hash = hashlib.md5()
            chunk_size = 8192
            while chunk := file_obj.read(chunk_size):
                md5_hash.update(chunk)
            checksum = md5_hash.hexdigest()
            file_obj.seek(0)  # Reset for upload
            
            # Upload to MinIO/S3
            self.client.put_object(
                self.bucket_name,
                object_name,
                file_obj,
                length=file_size,
                content_type=content_type
            )
            
            return object_name, checksum, file_size
            
        except S3Error as e:
            logger.error(f"Error uploading file {object_name}: {e}")
            raise
    
    def download_file(self, object_name: str) -> BinaryIO:
        try:
            response = self.client.get_object(self.bucket_name, object_name)
            return response
        except S3Error as e:
            logger.error(f"Error downloading file {object_name}: {e}")
            raise
    
    def delete_file(self, object_name: str) -> bool:
        try:
            self.client.remove_object(self.bucket_name, object_name)
            return True
        except S3Error as e:
            logger.error(f"Error deleting file {object_name}: {e}")
            return False
    
    def get_file_info(self, object_name: str) -> Optional[dict]:
        try:
            stat = self.client.stat_object(self.bucket_name, object_name)
            return {
                'size': stat.size,
                'etag': stat.etag,
                'content_type': stat.content_type,
                'last_modified': stat.last_modified
            }
        except S3Error as e:
            logger.error(f"Error getting file info for {object_name}: {e}")
            return None
    
    def generate_presigned_url(self, object_name: str, expiry_seconds: int = 3600) -> str:
        try:
            from datetime import timedelta
            url = self.client.presigned_get_object(
                self.bucket_name, 
                object_name, 
                expires=timedelta(seconds=expiry_seconds)
            )
            return url
        except S3Error as e:
            logger.error(f"Error generating presigned URL for {object_name}: {e}")
            raise