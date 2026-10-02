import pytest
from pathlib import Path
from types import SimpleNamespace
pytest.importorskip('playwright')
from scripts.leboncoin_browser import browser_profile


def test_fresh_profiles_are_isolated_and_removed_after_failure(monkeypatch):
    monkeypatch.setenv('LEBONCOIN_BROWSER_MODE','playwright')
    paths=[]
    closed=[]
    def launch(path, **kwargs):
        paths.append(path)
        assert Path(path).is_dir()
        return SimpleNamespace(close=lambda: closed.append(path))
    fake=SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
    for _ in range(2):
        with pytest.raises(RuntimeError):
            with browser_profile(fake,'fresh'):
                raise RuntimeError('simulated navigation failure')
        assert not Path(paths[-1]).exists()
    assert paths[0]!=paths[1]
    assert closed==paths


def test_persistent_profile_preserved(tmp_path,monkeypatch):
    monkeypatch.setenv('LEBONCOIN_BROWSER_MODE','playwright')
    monkeypatch.setenv('LEBONCOIN_PROFILE_DIR',str(tmp_path/'saved'))
    def launch(path, **kwargs):
        (Path(path)/'marker').write_text('preserve')
        return SimpleNamespace(close=lambda: None)
    fake=SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
    with browser_profile(fake,'persistent'):pass
    assert (tmp_path/'saved'/'marker').read_text()=='preserve'
