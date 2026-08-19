"""B — hợp đồng giữa framework và HỆ ĐƯỢC ĐO.

Đây là ranh giới thứ hai của framework (ranh giới thứ nhất là `CorpusLoader` — corpus
đi VÀO; cái này là chatbot bị ĐO). Mọi thứ tầng chấm cần biết về một hệ RAG nằm trọn
trong `RAGResult`; hệ nối vào bằng cách hiện thực một hàm duy nhất:

    ask(question, as_of_date) -> RAGResult

Hai mức tham gia, cố ý chênh nhau:

    HỘP ĐEN   chỉ cần `answer`. Grader vớt số hiệu ngay trong câu trả lời
              (`_neu_ra(hop_den=True)`), chấm được citation/validity/behavior.
              Có thêm `retrieved_contexts` thì đo được cả recall — theo NỘI DUNG
              (A2), không cần id.
    HỘP TRẮNG thêm `citations` có cấu trúc + `retrieved_ids` chung không gian với
              corpus -> đường nhanh id, và triage đủ ba nhãn.

`HTTPAdapter` ở dưới là adapter hộp đen mẫu — và nó quan trọng hơn vẻ ngoài: adapter
THỨ HAI là thứ duy nhất chứng minh hợp đồng đúng. Một adapter thì luôn vừa khít với
chính nó, kể cả khi thiết kế sai (bài học đã trả khi JsonlLoader lộ ra lỗi lấy mẫu
đầu-dãy của báo cáo năng lực).
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol


@dataclass(slots=True)
class RAGResult:
    """Câu trả lời của hệ được đo, đã quy về khuôn chung.

    `answer` là trường BẮT BUỘC duy nhất. Mọi trường khác vắng mặt chỉ làm hẹp phạm
    vi đo (mất recall, mất triage), không làm hỏng phép chấm — grader chỉ kiểm những
    khoá có mặt.
    """
    answer: str
    # đoạn văn bản NGUYÊN VĂN hệ đã lấy về, theo thứ hạng — nguyên liệu của A2
    retrieved_contexts: list[str] = field(default_factory=list)
    # id chunk nếu hệ chung không gian id với corpus — đường nhanh, tuỳ chọn
    retrieved_ids: list[str] = field(default_factory=list)
    # trích dẫn có cấu trúc: [{"so_hieu": ..., "dieu_khoan": ...}]
    citations: list[dict] = field(default_factory=list)
    focus_norms: list[dict] = field(default_factory=list)
    as_of_date: str | None = None
    status: str | None = None
    warnings: list[str] = field(default_factory=list)

    def thanh_dict(self) -> dict:
        """Khuôn dict mà `framework.grader.grade()` và tầng đo chunk tiêu thụ."""
        return {
            "answer": self.answer,
            "citations": self.citations,
            "focus_norms": self.focus_norms,
            "as_of_date": self.as_of_date,
            "status": self.status,
            "warnings": self.warnings,
            "retrieved_contexts": self.retrieved_contexts,
            "retrieved_chunks": self.retrieved_ids,
        }


class RAGAdapter(Protocol):
    """Hợp đồng hệ được đo. Một hàm, không hơn."""

    def ask(self, question: str, as_of_date: date | None = None) -> RAGResult: ...


# ── adapter hộp đen mẫu: HTTP JSON ──────────────────────────────────────────
# Các tên trường mà API RAG ngoài kia hay dùng — thử lần lượt, lấy tên đầu tiên có.
# Đây là danh sách MAP, không phải đoán mò: gặp API đặt tên khác thì truyền `map_truong`
# tường minh thay vì nối dài danh sách này vô hạn.
_TEN_ANSWER = ("answer", "response", "output", "result", "text")
_TEN_CONTEXTS = ("retrieved_contexts", "contexts", "documents", "chunks", "sources")
_TEN_IDS = ("retrieved_ids", "retrieved_chunks", "chunk_ids", "doc_ids")


def _lay(d: dict, ten: tuple[str, ...]):
    for t in ten:
        if t in d and d[t] is not None:
            return d[t]
    return None


def _thanh_texts(v) -> list[str]:
    """contexts có thể là list[str] hoặc list[dict] — vớt text từ các khoá quen."""
    if not isinstance(v, list):
        return []
    ra = []
    for x in v:
        if isinstance(x, str):
            ra.append(x)
        elif isinstance(x, dict):
            t = _lay(x, ("text", "content", "page_content", "chunk"))
            if isinstance(t, str):
                ra.append(t)
    return ra


class HTTPAdapter:
    """Hộp đen chuẩn: POST JSON `{"question": ..., "as_of_date": "YYYY-MM-DD"?}`,
    đọc JSON trả về theo các tên trường phổ biến (hoặc `map_truong` tường minh).

    Không retry, không stream, không auth cầu kỳ — adapter mẫu phải ĐỌC HIỂU ĐƯỢC
    trong một hơi để người ta chép về sửa theo API của họ, đó là toàn bộ giá trị
    của nó.
    """

    def __init__(self, url: str, timeout: float = 120.0,
                 headers: dict | None = None, map_truong: dict | None = None):
        self.url = url
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json", **(headers or {})}
        self.map = map_truong or {}

    def ask(self, question: str, as_of_date: date | None = None) -> RAGResult:
        body: dict = {"question": question}
        if as_of_date:
            body["as_of_date"] = as_of_date.isoformat()
        req = urllib.request.Request(
            self.url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=self.headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            d = json.loads(resp.read().decode("utf-8"))

        def lay(khoa: str, mac_dinh: tuple[str, ...]):
            if khoa in self.map:
                return d.get(self.map[khoa])
            return _lay(d, mac_dinh)

        answer = lay("answer", _TEN_ANSWER)
        if not isinstance(answer, str):
            raise ValueError(
                f"phản hồi từ {self.url} không có trường answer nào trong "
                f"{_TEN_ANSWER} — truyền map_truong={{'answer': '<tên thật>'}}")
        return RAGResult(
            answer=answer,
            retrieved_contexts=_thanh_texts(lay("contexts", _TEN_CONTEXTS)),
            retrieved_ids=[str(x) for x in (lay("ids", _TEN_IDS) or [])],
            citations=[x for x in (d.get("citations") or []) if isinstance(x, dict)],
            focus_norms=[x for x in (d.get("focus_norms") or []) if isinstance(x, dict)],
            as_of_date=d.get("as_of_date"),
            status=d.get("status"),
            warnings=[str(x) for x in (d.get("warnings") or [])],
        )
