"""Bọc `ask()` để giữ lại phần truy hồi mà nó bỏ đi.

`legal_rag.agent.graph.ask()` trả `citations` ĐÃ LỌC theo câu trả lời — tức đầu ra của
**synthesize**, không phải đầu ra của **retrieval**. Chấm bằng nó thì không tách được
ba nguyên nhân sai ở bảng triage (Mục 8):

    retriever sót  ·  retriever nhầm (bẫy xếp trên gold)  ·  tìm đúng nhưng trả lời sai

State của graph có sẵn khoá `retrieved` với payload đầy đủ (`expr_id`, `part`, …), chỉ
là `ask()` không trả ra. Bọc lại ở ĐÂY thay vì sửa repo kia — không đụng vào code đang
chạy production.

`chunk_id` không nằm trong payload, nhưng tính lại được:
    point_id = uuid5(_NS, expr_id[#part])
Công thức này đã được `verify_point_id()` đối chiếu khớp 20/20 với index thật.
"""
from __future__ import annotations

from datetime import date

from generator.common import point_id


def ask_full(question: str, as_of_date: date | None = None) -> dict:
    from legal_rag.agent.graph import get_graph
    from legal_rag.agent.nodes import filter_used_citations

    state: dict = {"question": question}
    if as_of_date:
        state["event_date"] = as_of_date
    out = get_graph().invoke(state)
    ed = out.get("event_date")

    hits = out.get("retrieved", []) or []
    chunks, ctx = [], []
    for h in hits:
        ex = h.get("expr_id")
        if ex:
            chunks.append(point_id(ex, int(h.get("part", 0) or 0)))
        if h.get("text"):
            ctx.append(h["text"])

    return {
        # ── đúng khuôn ask() để `legal_rag.grader.grade()` dùng được nguyên vẹn ──
        "answer": out.get("answer", ""),
        "citations": filter_used_citations(out.get("answer", ""), out.get("citations", [])),
        "focus_norms": out.get("focus_norms", []),
        "as_of_date": ed.isoformat() if ed else None,
        "query_type": out.get("query_type"),
        "status": out.get("resolution_status"),
        "conflict": out.get("conflict", []),
        "warnings": out.get("warnings", []),
        # ── phần bổ sung, chỉ score.py dùng ──
        "retrieved_chunks": chunks,        # theo THỨ HẠNG
        "retrieved_contexts": ctx,
    }
