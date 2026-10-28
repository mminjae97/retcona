"""Where the models run (infra/inference_client.py): the GPU through DirectML,
or the CPU — and the CPU when the GPU fails. ONNX Runtime and the tokenizer
are stood in for; no model is loaded."""

import json

import numpy as np
import pytest
import transformers

from infra import inference_client
from infra.inference_client import OnnxModel, get_inference_client, model_directory


class _Session:
    def __init__(self, provider: str, fails: bool) -> None:
        self.provider = provider
        self.fails = fails

    def get_providers(self) -> list[str]:
        return [self.provider, "CPUExecutionProvider"] if self.provider != "CPUExecutionProvider" else [self.provider]

    def run(self, outputs, feed):
        if self.fails:
            # As DirectML's can come back on a Korean Windows: undecodable.
            raise UnicodeDecodeError("utf-8", b"\xb8", 0, 1, "invalid start byte")
        return [np.full((1, 3), 1.0 if self.provider == "CPUExecutionProvider" else 2.0)]


@pytest.fixture
def model_dir(tmp_path, monkeypatch):
    (tmp_path / "model.onnx").write_bytes(b"")
    (tmp_path / "config.json").write_text(json.dumps({"id2label": {"0": "O", "1": "B-PS"}}), encoding="utf-8")
    monkeypatch.setattr(transformers.AutoTokenizer, "from_pretrained", lambda directory: "tokenizer")
    return tmp_path


def _onnxruntime(monkeypatch, *, directml: bool, gpu_session_fails_to_open=False, gpu_runs_fail=False):
    import onnxruntime

    available = ["DmlExecutionProvider", "CPUExecutionProvider"] if directml else ["CPUExecutionProvider"]
    monkeypatch.setattr(onnxruntime, "get_available_providers", lambda: available)
    opened = []

    def session(path, provider):
        opened.append(provider)
        if provider == "DmlExecutionProvider" and gpu_session_fails_to_open:
            raise UnicodeDecodeError("utf-8", b"\xb8", 0, 1, "invalid start byte")
        return _Session(provider, fails=provider == "DmlExecutionProvider" and gpu_runs_fail)

    monkeypatch.setattr(inference_client, "_session", session)
    return opened


_FEED = {"input_ids": [[0, 5, 2]], "attention_mask": [[1, 1, 1]]}


def test_a_gpu_is_used_where_there_is_one(model_dir, monkeypatch):
    _onnxruntime(monkeypatch, directml=True)
    model = OnnxModel(model_dir, "auto")
    assert model.on_gpu and model.device == "GPU (DirectML)"
    assert model.pad_to_multiple_of == 32
    assert model.run(["logits"], _FEED)[0][0, 0] == 2.0
    assert model.id2label == {0: "O", 1: "B-PS"}


def test_a_gpu_that_fails_a_run_gives_way_to_the_cpu_for_good(model_dir, monkeypatch):
    opened = _onnxruntime(monkeypatch, directml=True, gpu_runs_fail=True)
    model = OnnxModel(model_dir, "auto")
    assert model.on_gpu
    # The run is done again on the CPU, and the CPU is kept.
    assert model.run(["logits"], _FEED)[0][0, 0] == 1.0
    assert not model.on_gpu and model.pad_to_multiple_of is None
    model.run(["logits"], _FEED)
    assert opened == ["DmlExecutionProvider", "CPUExecutionProvider"]


def test_a_gpu_session_that_wont_open_leaves_the_cpu(model_dir, monkeypatch):
    opened = _onnxruntime(monkeypatch, directml=True, gpu_session_fails_to_open=True)
    for device in ("auto", "gpu"):
        assert not OnnxModel(model_dir, device).on_gpu
    assert opened == ["DmlExecutionProvider", "CPUExecutionProvider"] * 2


def test_cpu_never_tries_the_gpu_and_no_directml_means_the_cpu(model_dir, monkeypatch):
    opened = _onnxruntime(monkeypatch, directml=True)
    assert not OnnxModel(model_dir, "cpu").on_gpu
    assert opened == ["CPUExecutionProvider"]
    opened = _onnxruntime(monkeypatch, directml=False)
    assert not OnnxModel(model_dir, "gpu").on_gpu
    assert opened == ["CPUExecutionProvider"]


def test_a_failure_on_the_cpu_is_raised(model_dir, monkeypatch):
    _onnxruntime(monkeypatch, directml=False)
    model = OnnxModel(model_dir, "auto")
    model._session.fails = True
    with pytest.raises(UnicodeDecodeError):
        model.run(["logits"], _FEED)


def test_a_model_is_its_exported_directory_or_a_run_with_one_in_onnx(tmp_path):
    exported = tmp_path / "run" / "onnx"
    exported.mkdir(parents=True)
    (exported / "model.onnx").write_bytes(b"")
    assert model_directory(str(exported)) == exported
    assert model_directory(str(tmp_path / "run")) == exported
    with pytest.raises(RuntimeError, match="export_onnx.py"):
        model_directory(str(tmp_path))


def test_the_device_comes_from_inference_device(monkeypatch):
    for value, device in (("", "auto"), ("CPU", "cpu"), ("gpu", "gpu"), ("cuda", "auto")):
        monkeypatch.setenv("INFERENCE_DEVICE", value)
        get_inference_client.cache_clear()
        assert get_inference_client()._device == device
    get_inference_client.cache_clear()
