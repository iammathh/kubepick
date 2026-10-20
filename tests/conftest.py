import pytest


# Every test runs with its own HOME and XDG folders, so nothing touches the real configuration
@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
	monkeypatch.setenv("HOME", str(tmp_path))
	monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
	monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
	monkeypatch.delenv("AWS_CONFIG_FILE", raising=False)
	return tmp_path
