"""
SapBERT multilingual encoder + top-K cosine matcher.

Keeps the model resident in memory and mirrors the encoding used by the
offline CLI (scripts/sapbert_mapping.py): CLS-token embeddings from the
multilingual XLM-R SapBERT model, then chunked cosine top-K. The similarity
is computed on CPU (numpy) so it never competes with the model for GPU memory.
"""
import numpy as np


class SapbertEncoder:
    def __init__(self, model_name: str, device: str = "cuda", batch_size: int = 128):
        import torch
        from transformers import AutoModel, AutoTokenizer

        self.model_name = model_name
        self.batch_size = batch_size
        want_cuda = device == "cuda" and torch.cuda.is_available()
        self.device = "cuda" if want_cuda else "cpu"

        # The multilingual model is XLM-R based. Some transformers builds need
        # protobuf/tiktoken to convert the SentencePiece tokenizer to a fast
        # one — fall back to the slow tokenizer (identical input_ids) if so.
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        except Exception:
            self.tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=False)
        self.model = AutoModel.from_pretrained(model_name).eval().to(self.device)
        self.hidden_size = int(self.model.config.hidden_size)

    def encode(self, texts: list[str], batch_size: int | None = None) -> np.ndarray:
        """Encode texts into SapBERT CLS embeddings, shape (n, hidden_size)."""
        import torch

        bs = batch_size or self.batch_size
        chunks = []
        for i in range(0, len(texts), bs):
            batch = texts[i : i + bs]
            inputs = self.tokenizer(
                batch, padding=True, truncation=True, max_length=64, return_tensors="pt"
            ).to(self.device)
            with torch.no_grad():
                cls = self.model(**inputs).last_hidden_state[:, 0, :].cpu().numpy()
            chunks.append(cls)
        if not chunks:
            return np.zeros((0, self.hidden_size), dtype=np.float32)
        return np.vstack(chunks).astype(np.float32)

    @staticmethod
    def topk(
        source_embs: np.ndarray,
        target_embs: np.ndarray,
        k: int = 5,
        mem_budget_bytes: int = 1_000_000_000,
    ):
        """Cosine top-K. Returns (indices, scores), each shape (n_source, k).

        Memory- and time-optimized for very large target sets (e.g. 2M Drug
        concepts):
          - target embeddings are normalized **in place** (no full copy);
          - the source side is split so each chunk's similarity matrix + index
            array stay within ``mem_budget_bytes`` (caps peak RAM);
          - top-K is found with ``argpartition`` (O(n)) instead of a full
            ``argsort`` (O(n·log n)) — only the k winners are then sorted.
        """
        n_src = source_embs.shape[0]
        n_tgt = target_embs.shape[0]
        if n_src == 0 or n_tgt == 0:
            return np.zeros((n_src, 0), dtype=int), np.zeros((n_src, 0), dtype=float)
        k = min(k, n_tgt)

        s = source_embs / (np.linalg.norm(source_embs, axis=1, keepdims=True) + 1e-12)
        s = s.astype(np.float32, copy=False)
        # Normalize targets in place (avoids a second ~n_tgt*dim*4-byte array).
        target_embs = target_embs.astype(np.float32, copy=False)
        target_embs /= (np.linalg.norm(target_embs, axis=1, keepdims=True) + 1e-12)

        # Per source row a chunk allocates ~n_tgt * (4 sims + 8 index) = 12 bytes.
        chunk = max(1, min(1024, int(mem_budget_bytes // (n_tgt * 12))))

        idx_all, score_all = [], []
        for i in range(0, n_src, chunk):
            sims = s[i : i + chunk] @ target_embs.T          # (rows, n_tgt) float32
            part = np.argpartition(sims, -k, axis=1)[:, -k:]  # (rows, k) unordered top-k
            part_scores = np.take_along_axis(sims, part, axis=1)
            order = np.argsort(-part_scores, axis=1)          # sort only the k winners
            idx_all.append(np.take_along_axis(part, order, axis=1))
            score_all.append(np.take_along_axis(part_scores, order, axis=1))
        return np.vstack(idx_all), np.vstack(score_all)
