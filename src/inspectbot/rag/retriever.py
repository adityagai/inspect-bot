"""Procedure retrieval (Checkpoint 3.1): LangChain + Chroma, filtered by confirmed category.

- Corpus: corpus/*.md with front matter (source_id, title, category, doc_type, version,
  synthetic, superseded). Only the newest non-superseded version of each source_id is indexed.
- Chunking: section-aware RecursiveCharacterTextSplitter (~150-300 words, small overlap), so a
  rule keeps its conditions and exceptions together.
- Filter first, then rank: only the task's category plus 'general' guidance is eligible. The
  unfiltered top hits that the filter excluded are reported as `rejected`, so the safeguard is
  visible (a similar-sounding procedure for another category is never used).
- Passages containing embedded instructions are flagged and excluded (retrieved text is data).
- Embeddings: `hashing` (default; offline, deterministic, no model download) or `minilm`
  (Chroma's local all-MiniLM-L6-v2, downloaded on first use). Set INSPECTBOT_EMBEDDINGS.
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

GENERAL = "general"
INJECTION_PATTERNS = re.compile(
    r"(ignore (all |any )?(previous|prior|above) instructions|disregard (the )?(system|previous)|"
    r"system prompt|you (must|should) (now )?(report|output|answer)|act as|override (the )?(rules|policy))",
    re.IGNORECASE,
)


def corpus_dir() -> Path:
    env = os.getenv("INSPECTBOT_CORPUS_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[3] / "corpus"


class HashingEmbeddings(Embeddings):
    """Deterministic bag-of-words embeddings (scikit-learn HashingVectorizer). No downloads."""

    def __init__(self, n_features: int = 2048) -> None:
        from sklearn.feature_extraction.text import HashingVectorizer

        self._vec = HashingVectorizer(n_features=n_features, ngram_range=(1, 2), stop_words="english",
                                      alternate_sign=False, norm="l2")

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return self._vec.transform(texts).toarray().tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


class MiniLMEmbeddings(Embeddings):
    """Chroma's bundled ONNX all-MiniLM-L6-v2 (CPU). Downloads the model on first use."""

    def __init__(self) -> None:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        self._fn = DefaultEmbeddingFunction()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._fn(texts)]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


def make_embeddings(kind: str | None = None) -> Embeddings:
    kind = (kind or os.getenv("INSPECTBOT_EMBEDDINGS", "hashing")).lower()
    return MiniLMEmbeddings() if kind == "minilm" else HashingEmbeddings()


@dataclass
class CorpusDoc:
    meta: dict[str, Any]
    body: str


def _parse(path: Path) -> CorpusDoc:
    text = path.read_text()
    _, front, body = text.split("---", 2)
    meta = yaml.safe_load(front)
    meta["version"] = str(meta.get("version"))
    meta["file"] = path.name
    return CorpusDoc(meta, body.strip())


def load_corpus(directory: Path | None = None) -> tuple[list[CorpusDoc], list[dict[str, Any]]]:
    """Newest non-superseded version per source_id, plus the list of versions left out."""
    docs = [_parse(p) for p in sorted((directory or corpus_dir()).glob("*.md"))]
    latest: dict[str, CorpusDoc] = {}
    skipped: list[dict[str, Any]] = []
    for d in docs:
        if d.meta.get("superseded"):
            skipped.append({"source_id": d.meta["source_id"], "version": d.meta["version"], "reason": "superseded"})
            continue
        sid = d.meta["source_id"]
        if sid in latest:
            raise ValueError(f"two active versions of {sid}; mark one as superseded")
        latest[sid] = d
    return list(latest.values()), skipped


def chunk(docs: list[CorpusDoc]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(chunk_size=1600, chunk_overlap=150,
                                              separators=["\n## ", "\n\n", "\n", " "])
    out: list[Document] = []
    for d in docs:
        meta = {k: d.meta[k] for k in ("source_id", "title", "category", "doc_type", "version")}
        meta["synthetic"] = bool(d.meta.get("synthetic", True))
        for i, piece in enumerate(splitter.split_text(d.body)):
            out.append(Document(page_content=piece, metadata={**meta, "chunk": i,
                                                              "flagged": bool(INJECTION_PATTERNS.search(piece))}))
    return out


@dataclass
class Retrieval:
    query: str
    category: str
    passages: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    has_category_procedure: bool = False
    missing_guidance: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


class ProcedureRetriever:
    def __init__(self, directory: Path | None = None, embeddings: Embeddings | None = None) -> None:
        from langchain_chroma import Chroma

        docs, self.skipped = load_corpus(directory)
        self.chunks = chunk(docs)
        self.categories = sorted({d.meta["category"] for d in docs} - {GENERAL})
        # Unique collection per index: Chroma's in-memory client is shared process-wide.
        self.store = Chroma(collection_name=f"inspectbot_procedures_{uuid.uuid4().hex[:8]}",
                            embedding_function=embeddings or make_embeddings(),
                            collection_metadata={"hnsw:space": "cosine"})
        self.store.add_documents(self.chunks, ids=[f"{c.metadata['source_id']}#{c.metadata['chunk']}"
                                                   for c in self.chunks])

    def retrieve(self, query: str, category: str, k: int = 3) -> Retrieval:
        r = Retrieval(query=query, category=category)
        allowed = [category, GENERAL]
        hits = self.store.similarity_search_with_relevance_scores(
            query, k=k * 3, filter={"category": {"$in": allowed}})
        seen: set[str] = set()
        for doc, score in hits:
            m = doc.metadata
            if m["flagged"]:
                r.rejected.append({"source_id": m["source_id"], "reason": "contains embedded instructions"})
                continue
            if m["source_id"] in seen:
                continue
            seen.add(m["source_id"])
            r.passages.append({**{k_: m[k_] for k_ in ("source_id", "title", "category", "doc_type", "version")},
                               "score": round(float(score), 3), "text": doc.page_content})
            if len(r.passages) == k:
                break
        # Make the category safeguard visible: strong unfiltered hits the filter excluded.
        for doc, score in self.store.similarity_search_with_relevance_scores(query, k=k):
            m = doc.metadata
            if m["category"] not in allowed and not any(x["source_id"] == m["source_id"] for x in r.rejected):
                r.rejected.append({"source_id": m["source_id"], "category": m["category"],
                                   "score": round(float(score), 3),
                                   "reason": f"category mismatch: written for {m['category']}, task is {category}"})
        r.has_category_procedure = any(p["category"] == category and p["doc_type"] == "procedure"
                                       for p in r.passages)
        if not r.has_category_procedure:
            r.missing_guidance = f"no approved procedure for category '{category}'"
        return r


@lru_cache(maxsize=1)
def default_retriever() -> ProcedureRetriever:
    return ProcedureRetriever()
