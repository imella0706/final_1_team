from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Optional

import faiss
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ============================================================
# Global Store
# ============================================================


class RetrievalStore:
    """
    final_db를 메모리에 로드해서 검색에 사용하는 저장소.
    """

    def __init__(self) -> None:
        self.db_dir: Optional[Path] = None
        self.index: Optional[faiss.Index] = None
        self.embeddings: Optional[np.ndarray] = None
        self.mapping_df: Optional[pd.DataFrame] = None
        self.metadata_df: Optional[pd.DataFrame] = None

    def load(self, db_dir: str | Path) -> None:
        db_dir = Path(db_dir)

        faiss_path = db_dir / "faiss.index"
        embeddings_path = db_dir / "embeddings.npy"
        mapping_path = db_dir / "mapping.csv"
        metadata_path = db_dir / "metadata.parquet"

        if not db_dir.exists():
            raise FileNotFoundError(f"DB directory not found: {db_dir}")

        if not faiss_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {faiss_path}")

        if not embeddings_path.exists():
            raise FileNotFoundError(f"Embeddings not found: {embeddings_path}")

        if not mapping_path.exists():
            raise FileNotFoundError(f"Mapping file not found: {mapping_path}")

        self.db_dir = db_dir
        self.index = faiss.read_index(str(faiss_path))
        self.embeddings = np.load(embeddings_path).astype(np.float32)
        self.mapping_df = pd.read_csv(mapping_path)

        if metadata_path.exists():
            self.metadata_df = pd.read_parquet(metadata_path)
        else:
            self.metadata_df = None

        if self.index.ntotal != len(self.mapping_df):
            raise ValueError(
                f"FAISS index count and mapping count mismatch: "
                f"index={self.index.ntotal}, mapping={len(self.mapping_df)}"
            )

        if len(self.embeddings) != len(self.mapping_df):
            raise ValueError(
                f"Embedding count and mapping count mismatch: "
                f"embeddings={len(self.embeddings)}, mapping={len(self.mapping_df)}"
            )

    def is_loaded(self) -> bool:
        return (
            self.db_dir is not None
            and self.index is not None
            and self.embeddings is not None
            and self.mapping_df is not None
        )


store = RetrievalStore()


# ============================================================
# FastAPI App
# ============================================================

app = FastAPI(
    title="AIHub Food Advertisement Retrieval API",
    description="Food image and metadata retrieval API for advertisement prompt generation.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Request / Response Models
# ============================================================


class SearchRequest(BaseModel):
    query: Optional[str] = Field(
        default=None,
        description="Text query. Example: 딸기 케이크, 카페 브런치, 맥주 안주",
    )
    business_category: Optional[str] = Field(
        default=None,
        description="cafe, bakery, dessert, restaurant, pub",
    )
    product_group: Optional[str] = Field(
        default=None,
        description="coffee, cake, korean_food, seafood_side, etc.",
    )
    product_name: Optional[str] = Field(
        default=None,
        description="User product/menu name.",
    )
    top_k: int = Field(default=10, ge=1, le=100)
    candidate_limit: int = Field(default=500, ge=10, le=5000)


class SearchResult(BaseModel):
    rank: int
    score: float
    faiss_index_id: int
    final_image_id: Optional[int] = None
    image_path: Optional[str] = None
    final_image_path: Optional[str] = None
    final_image_file_name: Optional[str] = None
    original_food_name: Optional[str] = None
    product_name: Optional[str] = None
    food_code: Optional[str] = None
    business_category: Optional[str] = None
    product_group: Optional[str] = None
    caption: Optional[str] = None
    prompt_keywords: Optional[str] = None
    text_for_embedding: Optional[str] = None


class SearchResponse(BaseModel):
    query: Optional[str]
    business_category: Optional[str]
    product_group: Optional[str]
    product_name: Optional[str]
    top_k: int
    result_count: int
    results: List[SearchResult]


# ============================================================
# Utility Functions
# ============================================================


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def require_store_loaded() -> None:
    if not store.is_loaded():
        raise HTTPException(
            status_code=500,
            detail="Retrieval DB is not loaded. Start server with --db-dir or call /admin/load-db.",
        )


def row_to_search_result(row: pd.Series, rank: int, score: float) -> SearchResult:
    def get_value(name: str) -> Any:
        if name not in row:
            return None
        value = row[name]
        if pd.isna(value):
            return None
        return value

    return SearchResult(
        rank=rank,
        score=float(score),
        faiss_index_id=(
            int(get_value("faiss_index_id"))
            if get_value("faiss_index_id") is not None
            else -1
        ),
        final_image_id=(
            int(get_value("final_image_id"))
            if get_value("final_image_id") is not None
            else None
        ),
        image_path=get_value("image_path"),
        final_image_path=get_value("final_image_path"),
        final_image_file_name=get_value("final_image_file_name"),
        original_food_name=get_value("original_food_name"),
        product_name=get_value("product_name"),
        food_code=get_value("food_code"),
        business_category=get_value("business_category"),
        product_group=get_value("product_group"),
        caption=get_value("caption"),
        prompt_keywords=get_value("prompt_keywords"),
        text_for_embedding=get_value("text_for_embedding"),
    )


def filter_candidates(
    mapping_df: pd.DataFrame,
    business_category: Optional[str],
    product_group: Optional[str],
    product_name: Optional[str],
    query: Optional[str],
) -> pd.DataFrame:
    """
    텍스트 임베딩 없이도 사용할 수 있는 1차 필터링.
    현재는 final_db에 image embedding만 있으므로,
    business_category/product_group/product_name/query를 메타데이터 필터로 사용한다.
    """
    df = mapping_df.copy()

    if business_category:
        if "business_category" in df.columns:
            df = df[df["business_category"].astype(str) == business_category]

    if product_group:
        if "product_group" in df.columns:
            df = df[df["product_group"].astype(str) == product_group]

    search_terms = []

    if product_name:
        search_terms.append(product_name)

    if query:
        search_terms.extend(query.split())

    if search_terms:
        searchable_cols = [
            "original_food_name",
            "product_name",
            "food_code",
            "business_category",
            "product_group",
            "caption",
            "prompt_keywords",
            "text_for_embedding",
        ]

        existing_cols = [col for col in searchable_cols if col in df.columns]

        if existing_cols:
            search_text = df[existing_cols].fillna("").astype(str).agg(" ".join, axis=1)

            mask = pd.Series(False, index=df.index)

            for term in search_terms:
                term = term.strip()
                if term:
                    mask = mask | search_text.str.contains(
                        term, case=False, regex=False
                    )

            matched_df = df[mask]

            # 검색어 필터가 너무 강해서 0개가 되면 category filter 결과를 유지한다.
            if len(matched_df) > 0:
                df = matched_df

    return df


def get_representative_query_vector(candidate_df: pd.DataFrame) -> np.ndarray:
    """
    텍스트 인코더 없이 검색을 수행하기 위한 대표 쿼리 벡터 생성.

    방법:
    - 필터링된 후보 이미지들의 임베딩 평균을 query vector로 사용
    - 예: business_category=cafe, product_name=딸기케이크로 후보를 찾고,
      그 후보들의 평균 벡터와 가까운 이미지를 재검색

    장점:
    - CLIP 텍스트 임베딩 없이도 동작
    - 현재 10단계를 건너뛰어도 검색 가능
    """
    require_store_loaded()

    if store.embeddings is None:
        raise HTTPException(status_code=500, detail="Embeddings are not loaded.")

    if "faiss_index_id" not in candidate_df.columns:
        raise HTTPException(
            status_code=500, detail="faiss_index_id column missing in mapping."
        )

    ids = candidate_df["faiss_index_id"].astype(int).to_numpy()

    if len(ids) == 0:
        raise HTTPException(
            status_code=404, detail="No candidates found for the given filters."
        )

    candidate_embeddings = store.embeddings[ids]

    query_vector = candidate_embeddings.mean(axis=0, keepdims=True).astype(np.float32)

    norms = np.linalg.norm(query_vector, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    query_vector = query_vector / norms

    return query_vector.astype(np.float32)


def search_by_vector(
    query_vector: np.ndarray,
    candidate_df: pd.DataFrame,
    top_k: int,
    candidate_limit: int,
) -> List[SearchResult]:
    """
    query vector로 전체 FAISS 검색 후, candidate_df에 포함되는 결과만 반환한다.
    """
    require_store_loaded()

    if store.index is None or store.mapping_df is None:
        raise HTTPException(status_code=500, detail="Index or mapping is not loaded.")

    candidate_ids = set(candidate_df["faiss_index_id"].astype(int).tolist())

    search_k = min(max(candidate_limit, top_k), store.index.ntotal)

    scores, indices = store.index.search(query_vector.astype(np.float32), search_k)

    results: List[SearchResult] = []

    for score, idx in zip(scores[0], indices[0]):
        if idx < 0:
            continue

        if int(idx) not in candidate_ids:
            continue

        row = store.mapping_df.iloc[int(idx)]
        results.append(
            row_to_search_result(
                row=row,
                rank=len(results) + 1,
                score=float(score),
            )
        )

        if len(results) >= top_k:
            break

    # 후보 필터가 너무 좁은 경우, candidate_df 순서대로라도 반환
    if len(results) == 0:
        fallback_df = candidate_df.head(top_k)

        for _, row in fallback_df.iterrows():
            results.append(
                row_to_search_result(
                    row=row,
                    rank=len(results) + 1,
                    score=0.0,
                )
            )

    return results


# ============================================================
# API Routes
# ============================================================


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "db_loaded": store.is_loaded(),
        "db_dir": str(store.db_dir) if store.db_dir else None,
        "index_total": int(store.index.ntotal) if store.index is not None else 0,
    }


@app.post("/admin/load-db")
def load_db(db_dir: str = Query(default="data/final_db/5gb")) -> Dict[str, Any]:
    try:
        store.load(db_dir)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "status": "loaded",
        "db_dir": str(store.db_dir),
        "index_total": int(store.index.ntotal) if store.index is not None else 0,
        "mapping_count": (
            int(len(store.mapping_df)) if store.mapping_df is not None else 0
        ),
    }


@app.get("/categories")
def categories() -> Dict[str, Any]:
    require_store_loaded()

    assert store.mapping_df is not None
    df = store.mapping_df

    business_categories = []
    product_groups = []

    if "business_category" in df.columns:
        business_categories = sorted(
            df["business_category"].dropna().astype(str).unique().tolist()
        )

    if "product_group" in df.columns:
        product_groups = sorted(
            df["product_group"].dropna().astype(str).unique().tolist()
        )

    return {
        "business_categories": business_categories,
        "product_groups": product_groups,
    }


@app.post("/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    require_store_loaded()

    assert store.mapping_df is not None

    candidate_df = filter_candidates(
        mapping_df=store.mapping_df,
        business_category=request.business_category,
        product_group=request.product_group,
        product_name=request.product_name,
        query=request.query,
    )

    if len(candidate_df) == 0:
        raise HTTPException(status_code=404, detail="No candidates found.")

    query_vector = get_representative_query_vector(candidate_df)

    results = search_by_vector(
        query_vector=query_vector,
        candidate_df=candidate_df,
        top_k=request.top_k,
        candidate_limit=request.candidate_limit,
    )

    return SearchResponse(
        query=request.query,
        business_category=request.business_category,
        product_group=request.product_group,
        product_name=request.product_name,
        top_k=request.top_k,
        result_count=len(results),
        results=results,
    )


@app.get("/search/by-food-name", response_model=SearchResponse)
def search_by_food_name(
    food_name: str,
    top_k: int = 10,
) -> SearchResponse:
    request = SearchRequest(
        query=food_name,
        product_name=food_name,
        top_k=top_k,
    )
    return search(request)


@app.get("/items/{faiss_index_id}")
def get_item(faiss_index_id: int) -> Dict[str, Any]:
    require_store_loaded()

    assert store.mapping_df is not None

    if faiss_index_id < 0 or faiss_index_id >= len(store.mapping_df):
        raise HTTPException(status_code=404, detail="faiss_index_id out of range.")

    row = store.mapping_df.iloc[faiss_index_id]

    return row.fillna("").to_dict()


# ============================================================
# CLI Entrypoint
# ============================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Food Advertisement Retrieval API."
    )
    parser.add_argument(
        "--db-dir",
        type=str,
        default="data/final_db/5gb",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=7860,
    )
    return parser.parse_args()


def run_server() -> None:
    import uvicorn

    args = parse_args()

    if Path(args.db_dir).exists():
        print(f"[INFO] Loading DB: {args.db_dir}")
        store.load(args.db_dir)
        print(
            f"[INFO] DB loaded. index_total={store.index.ntotal if store.index else 0}"
        )
    else:
        print(f"[WARN] DB dir not found at startup: {args.db_dir}")
        print("[WARN] You can load DB later via POST /admin/load-db")

    uvicorn.run(
        "app.retrieval_api:app",
        host=args.host,
        port=args.port,
        reload=False,
    )


if __name__ == "__main__":
    run_server()
