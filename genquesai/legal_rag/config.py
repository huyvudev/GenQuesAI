"""Cấu hình legal-rag (pydantic-settings, đọc từ .env). Xem .env.example."""
from __future__ import annotations
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "legalrag123"
    neo4j_database: str = "neo4j"

    # Qdrant
    qdrant_url: str = "http://127.0.0.1:6333"  # 127.0.0.1 KHÔNG localhost: trên Windows
    # 'localhost' phân giải ::1 (IPv6) trước, tunnel chỉ bind IPv4 -> chờ timeout ~2s/request
    qdrant_collection: str = "legal_text_units"
    qdrant_timeout: int = 60          # timeout (giây) cho request Qdrant — tránh 'timed out' khi máy tải nặng

    # Embedding (bge-m3): dense 1024 + sparse
    embed_model: str = "BAAI/bge-m3"
    embed_dense_dim: int = 1024

    # Ngưỡng điểm rerank (logit thô bge-reranker-v2-m3) để coi là CÓ grounding.
    # Hiệu chuẩn trên data thật: câu trong-corpus ≥ 6; câu ngoài-corpus/ngoài-domain < 0.
    # Dưới ngưỡng -> guard TỪ CHỐI trả lời (ARCH §1.6). Xem nodes.is_grounded.
    rerank_min_score: float = 0.0

    # Số đoạn (Điều) đưa vào LLM sau rerank. Câu hỏi nội dung trải nhiều điều trong 1 VB
    # cần nhiều đoạn hơn để "bắt đủ". Tăng -> phủ tốt hơn nhưng tốn token/câu (quota LLM).
    rerank_top_k: int = 12
    # Giới hạn ứng viên hybrid: khi hỏi đích danh 1 VB -> truy hồi TRONG VB đó (scoped),
    # rồi bổ sung tìm toàn cục (bắt tham chiếu chéo). Xem nodes.retrieve.
    # Giữ RỘNG để recall tốt (fetch Qdrant rẻ ~150ms); chi phí rerank được chặn bằng CASCADE
    # (rerank_cascade_n) chứ KHÔNG cắt ở đây nữa → vừa recall cao vừa rerank ít cặp.
    retrieve_scoped_limit: int = 40
    retrieve_global_limit: int = 40
    # CASCADE: số ứng viên đưa vào cross-encoder. ƯU TIÊN CHÍNH XÁC → rerank TOÀN BỘ pool
    # retrieval (scoped+global ≤80), KHÔNG cắt bớt ứng viên trước rerank. Hạ số này để nhanh hơn.
    rerank_cascade_n: int = 80
    # NỞ NGỮ CẢNH THEO DÂY GUIDED_BY (Luật→Nghị định→Thông tư): sau rerank, đi 1-hop tới các VB
    # HƯỚNG DẪN/CĂN CỨ của VB top, tìm-TRONG-đó đoạn khớp câu hỏi rồi ghép làm context BỔ TRỢ
    # (đứng sau đoạn chính → chính luôn ưu tiên ngân sách). Giúp câu hỏi "1 luật" kéo được cả
    # Nghị định/Thông tư chi tiết mà semantic search có thể sót. False = tắt.
    guidance_closure: bool = True
    closure_anchor_norms: int = 3      # số VB gốc (top primary) để nở
    closure_neighbor_cap: int = 150    # trần số VB hàng xóm GUIDED_BY đưa vào tìm scoped
    closure_search_limit: int = 16     # ứng viên hybrid trong VB hàng xóm (30→16: giảm rerank closure ~1/2)
    closure_keep: int = 5              # số đoạn bổ trợ giữ lại sau rerank (chỉ đoạn CÓ grounding)
    # ƯU TIÊN CHÍNH XÁC → LUÔN nở "đi theo dây" GUIDED_BY (kéo thêm VB hướng dẫn/căn cứ) cho MỌI
    # câu, không gate theo cấp VB. Đặt True để chỉ nở khi top có VB cấp cao (nhanh hơn, kém đầy đủ).
    closure_require_highlevel: bool = False
    # Số ký tự MỖI đoạn đưa vào LLM khi synthesize. Trước để 1500 -> bảng định mức/điều dài
    # (vd Phụ lục gộp trong 1 Điều) bị cắt mất phần số liệu -> LLM không thấy. Nâng lên để
    # "bắt" đủ nội dung; tối đa nên = cap lưu chunk (index.py 4000). Cao -> tốn token/câu.
    synth_excerpt_chars: int = 3500
    # Riêng Phụ lục/ToanVan (bảng định mức/danh mục dài) cần ngân sách LỚN hơn để LLM thấy TRỌN
    # bảng → liệt kê đủ từng chức danh/hạng mục (không tóm tắt/bỏ sót).
    synth_excerpt_chars_table: int = 16000
    # NGÂN SÁCH TỔNG ký tự cho toàn bộ trích đoạn đưa vào LLM. Groq free tier giới hạn ~12k
    # token/phút → 1 bảng phụ lục lớn + tham chiếu chéo dễ vượt (lỗi 413). Ưu tiên đoạn XẾP HẠNG
    # CAO nhất (phụ lục của VB được hỏi thường đứng đầu), CẮT phần dư → vừa free tier. ~3.1 ký
    # tự/token nên 22000 ký tự ≈ 7k token input, chừa chỗ cho câu trả lời liệt kê dài.
    synth_context_budget_chars: int = 22000
    # Cửa sổ token reranker đọc mỗi đoạn. 1200 phủ hết chunk dài (Phụ lục/bảng định mức ở đuôi)
    # → ƯU TIÊN CHÍNH XÁC (user chọn: chậm hơn chấp nhận được, không hi sinh độ đúng cho tốc độ).
    rerank_max_length: int = 1200
    # Re-chunk khi embed: Điều/khoản quá dài (vd Phụ lục bảng định mức gộp trong 1 Điều) được
    # CẮT thành nhiều "cửa sổ" ~embed_window_chars ký tự (chồng lấn embed_window_overlap) -> mỗi
    # cửa sổ 1 point, embed ĐỦ (không bị 512-token nuốt đuôi) -> truy hồi được nội dung sâu dù
    # KHÔNG nêu tên VB. ~1000 ký tự để chắc chắn < 512 token bge-m3.
    embed_window_chars: int = 1000
    embed_window_overlap: int = 120
    # Trần token bge-m3 khi embed. Đo thực tế: VB luật ~4 ký tự/token, bảng đặc tới ~1.84 ->
    # cửa sổ 1000 ký tự tối đa ~543 token; 768 đủ chứa CẢ cửa sổ đặc nhất (không bị cắt lại).
    embed_max_length: int = 768

    # Corpus raw (output crawler) — dùng cho ingestion ở P1
    corpus_dir: str = "../crawl/data/raw"

    # LLM (chỉ understand + synthesize) — đa nhà cung cấp (OpenAI-compatible)
    llm_provider: str = "groq"         # groq | xai | openai | anthropic
    llm_model: str = "llama-3.3-70b-versatile"
    llm_api_key: str = ""              # LLM_API_KEY
    llm_base_url: str = ""             # tự suy theo provider nếu để trống
    # Trần token ĐẦU RA khi synthesize. 1200 quá thấp -> câu trả lời nhiều mục (vd ~15 trách
    # nhiệm) bị CẮT CỤT giữa chừng. Tiếng Việt tốn token hơn -> để rộng cho câu có bố cục dài.
    # DeepSeek V4 reasoning được TẮT (reasoning_effort=none trong llm.py) → dùng như chat thường,
    # 2048 đủ cho câu trả lời (không tốn token suy nghĩ).
    synth_max_tokens: int = 2048

    # Xác thực admin (nạp/ghi VB): để TRỐNG -> khoá luôn /admin/* (fail-closed).
    # Đặt ADMIN_TOKEN trong .env rồi gửi header X-Admin-Token để mở.
    admin_token: str = ""

    @property
    def llm_endpoint(self) -> str:
        if self.llm_base_url:
            return self.llm_base_url
        return {
            "groq": "https://api.groq.com/openai/v1",
            "xai": "https://api.x.ai/v1",
            "openai": "https://api.openai.com/v1",
            "anthropic": "https://api.anthropic.com/v1/",  # lớp tương thích OpenAI của Anthropic
            "deepseek": "https://api.deepseek.com",        # OpenAI-compatible (SDK tự nối /chat/completions)
        }.get(self.llm_provider, "https://api.groq.com/openai/v1")


@lru_cache
def get_settings() -> Settings:
    return Settings()
