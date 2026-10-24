from fastapi import APIRouter, Depends, HTTPException

from app import direct_uploads
from app.schemas import DirectUploadCompletion, DirectUploadRequest, DirectUploadTarget, EnqueuedJob
from app.security import Principal, require_editor

router = APIRouter(prefix='/documents/uploads', tags=['documents'])


@router.post('/prepare', response_model=DirectUploadTarget)
def prepare(body: DirectUploadRequest, principal: Principal = Depends(require_editor)):
    try:
        return direct_uploads.prepare(body, principal)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post('/complete', response_model=EnqueuedJob, status_code=202)
def complete(body: DirectUploadCompletion, principal: Principal = Depends(require_editor)):
    try:
        return direct_uploads.complete(body.ticket, principal)
    except PermissionError:
        raise HTTPException(403, 'Upload access denied') from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
