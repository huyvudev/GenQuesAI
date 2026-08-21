"""LLM client — OpenAI-compatible (Groq/xAI/OpenAI). Chỉ dùng ở understand + synthesize."""
from __future__ import annotations
import json
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
        self._extra = {"reasoning_effort": "none"} if self.provider == "deepseek" else {}

    def _create(self, **kw):
        """Gọi có retry/backoff khi rate-limit (429) hoặc lỗi tạm thời — cho batch lớn."""
        if self._extra:
            kw.setdefault("extra_body", {}).update(self._extra)
        for attempt in range(6):
            try:
                return self._client.chat.completions.create(**kw)
            except RateLimitError:
                time.sleep(min(2 ** attempt * 2, 60))
            except APIError:
                if attempt >= 3:
                    raise
                time.sleep(2 ** attempt)
        return self._client.chat.completions.create(**kw)

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
            # fallback: parse JSON từ text thường
            txt = self.chat(system + "\nCHỈ trả JSON hợp lệ.", user, temperature, max_tokens)
            a, b = txt.find("{"), txt.rfind("}")
            return json.loads(txt[a:b + 1]) if a >= 0 else {}
