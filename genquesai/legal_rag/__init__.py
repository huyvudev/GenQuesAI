"""genquesai.legal_rag — bản clone cơ chế CDI (Continuous Document Integration, §9
backbone.md) từ D:/Project/Chatbot-Law/chatbot/legal_rag/, để GenQuesAI tự chủ đọc/ghi
Neo4j+Qdrant mà không cần trỏ sang repo Chatbot-Law.

Clone ngày 2026-08-21. Mang theo: domain, ingestion/{loader,structural_parser,importer,
reconcile,text_unit}, graph, retrieval, cdi, agent/llm.py (LLM generic dùng cho
paraphrase). KHÔNG mang theo agent/graph.py (LangGraph — logic TRẢ LỜI câu hỏi), api/,
webapp/, evaluation/, hay các module chỉ phục vụ AV (§10 — versioning sửa đổi cấp
Điều: amendment_*, transition_extractor, reference_extractor, ocr, versioning,
internal_ref_extractor).

CỐ Ý đặt tên `genquesai.legal_rag` (namespace dưới `genquesai`), KHÔNG phải `legal_rag`
trần: hệ RAG đang được ĐO (system under test, trỏ qua `legal_rag_root`/`LEGAL_RAG_ROOT`
— xem framework/config.py) LUÔN cài đặt dưới tên package `legal_rag` trần, nạp bằng
sys.path (generator/common.py). Hai package cùng tên `legal_rag` trần sẽ ĐÈ LẪN NHAU
tuỳ thứ tự sys.path — đặt tên khác để KHÔNG BAO GIỜ xung đột, dù trỏ vào bất kỳ hệ RAG
nào đúng khuôn `legal_rag.agent.graph.get_graph()`.

Đây là bản sao độc lập, không tự động đồng bộ với Chatbot-Law — sửa bug ở parser/CDI
bên đó sẽ KHÔNG tự phản ánh sang đây.
"""
