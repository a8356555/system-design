from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, BigInteger
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    storage_quota = Column(BigInteger, default=15*1024*1024*1024)  # 15GB default
    storage_used = Column(BigInteger, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    files = relationship("File", back_populates="owner")
    shared_files = relationship("FileShare", back_populates="user")

class File(Base):
    __tablename__ = "files"
    
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, index=True)
    original_filename = Column(String)
    file_path = Column(String)  # S3/MinIO path
    file_size = Column(BigInteger)
    mime_type = Column(String)
    checksum = Column(String)
    is_folder = Column(Boolean, default=False)
    parent_folder_id = Column(Integer, ForeignKey("files.id"), nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    modified_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    
    owner = relationship("User", back_populates="files")
    parent_folder = relationship("File", remote_side=[id])
    shared_with = relationship("FileShare", back_populates="file")
    versions = relationship("FileVersion", back_populates="file")

class FileVersion(Base):
    __tablename__ = "file_versions"
    
    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("files.id"))
    version_number = Column(Integer)
    file_path = Column(String)
    file_size = Column(BigInteger)
    checksum = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    file = relationship("File", back_populates="versions")

class FileShare(Base):
    __tablename__ = "file_shares"
    
    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("files.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    permission = Column(String)  # 'read', 'write', 'admin'
    shared_at = Column(DateTime, default=datetime.utcnow)
    
    file = relationship("File", back_populates="shared_with")
    user = relationship("User", back_populates="shared_files")