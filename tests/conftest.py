"""Fixture dùng chung.

Nguyên tắc: test nào THIẾU dữ liệu thì `skip` kèm ĐÚNG câu lệnh để tạo ra dữ liệu đó.
Skip câm là cách chắc chắn nhất để một bộ test golden lặng lẽ ngừng kiểm gì cả.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

GOC = Path(__file__).resolve().parent.parent
BO_DE = GOC / "out" / "eval_set.jsonl"
KY_VONG = GOC / "tests" / "golden" / "ky_vong.jsonl"
FIXTURE = GOC / "tests" / "golden" / "fixture"


def _doc_jsonl(f: Path) -> list[dict]:
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


@pytest.fixture(scope="session")
def goc() -> Path:
    return GOC


@pytest.fixture(scope="session")
def bo_de() -> list[dict]:
    if not BO_DE.exists():
        pytest.skip(f"thiếu {BO_DE} — bộ đề đã freeze phải được version (Mục 9)")
    return _doc_jsonl(BO_DE)


@pytest.fixture(scope="session")
def _ky_vong_tho() -> list[dict]:
    if not KY_VONG.exists():
        pytest.skip(f"thiếu {KY_VONG} — chạy: python -m tests.trich_ky_vong")
    return _doc_jsonl(KY_VONG)


@pytest.fixture(scope="session")
def ky_vong_meta(_ky_vong_tho) -> dict:
    return _ky_vong_tho[0]["_meta"]


@pytest.fixture(scope="session")
def ky_vong(_ky_vong_tho) -> list[dict]:
    return _ky_vong_tho[1:]


@pytest.fixture(scope="session")
def corpus():
    """Corpus fixture — subgraph có đích, phủ đúng các thực thể bộ đề nhắc tới.

    KHÔNG dùng `out/corpus/` cho việc này: đó là mẫu 3.000 văn bản NGẪU NHIÊN, đo
    thật chỉ giao 19/438 văn bản mà bộ đề cần. Replay trên nó sẽ skip ~96% kỳ vọng
    và báo xanh — đúng kiểu xanh vô nghĩa mà bộ test này sinh ra để tránh.
    """
    if not (FIXTURE / "meta.json").exists():
        pytest.skip(
            f"thiếu fixture corpus ở {FIXTURE}.\n"
            "  Cần Neo4j đang chạy, rồi: python -m tests.trich_fixture\n"
            "  (xuất subgraph có đích quanh các thực thể bộ đề nhắc tới)")
    from framework.jsonl_loader import JsonlLoader
    from framework.schema import nap
    return nap(JsonlLoader(FIXTURE))
