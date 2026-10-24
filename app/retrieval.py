"""조항 벡터 검색 (ChromaDB persistent). 임베딩은 LLMClient(캐시)로 계산해 직접 넣는다.

Streamlit Cloud는 파일시스템이 비영속이라, 코퍼스 지문(fingerprint)이 다르거나 인덱스가 없으면
커밋된 플레이북 + 임베딩 캐시로 다시 만든다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import chromadb

from app.config import get_settings
from app.llm.client import LLMClient
from app.schemas import Clause, Event, Playbook

COLLECTION = "clauses"


def clause_document(clause: Clause) -> str:
    p = clause.premises
    parts = [
        clause.text,
        "전제 사건유형: " + ", ".join(t.value for t in p.event_types),
        "전제 채널: " + ", ".join(c.value for c in p.channels),
        "전제 지역: " + ", ".join(p.regions),
        "전제 조건: " + "; ".join(p.conditions),
        "조치: " + "; ".join(clause.actions),
    ]
    return "\n".join(parts)


def event_query(event: Event, extra: str = "") -> str:
    parts = [
        event.title,
        event.summary,
        "사건유형: " + event.type.value,
        "채널: " + ", ".join(c.value for c in event.channels),
        "지역: " + ", ".join(event.regions),
    ]
    return "\n".join(parts + ([extra] if extra else []))


def _fingerprint(clauses: list[Clause], embed_model: str) -> str:
    raw = json.dumps([[c.clause_id, clause_document(c)] for c in clauses] + [embed_model], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class ClauseIndex:
    def __init__(self, playbooks: list[Playbook], llm: LLMClient, path: Path | None = None):
        self.llm = llm
        self.clauses = {c.clause_id: c for p in playbooks for c in p.clauses}
        if path is None:  # 제공자별로 색인 분리 (Gemini 기본 색인을 다른 임베딩으로 덮어쓰지 않게)
            st = get_settings()
            provider = getattr(llm, "provider", "gemini")
            path = st.chroma_dir if provider == "gemini" else st.data_dir / f"chroma_{provider}"
        self._client = chromadb.PersistentClient(path=str(path))
        fp = _fingerprint(list(self.clauses.values()), llm.embed_model)
        try:
            col = self._client.get_collection(COLLECTION, embedding_function=None)
            if (col.metadata or {}).get("fingerprint") != fp:
                self._client.delete_collection(COLLECTION)
                col = None
        except Exception:
            col = None
        if col is None:
            col = self._build(fp)
        self.col = col

    def _build(self, fp: str):
        col = self._client.create_collection(
            COLLECTION, embedding_function=None, metadata={"hnsw:space": "cosine", "fingerprint": fp}
        )
        ids = list(self.clauses)
        docs = [clause_document(self.clauses[i]) for i in ids]
        embeddings = self.llm.embed(docs, purpose="index_clauses")
        col.add(ids=ids, embeddings=embeddings, documents=docs,
                metadatas=[{"doc_id": self.clauses[i].doc_id, "protected": self.clauses[i].protected} for i in ids])
        return col

    def search(self, query: str, top_k: int) -> list[Clause]:
        emb = self.llm.embed([query], purpose="retrieve_clauses")[0]
        res = self.col.query(query_embeddings=[emb], n_results=min(top_k, len(self.clauses)))
        return [self.clauses[i] for i in res["ids"][0]]

    def protected(self) -> list[Clause]:
        return [c for c in self.clauses.values() if c.protected]
