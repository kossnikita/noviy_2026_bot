from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from api.db_sa import Prize, PrizeWin
from api.schemas import (
    CountOut,
    DeletedOut,
    PrizeCreate,
    PrizeOut,
    PrizeUpdate,
    PrizeWinOut,
    PrizeWinsCreate,
)

router = APIRouter(prefix="/slot", tags=["slot"])


def _normalize_prize_name(name: str) -> str:
    return (name or "").strip()


_PRIZE_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def _validate_prize_name(name: str) -> str:
    v = _normalize_prize_name(name)
    if not v:
        raise HTTPException(status_code=422, detail="name must not be empty")
    if len(v) > 64:
        raise HTTPException(status_code=422, detail="name is too long")
    if not _PRIZE_NAME_RE.fullmatch(v):
        raise HTTPException(
            status_code=422,
            detail="name must match ^[a-z0-9_]+$",
        )
    return v


def _normalize_prize_title(title: str) -> str:
    return (title or "").strip()


def _validate_prize_title(title: str) -> str:
    v = _normalize_prize_title(title)
    if not v:
        raise HTTPException(status_code=422, detail="title must not be empty")
    if len(v) > 128:
        raise HTTPException(status_code=422, detail="title is too long")
    return v


def _prize_to_out(p: Prize) -> PrizeOut:
    return PrizeOut.model_validate(p)


def _win_to_out(win: PrizeWin, prize: Prize) -> PrizeWinOut:
    return PrizeWinOut(
        id=int(win.id),
        user_id=int(win.user_id),
        prize=_prize_to_out(prize),
        won_at=win.won_at,
    )


@router.get("/win", response_model=list[PrizeWinOut])
def list_wins(request: Request, limit: int = 200, offset: int = 0):
    with request.app.state.db.session() as s:
        stmt = (
            select(PrizeWin, Prize)
            .join(Prize, Prize.name == PrizeWin.prize_name)
            .order_by(PrizeWin.won_at.desc(), PrizeWin.id.desc())
            .limit(int(limit))
            .offset(int(offset))
        )
        return [_win_to_out(w, p) for (w, p) in s.execute(stmt).all()]


@router.get("/win/by-user/{user_id}", response_model=list[PrizeWinOut])
def list_wins_by_user(
    user_id: int, request: Request, limit: int = 200, offset: int = 0
):
    with request.app.state.db.session() as s:
        stmt = (
            select(PrizeWin, Prize)
            .join(Prize, Prize.name == PrizeWin.prize_name)
            .where(PrizeWin.user_id == int(user_id))
            .order_by(PrizeWin.won_at.desc(), PrizeWin.id.desc())
            .limit(int(limit))
            .offset(int(offset))
        )
        return [_win_to_out(w, p) for (w, p) in s.execute(stmt).all()]


@router.get("/win/count", response_model=CountOut)
def count_wins(request: Request):
    with request.app.state.db.session() as s:
        n = int(s.scalar(select(func.count()).select_from(PrizeWin)) or 0)
        return CountOut(count=n)


@router.post(
    "/win",
    response_model=list[PrizeWinOut],
    status_code=status.HTTP_201_CREATED,
)
def create_wins(
    payload: PrizeWinsCreate, request: Request
) -> list[PrizeWinOut]:
    if not payload.wins:
        raise HTTPException(status_code=422, detail="wins must not be empty")

    now = datetime.now(UTC)
    created: list[tuple[PrizeWin, Prize]] = []

    with request.app.state.db.session() as s:
        for w in payload.wins:
            prize_name = _validate_prize_name(w.prize_name)

            prize = s.scalar(select(Prize).where(Prize.name == prize_name))
            if prize is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Unknown prize: {prize_name}",
                )

            win = PrizeWin(
                user_id=int(w.user_id),
                prize_name=str(prize.name),
                won_at=(w.won_at or now),
            )
            s.add(win)
            s.flush()
            created.append((win, prize))

        s.commit()
        return [_win_to_out(win, prize) for (win, prize) in created]


@router.get("/prize", response_model=list[PrizeOut])
def list_prizes(request: Request, limit: int = 500, offset: int = 0):
    with request.app.state.db.session() as s:
        stmt = (
            select(Prize)
            .order_by(Prize.id.asc())
            .limit(int(limit))
            .offset(int(offset))
        )
        return [PrizeOut.model_validate(p) for p in s.scalars(stmt).all()]


@router.post(
    "/prize", response_model=PrizeOut, status_code=status.HTTP_201_CREATED
)
def create_prize(payload: PrizeCreate, request: Request) -> PrizeOut:
    name = _validate_prize_name(payload.name)
    title = _validate_prize_title(payload.title)
    with request.app.state.db.session() as s:
        exists = s.scalar(select(Prize).where(Prize.name == name))
        if exists is not None:
            raise HTTPException(status_code=409, detail="Prize already exists")
        p = Prize(name=name, title=title)
        s.add(p)
        s.commit()
        s.refresh(p)
        return PrizeOut.model_validate(p)


@router.get("/prize/{name}", response_model=PrizeOut)
def get_prize(name: str, request: Request) -> PrizeOut:
    key = _validate_prize_name(name)
    with request.app.state.db.session() as s:
        p = s.scalar(select(Prize).where(Prize.name == key))
        if p is None:
            raise HTTPException(status_code=404, detail="Prize not found")
        return PrizeOut.model_validate(p)


@router.put("/prize/{name}", response_model=PrizeOut)
def update_prize(
    name: str, payload: PrizeUpdate, request: Request
) -> PrizeOut:
    key = _validate_prize_name(name)
    title = _validate_prize_title(payload.title)
    with request.app.state.db.session() as s:
        p = s.scalar(select(Prize).where(Prize.name == key))
        if p is None:
            raise HTTPException(status_code=404, detail="Prize not found")
        p.title = title
        s.commit()
        s.refresh(p)
        return PrizeOut.model_validate(p)


@router.delete("/prize/{name}", response_model=DeletedOut)
def delete_prize(name: str, request: Request) -> DeletedOut:
    key = _validate_prize_name(name)
    with request.app.state.db.session() as s:
        p = s.scalar(select(Prize).where(Prize.name == key))
        if p is None:
            return DeletedOut(deleted=0)
        s.delete(p)
        s.commit()
        return DeletedOut(deleted=1)
