from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from api.db_sa import Prize, PrizeWin
from api.schemas import (
    CountOut,
    PrizeOut,
    PrizeWinOut,
    PrizeWinsCreate,
)

router = APIRouter(prefix="/slot", tags=["slot"])


def _normalize_prize_name(name: str) -> str:
    return (name or "").strip()


def _normalize_prize_friendly_name(name: str | None, fallback: str) -> str:
    v = (name or "").strip()
    return v if v else fallback


def _prize_to_out(p: Prize) -> PrizeOut:
    return PrizeOut.model_validate(p)


def _win_to_out(win: PrizeWin, prize: Prize) -> PrizeWinOut:
    return PrizeWinOut(
        id=int(win.id),
        user_id=int(win.user_id),
        prize=_prize_to_out(prize),
        won_at=win.won_at,
    )


@router.get("/wins", response_model=list[PrizeWinOut])
def list_wins(request: Request, limit: int = 200, offset: int = 0):
    with request.app.state.db.session() as s:
        stmt = (
            select(PrizeWin, Prize)
            .join(Prize, Prize.id == PrizeWin.prize_id)
            .order_by(PrizeWin.won_at.desc(), PrizeWin.id.desc())
            .limit(int(limit))
            .offset(int(offset))
        )
        return [_win_to_out(w, p) for (w, p) in s.execute(stmt).all()]


@router.get("/wins/by-user/{user_id}", response_model=list[PrizeWinOut])
def list_wins_by_user(
    user_id: int, request: Request, limit: int = 200, offset: int = 0
):
    with request.app.state.db.session() as s:
        stmt = (
            select(PrizeWin, Prize)
            .join(Prize, Prize.id == PrizeWin.prize_id)
            .where(PrizeWin.user_id == int(user_id))
            .order_by(PrizeWin.won_at.desc(), PrizeWin.id.desc())
            .limit(int(limit))
            .offset(int(offset))
        )
        return [_win_to_out(w, p) for (w, p) in s.execute(stmt).all()]


@router.get("/wins/count", response_model=CountOut)
def count_wins(request: Request):
    with request.app.state.db.session() as s:
        n = int(s.scalar(select(func.count()).select_from(PrizeWin)) or 0)
        return CountOut(count=n)


@router.post(
    "/wins",
    response_model=list[PrizeWinOut],
    status_code=status.HTTP_201_CREATED,
)
def create_wins(payload: PrizeWinsCreate, request: Request) -> list[PrizeWinOut]:
    if not payload.wins:
        raise HTTPException(status_code=422, detail="wins must not be empty")

    now = datetime.now(UTC)
    created: list[tuple[PrizeWin, Prize]] = []

    with request.app.state.db.session() as s:
        for w in payload.wins:
            prize_name = _normalize_prize_name(w.prize_name)
            if not prize_name:
                raise HTTPException(
                    status_code=422, detail="prize_name must not be empty"
                )

            prize = s.scalar(select(Prize).where(Prize.name == prize_name))
            if prize is None:
                prize = Prize(
                    name=prize_name,
                    friendly_name=_normalize_prize_friendly_name(
                        w.prize_friendly_name, prize_name
                    ),
                    # Weight is no longer used by the API; keep column satisfied.
                    weight=0.0,
                )
                s.add(prize)
                s.flush()
            else:
                friendly = _normalize_prize_friendly_name(
                    w.prize_friendly_name, prize.friendly_name
                )
                if friendly and friendly != prize.friendly_name:
                    prize.friendly_name = friendly

            win = PrizeWin(
                user_id=int(w.user_id),
                prize_id=int(prize.id),
                won_at=(w.won_at or now),
            )
            s.add(win)
            s.flush()
            created.append((win, prize))

        s.commit()
        return [_win_to_out(win, prize) for (win, prize) in created]
