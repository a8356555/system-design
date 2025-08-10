from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FastAPIFile, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import List, Optional
import io
from app.core.file_service import FileService
from app.storage.s3_storage import S3StorageService
from app.auth.auth import verify_token
from app.models.file import File, User
from pydantic import BaseModel

router = APIRouter(prefix="/api/files", tags=["files"])

class FileResponse(BaseModel):
    id: int
    filename: str
    file_size: int
    mime_type: Optional[str]
    is_folder: bool
    created_at: str
    modified_at: str
    owner_id: int

class ShareRequest(BaseModel):
    target_user_id: int
    permission: str

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

# Dependency to get file service
def get_file_service(db: Session = Depends(get_db)) -> FileService:
    # This should be implemented based on your storage setup
    pass

@router.post("/upload", response_model=FileResponse)
async def upload_file(
    file: UploadFile = FastAPIFile(...),
    parent_folder_id: Optional[int] = Form(None),
    current_user: dict = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    try:
        file_obj = io.BytesIO(await file.read())
        db_file = file_service.upload_file(
            user_id=current_user["user_id"],
            file_obj=file_obj,
            filename=file.filename,
            parent_folder_id=parent_folder_id,
            content_type=file.content_type
        )
        
        return FileResponse(
            id=db_file.id,
            filename=db_file.filename,
            file_size=db_file.file_size,
            mime_type=db_file.mime_type,
            is_folder=db_file.is_folder,
            created_at=db_file.created_at.isoformat(),
            modified_at=db_file.modified_at.isoformat(),
            owner_id=db_file.owner_id
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/folder", response_model=FileResponse)
async def create_folder(
    folder_name: str = Form(...),
    parent_folder_id: Optional[int] = Form(None),
    current_user: dict = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    try:
        folder = file_service.create_folder(
            user_id=current_user["user_id"],
            folder_name=folder_name,
            parent_folder_id=parent_folder_id
        )
        
        return FileResponse(
            id=folder.id,
            filename=folder.filename,
            file_size=folder.file_size,
            mime_type=folder.mime_type,
            is_folder=folder.is_folder,
            created_at=folder.created_at.isoformat(),
            modified_at=folder.modified_at.isoformat(),
            owner_id=folder.owner_id
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/list", response_model=List[FileResponse])
async def list_files(
    parent_folder_id: Optional[int] = None,
    current_user: dict = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    files = file_service.list_files(
        user_id=current_user["user_id"],
        parent_folder_id=parent_folder_id
    )
    
    return [
        FileResponse(
            id=file.id,
            filename=file.filename,
            file_size=file.file_size,
            mime_type=file.mime_type,
            is_folder=file.is_folder,
            created_at=file.created_at.isoformat(),
            modified_at=file.modified_at.isoformat(),
            owner_id=file.owner_id
        )
        for file in files
    ]

@router.get("/download/{file_id}")
async def download_file(
    file_id: int,
    current_user: dict = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    try:
        file_stream, db_file = file_service.download_file(file_id, current_user["user_id"])
        
        def iter_file():
            while True:
                chunk = file_stream.read(8192)
                if not chunk:
                    break
                yield chunk
            file_stream.close()
        
        return StreamingResponse(
            iter_file(),
            media_type=db_file.mime_type or "application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={db_file.filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete("/{file_id}")
async def delete_file(
    file_id: int,
    current_user: dict = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    success = file_service.delete_file(file_id, current_user["user_id"])
    if not success:
        raise HTTPException(status_code=404, detail="File not found or access denied")
    return {"message": "File deleted successfully"}

@router.post("/{file_id}/share")
async def share_file(
    file_id: int,
    share_request: ShareRequest,
    current_user: dict = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    try:
        share = file_service.share_file(
            file_id=file_id,
            owner_id=current_user["user_id"],
            target_user_id=share_request.target_user_id,
            permission=share_request.permission
        )
        return {"message": "File shared successfully", "share_id": share.id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/shared", response_model=List[FileResponse])
async def get_shared_files(
    current_user: dict = Depends(get_current_user),
    file_service: FileService = Depends(get_file_service)
):
    files = file_service.get_shared_files(current_user["user_id"])
    
    return [
        FileResponse(
            id=file.id,
            filename=file.filename,
            file_size=file.file_size,
            mime_type=file.mime_type,
            is_folder=file.is_folder,
            created_at=file.created_at.isoformat(),
            modified_at=file.modified_at.isoformat(),
            owner_id=file.owner_id
        )
        for file in files
    ]