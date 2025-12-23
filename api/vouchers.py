from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from api.db_sa import Voucher
from api.schemas import VoucherCreate, VoucherOut

router = APIRouter(prefix="/vouchers", tags=["vouchers"])


def _generate_code() -> str:
    # URL-safe, no slashes; 32 hex chars.
    return secrets.token_hex(16)


@router.post(
    "", response_model=VoucherOut, status_code=status.HTTP_201_CREATED
)
def create_voucher(payload: VoucherCreate, request: Request) -> VoucherOut:
    user_id = int(payload.user_id)

    with request.app.state.db.session() as s:
        # Retry a few times on the extremely unlikely chance of a collision.
        for _ in range(10):
            code = _generate_code()
            v = Voucher(code=code, user_id=user_id)
            s.add(v)
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
                continue
            s.refresh(v)
            return VoucherOut.model_validate(v)

        raise HTTPException(
            status_code=500,
            detail="Failed to generate unique voucher code",
        )
