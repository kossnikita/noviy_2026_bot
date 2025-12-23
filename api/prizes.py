from __future__ import annotations

import random
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from api.db_sa import Prize, PrizeRemaining, PrizeWin, Voucher
from api.schemas import (
    CountOut,
    DeletedOut,
    PrizeCreate,
    PrizeDrawIn,
    PrizeDrawOut,
    PrizeOut,
    PrizeRemainingOut,
    PrizeRemainingUpsert,
    PrizeWinOut,
)

router = APIRouter(prefix="/prizes", tags=["prizes"])


def _weighted_choice(
    items: list[tuple[Prize, PrizeRemaining]],
) -> tuple[Prize, PrizeRemaining]:
    # Probability is proportional to (weight * remaining).
    weights: list[float] = []
    for prize, rem in items:
        w = float(getattr(prize, "weight", 0.0) or 0.0)
        r = int(getattr(rem, "remaining", 0) or 0)
        weights.append(max(0.0, w) * max(0, r))

    total = sum(weights)
    if total <= 0:
        return items[int(random.random() * len(items))]

    pick = random.random() * total
    acc = 0.0
    for pair, w in zip(items, weights):
        acc += w
        if pick <= acc:
            return pair
    return items[-1]


@router.get("", response_model=list[PrizeOut])
def list_prizes(request: Request, limit: int = 200, offset: int = 0):
    with request.app.state.db.session() as s:
        stmt = (
            select(Prize)
            .order_by(Prize.id.asc())
            .limit(int(limit))
            .offset(int(offset))
        )
        return list(s.scalars(stmt))


@router.post("", response_model=PrizeOut, status_code=status.HTTP_201_CREATED)
def create_prize(payload: PrizeCreate, request: Request):
    with request.app.state.db.session() as s:
        p = Prize(
            name=(payload.name or "").strip(),
            friendly_name=(payload.friendly_name or "").strip(),
            weight=float(payload.weight),
        )
        s.add(p)
        try:
            s.commit()
        except Exception:
            s.rollback()
            raise
        s.refresh(p)
        return p


@router.get("/remaining", response_model=list[PrizeRemainingOut])
def list_remaining(request: Request, limit: int = 500, offset: int = 0):
    with request.app.state.db.session() as s:
        stmt = (
            select(PrizeRemaining)
            .order_by(PrizeRemaining.prize_id.asc())
            .limit(int(limit))
            .offset(int(offset))
        )
        return [
            PrizeRemainingOut(
                prize_id=int(r.prize_id), remaining=int(r.remaining)
            )
            for r in s.scalars(stmt)
        ]


@router.get("/remaining/{prize_id}", response_model=PrizeRemainingOut)
def get_remaining(prize_id: int, request: Request):
    with request.app.state.db.session() as s:
        r = s.get(PrizeRemaining, int(prize_id))
        if r is None:
            raise HTTPException(status_code=404, detail="Remaining not found")
        return PrizeRemainingOut(
            prize_id=int(r.prize_id), remaining=int(r.remaining)
        )


@router.put("/remaining/{prize_id}", response_model=PrizeRemainingOut)
def upsert_remaining(
    prize_id: int, payload: PrizeRemainingUpsert, request: Request
):
    if payload.remaining < 0:
        raise HTTPException(status_code=422, detail="remaining must be >= 0")

    with request.app.state.db.session() as s:
        p = s.get(Prize, int(prize_id))
        if p is None:
            raise HTTPException(status_code=404, detail="Prize not found")

        r = s.get(PrizeRemaining, int(prize_id))
        if payload.remaining == 0:
            if r is not None:
                s.delete(r)
                s.commit()
            return PrizeRemainingOut(prize_id=int(prize_id), remaining=0)

        if r is None:
            r = PrizeRemaining(
                prize_id=int(prize_id), remaining=int(payload.remaining)
            )
            s.add(r)
        else:
            r.remaining = int(payload.remaining)
        s.commit()
        return PrizeRemainingOut(
            prize_id=int(r.prize_id), remaining=int(r.remaining)
        )


@router.delete("/remaining/{prize_id}", response_model=DeletedOut)
def delete_remaining(prize_id: int, request: Request):
    with request.app.state.db.session() as s:
        r = s.get(PrizeRemaining, int(prize_id))
        if r is None:
            return DeletedOut(deleted=0)
        s.delete(r)
        s.commit()
        return DeletedOut(deleted=1)


@router.get("/wins", response_model=list[PrizeWinOut])
def list_wins(request: Request, limit: int = 200, offset: int = 0):
    with request.app.state.db.session() as s:
        stmt = (
            select(PrizeWin)
            .order_by(PrizeWin.won_at.desc(), PrizeWin.id.desc())
            .limit(int(limit))
            .offset(int(offset))
        )
        return [PrizeWinOut.model_validate(w) for w in s.scalars(stmt)]


@router.get("/wins/by-user/{user_id}", response_model=list[PrizeWinOut])
def list_wins_by_user(
    user_id: int, request: Request, limit: int = 200, offset: int = 0
):
    with request.app.state.db.session() as s:
        stmt = (
            select(PrizeWin)
            .where(PrizeWin.user_id == int(user_id))
            .order_by(PrizeWin.won_at.desc(), PrizeWin.id.desc())
            .limit(int(limit))
            .offset(int(offset))
        )
        return [PrizeWinOut.model_validate(w) for w in s.scalars(stmt)]


@router.get("/wins/count", response_model=CountOut)
def count_wins(request: Request):
    with request.app.state.db.session() as s:
        n = int(s.scalar(select(func.count()).select_from(PrizeWin)) or 0)
        return CountOut(count=n)


@router.post("/draw", response_model=PrizeDrawOut)
def draw_prize(payload: PrizeDrawIn, request: Request) -> PrizeDrawOut:
    code = (payload.voucher or "").strip()
    if not code:
        raise HTTPException(status_code=422, detail="voucher is required")

    with request.app.state.db.session() as s:
        v_stmt = select(Voucher).where(Voucher.code == code)
        try:
            if (
                getattr(s.bind, "dialect", None)
                and s.bind.dialect.name != "sqlite"
            ):
                v_stmt = v_stmt.with_for_update()
        except Exception:
            pass

        v = s.scalar(v_stmt)
        if v is None:
            raise HTTPException(status_code=404, detail="Voucher not found")
        if v.used_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Voucher already used",
            )

        user_id = int(v.user_id)

        stmt = (
            select(Prize, PrizeRemaining)
            .join(PrizeRemaining, PrizeRemaining.prize_id == Prize.id)
            .where(PrizeRemaining.remaining > 0)
        )

        try:
            if (
                getattr(s.bind, "dialect", None)
                and s.bind.dialect.name != "sqlite"
            ):
                stmt = stmt.with_for_update()
        except Exception:
            pass

        rows = list(s.execute(stmt).all())
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No prizes remaining",
            )

        prize, rem = _weighted_choice(rows)

        rem_row = s.get(PrizeRemaining, int(rem.prize_id))
        if rem_row is None or int(rem_row.remaining) <= 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Prize just ran out, retry",
            )

        if int(rem_row.remaining) <= 1:
            s.delete(rem_row)
        else:
            rem_row.remaining = int(rem_row.remaining) - 1

        win = PrizeWin(user_id=user_id, prize_id=int(prize.id))
        s.add(win)

        v.used_at = datetime.now(UTC)
        s.commit()

        try:
            s.refresh(win)
        except Exception:
            pass

        return PrizeDrawOut(
            user_id=user_id,
            prize=PrizeOut.model_validate(prize),
            won_at=win.won_at,
        )


@router.get("/{prize_id}", response_model=PrizeOut)
def get_prize(prize_id: int, request: Request):
    with request.app.state.db.session() as s:
        p = s.get(Prize, int(prize_id))
        if p is None:
            raise HTTPException(status_code=404, detail="Prize not found")
        return p


@router.put("/{prize_id}", response_model=PrizeOut)
def update_prize(prize_id: int, payload: dict, request: Request):
    # Keep simple: allow partial updates without adding another schema.
    with request.app.state.db.session() as s:
        p = s.get(Prize, int(prize_id))
        if p is None:
            raise HTTPException(status_code=404, detail="Prize not found")

        if "name" in payload and payload["name"] is not None:
            p.name = str(payload["name"]).strip()
        if "friendly_name" in payload and payload["friendly_name"] is not None:
            p.friendly_name = str(payload["friendly_name"]).strip()
        if "weight" in payload and payload["weight"] is not None:
            p.weight = float(payload["weight"])

        s.commit()
        return p


@router.delete("/{prize_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prize(prize_id: int, request: Request):
    with request.app.state.db.session() as s:
        p = s.get(Prize, int(prize_id))
        if p is None:
            return
        s.delete(p)
        s.commit()
        return
