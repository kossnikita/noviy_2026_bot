from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from api.db_sa import Photo
from api.schemas import PhotoCreate, PhotoOut

router = APIRouter(prefix="/photos", tags=["photos"])


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
