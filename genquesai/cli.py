"""CLI hợp nhất — điểm vào duy nhất cho `genquesai`.

    genquesai qa-gen [--total N] [--workers N]   sinh bộ đề QA luật (5 loại,
                                                  xem genquesai.legal_rag.qa_gen)

Sửa 2026-08-26: hệ sinh câu hỏi cũ (`generator`/`evaluate`/`framework`, dựa trên
kNN cosine trên corpus phẳng) đã bị xoá theo yêu cầu người dùng — không còn đủ chỗ
dựa để đoán quan hệ, thay bằng `genquesai.legal_rag.qa_gen` (dùng thẳng quan hệ
pháp lý thật từ Neo4j + nội dung Neo4j/Qdrant). CLI này định tuyến sang hệ mới.
"""
from __future__ import annotations

import sys

_LENH = ("qa-gen",)


def _tro_giup() -> str:
    return (__doc__ or "").strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")   # console Windows mặc định cp1252 -> vỡ chữ Việt
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        print(_tro_giup())
        return 0 if argv else 2

    lenh, con = argv[0], argv[1:]
    if lenh == "qa-gen":
        return _qa_gen(con)

    print(f"lệnh không biết: {lenh!r} — có: {', '.join(_LENH)}\n\n{_tro_giup()}")
    return 2


def _qa_gen(argv: list[str]) -> int:
    import argparse

    from genquesai.legal_rag.qa_gen.run import main as sinh

    ap = argparse.ArgumentParser(prog="genquesai qa-gen")
    ap.add_argument("--total", type=int, default=20, help="tổng số câu hỏi mục tiêu (mặc định 20)")
    ap.add_argument("--workers", type=int, default=8, help="số luồng gọi LLM song song (mặc định 8)")
    a = ap.parse_args(argv)

    sinh(tong_muc_tieu=a.total, workers=a.workers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
