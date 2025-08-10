from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    documents = relationship("Document", back_populates="owner")
    shared_documents = relationship("DocumentShare", back_populates="user")
    operations = relationship("Operation", back_populates="user")
    cursors = relationship("UserCursor", back_populates="user")

class Document(Base):
    __tablename__ = "documents"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    content = Column(Text, default="")
    owner_id = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    modified_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted = Column(Boolean, default=False)
    version = Column(Integer, default=1)
    
    # Operational Transform state
    revision = Column(Integer, default=0)
    
    owner = relationship("User", back_populates="documents")
    shared_with = relationship("DocumentShare", back_populates="document")
    operations = relationship("Operation", back_populates="document")
    cursors = relationship("UserCursor", back_populates="document")

class DocumentShare(Base):
    __tablename__ = "document_shares"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    permission = Column(String)  # 'read', 'write', 'admin'
    shared_at = Column(DateTime, default=datetime.utcnow)
    
    document = relationship("Document", back_populates="shared_with")
    user = relationship("User", back_populates="shared_documents")

class Operation(Base):
    """Stores operations for Operational Transform"""
    __tablename__ = "operations"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    revision = Column(Integer)  # Document revision when operation was created
    operation_type = Column(String)  # 'insert', 'delete', 'retain'
    position = Column(Integer)
    content = Column(Text, nullable=True)  # For insert operations
    length = Column(Integer, nullable=True)  # For delete/retain operations
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Store operation metadata
    metadata = Column(JSON, default={})
    
    document = relationship("Document", back_populates="operations")
    user = relationship("User", back_populates="operations")

class UserCursor(Base):
    """Stores user cursor positions for real-time collaboration"""
    __tablename__ = "user_cursors"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    position = Column(Integer)
    selection_start = Column(Integer, nullable=True)
    selection_end = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    document = relationship("Document", back_populates="cursors")
    user = relationship("User", back_populates="cursors")

class Comment(Base):
    __tablename__ = "comments"
    
    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"))
    user_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text)
    position_start = Column(Integer)
    position_end = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_resolved = Column(Boolean, default=False)
    
    # Parent comment for replies
    parent_id = Column(Integer, ForeignKey("comments.id"), nullable=True)
    replies = relationship("Comment", remote_side=[id])