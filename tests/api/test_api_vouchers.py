import hashlib

from fastapi.testclient import TestClient

from api.app import create_app
from api.db_sa import ApiToken, Base, create_db


def _client() -> TestClient:
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
    return c


def test_create_voucher_generates_unique_code():
    c = _client()

    r1 = c.get("/vouchers/by-user/1")
    assert r1.status_code == 200
    v1 = r1.json()
    assert int(v1["user_id"]) == 1
    assert isinstance(v1["code"], str)
    assert len(v1["code"]) >= 1

    # Same user should get the same active voucher.
    r2 = c.get("/vouchers/by-user/1")
    assert r2.status_code == 200
    v2 = r2.json()
    assert v2["code"] == v1["code"]

    # Mark as used -> becomes available for reuse.
    r3 = c.post("/vouchers/used", json={"code": v1["code"]})
    assert r3.status_code == 200
    used = r3.json()
    assert used["code"] == v1["code"]
    assert used["user_id"] is None

    # Next user should reuse the released code.
    r4 = c.get("/vouchers/by-user/2")
    assert r4.status_code == 200
    v4 = r4.json()
    assert v4["code"] == v1["code"]
    assert int(v4["user_id"]) == 2
