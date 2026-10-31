from pathlib import Path

import yaml


def test_runtime_uses_host_sdk_without_vendored_dependencies():
    root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((root / "extension.yaml").read_text())
    assert manifest["python_requirements"] == []
    assert not list((root / "wheels").glob("*.whl"))
    assert list((root / "dev-wheels").glob("flowsteward_extension_sdk-*.whl"))
