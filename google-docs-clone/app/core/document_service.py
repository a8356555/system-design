from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from app.models.document import Document, User, DocumentShare, Operation as DBOperation, UserCursor, Comment
from app.core.operational_transform import Operation, OperationalTransform, DocumentState
from typing import List, Optional, Dict, Any
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class DocumentService:
    def __init__(self, db: Session):
        self.db = db
        self.document_states: Dict[int, DocumentState] = {}
    
    def create_document(self, user_id: int, title: str, initial_content: str = "") -> Document:
        """Create a new document"""
        document = Document(
            title=title,
            content=initial_content,
            owner_id=user_id,
            revision=0
        )
        
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        
        # Initialize document state
        self.document_states[document.id] = DocumentState(document.id, initial_content)
        
        logger.info(f"Document '{title}' created by user {user_id}")
        return document
    
    def get_document(self, document_id: int, user_id: int) -> Optional[Document]:
        """Get document if user has access"""
        return self.db.query(Document).filter(
            and_(
                Document.id == document_id,
                Document.is_deleted == False,
                or_(
                    Document.owner_id == user_id,
                    Document.shared_with.any(
                        and_(
                            DocumentShare.user_id == user_id,
                            DocumentShare.permission.in_(['read', 'write', 'admin'])
                        )
                    )
                )
            )
        ).first()
    
    def list_documents(self, user_id: int) -> List[Document]:
        """List all documents accessible to user"""
        return self.db.query(Document).filter(
            and_(
                Document.is_deleted == False,
                or_(
                    Document.owner_id == user_id,
                    Document.shared_with.any(
                        and_(
                            DocumentShare.user_id == user_id,
                            DocumentShare.permission.in_(['read', 'write', 'admin'])
                        )
                    )
                )
            )
        ).order_by(Document.modified_at.desc()).all()
    
    def share_document(self, document_id: int, owner_id: int, target_user_id: int, permission: str) -> DocumentShare:
        """Share document with another user"""
        document = self.db.query(Document).filter(
            and_(Document.id == document_id, Document.owner_id == owner_id)
        ).first()
        
        if not document:
            raise ValueError("Document not found or not owned by user")
        
        if permission not in ['read', 'write', 'admin']:
            raise ValueError("Invalid permission")
        
        # Check if already shared
        existing_share = self.db.query(DocumentShare).filter(
            and_(DocumentShare.document_id == document_id, DocumentShare.user_id == target_user_id)
        ).first()
        
        if existing_share:
            existing_share.permission = permission
            share = existing_share
        else:
            share = DocumentShare(
                document_id=document_id,
                user_id=target_user_id,
                permission=permission
            )
            self.db.add(share)
        
        self.db.commit()
        self.db.refresh(share)
        
        logger.info(f"Document {document.title} shared with user {target_user_id} with {permission} permission")
        return share
    
    def apply_operation(self, document_id: int, user_id: int, operation_data: Dict[str, Any], client_revision: int) -> Dict[str, Any]:
        """Apply an operation to a document using Operational Transform"""
        document = self.get_document(document_id, user_id)
        if not document:
            raise ValueError("Document not found or access denied")
        
        # Check write permission
        if document.owner_id != user_id:
            share = self.db.query(DocumentShare).filter(
                and_(
                    DocumentShare.document_id == document_id,
                    DocumentShare.user_id == user_id,
                    DocumentShare.permission.in_(['write', 'admin'])
                )
            ).first()
            if not share:
                raise ValueError("Write permission required")
        
        # Get or create document state
        if document_id not in self.document_states:
            self.document_states[document_id] = DocumentState(document_id, document.content)
            self.document_states[document_id].revision = document.revision
        
        doc_state = self.document_states[document_id]
        
        # Create operation from data
        operation = Operation.from_dict(operation_data)
        
        # Transform operation against all operations since client's revision
        if client_revision < doc_state.revision:
            operation = doc_state.transform_operation_against_history(operation, client_revision)
        
        # Apply operation to document state
        new_revision = doc_state.apply_operation(operation, user_id)
        
        # Store operation in database
        db_operation = DBOperation(
            document_id=document_id,
            user_id=user_id,
            revision=client_revision,
            operation_type=operation.type,
            position=operation.position,
            content=operation.content,
            length=operation.length
        )
        self.db.add(db_operation)
        
        # Update document
        document.content = doc_state.content
        document.revision = new_revision
        document.modified_at = datetime.utcnow()
        
        self.db.commit()
        
        return {
            'success': True,
            'revision': new_revision,
            'operation': operation.to_dict(),
            'content': doc_state.content
        }
    
    def get_operations_since_revision(self, document_id: int, user_id: int, revision: int) -> List[Dict[str, Any]]:
        """Get all operations since a specific revision"""
        document = self.get_document(document_id, user_id)
        if not document:
            raise ValueError("Document not found or access denied")
        
        operations = self.db.query(DBOperation).filter(
            and_(
                DBOperation.document_id == document_id,
                DBOperation.revision >= revision
            )
        ).order_by(DBOperation.created_at).all()
        
        return [
            {
                'type': op.operation_type,
                'position': op.position,
                'content': op.content,
                'length': op.length,
                'user_id': op.user_id,
                'revision': op.revision
            }
            for op in operations
        ]
    
    def update_cursor_position(self, document_id: int, user_id: int, position: int, 
                             selection_start: Optional[int] = None, selection_end: Optional[int] = None):
        """Update user's cursor position in document"""
        cursor = self.db.query(UserCursor).filter(
            and_(UserCursor.document_id == document_id, UserCursor.user_id == user_id)
        ).first()
        
        if cursor:
            cursor.position = position
            cursor.selection_start = selection_start
            cursor.selection_end = selection_end
            cursor.updated_at = datetime.utcnow()
        else:
            cursor = UserCursor(
                document_id=document_id,
                user_id=user_id,
                position=position,
                selection_start=selection_start,
                selection_end=selection_end
            )
            self.db.add(cursor)
        
        self.db.commit()
        return cursor
    
    def get_active_cursors(self, document_id: int, user_id: int) -> List[Dict[str, Any]]:
        """Get all active cursor positions for a document (excluding current user)"""
        cursors = self.db.query(UserCursor, User).join(User).filter(
            and_(
                UserCursor.document_id == document_id,
                UserCursor.user_id != user_id
            )
        ).all()
        
        return [
            {
                'user_id': cursor.user_id,
                'username': user.username,
                'position': cursor.position,
                'selection_start': cursor.selection_start,
                'selection_end': cursor.selection_end,
                'updated_at': cursor.updated_at.isoformat()
            }
            for cursor, user in cursors
        ]
    
    def add_comment(self, document_id: int, user_id: int, content: str, 
                   position_start: int, position_end: int, parent_id: Optional[int] = None) -> Comment:
        """Add a comment to a document"""
        document = self.get_document(document_id, user_id)
        if not document:
            raise ValueError("Document not found or access denied")
        
        comment = Comment(
            document_id=document_id,
            user_id=user_id,
            content=content,
            position_start=position_start,
            position_end=position_end,
            parent_id=parent_id
        )
        
        self.db.add(comment)
        self.db.commit()
        self.db.refresh(comment)
        
        return comment
    
    def get_comments(self, document_id: int, user_id: int) -> List[Dict[str, Any]]:
        """Get all comments for a document"""
        document = self.get_document(document_id, user_id)
        if not document:
            raise ValueError("Document not found or access denied")
        
        comments = self.db.query(Comment, User).join(User).filter(
            Comment.document_id == document_id
        ).order_by(Comment.created_at).all()
        
        return [
            {
                'id': comment.id,
                'content': comment.content,
                'position_start': comment.position_start,
                'position_end': comment.position_end,
                'user_id': comment.user_id,
                'username': user.username,
                'created_at': comment.created_at.isoformat(),
                'is_resolved': comment.is_resolved,
                'parent_id': comment.parent_id
            }
            for comment, user in comments
        ]