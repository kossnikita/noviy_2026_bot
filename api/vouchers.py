from __future__ import annotations

import random
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.db_sa import Voucher
from api.schemas import VoucherCreate, VoucherOut, VoucherUse

router = APIRouter(prefix="/slot/voucher", tags=["slot", "voucher"])


def _generate_code() -> str:
    # Keep it a short "number"-like string.
    return f"{random.randint(0, 9999):04d}"


def _issue_voucher_for_user(
    request: Request,
    user_id: int,
    issued_by: int | None = None,
    total_games: int = 1,
) -> Voucher:
    with request.app.state.db.session() as s:
        # First, try to find an available voucher with remaining games (user_id is NULL and remaining games > 0)
        available_with_games = s.scalar(
            select(Voucher)
            .where(Voucher.user_id.is_(None))
            .where(Voucher.use_count < Voucher.total_games)
            .order_by(Voucher.created_at.asc(), Voucher.id.asc())
            .limit(1)
        )
        if available_with_games is not None:
            available_with_games.user_id = int(user_id)
            if issued_by is not None:
                available_with_games.issued_by = int(issued_by)
            # Reset the voucher for new use
            available_with_games.use_count = 0
            available_with_games.total_games = int(total_games)
            available_with_games.used_at = None
            s.commit()
            s.refresh(available_with_games)
            return available_with_games

        # Second, try to reuse an exhausted voucher (use_count >= total_games)
        exhausted = s.scalar(
            select(Voucher)
            .where(Voucher.use_count >= Voucher.total_games)
            .order_by(Voucher.used_at.asc().nullsfirst(), Voucher.id.asc())
            .limit(1)
        )
        if exhausted is not None:
            exhausted.user_id = int(user_id)
            if issued_by is not None:
                exhausted.issued_by = int(issued_by)
            exhausted.use_count = 0
            exhausted.total_games = int(total_games)
            exhausted.used_at = None
            s.commit()
            s.refresh(exhausted)
            return exhausted

        # Otherwise, create a new code.
        for _ in range(9999):
            code = _generate_code()
            v = Voucher(
                code=code,
                user_id=int(user_id),
                issued_by=(int(issued_by) if issued_by is not None else None),
                use_count=0,
                total_games=int(total_games),
            )
            s.add(v)
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
                continue
            s.refresh(v)
            return v

        raise HTTPException(
            status_code=500,
            detail="Failed to generate unique voucher code",
        )


@router.get("", response_model=list[VoucherOut])
def list_vouchers(
    request: Request,
    limit: int = 200,
    offset: int = 0,
    active_only: int = 0,
    user_id: int | None = None,
    code: str | None = None,
) -> list[VoucherOut]:
    with request.app.state.db.session() as s:
        stmt = (
            select(Voucher)
            .order_by(Voucher.id.desc())
            .limit(int(limit))
            .offset(int(offset))
        )
        if int(active_only) == 1:
            # Only return vouchers with remaining games
            stmt = stmt.where(Voucher.use_count < Voucher.total_games)
        if user_id is not None:
            stmt = stmt.where(Voucher.user_id == int(user_id))
        if code is not None:
            stmt = stmt.where(Voucher.code == code.strip())
        return [VoucherOut.model_validate(v) for v in s.scalars(stmt).all()]


@router.post(
    "", response_model=VoucherOut, status_code=status.HTTP_201_CREATED
)
def create_voucher(payload: VoucherCreate, request: Request) -> VoucherOut:
    v = _issue_voucher_for_user(
        request,
        int(payload.user_id),
        int(payload.issued_by) if payload.issued_by is not None else None,
        int(payload.total_games),
    )
    return VoucherOut.model_validate(v)


@router.put("/{voucher_id}/count", response_model=VoucherOut)
def set_voucher_count(
    voucher_id: int,
    request: Request,
    add: int | None = None,
    decrease: int | None = None,
    set: int | None = None,
) -> VoucherOut:
    """
    Modify the total games count of a voucher.
    Query parameters:
    - add: increment total_games by this amount
    - decrease: decrement total_games by this amount
    - set: set total_games to this exact value
    Returns 404 if voucher not found.
    """
    with request.app.state.db.session() as s:
        v = s.scalar(select(Voucher).where(Voucher.id == int(voucher_id)))
        if v is None:
            raise HTTPException(status_code=404, detail="Voucher not found")

        if add is not None:
            v.total_games += int(add)
        elif decrease is not None:
            v.total_games -= int(decrease)
        elif set is not None:
            v.total_games = int(set)

        s.commit()
        s.refresh(v)
        return VoucherOut.model_validate(v)


@router.put("/{voucher_id}/play", response_model=VoucherOut)
def play_game(voucher_id: int, request: Request) -> VoucherOut:
    """
    Use a game from the voucher. Decrements remaining games by 1.
    Returns 404 if voucher not found or has no remaining games.
    """
    now = datetime.now(UTC)
    with request.app.state.db.session() as s:
        v = s.scalar(select(Voucher).where(Voucher.id == int(voucher_id)))
        if v is None:
            raise HTTPException(status_code=404, detail="Voucher not found")

        # Check if voucher has remaining games
        if v.use_count >= v.total_games:
            raise HTTPException(
                status_code=400, detail="Voucher has no remaining games"
            )

        # Increment use count and update used_at timestamp
        v.use_count += 1
        v.used_at = now
        s.commit()
        s.refresh(v)
        return VoucherOut.model_validate(v)


@router.post("/used", response_model=VoucherOut)
def mark_voucher_used(payload: VoucherUse, request: Request) -> VoucherOut:
    """
    DEPRECATED: Use PUT /{voucher_id}/play instead.
    This endpoint is kept for backwards compatibility.
    """
    code = (payload.code or "").strip()
    if not code:
        raise HTTPException(status_code=422, detail="code is required")

    now = datetime.now(UTC)
    with request.app.state.db.session() as s:
        v = s.scalar(select(Voucher).where(Voucher.code == code))
        if v is None:
            raise HTTPException(status_code=404, detail="Voucher not found")

        # Check if voucher has remaining games
        if v.use_count >= v.total_games:
            raise HTTPException(
                status_code=400, detail="Voucher has no remaining games"
            )

        # Increment use count
        v.use_count += 1
        v.used_at = now
        s.commit()
        s.refresh(v)
        return VoucherOut.model_validate(v)
