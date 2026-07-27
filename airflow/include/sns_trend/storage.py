from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


class StorageError(RuntimeError):
    """Raised when a storage operation cannot be completed safely."""


_VERSION_PATTERN = re.compile(r"^v([1-9]\d*)$")


def parse_gcs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise StorageError(f"GCS URI must start with gs://: {uri}")
    without_scheme = uri.removeprefix("gs://")
    bucket, separator, prefix = without_scheme.partition("/")
    if not bucket or not separator:
        raise StorageError(f"GCS URI must include bucket and object prefix: {uri}")
    normalized_prefix = prefix.strip("/")
    if not normalized_prefix:
        raise StorageError(f"GCS URI must include object prefix: {uri}")
    return bucket, normalized_prefix


def _storage_client() -> Any:
    try:
        from google.cloud import storage
    except ModuleNotFoundError as error:  # pragma: no cover - image dependency path
        raise StorageError(
            "google-cloud-storage is required for GCS sync. "
            "Rebuild the Airflow image after updating requirements.airflow.txt."
        ) from error
    return storage.Client()


def _safe_relative_path(blob_name: str, prefix: str) -> Path:
    if blob_name == prefix:
        raise StorageError(f"GCS object is the prefix itself, not a file: {blob_name}")
    prefix_with_slash = f"{prefix.rstrip('/')}/"
    if not blob_name.startswith(prefix_with_slash):
        raise StorageError(f"GCS object is outside expected prefix: {blob_name}")

    relative = PurePosixPath(blob_name.removeprefix(prefix_with_slash))
    if not str(relative) or str(relative).endswith("/"):
        raise StorageError(f"GCS object is not a file: {blob_name}")
    if relative.is_absolute() or ".." in relative.parts:
        raise StorageError(f"Unsafe GCS object path: {blob_name}")
    return Path(*relative.parts)


def _version_number(version: str) -> int | None:
    match = _VERSION_PATTERN.fullmatch(version)
    if not match:
        return None
    return int(match.group(1))


def discover_latest_gcs_processed_version(
    *,
    gcs_root: str,
    artifact_name: str,
    client: Any | None = None,
) -> dict[str, Any]:
    bucket_name, root_prefix = parse_gcs_uri(gcs_root)
    active_client = client or _storage_client()
    root_prefix = root_prefix.rstrip("/")
    root_prefix_with_slash = f"{root_prefix}/"

    try:
        blobs = list(active_client.list_blobs(bucket_name, prefix=root_prefix_with_slash))
    except Exception as error:  # pragma: no cover - external GCS/auth path
        raise StorageError(
            "Failed to list GCS processed root. "
            "Check ADC with `gcloud auth application-default login` and bucket access: "
            f"{gcs_root}"
        ) from error

    versions: dict[str, dict[str, Any]] = {}
    for blob in blobs:
        blob_name = getattr(blob, "name", "")
        if not blob_name or not blob_name.startswith(root_prefix_with_slash):
            continue

        relative = PurePosixPath(blob_name.removeprefix(root_prefix_with_slash))
        if not relative.parts:
            continue

        version = relative.parts[0]
        number = _version_number(version)
        if number is None:
            continue

        info = versions.setdefault(
            version,
            {
                "version": version,
                "version_number": number,
                "object_count": 0,
                "artifact_object_count": 0,
            },
        )
        if not blob_name.endswith("/"):
            info["object_count"] += 1
            if len(relative.parts) >= 2 and relative.parts[1] == artifact_name:
                info["artifact_object_count"] += 1

    if not versions:
        raise StorageError(f"No processed version directories found under {gcs_root}")

    latest = max(versions.values(), key=lambda item: item["version_number"])
    source_gcs_prefix = (
        f"gs://{bucket_name}/{root_prefix}/{latest['version']}/{artifact_name}/"
    )

    return {
        "status": "discovered",
        "source_gcs_root": gcs_root.rstrip("/") + "/",
        "source_gcs_prefix": source_gcs_prefix,
        "version": latest["version"],
        "version_number": latest["version_number"],
        "discovered_versions": [
            item["version"]
            for item in sorted(versions.values(), key=lambda item: item["version_number"])
        ],
        "object_count_by_version": {
            item["version"]: item["object_count"]
            for item in sorted(versions.values(), key=lambda item: item["version_number"])
        },
        "artifact_object_count": latest["artifact_object_count"],
    }


def sync_gcs_prefix_to_local(
    *,
    gcs_prefix: str,
    local_dir: Path,
    required_file_names: set[str] | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    bucket_name, prefix = parse_gcs_uri(gcs_prefix)
    active_client = client or _storage_client()
    bucket = active_client.bucket(bucket_name)
    try:
        blobs = list(active_client.list_blobs(bucket_name, prefix=f"{prefix}/"))
    except Exception as error:  # pragma: no cover - external GCS/auth path
        raise StorageError(
            "Failed to list GCS processed prefix. "
            "Check ADC with `gcloud auth application-default login` and bucket access: "
            f"{gcs_prefix}"
        ) from error
    if not blobs:
        raise StorageError(f"No GCS objects found under {gcs_prefix}")

    local_dir.mkdir(parents=True, exist_ok=True)

    synced_files: list[dict[str, Any]] = []
    downloaded_names: set[str] = set()
    for blob in blobs:
        blob_name = getattr(blob, "name", "")
        if not blob_name or blob_name.endswith("/"):
            continue

        relative_path = _safe_relative_path(blob_name, prefix)
        if required_file_names and relative_path.name not in required_file_names:
            continue

        target_path = local_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            blob.download_to_filename(str(target_path))
        except Exception as error:  # pragma: no cover - external GCS/auth path
            raise StorageError(
                "Failed to download GCS object to local cache: "
                f"gs://{bucket.name}/{blob_name} -> {target_path}"
            ) from error
        downloaded_names.add(relative_path.name)
        synced_files.append(
            {
                "gcs_uri": f"gs://{bucket.name}/{blob_name}",
                "local_path": str(target_path),
                "size": getattr(blob, "size", None),
            }
        )

    if required_file_names:
        missing = sorted(required_file_names.difference(downloaded_names))
        if missing:
            raise StorageError(
                "Required processed files are missing from GCS prefix: "
                + ", ".join(missing)
            )

    return {
        "status": "synced",
        "source_gcs_prefix": gcs_prefix.rstrip("/") + "/",
        "local_dir": str(local_dir),
        "file_count": len(synced_files),
        "files": synced_files,
    }


def upload_json_to_gcs(
    *,
    gcs_uri: str,
    payload: dict[str, Any],
    client: Any | None = None,
) -> dict[str, Any]:
    bucket_name, object_name = parse_gcs_uri(gcs_uri)
    active_client = client or _storage_client()
    bucket = active_client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    try:
        blob.upload_from_string(body, content_type="application/json; charset=utf-8")
    except Exception as error:  # pragma: no cover - external GCS/auth path
        raise StorageError(
            "Failed to upload validation summary to GCS. "
            "Check ADC with `gcloud auth application-default login` and bucket write access: "
            f"{gcs_uri}"
        ) from error
    return {
        "status": "uploaded",
        "gcs_uri": gcs_uri,
        "size": len(body.encode("utf-8")),
    }
