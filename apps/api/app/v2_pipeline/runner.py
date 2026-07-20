"""Async v2 batch runner using the project's existing generation flow."""
from __future__ import annotations
import asyncio, hashlib
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from app.extensions.ad_content.router import generate_content
from app.extensions.ad_content.schemas import AdContentRequest, BlogImageInput, ImageModel
from app.modules.ad_copy.schemas import AdCopyRequest, AdModel
from app.v2_pipeline.loader import DataRecord
from app.v2_pipeline.logger import RunLogger
from app.v2_pipeline.matcher import MatchError, build_copy_request_payload, match_record
from app.v2_pipeline.result_writer import ResultWriter
from app.v2_pipeline.state_manager import StateManager
from app.v2_pipeline.artifact_renderer import save_channel_artifacts

def _verify_prompt_integrity(original: str, stored_hash: str) -> None:
    if hashlib.sha256(original.encode("utf-8")).hexdigest() != stored_hash:
        raise RuntimeError("Prompt integrity check failed: prompt_keywords was mutated.")

def _model_context(llm_model: AdModel, image_model: ImageModel) -> dict[str, str]:
    """Record the production models used without logging prompt text or secrets."""
    llm_value = getattr(llm_model, "value", str(llm_model))
    image_value = getattr(image_model, "value", str(image_model))
    return {
        "llm_model": llm_value,
        # The existing visualizer/reference analyzer receives copy_request,
        # so it uses this same configured text/vision-capable runtime.
        "vision_runtime_model": llm_value,
        "image_model": image_value,
    }


async def _process_one(record: DataRecord, max_retries: int, logger: RunLogger, writer: ResultWriter, state: StateManager, image_model: ImageModel, llm_model: AdModel = AdModel.QWEN_2_5_7B, channel: str = "instagram") -> dict[str, Any]:
    image_id = record.final_image_id
    models = _model_context(llm_model, image_model)
    try:
        matched = match_record(record)
        _verify_prompt_integrity(record.prompt_keywords, matched.prompt_hash)
    except (MatchError, RuntimeError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.log_item_failed(image_id, record.final_image_path, "", 0, error)
        state.mark_failed(image_id, "", 0, error)
        writer.write_result(image_id, "", record.final_image_path, "", "failed", 0, error, {"models": models})
        return {"image_id": image_id, "status": "failed", "error": error}
    logger.log_item_start(image_id, record.final_image_path, matched.prompt_hash)
    last_error = ""
    for attempt in range(1, max_retries + 2):
        try:
            started = perf_counter()
            # Invoke the same API orchestration used by the existing project.
            # This preserves the existing Naver Blog branch, including its
            # uploaded-photo behavior and skipped image-generation step.
            copy_request = AdCopyRequest.model_validate(
                build_copy_request_payload(matched, channel, llm_model.value)
            )
            is_naver_blog = channel == "naver_blog"
            content_request = AdContentRequest(
                copy=copy_request,
                image_model=image_model,
                reference_image_data_url=matched.image_data_url,
                blog_images=(
                    [
                        BlogImageInput(
                            id=image_id,
                            name=record.product_name,
                            data_url=matched.image_data_url,
                        )
                    ]
                    if is_naver_blog
                    else []
                ),
            )
            content_response = await generate_content(content_request)
            latency_ms = round((perf_counter() - started) * 1000)
            copy_data = content_response.copy_result.model_dump(mode="json")
            artifacts = save_channel_artifacts(
                writer.results_dir.parent,
                image_id,
                channel,
                copy_data,
                content_response.image.image_base64,
                content_response.image.media_type,
            )
            result_path = writer.write_result(image_id, matched.prompt_hash, record.final_image_path, "", "success", attempt, None, {"channel": channel, "models": models, "copy": copy_data, "artifacts": {"v2": artifacts, "existing_api": content_response.artifacts}, "image": {"model": content_response.image.model, "media_type": content_response.image.media_type, "latency_ms": content_response.image.latency_ms, "image_base64": content_response.image.image_base64}, "image_prompt": content_response.image_prompt, "negative_prompt": content_response.negative_prompt, "validation": content_response.validation})
            state.mark_success(image_id, matched.prompt_hash, str(result_path), attempt)
            logger.log_item_success(image_id, record.final_image_path, matched.prompt_hash, attempt, str(result_path), latency_ms)
            return {"image_id": image_id, "status": "success", "attempts": attempt}
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt <= max_retries:
                logger.log_retry(image_id, attempt, last_error)
                await asyncio.sleep(2.0 * attempt)
    writer.write_result(image_id, matched.prompt_hash, record.final_image_path, "", "failed", max_retries + 1, last_error, {"models": models})
    state.mark_failed(image_id, matched.prompt_hash, max_retries + 1, last_error)
    logger.log_item_failed(image_id, record.final_image_path, matched.prompt_hash, max_retries + 1, last_error)
    return {"image_id": image_id, "status": "failed", "error": last_error}

async def run_batch(records: list[DataRecord], batch_size: int, output_dir_root: Any, max_retries: int, resume: bool, dry_run: bool, image_model: ImageModel, verbose: bool = True, channel: str = "instagram", llm_model: AdModel = AdModel.QWEN_2_5_7B) -> int:
    output_dir = output_dir_root
    writer, state = ResultWriter(output_dir), StateManager(output_dir / "state.json")
    logger = RunLogger(output_dir / "logs", batch_size, verbose)
    started, summaries = datetime.now(UTC), []
    logger.log_run_start("", str(output_dir))
    try:
        for record in records:
            prompt_hash = hashlib.sha256(record.prompt_keywords.encode("utf-8")).hexdigest()
            if resume and state.is_done(record.final_image_id):
                logger.log_item_skipped(record.final_image_id, "already successful in this batch state")
                summaries.append({"image_id": record.final_image_id, "status": "skipped"})
            elif dry_run:
                logger.log_dry_run_item(record.final_image_id, record.final_image_path, record.abs_image_path.exists(), prompt_hash, str(writer.result_path(record.final_image_id)))
                summaries.append({"image_id": record.final_image_id, "status": "skipped", "dry_run": True, "models": _model_context(llm_model, image_model)})
            else:
                summaries.append(await _process_one(
                    record,
                    max_retries=max_retries,
                    logger=logger,
                    writer=writer,
                    state=state,
                    image_model=image_model,
                    llm_model=llm_model,
                    channel=channel,
                ))
    finally:
        ended = datetime.now(UTC)
        writer.write_manifest(batch_size, started, ended, summaries)
        logger.log_run_end(len(summaries), sum(x["status"] == "success" for x in summaries), sum(x["status"] == "failed" for x in summaries), sum(x["status"] == "skipped" for x in summaries), (ended-started).total_seconds())
        logger.close()
    return 1 if any(x["status"] == "failed" for x in summaries) else 0
