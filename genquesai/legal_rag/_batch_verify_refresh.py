"""Goi dinh ky (sau moi N lo) de: ap dung log JSONL vao Neo4j (da_duyet=true cho
'dung'), xuat lai _da_khop.csv/_can_ra.xlsx, roi COPY de lam moi ban giao trong
_CAN_RA_SOAT/ (giu nguyen ten file goc user dang dung). Muc dich: 'lam den dau
sua file excel den day' — file giao cho user luon phan anh tien do moi nhat."""
from __future__ import annotations
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).parent
PY = sys.executable
OUT_DIR = HERE / "_CAN_RA_SOAT"


def main() -> None:
    print("== 1/3 áp dụng log vào Neo4j ==")
    subprocess.run([PY, str(HERE / "_batch_verify_apply.py")], check=True)

    print("== 2/3 xuất lại _da_khop.csv / _can_ra.xlsx ==")
    subprocess.run([PY, str(HERE / "_xuat_ket_qua_rebuild.py")], check=True)

    print("== 3/3 copy vào _CAN_RA_SOAT/ ==")
    shutil.copy2(HERE / "_can_ra.xlsx", OUT_DIR / "1_CAN_DUYET_can_ra.xlsx")
    shutil.copy2(HERE / "_da_khop.csv", OUT_DIR / "3_THAM_KHAO_da_khop.csv")
    print("Xong — file trong _CAN_RA_SOAT/ đã cập nhật tiến độ mới nhất.")


if __name__ == "__main__":
    main()
