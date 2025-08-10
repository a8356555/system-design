from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import json
from app.core.document_service import DocumentService
from app.websocket.collaboration import collaboration_manager, handle_websocket_message
from app.auth.auth import verify_token
from app.models.document import Document

router = APIRouter(prefix="/api/documents", tags=["documents"])

class DocumentResponse(BaseModel):
    id: int
    title: str
    content: str
    owner_id: int
    created_at: str
    modified_at: str
    revision: int

class DocumentCreate(BaseModel):
    title: str
    content: str = ""

class DocumentShare(BaseModel):
    target_user_id: int
    permission: str  # 'read', 'write', 'admin'

class OperationRequest(BaseModel):
    operation: Dict[str, Any]
    revision: int

class CommentCreate(BaseModel):
    content: str
    position_start: int
    position_end: int
    parent_id: Optional[int] = None

# Dependency to get current user
def get_current_user(token: str = Depends()) -> dict:
    user_data = verify_token(token)
    if not user_data:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user_data

# Dependency to get database session
def get_db() -> Session:
    # This should be implemented based on your database setup
    pass

# Dependency to get document service
def get_document_service(db: Session = Depends(get_db)) -> DocumentService:
    return DocumentService(db)

@router.post("/", response_model=DocumentResponse)
async def create_document(
    doc_create: DocumentCreate,
    current_user: dict = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """Create a new document"""
    try:
        document = document_service.create_document(
            user_id=current_user["user_id"],
            title=doc_create.title,
            initial_content=doc_create.content
        )
        
        return DocumentResponse(
            id=document.id,
            title=document.title,
            content=document.content,
            owner_id=document.owner_id,
            created_at=document.created_at.isoformat(),
            modified_at=document.modified_at.isoformat(),
            revision=document.revision
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/", response_model=List[DocumentResponse])
async def list_documents(
    current_user: dict = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """List all documents accessible to the user"""
    documents = document_service.list_documents(current_user["user_id"])
    
    return [
        DocumentResponse(
            id=doc.id,
            title=doc.title,
            content=doc.content,
            owner_id=doc.owner_id,
            created_at=doc.created_at.isoformat(),
            modified_at=doc.modified_at.isoformat(),
            revision=doc.revision
        )
        for doc in documents
    ]

@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: int,
    current_user: dict = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """Get a specific document"""
    document = document_service.get_document(document_id, current_user["user_id"])
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return DocumentResponse(
        id=document.id,
        title=document.title,
        content=document.content,
        owner_id=document.owner_id,
        created_at=document.created_at.isoformat(),
        modified_at=document.modified_at.isoformat(),
        revision=document.revision
    )

@router.post("/{document_id}/share")
async def share_document(
    document_id: int,
    share_data: DocumentShare,
    current_user: dict = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """Share a document with another user"""
    try:
        share = document_service.share_document(
            document_id=document_id,
            owner_id=current_user["user_id"],
            target_user_id=share_data.target_user_id,
            permission=share_data.permission
        )
        return {"message": "Document shared successfully", "share_id": share.id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{document_id}/operations")
async def apply_operation(
    document_id: int,
    operation_request: OperationRequest,
    current_user: dict = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """Apply an operation to a document (for non-WebSocket clients)"""
    try:
        result = document_service.apply_operation(
            document_id=document_id,
            user_id=current_user["user_id"],
            operation_data=operation_request.operation,
            client_revision=operation_request.revision
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{document_id}/operations")
async def get_operations_since_revision(
    document_id: int,
    revision: int = 0,
    current_user: dict = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """Get operations since a specific revision"""
    try:
        operations = document_service.get_operations_since_revision(
            document_id, current_user["user_id"], revision
        )
        return {"operations": operations}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{document_id}/cursors")
async def get_active_cursors(
    document_id: int,
    current_user: dict = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """Get active cursor positions for a document"""
    try:
        cursors = document_service.get_active_cursors(document_id, current_user["user_id"])
        return {"cursors": cursors}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/{document_id}/comments")
async def add_comment(
    document_id: int,
    comment_data: CommentCreate,
    current_user: dict = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """Add a comment to a document"""
    try:
        comment = document_service.add_comment(
            document_id=document_id,
            user_id=current_user["user_id"],
            content=comment_data.content,
            position_start=comment_data.position_start,
            position_end=comment_data.position_end,
            parent_id=comment_data.parent_id
        )
        return {"message": "Comment added successfully", "comment_id": comment.id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{document_id}/comments")
async def get_comments(
    document_id: int,
    current_user: dict = Depends(get_current_user),
    document_service: DocumentService = Depends(get_document_service)
):
    """Get all comments for a document"""
    try:
        comments = document_service.get_comments(document_id, current_user["user_id"])
        return {"comments": comments}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.websocket("/{document_id}/collaborate")
async def collaborate_websocket(
    websocket: WebSocket,
    document_id: int,
    token: str,
    db: Session = Depends(get_db)
):
    """WebSocket endpoint for real-time collaboration"""
    # Verify token
    user_data = verify_token(token)
    if not user_data:
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    user_id = user_data["user_id"]
    username = user_data["username"]
    
    # Verify document access
    document_service = DocumentService(db)
    document = document_service.get_document(document_id, user_id)
    if not document:
        await websocket.close(code=4004, reason="Document not found or access denied")
        return
    
    # Connect to collaboration session
    await collaboration_manager.connect(websocket, document_id, user_id, username)
    
    try:
        while True:
            # Receive message
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Handle message
            await handle_websocket_message(websocket, message, document_service, db)
    
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        await collaboration_manager.disconnect(websocket)