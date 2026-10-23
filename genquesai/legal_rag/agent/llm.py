"""LLM client — OpenAI-compatible (Groq/xAI/OpenAI). Chỉ dùng ở understand + synthesize."""
from __future__ import annotations
import json
import threading
import time

from openai import OpenAI, APIError, RateLimitError

from ..config import Settings, get_settings


class LLM:
    def __init__(self, settings: Settings | None = None):
        s = settings or get_settings()
        self.model = s.llm_model
        self.provider = s.llm_provider
        self._client = OpenAI(api_key=s.llm_api_key, base_url=s.llm_endpoint)
        # DeepSeek V4 (flash/pro) là REASONING model → mặc định "suy nghĩ" tốn 3-6k token trước
        # câu trả lời (dễ rỗng + rất chậm). TẮT reasoning để dùng như model chat thường (nhanh).
        if self.provider == "deepseek":
            self._extra = {"reasoning_effort": "none"}
        elif self.provider == "gemini":
            # Gemini 2.5 mặc định BẬT "thinking" (suy luận ẩn) — đo thực tế 2026-09-07:
            # max_tokens=20 chỉ đủ cho thinking, content trả về None. TẮT bằng thinking_budget=0
            # (cú pháp lớp tương thích OpenAI của Google: field JSON tên "extra_body" LỒNG bên
            # trong extra_body của request, không phải extra_body phẳng như deepseek).
            self._extra = {"extra_body": {"google": {"thinking_config": {"thinking_budget": 0}}}}
        else:
            self._extra = {}
        # Đếm token dồn tích (đa luồng an toàn) — dùng để ước tính cost/câu (eval/measure_cost.py),
        # không ảnh hưởng luồng chat()/chat_json() bình thường (chỉ đọc thêm r.usage đã có sẵn).
        self._usage_lock = threading.Lock()
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cache_hit_tokens = 0
        self.total_cache_miss_tokens = 0
        self.n_calls = 0

    def _track_usage(self, r) -> None:
        u = getattr(r, "usage", None)
        if u is None:
            return
        with self._usage_lock:
            self.total_prompt_tokens += getattr(u, "prompt_tokens", 0) or 0
            self.total_completion_tokens += getattr(u, "completion_tokens", 0) or 0
            self.total_cache_hit_tokens += getattr(u, "prompt_cache_hit_tokens", 0) or 0
            self.total_cache_miss_tokens += getattr(u, "prompt_cache_miss_tokens", 0) or 0
            self.n_calls += 1

    def _create(self, **kw):
        """Gọi có retry/backoff khi rate-limit (429) hoặc lỗi tạm thời — cho batch lớn."""
        if self._extra:
            kw.setdefault("extra_body", {}).update(self._extra)
        for attempt in range(6):
            try:
                r = self._client.chat.completions.create(**kw)
                self._track_usage(r)
                return r
            except RateLimitError:
                time.sleep(min(2 ** attempt * 2, 60))
            except APIError:
                if attempt >= 3:
                    raise
                time.sleep(2 ** attempt)
        r = self._client.chat.completions.create(**kw)
        self._track_usage(r)
        return r

    def chat(self, system: str, user: str, temperature: float = 0.0,
             max_tokens: int = 1200) -> str:
        r = self._create(
            model=self.model, temperature=temperature, max_tokens=max_tokens,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
        )
        return (r.choices[0].message.content or "").strip()

    def chat_stream(self, system: str, user: str, temperature: float = 0.0,
                    max_tokens: int = 1200):
        """Sinh câu trả lời theo từng đoạn (token) — cho SSE streaming ở UI."""
        stream = self._client.chat.completions.create(
            model=self.model, temperature=temperature, max_tokens=max_tokens, stream=True,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            extra_body=self._extra or None,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    def chat_json(self, system: str, user: str, temperature: float = 0.0,
                  max_tokens: int = 800) -> dict:
        try:
            r = self._create(
                model=self.model, temperature=temperature, max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
            )
            return json.loads(r.choices[0].message.content)
        except Exception:
            # fallback: parse JSON từ text thường. Nếu response bị cắt cụt (hết
            # max_tokens giữa chừng — hay gặp với VB có nhiều quan hệ) thì JSON vẫn
            # có thể hỏng ở đây — KHÔNG raise nữa (từng làm sập cả batch xử lý song
            # song, xem rule.md mục 9.2), coi như "không trích được gì" cho lượt này.
            try:
                txt = self.chat(system + "\nCHỈ trả JSON hợp lệ.", user, temperature, max_tokens)
                a, b = txt.find("{"), txt.rfind("}")
                return json.loads(txt[a:b + 1]) if a >= 0 else {}
            except Exception:
                return {}
