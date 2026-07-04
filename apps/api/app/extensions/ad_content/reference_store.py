import json
import sqlite3
from pathlib import Path

from app.core.config import settings
from app.extensions.ad_content.product_visualizer import ProductVisual, ProductVisualization


def normalize_product_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


class ProductVisualProfileStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = Path(db_path or settings.product_visual_db_path)

    def _connect(self) -> sqlite3.Connection:
        if self.db_path.parent != Path("."):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS product_visual_profiles (
                normalized_name TEXT PRIMARY KEY,
                original_name TEXT NOT NULL,
                category TEXT NOT NULL,
                english_name TEXT NOT NULL,
                visual_description_json TEXT NOT NULL,
                serving_style_json TEXT NOT NULL,
                must_show_json TEXT NOT NULL,
                must_not_replace_with_json TEXT NOT NULL,
                reference_query TEXT NOT NULL DEFAULT '',
                reference_sources_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        return connection

    def get(self, product_name: str) -> ProductVisual | None:
        normalized_name = normalize_product_name(product_name)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT original_name, english_name, category, visual_description_json,
                       serving_style_json, must_show_json, must_not_replace_with_json
                FROM product_visual_profiles
                WHERE normalized_name = ?
                """,
                (normalized_name,),
            ).fetchone()
        if row is None:
            return None
        return ProductVisual(
            original_name=product_name,
            english_name=row[1],
            category=row[2],
            visual_description=json.loads(row[3]),
            serving_style=json.loads(row[4]),
            must_show=json.loads(row[5]),
            must_not_replace_with=json.loads(row[6]),
        )

    def get_many(self, product_names: list[str]) -> dict[str, ProductVisual]:
        return {
            product_name: product
            for product_name in product_names
            if (product := self.get(product_name)) is not None
        }

    def upsert(
        self,
        product: ProductVisual,
        *,
        reference_query: str = "",
        reference_sources: list[dict[str, str]] | None = None,
    ) -> None:
        normalized_name = normalize_product_name(product.original_name)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO product_visual_profiles (
                    normalized_name,
                    original_name,
                    category,
                    english_name,
                    visual_description_json,
                    serving_style_json,
                    must_show_json,
                    must_not_replace_with_json,
                    reference_query,
                    reference_sources_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(normalized_name) DO UPDATE SET
                    original_name = excluded.original_name,
                    category = excluded.category,
                    english_name = excluded.english_name,
                    visual_description_json = excluded.visual_description_json,
                    serving_style_json = excluded.serving_style_json,
                    must_show_json = excluded.must_show_json,
                    must_not_replace_with_json = excluded.must_not_replace_with_json,
                    reference_query = excluded.reference_query,
                    reference_sources_json = excluded.reference_sources_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    normalized_name,
                    product.original_name,
                    product.category,
                    product.english_name,
                    json.dumps(product.visual_description, ensure_ascii=False),
                    json.dumps(product.serving_style, ensure_ascii=False),
                    json.dumps(product.must_show, ensure_ascii=False),
                    json.dumps(product.must_not_replace_with, ensure_ascii=False),
                    reference_query,
                    json.dumps(reference_sources or [], ensure_ascii=False),
                ),
            )

    def upsert_visualization(
        self,
        visualization: ProductVisualization,
        *,
        reference_query: str = "",
        reference_sources: list[dict[str, str]] | None = None,
    ) -> None:
        for product in visualization.products:
            self.upsert(
                product,
                reference_query=reference_query,
                reference_sources=reference_sources,
            )
