import json
from datetime import datetime
from types import SimpleNamespace

from app.extensions.ad_content import artifact_store


class DummyResponse:
    def __init__(self) -> None:
        self.models = {"copy_model": "copy-model", "image_model": "image-model"}
        self.copy_result = SimpleNamespace(model="copy-model", latency_ms=123)
        self.image = SimpleNamespace(
            model="image-model",
            media_type="image/png",
            image_base64="AA==",
            latency_ms=456,
        )
        self.image_prompt = "generated prompt"

    def model_dump(self, mode: str = "json", by_alias: bool = False) -> dict:
        return {
            "models": self.models,
            "copy_result": {"model": self.copy_result.model, "latency_ms": self.copy_result.latency_ms},
            "image": {
                "model": self.image.model,
                "media_type": self.image.media_type,
                "image_base64": self.image.image_base64,
                "latency_ms": self.image.latency_ms,
            },
            "image_prompt": self.image_prompt,
        }


def test_save_ad_content_artifacts_includes_saved_time(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(artifact_store, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(artifact_store, "ARTIFACT_ROOT", tmp_path / "artifacts")

    result = artifact_store.save_ad_content_artifacts(DummyResponse())

    metadata_path = tmp_path / result["metadata_json"]
    assert metadata_path.exists()

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert "saved_at" in metadata
    assert "generated_at" in metadata
    assert "total_latency_ms" in metadata

    datetime.fromisoformat(metadata["saved_at"])
    assert metadata["total_latency_ms"] == 579
