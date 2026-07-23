from __future__ import annotations

import argparse
import builtins
from types import SimpleNamespace

import pytest

from scripts import train_meme_lora


class _FakeCuda:
    def __init__(self, *, bf16_supported: bool) -> None:
        self._bf16_supported = bf16_supported

    def is_bf16_supported(self) -> bool:
        return self._bf16_supported

    @staticmethod
    def current_device() -> int:
        return 0


def _fake_torch(*, bf16_supported: bool) -> SimpleNamespace:
    return SimpleNamespace(
        cuda=_FakeCuda(bf16_supported=bf16_supported),
        float16="torch.float16",
        bfloat16="torch.bfloat16",
    )


def test_auto_compute_dtype_uses_fp16_on_t4_class_gpu() -> None:
    name, dtype = train_meme_lora._resolve_compute_dtype(
        _fake_torch(bf16_supported=False),
        "auto",
    )

    assert name == "float16"
    assert dtype == "torch.float16"


def test_auto_compute_dtype_uses_bf16_on_a100_class_gpu() -> None:
    name, dtype = train_meme_lora._resolve_compute_dtype(
        _fake_torch(bf16_supported=True),
        "auto",
    )

    assert name == "bfloat16"
    assert dtype == "torch.bfloat16"


def test_explicit_bf16_is_rejected_when_device_does_not_support_it() -> None:
    with pytest.raises(SystemExit, match="does not report BF16 support"):
        train_meme_lora._resolve_compute_dtype(
            _fake_torch(bf16_supported=False),
            "bfloat16",
        )


def test_qlora_model_loader_uses_nf4_double_quant_and_kbit_preparation() -> None:
    quantization_kwargs: dict[str, object] = {}
    model_kwargs: dict[str, object] = {}
    prepare_kwargs: dict[str, object] = {}

    class FakeBitsAndBytesConfig:
        def __init__(self, **kwargs: object) -> None:
            quantization_kwargs.update(kwargs)

    model = SimpleNamespace(config=SimpleNamespace(use_cache=True))

    class FakeAutoModel:
        @staticmethod
        def from_pretrained(model_name: str, **kwargs: object) -> object:
            model_kwargs["model_name"] = model_name
            model_kwargs.update(kwargs)
            return model

    def fake_prepare(candidate: object, **kwargs: object) -> object:
        assert candidate is model
        prepare_kwargs.update(kwargs)
        return candidate

    loaded, quantization_config = train_meme_lora._load_qlora_model(
        AutoModelForCausalLM=FakeAutoModel,
        BitsAndBytesConfig=FakeBitsAndBytesConfig,
        prepare_model_for_kbit_training=fake_prepare,
        torch=_fake_torch(bf16_supported=False),
        base_revision="a" * 40,
        compute_dtype="torch.float16",
    )

    assert loaded is model
    assert model.config.use_cache is False
    assert model_kwargs["model_name"] == train_meme_lora.BASE_MODEL
    assert model_kwargs["revision"] == "a" * 40
    assert model_kwargs["quantization_config"] is quantization_config
    assert model_kwargs["device_map"] == {"": 0}
    assert quantization_kwargs == {
        "load_in_4bit": True,
        "bnb_4bit_quant_type": "nf4",
        "bnb_4bit_use_double_quant": True,
        "bnb_4bit_compute_dtype": "torch.float16",
    }
    assert prepare_kwargs == {
        "use_gradient_checkpointing": True,
        "gradient_checkpointing_kwargs": {"use_reentrant": False},
    }


def test_quantization_manifest_records_reproducibility_contract() -> None:
    assert train_meme_lora._quantization_manifest("float16") == {
        "method": "bitsandbytes",
        "load_in_4bit": True,
        "quant_type": "nf4",
        "use_double_quant": True,
        "compute_dtype": "float16",
    }


def test_validate_only_path_never_imports_torch_or_bitsandbytes(monkeypatch) -> None:
    args = argparse.Namespace(
        train_file=train_meme_lora.DEFAULT_TRAIN_FILE,
        validation_file=train_meme_lora.DEFAULT_VALIDATION_FILE,
        overlap_file=[],
        validate_only=True,
        allow_unreviewed_seeds=False,
        base_revision=None,
        output_dir=None,
        epochs=3.0,
        learning_rate=2e-4,
        max_length=train_meme_lora.DEFAULT_MAX_LENGTH,
        compute_dtype="auto",
        gradient_accumulation_steps=8,
        lora_r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        seed=42,
    )
    train_example = object()
    validation_example = object()

    monkeypatch.setattr(train_meme_lora, "parse_args", lambda: args)
    monkeypatch.setattr(
        train_meme_lora,
        "_load_jsonl",
        lambda _path, split: [
            train_example if split == "train" else validation_example
        ],
    )
    monkeypatch.setattr(
        train_meme_lora,
        "_validate_split_isolation",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        train_meme_lora,
        "_validate_comparison_isolation",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        train_meme_lora,
        "_materialize",
        lambda _example: ({"prompt": [], "completion": []}, None, None),
    )
    monkeypatch.setattr(
        train_meme_lora,
        "_train",
        lambda *_args: pytest.fail("validate-only must not enter the training path"),
    )

    real_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name.split(".", maxsplit=1)[0] in {"torch", "bitsandbytes"}:
            pytest.fail(f"validate-only imported optional GPU dependency: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    train_meme_lora.main()


def test_cli_defaults_are_t4_safe_and_keep_qlora_auto_dtype(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["train_meme_lora"])

    args = train_meme_lora.parse_args()

    assert args.max_length == 4096
    assert args.compute_dtype == "auto"


def test_qlora_optimizer_is_paged_8bit() -> None:
    assert train_meme_lora.QLORA_OPTIMIZER == "paged_adamw_8bit"
