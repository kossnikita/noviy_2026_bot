import hashlib

import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.db_sa import (
    ApiToken,
    Base,
    Prize,
    PrizeRemaining,
    PrizeWin,
    create_db,
)


def _client_with_token() -> TestClient:
    db = create_db(
        database_url="sqlite+pysqlite:///:memory:", db_path=":memory:"
    )
    Base.metadata.create_all(db.engine)

    token = "TEST_TOKEN"
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with db.session() as s:
        s.add(ApiToken(token_hash=token_hash, label="test"))
        s.commit()

    app = create_app(db=db)
    c = TestClient(app)
    c.headers.update({"Authorization": f"Bearer {token}"})
    c._test_db = db  # type: ignore[attr-defined]
    return c


@pytest.mark.asyncio
async def test_prize_draw_decrements_remaining_and_records_win():
    c = _client_with_token()
    db = c._test_db  # type: ignore[attr-defined]

    with db.session() as s:
        p = Prize(name="p1", friendly_name="Prize 1", weight=1.0)
        s.add(p)
        s.commit()
        s.refresh(p)
        s.add(PrizeRemaining(prize_id=int(p.id), remaining=2))
        s.commit()

    vr = c.post("/vouchers", json={"user_id": 123})
    assert vr.status_code == 201
    code = vr.json()["code"]

    r = c.post("/prizes/draw", json={"voucher": code})
    assert r.status_code == 200
    data = r.json()
    assert data["user_id"] == 123
    assert data["prize"]["name"] == "p1"
    pid = int(data["prize"]["id"])

    with db.session() as s:
        rem = s.get(PrizeRemaining, pid)
        assert rem is not None
        assert rem.remaining == 1
        wins = list(s.query(PrizeWin).all())
        assert len(wins) == 1
        assert wins[0].user_id == 123
        assert wins[0].prize_id == pid


def test_prize_draw_last_item_removes_remaining_row():
    c = _client_with_token()
    db = c._test_db  # type: ignore[attr-defined]

    with db.session() as s:
        p = Prize(name="p1", friendly_name="Prize 1", weight=1.0)
        s.add(p)
        s.commit()
        s.refresh(p)
        s.add(PrizeRemaining(prize_id=int(p.id), remaining=1))
        s.commit()

    vr = c.post("/vouchers", json={"user_id": 123})
    assert vr.status_code == 201
    code = vr.json()["code"]

    r = c.post("/prizes/draw", json={"voucher": code})
    assert r.status_code == 200
    pid = int(r.json()["prize"]["id"])

    with db.session() as s:
        rem = s.get(PrizeRemaining, pid)
        assert rem is None


def test_prize_draw_when_no_prizes_left_returns_409():
    c = _client_with_token()

    vr = c.post("/vouchers", json={"user_id": 1})
    assert vr.status_code == 201
    code = vr.json()["code"]

    r = c.post("/prizes/draw", json={"voucher": code})
    assert r.status_code == 409


def test_prize_draw_excludes_prizes_without_remaining_row():
    c = _client_with_token()
    db = c._test_db  # type: ignore[attr-defined]

    with db.session() as s:
        p1 = Prize(name="p1", friendly_name="Prize 1", weight=1.0)
        p2 = Prize(name="p2", friendly_name="Prize 2", weight=999.0)
        s.add_all([p1, p2])
        s.commit()
        s.refresh(p1)
        s.refresh(p2)
        # Only p1 is available; p2 has no remaining row.
        s.add(PrizeRemaining(prize_id=int(p1.id), remaining=1))
        s.commit()

    vr = c.post("/vouchers", json={"user_id": 10})
    assert vr.status_code == 201
    code = vr.json()["code"]

    r = c.post("/prizes/draw", json={"voucher": code})
    assert r.status_code == 200
    data = r.json()
    assert int(data["prize"]["id"]) == int(p1.id)
    assert data["prize"]["name"] == "p1"

    # Now everything is exhausted.
    vr2 = c.post("/vouchers", json={"user_id": 11})
    assert vr2.status_code == 201
    code2 = vr2.json()["code"]
    r2 = c.post("/prizes/draw", json={"voucher": code2})
    assert r2.status_code == 409


def test_prize_draw_excludes_prizes_with_remaining_zero():
    c = _client_with_token()
    db = c._test_db  # type: ignore[attr-defined]

    with db.session() as s:
        p1 = Prize(name="p1", friendly_name="Prize 1", weight=1.0)
        p2 = Prize(name="p2", friendly_name="Prize 2", weight=1.0)
        s.add_all([p1, p2])
        s.commit()
        s.refresh(p1)
        s.refresh(p2)
        # p1 is available, p2 has a remaining row but is exhausted.
        s.add_all(
            [
                PrizeRemaining(prize_id=int(p1.id), remaining=1),
                PrizeRemaining(prize_id=int(p2.id), remaining=0),
            ]
        )
        s.commit()

    vr = c.post("/vouchers", json={"user_id": 20})
    assert vr.status_code == 201
    code = vr.json()["code"]

    r = c.post("/prizes/draw", json={"voucher": code})
    assert r.status_code == 200
    data = r.json()
    assert int(data["prize"]["id"]) == int(p1.id)
    assert data["prize"]["name"] == "p1"


def test_prize_draw_voucher_is_single_use():
    c = _client_with_token()
    db = c._test_db  # type: ignore[attr-defined]

    with db.session() as s:
        p = Prize(name="p1", friendly_name="Prize 1", weight=1.0)
        s.add(p)
        s.commit()
        s.refresh(p)
        s.add(PrizeRemaining(prize_id=int(p.id), remaining=2))
        s.commit()

    vr = c.post("/vouchers", json={"user_id": 42})
    assert vr.status_code == 201
    code = vr.json()["code"]

    r1 = c.post("/prizes/draw", json={"voucher": code})
    assert r1.status_code == 200
    assert int(r1.json()["user_id"]) == 42

    r2 = c.post("/prizes/draw", json={"voucher": code})
    assert r2.status_code == 409
