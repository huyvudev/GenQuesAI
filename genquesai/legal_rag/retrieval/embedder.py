"""Embedder bge-m3 — dense (1024) + sparse (lexical), lazy-load model (ARCH §4.3, §5.1.8)."""
from __future__ import annotations
import threading


def _auto_device() -> str:
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class Embedder:
    def __init__(self, model_name: str = "BAAI/bge-m3", device: str | None = None,
                 max_length: int = 512):
        self.model_name = model_name
        self.device = device or _auto_device()
        self.max_length = max_length     # trần token (config.embed_max_length) — tránh cắt cửa sổ dài
        self._model = None
        self._load_lock = threading.Lock()

    def _load(self) -> None:
        from FlagEmbedding import BGEM3FlagModel
        # fp16 trên GPU (CUDA/MPS) ~2x nhanh; CPU dùng fp32
        self._model = BGEM3FlagModel(
            self.model_name, use_fp16=(self.device != "cpu"), devices=self.device,
        )

    def encode(self, texts: list[str], batch_size: int = 128, max_length: int | None = None):
        """Trả (dense_vecs: np.ndarray[n,1024], lexical_weights: list[dict[token->weight]])."""
        if self._model is None:
            with self._load_lock:      # double-checked locking: tránh 2 thread cùng _load() đè nhau
                if self._model is None:
                    self._load()
        out = self._model.encode(
            texts, batch_size=batch_size, max_length=max_length or self.max_length,
            return_dense=True, return_sparse=True, return_colbert_vecs=False,
        )
        return out["dense_vecs"], out["lexical_weights"]

    def encode_query(self, text: str):
        d, s = self.encode([text])
        return d[0], s[0]
