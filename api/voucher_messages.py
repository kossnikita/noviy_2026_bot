from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select

from api.db_sa import VoucherMessage
from api.schemas import VoucherMessageCreate, VoucherMessageOut

router = APIRouter(prefix="/slot/voucher-messages", tags=["slot", "voucher"])


@router.post(
    "", response_model=VoucherMessageOut, status_code=status.HTTP_201_CREATED
)
def create_voucher_message(
    payload: VoucherMessageCreate, request: Request
) -> VoucherMessageOut:
    """Create a new voucher message record (when DM is sent to user)"""
    with request.app.state.db.session() as s:
        msg = VoucherMessage(
            user_id=int(payload.user_id),
            voucher_code=str(payload.voucher_code).strip(),
            message_id=int(payload.message_id),
        )
        s.add(msg)
        s.commit()
        s.refresh(msg)
        return VoucherMessageOut.model_validate(msg)


@router.get("", response_model=list[VoucherMessageOut])
def list_voucher_messages(
    request: Request,
    user_id: int | None = None,
    voucher_code: str | None = None,
    active_only: int = 1,
    limit: int = 200,
    offset: int = 0,
) -> list[VoucherMessageOut]:
    """
    List voucher messages.
    Query parameters:
    - user_id: filter by user ID
    - voucher_code: filter by voucher code
    - active_only: if 1, only return records with deleted_at IS NULL (default 1)
    - limit, offset: pagination
    """
    with request.app.state.db.session() as s:
        stmt = select(VoucherMessage).order_by(VoucherMessage.id.desc())

        if int(active_only) == 1:
            stmt = stmt.where(VoucherMessage.deleted_at.is_(None))

        if user_id is not None:
            stmt = stmt.where(VoucherMessage.user_id == int(user_id))

        if voucher_code is not None:
            stmt = stmt.where(
                VoucherMessage.voucher_code == str(voucher_code).strip()
            )

        stmt = stmt.limit(int(limit)).offset(int(offset))
        return [
            VoucherMessageOut.model_validate(v) for v in s.scalars(stmt).all()
        ]


@router.delete("/{message_record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_voucher_message(message_record_id: int, request: Request) -> None:
    """Mark voucher message record as deleted (soft delete)"""
    with request.app.state.db.session() as s:
        msg = s.scalar(
            select(VoucherMessage).where(
                VoucherMessage.id == int(message_record_id)
            )
        )
        if msg is None:
            raise HTTPException(
                status_code=404, detail="Message record not found"
            )

        msg.deleted_at = datetime.now(UTC)
        s.commit()
