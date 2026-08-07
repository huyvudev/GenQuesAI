"""CLI framework: xuất corpus ra JSONL, và soi năng lực của một corpus.

    python -m framework.cli xuat  --ra out/corpus --gioi-han 2000
    python -m framework.cli soi   out/corpus
    python -m framework.cli soi   --neo4j
"""
from __future__ import annotations

import argparse
import sys

from generator.common import open_neo4j, setup_stdout
from .capabilities import danh_gia, in_bao_cao, kiem_chat_luong
from .jsonl_loader import JsonlLoader, JsonlWriter
from .neo4j_loader import Neo4jLoader
from .schema import nap


def xuat(ra: str, gioi_han: int | None) -> int:
    neo = open_neo4j()
    try:
        ld = Neo4jLoader(neo, gioi_han_norm=gioi_han)
        with JsonlWriter(ra) as w:
            w.meta(ld.meta())
            print(f"xuất -> {ra}" + (f"  (mẫu {gioi_han:,} văn bản)" if gioi_han else ""))
            for ten, it in (("norms.jsonl", ld.norms()),
                            ("components.jsonl", ld.components()),
                            ("expressions.jsonl", ld.expressions()),
                            ("quan_he.jsonl", ld.quan_he()),
                            ("chuyen_tiep.jsonl", ld.chuyen_tiep())):
                for x in it:
                    w.ghi(ten, x)
                print(f"  {ten:22} {w.dem.get(ten, 0):>9,}")
    finally:
        neo.close()
    return 0


def soi(nguon: str | None, dung_neo4j: bool) -> int:
    if dung_neo4j:
        neo = open_neo4j()
        try:
            c = nap(Neo4jLoader(neo))
        finally:
            neo.close()
    else:
        c = nap(JsonlLoader(nguon))
    in_bao_cao(c, danh_gia(c))
    canh = kiem_chat_luong(c)
    if canh:
        print("\n  Chất lượng dữ liệu — mỗi mục là một lỗi ĐÃ GẶP THẬT:")
        for x in canh:
            print(f"   ·  {x}")
    return 0


def main() -> int:
    setup_stdout()
    ap = argparse.ArgumentParser(prog="framework")
    sub = ap.add_subparsers(dest="lenh", required=True)
    p = sub.add_parser("xuat", help="Neo4j -> JSONL")
    p.add_argument("--ra", default="out/corpus")
    p.add_argument("--gioi-han", type=int, default=None, help="số văn bản (lấy mẫu)")
    s = sub.add_parser("soi", help="báo cáo năng lực corpus")
    s.add_argument("nguon", nargs="?", default="out/corpus")
    s.add_argument("--neo4j", action="store_true")
    a = ap.parse_args()
    return xuat(a.ra, a.gioi_han) if a.lenh == "xuat" else soi(a.nguon, a.neo4j)


if __name__ == "__main__":
    sys.exit(main())
