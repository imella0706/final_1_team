from __future__ import annotations

from pathlib import Path

import pytest

from sns_trend.storage import (
    StorageError,
    discover_latest_gcs_processed_version,
    parse_gcs_uri,
    sync_gcs_prefix_to_local,
    upload_json_to_gcs,
)


class FakeBlob:
    def __init__(self, name: str, body: str = "payload") -> None:
        self.name = name
        self.body = body
        self.size = len(body.encode("utf-8"))
        self.uploaded: str | None = None
        self.content_type: str | None = None

    def download_to_filename(self, filename: str) -> None:
        Path(filename).write_text(self.body, encoding="utf-8")

    def upload_from_string(self, body: str, *, content_type: str) -> None:
        self.uploaded = body
        self.content_type = content_type
        self.size = len(body.encode("utf-8"))


class FakeBucket:
    def __init__(self, name: str) -> None:
        self.name = name
        self.uploads: dict[str, FakeBlob] = {}

    def blob(self, name: str) -> FakeBlob:
        blob = FakeBlob(name, "")
        self.uploads[name] = blob
        return blob


class FakeClient:
    def __init__(self, blobs: list[FakeBlob] | None = None) -> None:
        self.blobs = blobs or []
        self.buckets: dict[str, FakeBucket] = {}

    def bucket(self, name: str) -> FakeBucket:
        return self.buckets.setdefault(name, FakeBucket(name))

    def list_blobs(self, bucket_name: str, *, prefix: str) -> list[FakeBlob]:
        return [blob for blob in self.blobs if blob.name.startswith(prefix)]


def test_parse_gcs_uri_requires_bucket_and_prefix() -> None:
    assert parse_gcs_uri("gs://ssakda/projects/brandmate/data") == (
        "ssakda",
        "projects/brandmate/data",
    )

    with pytest.raises(StorageError):
        parse_gcs_uri("gs://ssakda")

    with pytest.raises(StorageError):
        parse_gcs_uri("data/processed/sns_trend")


def test_sync_gcs_prefix_to_local_downloads_required_processed_files(tmp_path: Path) -> None:
    prefix = "projects/brandmate/data/processed/sns_trend/v2/cross_platform_signal_top_candidates"
    client = FakeClient(
        [
            FakeBlob(f"{prefix}/cross_platform_signal_top_candidates.json", "{}"),
            FakeBlob(f"{prefix}/cross_platform_signal_top_candidates.csv", "meme_id\n"),
            FakeBlob(f"{prefix}/ignored.txt", "ignore"),
        ]
    )

    summary = sync_gcs_prefix_to_local(
        gcs_prefix=f"gs://ssakda/{prefix}/",
        local_dir=tmp_path,
        required_file_names={
            "cross_platform_signal_top_candidates.json",
            "cross_platform_signal_top_candidates.csv",
        },
        client=client,
    )

    assert summary["status"] == "synced"
    assert summary["file_count"] == 2
    assert (tmp_path / "cross_platform_signal_top_candidates.json").read_text(
        encoding="utf-8"
    ) == "{}"
    assert (tmp_path / "cross_platform_signal_top_candidates.csv").read_text(
        encoding="utf-8"
    ) == "meme_id\n"
    assert not (tmp_path / "ignored.txt").exists()


def test_sync_gcs_prefix_to_local_rejects_missing_required_file(tmp_path: Path) -> None:
    prefix = "projects/brandmate/data/processed/sns_trend/v2/cross_platform_signal_top_candidates"
    client = FakeClient(
        [FakeBlob(f"{prefix}/cross_platform_signal_top_candidates.json", "{}")]
    )

    with pytest.raises(StorageError, match="missing"):
        sync_gcs_prefix_to_local(
            gcs_prefix=f"gs://ssakda/{prefix}/",
            local_dir=tmp_path,
            required_file_names={
                "cross_platform_signal_top_candidates.json",
                "cross_platform_signal_top_candidates.csv",
            },
            client=client,
        )


def test_discover_latest_gcs_processed_version_picks_highest_numeric_version() -> None:
    root = "projects/brandmate/data/processed/sns_trend"
    artifact_name = "cross_platform_signal_top_candidates"
    client = FakeClient(
        [
            FakeBlob(f"{root}/v2/{artifact_name}/cross_platform_signal_top_candidates.json"),
            FakeBlob(f"{root}/v2/{artifact_name}/cross_platform_signal_top_candidates.csv"),
            FakeBlob(f"{root}/v10/{artifact_name}/cross_platform_signal_top_candidates.json"),
            FakeBlob(f"{root}/v3/other_artifact/output.json"),
            FakeBlob(f"{root}/draft/{artifact_name}/ignored.json"),
            FakeBlob("projects/brandmate/data/processed/other/v99/output.json"),
        ]
    )

    result = discover_latest_gcs_processed_version(
        gcs_root=f"gs://ssakda/{root}/",
        artifact_name=artifact_name,
        client=client,
    )

    assert result["status"] == "discovered"
    assert result["version"] == "v10"
    assert result["version_number"] == 10
    assert result["source_gcs_prefix"] == f"gs://ssakda/{root}/v10/{artifact_name}/"
    assert result["discovered_versions"] == ["v2", "v3", "v10"]
    assert result["object_count_by_version"] == {"v2": 2, "v3": 1, "v10": 1}
    assert result["artifact_object_count"] == 1


def test_discover_latest_gcs_processed_version_ignores_non_version_prefixes() -> None:
    root = "projects/brandmate/data/processed/sns_trend"
    client = FakeClient(
        [
            FakeBlob(f"{root}/latest/cross_platform_signal_top_candidates/data.json"),
            FakeBlob(f"{root}/v0/cross_platform_signal_top_candidates/data.json"),
            FakeBlob(f"{root}/version=2/cross_platform_signal_top_candidates/data.json"),
        ]
    )

    with pytest.raises(StorageError, match="No processed version"):
        discover_latest_gcs_processed_version(
            gcs_root=f"gs://ssakda/{root}",
            artifact_name="cross_platform_signal_top_candidates",
            client=client,
        )


def test_upload_json_to_gcs_writes_json_body() -> None:
    client = FakeClient()

    result = upload_json_to_gcs(
        gcs_uri="gs://ssakda/projects/brandmate/logs/run/validation_summary.json",
        payload={"status": "passed", "count": 20},
        client=client,
    )

    upload = client.buckets["ssakda"].uploads[
        "projects/brandmate/logs/run/validation_summary.json"
    ]
    assert result["status"] == "uploaded"
    assert upload.content_type == "application/json; charset=utf-8"
    assert '"status": "passed"' in (upload.uploaded or "")
