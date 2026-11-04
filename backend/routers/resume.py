"""
Resume API routes.
Upload / inspect / remove the PDF resume attached to outgoing emails.
"""
import json
import logging
import os
import re
from datetime import datetime

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from config import settings
from schemas import ResumeInfoResponse

logger = logging.getLogger("Resume")

router = APIRouter(prefix="/api/resume", tags=["Resume"])

PDF_MAGIC = b"%PDF-"
CHUNK = 64 * 1024


def _safe_filename(name: str) -> str:
    """Keep the uploaded name for display, minus anything path-like."""
    name = os.path.basename(name or "").strip()
    name = re.sub(r"[^\w.\- ]", "_", name)
    return name[:200] or "resume.pdf"


def read_meta() -> dict:
    """Stored resume metadata, or {} when nothing has been uploaded."""
    try:
        with open(settings.resume_meta_path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _current_info() -> dict:
    exists = os.path.exists(settings.resume_path)
    meta = read_meta() if exists else {}
    return {
        "exists": exists,
        "filename": meta.get("original_filename") if exists else None,
        "size_bytes": (
            meta.get("size_bytes")
            if meta.get("size_bytes") is not None
            else (os.path.getsize(settings.resume_path) if exists else None)
        ),
        "uploaded_at": meta.get("uploaded_at") if exists else None,
        "max_size_mb": settings.max_resume_mb,
    }


@router.get("", response_model=ResumeInfoResponse)
async def get_resume_info():
    """Report whether a resume is stored, and its name/size."""
    return ResumeInfoResponse(**_current_info())


@router.post("/upload", response_model=ResumeInfoResponse)
async def upload_resume(file: UploadFile = File(...)):
    """Replace the stored resume with an uploaded PDF."""
    original = _safe_filename(file.filename)
    if not original.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    limit = settings.max_resume_mb * 1024 * 1024
    # Write to a temp file first so a rejected or half-finished upload can never
    # clobber a working resume.
    tmp_path = settings.resume_path + ".uploading"
    size = 0
    try:
        with open(tmp_path, "wb") as out:
            first = True
            while chunk := await file.read(CHUNK):
                if first:
                    if not chunk.startswith(PDF_MAGIC):
                        raise HTTPException(
                            status_code=400,
                            detail="That file is not a valid PDF (bad file header).",
                        )
                    first = False
                size += len(chunk)
                if size > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Resume is larger than the {settings.max_resume_mb} MB limit.",
                    )
                out.write(chunk)

        if size == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty.")

        os.replace(tmp_path, settings.resume_path)
    except HTTPException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        logger.error(f"Resume upload failed: {e}")
        raise HTTPException(status_code=500, detail=f"Could not save resume: {e}")
    finally:
        await file.close()

    meta = {
        "original_filename": original,
        "size_bytes": size,
        "uploaded_at": datetime.utcnow().isoformat(timespec="seconds"),
    }
    with open(settings.resume_meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    logger.info(f"Resume uploaded: {original} ({size} bytes)")
    return ResumeInfoResponse(**_current_info())


@router.get("/download")
async def download_resume():
    """Download the stored resume, to confirm what will be attached."""
    if not os.path.exists(settings.resume_path):
        raise HTTPException(status_code=404, detail="No resume uploaded yet.")
    return FileResponse(
        settings.resume_path,
        media_type="application/pdf",
        filename=read_meta().get("original_filename", "resume.pdf"),
    )


@router.delete("", response_model=ResumeInfoResponse)
async def delete_resume():
    """Remove the stored resume."""
    if not os.path.exists(settings.resume_path):
        raise HTTPException(status_code=404, detail="No resume uploaded yet.")
    os.remove(settings.resume_path)
    if os.path.exists(settings.resume_meta_path):
        os.remove(settings.resume_meta_path)
    logger.info("Resume deleted")
    return ResumeInfoResponse(**_current_info())
