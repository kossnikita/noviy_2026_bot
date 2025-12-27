from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select

from api.db_sa import Photo
from api.schemas import PhotoCreate, PhotoOut

router = APIRouter(prefix="/photos", tags=["photos"])


def _photos_dir() -> Path:
    # Must be writable and typically backed by a Docker volume.
    raw = (os.environ.get("PHOTOS_DIR") or "/app/data/img").strip()
    return Path(raw)


def _sanitize_filename(name: str) -> str:
    # Strip any path components and keep it reasonably safe.
    base = Path(name or "").name.strip()
    if not base:
        base = "photo"
    # Keep only a conservative set of characters
    cleaned = []
    for ch in base:
        if ch.isalnum() or ch in {"-", "_", "."}:
            cleaned.append(ch)
        else:
            cleaned.append("_")
    out = "".join(cleaned).strip("._")
    return out or "photo"


@router.post("/upload", response_model=PhotoOut, status_code=status.HTTP_201_CREATED)
def upload_photo(
    request: Request,
    file: UploadFile = File(...),
    added_by: int = Form(...),
) -> PhotoOut:
    photos_dir = _photos_dir()
    try:
        photos_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create photos dir")

    original = file.filename or "photo"
    safe_name = _sanitize_filename(original)
    dst_path = photos_dir / safe_name

    # Idempotency: if we already have this name in DB, do not store duplicates.
    with request.app.state.db.session() as s:
        existing = s.scalar(select(Photo).where(Photo.name == safe_name))
        if existing is not None:
            try:
                file.file.close()
            except Exception:
                pass
            return PhotoOut.model_validate(existing)

    # If the file exists on disk (e.g., left over from a previous run), reuse it.
    if dst_path.exists():
        with request.app.state.db.session() as s:
            row = Photo(
                name=dst_path.name,
                url=f"/img/{dst_path.name}",
                added_by=int(added_by),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            try:
                file.file.close()
            except Exception:
                pass
            return PhotoOut.model_validate(row)

    try:
        assert file.file is not None
        with open(dst_path, "wb") as out:
            shutil.copyfileobj(file.file, out)
    except Exception:
        try:
            if dst_path.exists():
                dst_path.unlink()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    # Record in DB
    try:
        with request.app.state.db.session() as s:
            row = Photo(
                name=dst_path.name,
                url=f"/img/{dst_path.name}",
                added_by=int(added_by),
            )
            s.add(row)
            s.commit()
            s.refresh(row)
            return PhotoOut.model_validate(row)
    except Exception:
        try:
            if dst_path.exists():
                dst_path.unlink()
        except Exception:
            pass
        raise


@router.post("", response_model=PhotoOut, status_code=status.HTTP_201_CREATED)
def create_photo(payload: PhotoCreate, request: Request) -> PhotoOut:
    name = (payload.name or "").strip()
    url = (payload.url or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    if not url:
        raise HTTPException(status_code=422, detail="url is required")

    with request.app.state.db.session() as s:
        row = Photo(name=name, url=url, added_by=int(payload.added_by))
        s.add(row)
        s.commit()
        s.refresh(row)
        return PhotoOut.model_validate(row)


@router.get("", response_model=list[PhotoOut])
def list_photos(
    request: Request,
    limit: int = 100,
    offset: int = 0,
    after_id: int | None = None,
):
    with request.app.state.db.session() as s:
        stmt = select(Photo)
        if after_id is not None:
            stmt = stmt.where(Photo.id > int(after_id))
            stmt = stmt.order_by(Photo.id.asc())
        else:
            stmt = stmt.order_by(Photo.id.desc())

        stmt = stmt.limit(int(limit)).offset(
            int(offset) if after_id is None else 0
        )
        return [PhotoOut.model_validate(p) for p in s.scalars(stmt)]


@router.get("/{photo_id}", response_model=PhotoOut)
def get_photo(photo_id: int, request: Request) -> PhotoOut:
    with request.app.state.db.session() as s:
        row = s.get(Photo, int(photo_id))
        if row is None:
            raise HTTPException(status_code=404, detail="Photo not found")
        return PhotoOut.model_validate(row)
