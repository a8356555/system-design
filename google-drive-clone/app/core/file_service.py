from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.models.file import File, User, FileVersion, FileShare
from app.storage.s3_storage import S3StorageService
from typing import List, Optional, BinaryIO
import uuid
import os
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class FileService:
    def __init__(self, db: Session, storage_service: S3StorageService):
        self.db = db
        self.storage = storage_service
    
    def upload_file(self, user_id: int, file_obj: BinaryIO, filename: str, 
                   parent_folder_id: Optional[int] = None, content_type: str = None) -> File:
        # Check user storage quota
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise ValueError("User not found")
        
        # Get file size
        file_obj.seek(0, 2)
        file_size = file_obj.tell()
        file_obj.seek(0)
        
        if user.storage_used + file_size > user.storage_quota:
            raise ValueError("Storage quota exceeded")
        
        # Generate unique filename for storage
        unique_filename = f"{uuid.uuid4()}_{filename}"
        
        # Upload to storage
        object_name, checksum, actual_size = self.storage.upload_file(
            file_obj, unique_filename, content_type
        )
        
        # Create file record
        db_file = File(
            filename=filename,
            original_filename=filename,
            file_path=object_name,
            file_size=actual_size,
            mime_type=content_type,
            checksum=checksum,
            parent_folder_id=parent_folder_id,
            owner_id=user_id,
            is_folder=False
        )
        
        self.db.add(db_file)
        
        # Update user storage usage
        user.storage_used += actual_size
        
        # Create initial version
        version = FileVersion(
            file=db_file,
            version_number=1,
            file_path=object_name,
            file_size=actual_size,
            checksum=checksum
        )
        self.db.add(version)
        
        self.db.commit()
        self.db.refresh(db_file)
        
        logger.info(f"File {filename} uploaded by user {user_id}")
        return db_file
    
    def create_folder(self, user_id: int, folder_name: str, 
                     parent_folder_id: Optional[int] = None) -> File:
        folder = File(
            filename=folder_name,
            original_filename=folder_name,
            file_path="",
            file_size=0,
            mime_type="application/vnd.google-apps.folder",
            is_folder=True,
            parent_folder_id=parent_folder_id,
            owner_id=user_id
        )
        
        self.db.add(folder)
        self.db.commit()
        self.db.refresh(folder)
        
        logger.info(f"Folder {folder_name} created by user {user_id}")
        return folder
    
    def get_file(self, file_id: int, user_id: int) -> Optional[File]:
        return self.db.query(File).filter(
            and_(
                File.id == file_id,
                File.is_deleted == False,
                or_(
                    File.owner_id == user_id,
                    File.shared_with.any(
                        and_(
                            FileShare.user_id == user_id,
                            FileShare.permission.in_(['read', 'write', 'admin'])
                        )
                    )
                )
            )
        ).first()
    
    def list_files(self, user_id: int, parent_folder_id: Optional[int] = None) -> List[File]:
        query = self.db.query(File).filter(
            and_(
                File.is_deleted == False,
                File.parent_folder_id == parent_folder_id,
                or_(
                    File.owner_id == user_id,
                    File.shared_with.any(
                        and_(
                            FileShare.user_id == user_id,
                            FileShare.permission.in_(['read', 'write', 'admin'])
                        )
                    )
                )
            )
        ).order_by(File.is_folder.desc(), File.filename)
        
        return query.all()
    
    def download_file(self, file_id: int, user_id: int) -> tuple[BinaryIO, File]:
        file = self.get_file(file_id, user_id)
        if not file or file.is_folder:
            raise ValueError("File not found or is a folder")
        
        file_stream = self.storage.download_file(file.file_path)
        return file_stream, file
    
    def delete_file(self, file_id: int, user_id: int) -> bool:
        file = self.get_file(file_id, user_id)
        if not file:
            return False
        
        # Check if user has admin permission
        if file.owner_id != user_id:
            share = self.db.query(FileShare).filter(
                and_(
                    FileShare.file_id == file_id,
                    FileShare.user_id == user_id,
                    FileShare.permission == 'admin'
                )
            ).first()
            if not share:
                return False
        
        # Soft delete
        file.is_deleted = True
        
        # Update storage usage if owner
        if file.owner_id == user_id and not file.is_folder:
            user = self.db.query(User).filter(User.id == user_id).first()
            if user:
                user.storage_used -= file.file_size
        
        self.db.commit()
        
        logger.info(f"File {file.filename} deleted by user {user_id}")
        return True
    
    def share_file(self, file_id: int, owner_id: int, target_user_id: int, 
                  permission: str) -> FileShare:
        file = self.db.query(File).filter(
            and_(File.id == file_id, File.owner_id == owner_id)
        ).first()
        
        if not file:
            raise ValueError("File not found or not owned by user")
        
        if permission not in ['read', 'write', 'admin']:
            raise ValueError("Invalid permission")
        
        # Check if already shared
        existing_share = self.db.query(FileShare).filter(
            and_(FileShare.file_id == file_id, FileShare.user_id == target_user_id)
        ).first()
        
        if existing_share:
            existing_share.permission = permission
            share = existing_share
        else:
            share = FileShare(
                file_id=file_id,
                user_id=target_user_id,
                permission=permission
            )
            self.db.add(share)
        
        self.db.commit()
        self.db.refresh(share)
        
        logger.info(f"File {file.filename} shared with user {target_user_id} with {permission} permission")
        return share
    
    def get_shared_files(self, user_id: int) -> List[File]:
        shares = self.db.query(FileShare).filter(
            FileShare.user_id == user_id
        ).all()
        
        file_ids = [share.file_id for share in shares]
        files = self.db.query(File).filter(
            and_(File.id.in_(file_ids), File.is_deleted == False)
        ).all()
        
        return files