from __future__ import annotations

import random
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.db_sa import Voucher
from api.schemas import VoucherCreate, VoucherOut, VoucherUse

router = APIRouter(prefix="/vouchers", tags=["vouchers"])


def _generate_code() -> str:
    # Keep it a short "number"-like string.
    return f"{random.randint(0, 9999):04d}"


def _issue_voucher_for_user(
    request: Request, user_id: int, issued_by: int | None = None
) -> Voucher:
    with request.app.state.db.session() as s:
        # If the user already has an active voucher, return it.
        existing = s.scalar(
            select(Voucher).where(Voucher.user_id == int(user_id))
        )
        if existing is not None:
            if (
                issued_by is not None
                and getattr(existing, "issued_by", None) is None
            ):
                existing.issued_by = int(issued_by)
                s.commit()
                s.refresh(existing)
            return existing

        # Reuse the oldest available voucher (released after usage).
        available = s.scalar(
            select(Voucher)
            .where(Voucher.user_id.is_(None))
            .order_by(Voucher.used_at.asc().nullsfirst(), Voucher.id.asc())
            .limit(1)
        )
        if available is not None:
            available.user_id = int(user_id)
            if issued_by is not None:
                available.issued_by = int(issued_by)
            s.commit()
            s.refresh(available)
            return available

        # Otherwise, create a new code.
        for _ in range(9999):
            code = _generate_code()
            v = Voucher(
                code=code,
                user_id=int(user_id),
                issued_by=(int(issued_by) if issued_by is not None else None),
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
) -> list[VoucherOut]:
    with request.app.state.db.session() as s:
        stmt = (
            select(Voucher)
            .order_by(Voucher.id.desc())
            .limit(int(limit))
            .offset(int(offset))
        )
        if int(active_only) == 1:
            stmt = stmt.where(Voucher.user_id.is_not(None))
        return [VoucherOut.model_validate(v) for v in s.scalars(stmt).all()]


@router.post(
    "", response_model=VoucherOut, status_code=status.HTTP_201_CREATED
)
def create_voucher(payload: VoucherCreate, request: Request) -> VoucherOut:
    v = _issue_voucher_for_user(
        request,
        int(payload.user_id),
        int(payload.issued_by) if payload.issued_by is not None else None,
    )
    return VoucherOut.model_validate(v)


@router.get("/by-user/{user_id}", response_model=VoucherOut)
def get_or_create_voucher_by_user(
    user_id: int, request: Request
) -> VoucherOut:
    v = _issue_voucher_for_user(request, int(user_id), None)
    return VoucherOut.model_validate(v)


@router.get("/by-code/{code}", response_model=VoucherOut)
def get_voucher_by_code(code: str, request: Request) -> VoucherOut:
    key = (code or "").strip()
    if not key:
        raise HTTPException(status_code=422, detail="code is required")

    with request.app.state.db.session() as s:
        v = s.scalar(select(Voucher).where(Voucher.code == key))
        if v is None:
            raise HTTPException(status_code=404, detail="Voucher not found")
        return VoucherOut.model_validate(v)


@router.post("/used", response_model=VoucherOut)
def mark_voucher_used(payload: VoucherUse, request: Request) -> VoucherOut:
    code = (payload.code or "").strip()
    if not code:
        raise HTTPException(status_code=422, detail="code is required")

    now = datetime.now(UTC)
    with request.app.state.db.session() as s:
        v = s.scalar(select(Voucher).where(Voucher.code == code))
        if v is None:
            raise HTTPException(status_code=404, detail="Voucher not found")

        # Release the code back to the pool so it can be reused.
        v.used_at = now
        v.use_count = int(getattr(v, "use_count", 0) or 0) + 1
        v.user_id = None
        s.commit()
        s.refresh(v)
        return VoucherOut.model_validate(v)
