"""Build small self-contained HTML galleries for a completed benchmark run.

The Notion connector accepts inline HTML attachments up to 200 KiB. This tool
creates one attachment per LLM, with source photos and meme/no-meme poster
results grouped by image model. Thumbnails are progressively compressed until
each file fits the connector limit.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


MAX_ATTACHMENT_BYTES = 195 * 1024


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args()


def read_records(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "trials.jsonl"
    if not path.is_file():
        raise FileNotFoundError(path)
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def image_data_uri(path: Path, width: int, quality: int) -> str:
    with Image.open(path) as image:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((width, round(width * 1.35)), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, "JPEG", quality=quality, optimize=True)
    payload = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{payload}"


def safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("_") or "model"


def render_gallery(
    llm_model: str,
    records: list[dict[str, Any]],
    *,
    width: int,
    quality: int,
) -> str:
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_case[record["case_id"]].append(record)

    parts = [
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>",
        "<style>",
        "body{font:13px/1.45 system-ui,sans-serif;margin:16px;color:#222}",
        "h1{font-size:20px}h2{font-size:16px;margin-top:24px}",
        ".source,.pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}",
        ".source{grid-template-columns:160px 1fr;align-items:center}",
        ".card{border:1px solid #ddd;border-radius:10px;padding:8px;background:#fff}",
        "img{width:100%;height:auto;border-radius:7px;background:#eee}",
        ".meta{font-size:11px;color:#666;margin-top:5px;word-break:break-word}",
        ".error{color:#a00;background:#fff3f3;padding:10px;border-radius:7px}",
        "</style></head><body>",
        f"<h1>{html.escape(llm_model)}</h1>",
        "<p>동일한 원본과 광고 조건에서 이미지 모델·밈 유무를 비교합니다.</p>",
    ]

    for case_id in sorted(by_case):
        case_records = by_case[case_id]
        first = case_records[0]
        product_name = html.escape(str(first.get("product_name") or case_id))
        parts.append(f"<h2>{product_name} · {html.escape(case_id)}</h2>")

        source = Path(str(first.get("saved_source_image") or first.get("source_image")))
        if source.is_file():
            source_uri = image_data_uri(source, width, quality)
            parts.append(
                "<div class='source'><div class='card'>"
                f"<img src='{source_uri}' alt='원본'></div>"
                "<div><strong>원본 사진</strong><br>"
                f"{product_name}<br><span class='meta'>{html.escape(str(source))}</span>"
                "</div></div>"
            )

        by_image: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for record in case_records:
            by_image[record["image_model"]][record.get("meme_arm") or "single"] = record

        for image_model in sorted(by_image):
            parts.append(f"<h3>{html.escape(image_model)}</h3><div class='pair'>")
            for arm in ("without_meme", "with_meme"):
                record = by_image[image_model].get(arm)
                label = "밈 없음" if arm == "without_meme" else "밈 있음"
                parts.append(f"<div class='card'><strong>{label}</strong>")
                if not record:
                    parts.append("<div class='error'>결과 없음</div></div>")
                    continue
                poster = Path(str(record.get("generated_image_with_copy") or ""))
                if record.get("success") and poster.is_file():
                    headline = html.escape(str(record.get("headline") or ""))
                    caption = html.escape(str(record.get("instagram_caption") or ""))[:500]
                    fallback = "사용" if record.get("fallback_copy_used") else "미사용"
                    uri = image_data_uri(poster, width, quality)
                    parts.append(
                        f"<div><b>{headline}</b></div><div>{caption}</div>"
                        f"<img src='{uri}' alt='{label}'>"
                        f"<div class='meta'>fallback: {fallback} · "
                        f"{record.get('wall_latency_ms', 0):.0f} ms</div>"
                    )
                else:
                    error = html.escape(str(record.get("error") or "생성 실패"))
                    parts.append(f"<div class='error'>{error}</div>")
                parts.append("</div>")
            parts.append("</div>")

    parts.append("</body></html>")
    return "".join(parts)


def main() -> None:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    output_dir = (args.output_dir or run_dir / "notion-gallery").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in read_records(run_dir):
        grouped[record["llm_model"]].append(record)

    manifest: list[dict[str, Any]] = []
    for llm_model, records in sorted(grouped.items()):
        rendered = ""
        selected = None
        for width, quality in ((180, 42), (160, 36), (140, 30), (120, 25), (100, 22)):
            rendered = render_gallery(
                llm_model,
                records,
                width=width,
                quality=quality,
            )
            if len(rendered.encode("utf-8")) <= MAX_ATTACHMENT_BYTES:
                selected = (width, quality)
                break
        if selected is None:
            raise RuntimeError(f"Could not fit Notion attachment for {llm_model}")

        path = output_dir / f"{safe_name(llm_model)}.html"
        path.write_text(rendered, encoding="utf-8")
        manifest.append(
            {
                "llm_model": llm_model,
                "file": str(path),
                "bytes": path.stat().st_size,
                "thumbnail_width": selected[0],
                "jpeg_quality": selected[1],
                "records": len(records),
            }
        )

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(manifest_path)


if __name__ == "__main__":
    main()
