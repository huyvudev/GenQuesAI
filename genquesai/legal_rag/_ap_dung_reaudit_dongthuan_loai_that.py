"""Áp dụng kết quả re-audit nhóm 'đồng thuận cao về loại thật' — tái sử dụng logic của
_ap_dung_reaudit_thi_hanh_v2.py, chỉ đổi log path + bỏ giả định "loai_moi luôn khác
KhongLienQuan" (nhóm này re-audit CÓ THỂ ra KhongLienQuan mới, khác nhóm A/B/C).

Chạy: cd genquesai/legal_rag && python _ap_dung_reaudit_dongthuan_loai_that.py [--apply]
"""
from __future__ import annotations
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

import _ap_dung_reaudit_thi_hanh_v2 as base

base.LOG_PATH = "_reaudit_dongthuan_loai_that_log.jsonl"

if __name__ == "__main__":
    base.main(apply="--apply" in sys.argv)
