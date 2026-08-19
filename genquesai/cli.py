"""CLI hợp nhất — điểm vào duy nhất cho toàn bộ luồng sinh + chấm bộ đề (ROADMAP C).

    genquesai corpus soi [...]      framework.cli soi   — báo cáo năng lực corpus
    genquesai corpus xuat [...]     framework.cli xuat  — Neo4j -> JSONL
    genquesai gen [...]             generator.run_all   — sinh bộ đề (--c4: chạy cổng
                                                           C4 ngay sau khi sinh xong)
    genquesai run [...]             evaluate.score      — chấm hệ được đo
    genquesai report [...]          in lại báo cáo từ file kết quả đã lưu, không chấm lại

Mỗi lệnh con nhận đúng cờ của module gốc — xem `genquesai <lệnh> --help`. File này
CHỈ định tuyến (router mỏng), không chứa logic riêng ngoài `report` (thứ chưa có sẵn
ở đâu khác) — sinh/chấm/soi corpus vẫn nằm nguyên ở `generator`/`evaluate`/`framework`,
tránh trùng một nguồn sự thật.

Vì sao KHÔNG dùng `argparse` subparsers lồng cho `corpus`: `framework.cli` đã tự định
nghĩa hai lệnh con `xuat`/`soi` của riêng nó — khai lại ở đây là hai nguồn sự thật
cho cùng một tập cờ, lệch nhau là chuyện thời gian. Định tuyến bằng cách cắt token đầu
rồi giao thẳng phần argv còn lại cho module gốc tự phân tích.
"""
from __future__ import annotations

import sys

_LENH = ("corpus", "gen", "run", "report")


def _tro_giup() -> str:
    return (__doc__ or "").strip() + "\n"


def main(argv: list[str] | None = None) -> int:
    from generator.common import setup_stdout
    setup_stdout()                      # console Windows mặc định cp1252 -> vỡ chữ Việt
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(_tro_giup())
        return 2
    if argv[0] in ("-h", "--help"):
        print(_tro_giup())
        return 0

    lenh, con = argv[0], argv[1:]
    if lenh == "corpus":
        from framework.cli import main as chay
        return chay(con)
    if lenh == "gen":
        return _gen(con)
    if lenh == "run":
        from evaluate.score import main as chay
        return chay(con)
    if lenh == "report":
        return _report(con)

    print(f"lệnh không biết: {lenh!r} — có: {', '.join(_LENH)}\n\n{_tro_giup()}")
    return 2


def _gen(argv: list[str]) -> int:
    """`generator.run_all`, cộng cờ `--c4` gọi tiếp `generator.run_c4` trên đúng file
    vừa ghi — hai bước tách rời trong code gốc (I2: kiểm-trước-khi-tin), nhưng người
    dùng ngoài không cần biết ranh giới đó, gộp lại cho tiện dùng.

    `--help`/`-h` xử lý TAY ở đây (không `add_help` cho argparse riêng) vì phải in
    CẢ cờ của lệnh này (`--c4`) LẪN cờ gốc của `run_all` — hai parser tách rời, một
    trong hai `--help` tự động sẽ nuốt mất cờ của bên kia."""
    import argparse

    from generator.run_all import main as sinh

    if "-h" in argv or "--help" in argv:
        print("thêm, so với `python -m generator.run_all --help`:\n"
              "  --c4        chạy cổng C4 (gọi LLM) ngay sau khi sinh xong\n")
        return sinh(["--help"])

    ap = argparse.ArgumentParser(prog="genquesai gen", add_help=False)
    ap.add_argument("--c4", action="store_true")
    ap.add_argument("--out", default="out/eval_set.jsonl")
    a, con = ap.parse_known_args(argv)

    ra = sinh(["--out", a.out, *con])
    if ra != 0 or not a.c4:
        return ra

    from generator.run_c4 import main as c4
    return c4([a.out])


def _report(argv: list[str]) -> int:
    """In lại đúng báo cáo `evaluate.score` đã in khi chạy `run` — đọc từ file JSON đã
    lưu (`--out` của `run`), KHÔNG chấm lại. Dùng khi muốn xem lại/so hai lần chạy mà
    không tốn thời gian gọi lại hệ được đo."""
    import argparse
    import json
    from pathlib import Path

    from evaluate.score import in_bao_cao

    ap = argparse.ArgumentParser(prog="genquesai report")
    ap.add_argument("file", nargs="?", default="out/ket_qua_eval.json",
                    help="file JSON do 'genquesai run --out <file>' ghi ra")
    a = ap.parse_args(argv)

    duong_dan = Path(a.file)
    if not duong_dan.exists():
        print(f"không thấy {duong_dan} — chạy 'genquesai run' trước")
        return 1
    bao = json.loads(duong_dan.read_text(encoding="utf-8"))
    in_bao_cao(bao, bao["rows"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
