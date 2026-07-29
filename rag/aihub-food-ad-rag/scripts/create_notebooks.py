from __future__ import annotations

from pathlib import Path

import nbformat as nbf


def make_notebook(cells: list[str], output_path: str) -> None:
    nb = nbf.v4.new_notebook()

    nb["cells"] = []

    for cell in cells:
        if cell.strip().startswith("# "):
            nb["cells"].append(nbf.v4.new_markdown_cell(cell))
        else:
            nb["cells"].append(nbf.v4.new_code_cell(cell))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as f:
        nbf.write(nb, f)

    print(f"[DONE] created: {output}")


metadata_eda_cells = [
    """# 01 Metadata EDA

이 노트북은 `raw_metadata.parquet`, `category_enriched_metadata.parquet`를 확인하기 위한 EDA 노트북입니다.

목적:
- 전체 데이터 개수 확인
- 음식명/음식코드 분포 확인
- 업종/상품군 매핑 결과 확인
- fallback_default 항목 확인
- 최종 DB 생성 전 데이터 상태 점검
""",
    """
from pathlib import Path
import json

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

pd.set_option("display.max_columns", 100)
pd.set_option("display.max_colwidth", 120)

ROOT = Path("..").resolve()
RAW_METADATA_PATH = ROOT / "data" / "metadata" / "raw_metadata.parquet"
CATEGORY_METADATA_PATH = ROOT / "data" / "metadata" / "category_enriched_metadata.parquet"

RAW_METADATA_PATH, CATEGORY_METADATA_PATH
""",
    """
raw_df = pd.read_parquet(RAW_METADATA_PATH)
print("raw_df shape:", raw_df.shape)
raw_df.head()
""",
    """
raw_df.info()
""",
    """
raw_df[[
    "source_file_name",
    "original_food_name",
    "product_name",
    "food_code",
    "image_path",
    "image_width",
    "image_height",
    "image_size_bytes",
]].head(20)
""",
    """
summary = {
    "row_count": len(raw_df),
    "unique_food_name_count": raw_df["original_food_name"].nunique(),
    "unique_food_code_count": raw_df["food_code"].nunique(),
    "missing_image_count": raw_df["image_path"].isna().sum(),
    "food_name_missing_count": (raw_df["original_food_name"].fillna("").astype(str).str.strip() == "").sum(),
    "total_image_size_gb": raw_df["image_size_bytes"].sum() / (1024 ** 3),
    "avg_image_size_mb": raw_df["image_size_bytes"].mean() / (1024 ** 2),
}
summary
""",
    """
food_name_dist = (
    raw_df["original_food_name"]
    .value_counts()
    .reset_index()
)
food_name_dist.columns = ["original_food_name", "count"]
food_name_dist.head(30)
""",
    """
top_n = 30

plot_df = food_name_dist.head(top_n).sort_values("count")

plt.figure(figsize=(10, 8))
plt.barh(plot_df["original_food_name"], plot_df["count"])
plt.title(f"Top {top_n} Food Names")
plt.xlabel("Image Count")
plt.ylabel("Food Name")
plt.tight_layout()
plt.show()
""",
    """
food_code_dist = (
    raw_df["food_code"]
    .value_counts()
    .reset_index()
)
food_code_dist.columns = ["food_code", "count"]
food_code_dist.head(30)
""",
    """
plt.figure(figsize=(10, 8))
plot_df = food_code_dist.head(30).sort_values("count")
plt.barh(plot_df["food_code"], plot_df["count"])
plt.title("Top 30 Food Codes")
plt.xlabel("Image Count")
plt.ylabel("Food Code")
plt.tight_layout()
plt.show()
""",
    """
if CATEGORY_METADATA_PATH.exists():
    category_df = pd.read_parquet(CATEGORY_METADATA_PATH)
    print("category_df shape:", category_df.shape)
else:
    category_df = None
    print("category_enriched_metadata.parquet does not exist.")
""",
    """
if category_df is not None:
    display(category_df[[
        "original_food_name",
        "food_code",
        "business_category",
        "product_group",
        "category_mapping_status",
        "category_matched_keyword",
    ]].head(30))
""",
    """
if category_df is not None:
    status_dist = category_df["category_mapping_status"].value_counts().reset_index()
    status_dist.columns = ["category_mapping_status", "count"]
    status_dist["ratio"] = status_dist["count"] / len(category_df)
    display(status_dist)
""",
    """
if category_df is not None:
    business_dist = category_df["business_category"].value_counts().reset_index()
    business_dist.columns = ["business_category", "count"]
    business_dist["ratio"] = business_dist["count"] / len(category_df)
    display(business_dist)

    plt.figure(figsize=(8, 5))
    plt.bar(business_dist["business_category"], business_dist["count"])
    plt.title("Business Category Distribution")
    plt.xlabel("Business Category")
    plt.ylabel("Count")
    plt.tight_layout()
    plt.show()
""",
    """
if category_df is not None:
    product_group_dist = category_df["product_group"].value_counts().reset_index()
    product_group_dist.columns = ["product_group", "count"]
    product_group_dist["ratio"] = product_group_dist["count"] / len(category_df)
    display(product_group_dist.head(50))

    plt.figure(figsize=(10, 8))
    plot_df = product_group_dist.head(30).sort_values("count")
    plt.barh(plot_df["product_group"], plot_df["count"])
    plt.title("Top Product Groups")
    plt.xlabel("Count")
    plt.ylabel("Product Group")
    plt.tight_layout()
    plt.show()
""",
    """
if category_df is not None:
    fallback_df = category_df[
        category_df["category_mapping_status"] == "fallback_default"
    ][[
        "original_food_name",
        "product_name",
        "food_code",
        "business_category",
        "product_group",
        "category_mapping_status",
    ]].drop_duplicates().sort_values("original_food_name")

    print("fallback unique food count:", len(fallback_df))
    display(fallback_df.head(100))
""",
    """
if category_df is not None:
    sample_df = (
        category_df
        .sample(min(20, len(category_df)), random_state=42)
        [[
            "original_food_name",
            "food_code",
            "business_category",
            "product_group",
            "image_path",
        ]]
    )
    display(sample_df)
""",
]


quality_check_cells = [
    """# 02 Quality Check

이 노트북은 품질 필터링 결과를 확인하기 위한 노트북입니다.

목적:
- `quality_filtered_metadata.parquet` 결과 확인
- 탈락 이미지 확인
- 블러 점수 분포 확인
- 실제 이미지 샘플 시각화
""",
    """
from pathlib import Path
import json

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image

pd.set_option("display.max_columns", 100)
pd.set_option("display.max_colwidth", 120)

ROOT = Path("..").resolve()

QUALITY_METADATA_PATH = ROOT / "data" / "metadata" / "quality_filtered_metadata.parquet"
QUALITY_REPORT_PATH = ROOT / "outputs" / "reports" / "quality_filter" / "quality_filter_summary.json"
REJECTED_PATH = ROOT / "outputs" / "reports" / "quality_filter" / "rejected_images.csv"

QUALITY_METADATA_PATH
""",
    """
quality_df = pd.read_parquet(QUALITY_METADATA_PATH)
print("quality_df shape:", quality_df.shape)
quality_df.head()
""",
    """
if QUALITY_REPORT_PATH.exists():
    with open(QUALITY_REPORT_PATH, "r", encoding="utf-8") as f:
        summary = json.load(f)
    summary
else:
    print("quality_filter_summary.json does not exist.")
""",
    """
quality_cols = [
    "original_food_name",
    "business_category",
    "product_group",
    "quality_pass",
    "quality_status",
    "quality_score",
    "blur_score",
    "actual_width",
    "actual_height",
    "image_path",
]

existing_cols = [col for col in quality_cols if col in quality_df.columns]
quality_df[existing_cols].head(30)
""",
    """
if "quality_status" in quality_df.columns:
    status_dist = quality_df["quality_status"].value_counts().reset_index()
    status_dist.columns = ["quality_status", "count"]
    status_dist["ratio"] = status_dist["count"] / len(quality_df)
    display(status_dist)
""",
    """
if "quality_score" in quality_df.columns:
    plt.figure(figsize=(8, 5))
    plt.hist(quality_df["quality_score"].dropna(), bins=20)
    plt.title("Quality Score Distribution")
    plt.xlabel("Quality Score")
    plt.ylabel("Count")
    plt.tight_layout()
    plt.show()
""",
    """
if "blur_score" in quality_df.columns:
    plt.figure(figsize=(8, 5))
    plt.hist(quality_df["blur_score"].dropna(), bins=50)
    plt.title("Blur Score Distribution")
    plt.xlabel("Blur Score")
    plt.ylabel("Count")
    plt.tight_layout()
    plt.show()
""",
    """
if REJECTED_PATH.exists():
    rejected_df = pd.read_csv(REJECTED_PATH)
    print("rejected_df shape:", rejected_df.shape)
    display(rejected_df.head(50))
else:
    rejected_df = pd.DataFrame()
    print("No rejected_images.csv found.")
""",
    """
def show_image_grid(df, image_col="image_path", title_col="original_food_name", n=12, cols=4):
    sample = df.head(n).copy()
    rows = int(np.ceil(len(sample) / cols))

    plt.figure(figsize=(cols * 4, rows * 4))

    for i, (_, row) in enumerate(sample.iterrows(), start=1):
        image_path = Path(str(row[image_col]))

        plt.subplot(rows, cols, i)
        plt.axis("off")

        try:
            img = Image.open(image_path).convert("RGB")
            plt.imshow(img)
            plt.title(str(row.get(title_col, ""))[:30])
        except Exception as e:
            plt.title(f"error: {e}")

    plt.tight_layout()
    plt.show()
""",
    """
sample_df = quality_df.sample(min(12, len(quality_df)), random_state=42)
show_image_grid(sample_df, n=12, cols=4)
""",
    """
if len(rejected_df) > 0 and "image_path" in rejected_df.columns:
    show_image_grid(rejected_df, n=12, cols=4)
else:
    print("No rejected images to display.")
""",
    """
if "business_category" in quality_df.columns:
    business_quality = (
        quality_df
        .groupby("business_category")
        .agg(
            count=("business_category", "size"),
            avg_quality_score=("quality_score", "mean"),
            avg_blur_score=("blur_score", "mean"),
            min_width=("actual_width", "min"),
            min_height=("actual_height", "min"),
        )
        .reset_index()
        .sort_values("count", ascending=False)
    )
    display(business_quality)
""",
]


retrieval_test_cells = [
    """# 03 Retrieval Test

이 노트북은 최종 FAISS 검색 품질을 확인하기 위한 노트북입니다.

목적:
- final_db 로드
- FAISS 검색 테스트
- 음식명/업종/상품군 필터 검색
- 검색 결과 이미지 시각화
""",
    """
from pathlib import Path

import faiss
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from PIL import Image

pd.set_option("display.max_columns", 100)
pd.set_option("display.max_colwidth", 120)

ROOT = Path("..").resolve()
FINAL_DB_DIR = ROOT / "data" / "final_db" / "5gb"

FAISS_PATH = FINAL_DB_DIR / "faiss.index"
EMBEDDINGS_PATH = FINAL_DB_DIR / "embeddings.npy"
MAPPING_PATH = FINAL_DB_DIR / "mapping.csv"
PROMPT_METADATA_PATH = FINAL_DB_DIR / "prompt_metadata.parquet"

FINAL_DB_DIR
""",
    """
index = faiss.read_index(str(FAISS_PATH))
embeddings = np.load(EMBEDDINGS_PATH).astype("float32")
mapping_df = pd.read_csv(MAPPING_PATH)

if PROMPT_METADATA_PATH.exists():
    prompt_df = pd.read_parquet(PROMPT_METADATA_PATH)
else:
    prompt_df = None

print("index.ntotal:", index.ntotal)
print("embeddings:", embeddings.shape)
print("mapping_df:", mapping_df.shape)

mapping_df.head()
""",
    """
def normalize_vectors(x):
    x = x.astype("float32")
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return x / norms


def show_search_results(result_df, image_col="final_image_path", title_cols=None, n=8, cols=4):
    if title_cols is None:
        title_cols = ["original_food_name", "business_category", "product_group"]

    sample = result_df.head(n).copy()
    rows = int(np.ceil(len(sample) / cols))

    plt.figure(figsize=(cols * 4, rows * 4))

    for i, (_, row) in enumerate(sample.iterrows(), start=1):
        image_path = Path(str(row[image_col]))

        plt.subplot(rows, cols, i)
        plt.axis("off")

        try:
            img = Image.open(image_path).convert("RGB")
            plt.imshow(img)

            title_parts = []
            for col in title_cols:
                if col in row and pd.notna(row[col]):
                    title_parts.append(str(row[col]))

            if "score" in row:
                title_parts.append(f"score={row['score']:.3f}")

            plt.title("\\n".join(title_parts)[:80])

        except Exception as e:
            plt.title(f"error: {e}")

    plt.tight_layout()
    plt.show()
""",
    """
def search_by_item_index(item_index=0, top_k=8):
    query = embeddings[item_index:item_index+1].astype("float32")
    query = normalize_vectors(query)

    scores, indices = index.search(query, top_k)

    result_df = mapping_df.iloc[indices[0]].copy()
    result_df["score"] = scores[0]

    return result_df


result_df = search_by_item_index(0, top_k=8)
display(result_df[[
    "faiss_index_id",
    "original_food_name",
    "business_category",
    "product_group",
    "score",
    "final_image_path",
]])
show_search_results(result_df, n=8, cols=4)
""",
    """
def search_by_metadata_filter(
    query_text=None,
    business_category=None,
    product_group=None,
    food_name=None,
    top_k=8,
    candidate_limit=500,
):
    df = mapping_df.copy()

    if business_category:
        df = df[df["business_category"].astype(str) == business_category]

    if product_group:
        df = df[df["product_group"].astype(str) == product_group]

    terms = []

    if query_text:
        terms.extend(str(query_text).split())

    if food_name:
        terms.append(food_name)

    if terms:
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
        search_text = df[existing_cols].fillna("").astype(str).agg(" ".join, axis=1)

        mask = pd.Series(False, index=df.index)

        for term in terms:
            mask = mask | search_text.str.contains(term, case=False, regex=False)

        matched = df[mask]

        if len(matched) > 0:
            df = matched

    if len(df) == 0:
        return df

    candidate_ids = df["faiss_index_id"].astype(int).to_numpy()
    candidate_vectors = embeddings[candidate_ids]
    query_vector = normalize_vectors(candidate_vectors).mean(axis=0, keepdims=True)
    query_vector = normalize_vectors(query_vector)

    search_k = min(max(candidate_limit, top_k), index.ntotal)
    scores, indices = index.search(query_vector.astype("float32"), search_k)

    candidate_set = set(candidate_ids.tolist())

    rows = []

    for score, idx in zip(scores[0], indices[0]):
        if int(idx) in candidate_set:
            row = mapping_df.iloc[int(idx)].copy()
            row["score"] = float(score)
            rows.append(row)

        if len(rows) >= top_k:
            break

    if not rows:
        fallback = df.head(top_k).copy()
        fallback["score"] = 0.0
        return fallback

    return pd.DataFrame(rows)
""",
    """
# 테스트 1: 디저트 케이크
result_df = search_by_metadata_filter(
    query_text="딸기 케이크",
    business_category="dessert",
    product_group="cake",
    top_k=8,
)

display(result_df[[
    "original_food_name",
    "business_category",
    "product_group",
    "score",
    "final_image_path",
]])
show_search_results(result_df, n=8, cols=4)
""",
    """
# 테스트 2: 카페 브런치
result_df = search_by_metadata_filter(
    query_text="브런치 샌드위치",
    business_category="cafe",
    product_group="brunch",
    top_k=8,
)

display(result_df[[
    "original_food_name",
    "business_category",
    "product_group",
    "score",
    "final_image_path",
]])
show_search_results(result_df, n=8, cols=4)
""",
    """
# 테스트 3: 주점 해산물 안주
result_df = search_by_metadata_filter(
    query_text="회 해산물 안주",
    business_category="pub",
    product_group="seafood_side",
    top_k=8,
)

display(result_df[[
    "original_food_name",
    "business_category",
    "product_group",
    "score",
    "final_image_path",
]])
show_search_results(result_df, n=8, cols=4)
""",
    """
# 테스트 4: 음식점 한식
result_df = search_by_metadata_filter(
    query_text="찌개 한식",
    business_category="restaurant",
    product_group="korean_food",
    top_k=8,
)

display(result_df[[
    "original_food_name",
    "business_category",
    "product_group",
    "score",
    "final_image_path",
]])
show_search_results(result_df, n=8, cols=4)
""",
    """
# 카테고리별 데이터 개수 확인
business_dist = mapping_df["business_category"].value_counts().reset_index()
business_dist.columns = ["business_category", "count"]
display(business_dist)

product_dist = mapping_df["product_group"].value_counts().reset_index()
product_dist.columns = ["product_group", "count"]
display(product_dist.head(30))
""",
    """
# 검색 결과를 prompt_rag에 넣기 좋은 형태로 확인
if prompt_df is not None:
    display(prompt_df.head(10))
else:
    print("prompt_metadata.parquet does not exist.")
""",
]


def main() -> None:
    make_notebook(metadata_eda_cells, "notebooks/01_metadata_eda.ipynb")
    make_notebook(quality_check_cells, "notebooks/02_quality_check.ipynb")
    make_notebook(retrieval_test_cells, "notebooks/03_retrieval_test.ipynb")


if __name__ == "__main__":
    main()
