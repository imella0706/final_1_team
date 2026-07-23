"""Pre-flight validation for the v2 pipeline batch.

Validates the selected DataRecord list *before* any model calls are made.
No source files are modified during validation.

Checks performed:
1.  Image path existence
2.  Image file extension support
3.  Image file integrity (magic bytes)
4.  Prompt field presence (non-empty)
5.  Image-prompt matching (final_image_id ↔ prompt_keywords not empty)
6.  Duplicate final_image_id detection
7.  Output file collision detection
8.  Duplicate prompt_keywords within the batch (warning only, not fatal)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.v2_pipeline.loader import DataRecord
from app.v2_pipeline.matcher import SUPPORTED_EXTENSIONS

_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@dataclass
class ValidationIssue:
    level: str          # "error" | "warning"
    image_id: str
    message: str


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, image_id: str, message: str) -> None:
        self.issues.append(ValidationIssue("error", image_id, message))

    def add_warning(self, image_id: str, message: str) -> None:
        self.issues.append(ValidationIssue("warning", image_id, message))


def validate_batch(
    records: list[DataRecord],
    output_dir: Path,
) -> ValidationReport:
    """Run all pre-flight checks and return a ValidationReport.

    Args:
        records: The exact batch of DataRecord objects to be processed.
        output_dir: The batch-specific output directory
                    (e.g. data/outputs/v2_model_results/batch_10/results/).

    Returns:
        ValidationReport with errors and warnings populated.
    """
    report = ValidationReport()

    # 1. Duplicate ID check
    seen_ids: dict[str, int] = {}
    for idx, rec in enumerate(records):
        if rec.final_image_id in seen_ids:
            report.add_error(
                rec.final_image_id,
                f"Duplicate final_image_id at row {idx} "
                f"(first seen at row {seen_ids[rec.final_image_id]}).",
            )
        else:
            seen_ids[rec.final_image_id] = idx

    for rec in records:
        img_id = rec.final_image_id

        # 2. Image path existence
        if not rec.abs_image_path.exists():
            report.add_error(img_id, f"Image file not found: {rec.abs_image_path}")
            continue  # skip further checks for this record

        # 3. Extension check
        ext = rec.abs_image_path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            report.add_error(
                img_id,
                f"Unsupported image extension '{ext}'. "
                f"Supported: {sorted(SUPPORTED_EXTENSIONS)}",
            )
            continue

        # 4. File integrity (magic bytes, non-empty)
        try:
            raw_header = rec.abs_image_path.read_bytes()[:8]
        except OSError as exc:
            report.add_error(img_id, f"Cannot read image file: {exc}")
            continue

        if not raw_header:
            report.add_error(img_id, "Image file is empty.")
            continue

        # A few source files carry a .jpg suffix while their bytes are PNG.
        # Validate the actual supported encoding, then let matcher create the
        # correct data URL media type; source files are never renamed.
        if not (
            raw_header[:3] == _JPEG_MAGIC
            or raw_header[:8] == _PNG_MAGIC
            or (raw_header[:4] == b"RIFF" and raw_header[8:12] == b"WEBP")
        ):
            report.add_error(img_id, "Unsupported or corrupt image content.")

        # 5. Prompt presence
        if not rec.prompt_keywords:
            report.add_error(img_id, "prompt_keywords is empty.")
        if not rec.caption:
            report.add_warning(img_id, "caption is empty.")

        # 6. Image-prompt match (ID must be non-empty and path resolvable)
        if not rec.final_image_id:
            report.add_error(img_id, "final_image_id is empty — cannot match.")
        if not rec.final_image_path:
            report.add_error(img_id, "final_image_path is empty — cannot match.")

        # 7. Output file collision
        expected_output = output_dir / f"{rec.final_image_id}.json"
        if expected_output.exists():
            report.add_warning(
                img_id,
                f"Output file already exists (will be skipped in resume mode): "
                f"{expected_output}",
            )

    # 8. Duplicate prompt_keywords warning
    seen_prompts: dict[str, str] = {}
    for rec in records:
        kw = rec.prompt_keywords
        if kw in seen_prompts:
            report.add_warning(
                rec.final_image_id,
                f"prompt_keywords identical to record {seen_prompts[kw]}.",
            )
        else:
            seen_prompts[kw] = rec.final_image_id

    return report
