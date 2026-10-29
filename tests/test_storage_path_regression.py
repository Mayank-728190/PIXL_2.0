import os
from pathlib import Path

import pytest

from pixl.core.config import settings
from pixl.core.exceptions import UnprocessableError
from pixl.core.storage import storage_path


def test_storage_rejects_traversal_and_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_STORAGE_PATH", str(tmp_path / "storage"))
    for key in ("../escape", "", "nested/../../escape", str(tmp_path / "outside")):
        with pytest.raises(UnprocessableError):
            storage_path(key)
    assert storage_path("published/agency/asset.png").name == "asset.png"


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-path namespace regression")
def test_extended_prefix_does_not_break_containment(tmp_path, monkeypatch):
    root = (tmp_path / "storage").resolve()
    monkeypatch.setattr(settings, "LOCAL_STORAGE_PATH", str(root))
    original_resolve = type(root).resolve

    def mixed_namespace_resolve(self, *args, **kwargs):
        resolved = original_resolve(self, *args, **kwargs)
        if "asset.png" in str(self) and not str(resolved).startswith("\\\\?\\"):
            return Path("\\\\?\\" + str(resolved))
        return resolved

    monkeypatch.setattr(type(root), "resolve", mixed_namespace_resolve)
    assert storage_path("published/agency/asset.png").name == "asset.png"
    with pytest.raises(UnprocessableError):
        storage_path("../outside/asset.png")
