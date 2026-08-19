"""Hai adapter mẫu của B — một hộp trắng, một hộp đen.

    legal_rag  hộp trắng: đủ citations có cấu trúc + retrieved_ids chung không gian
               với corpus -> đường nhanh id, triage đủ ba nhãn
    http       hộp đen chuẩn (framework.adapter.HTTPAdapter): chỉ cần một endpoint
               POST JSON trả {"answer": ...}; có contexts thì đo được recall theo
               nội dung (A2)

Chọn qua `score.py --adapter legal_rag|http [--url ...]`.
"""
from __future__ import annotations

from datetime import date

from framework.adapter import HTTPAdapter, RAGResult


class LegalRagAdapter:
    """Hộp trắng cho hệ `legal-rag` — bọc `ask_full` (giữ phần truy hồi mà `ask()`
    bỏ đi) rồi quy về khuôn `RAGResult`. Cần repo Chatbot-Law trên máy."""

    def ask(self, question: str, as_of_date: date | None = None) -> RAGResult:
        from .ask_full import ask_full
        r = ask_full(question, as_of_date)
        return RAGResult(
            answer=r.get("answer", ""),
            retrieved_contexts=r.get("retrieved_contexts", []) or [],
            retrieved_ids=r.get("retrieved_chunks", []) or [],
            citations=r.get("citations", []) or [],
            focus_norms=r.get("focus_norms", []) or [],
            as_of_date=r.get("as_of_date"),
            status=r.get("status"),
            warnings=r.get("warnings", []) or [],
        )


def tao_adapter(ten: str, url: str | None = None):
    if ten == "legal_rag":
        return LegalRagAdapter()
    if ten == "http":
        if not url:
            raise SystemExit("--adapter http cần --url <endpoint POST JSON>")
        return HTTPAdapter(url)
    raise SystemExit(f"adapter không biết: {ten!r} (có: legal_rag, http)")
