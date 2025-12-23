import hashlib
import json
from pathlib import Path

from api.app import create_app


def _fingerprint(obj: object) -> str:
    # Stable fingerprint independent of key order/whitespace.
    payload = json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_openapi_json_matches_app_schema(db):
    app = create_app(db=db)
    generated = app.openapi()

    repo_root = Path(__file__).resolve().parents[1]
    openapi_path = repo_root / "openapi.json"
    saved = json.loads(openapi_path.read_text(encoding="utf-8"))

    saved_fp = _fingerprint(saved)
    gen_fp = _fingerprint(generated)

    assert saved_fp == gen_fp, (
        "openapi.json is out of date. "
        "Regenerate it with: "
        "python scripts/export_openapi.py --out openapi.json "
        f"(saved={saved_fp}, generated={gen_fp})"
    )
