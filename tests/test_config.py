from pathlib import Path

import pytest

from mortality import config
from mortality.cli import main


def test_project_root_contains_pyproject():
    assert (config.PROJECT_ROOT / "pyproject.toml").is_file()


def test_find_project_root_fails_outside_project(tmp_path):
    with pytest.raises(FileNotFoundError):
        config.find_project_root(tmp_path)


def test_default_data_dir(monkeypatch):
    monkeypatch.delenv("MTB_DATA_DIR", raising=False)
    paths = config.get_paths()
    assert paths.data == config.PROJECT_ROOT / "data"
    assert paths.raw == paths.data / "raw"
    assert paths.database.suffix == ".sqlite"


def test_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MTB_DATA_DIR", str(tmp_path / "elsewhere"))
    paths = config.get_paths().ensure()
    assert paths.data == (tmp_path / "elsewhere").resolve()
    assert paths.raw.is_dir() and paths.processed.is_dir()


def test_hmd_credentials_missing(monkeypatch):
    monkeypatch.delenv("HMD_USERNAME", raising=False)
    monkeypatch.delenv("HMD_PASSWORD", raising=False)
    with pytest.raises(config.MissingCredentialsError):
        config.hmd_credentials()


def test_hmd_credentials_hide_password(monkeypatch):
    monkeypatch.setenv("HMD_USERNAME", "actuary@example.com")
    monkeypatch.setenv("HMD_PASSWORD", "s3cret")
    creds = config.hmd_credentials()
    assert creds.password == "s3cret"
    assert "s3cret" not in repr(creds)


def test_cli_doctor_runs(monkeypatch, capsys):
    monkeypatch.setenv("HMD_USERNAME", "actuary@example.com")
    monkeypatch.setenv("HMD_PASSWORD", "s3cret")
    assert main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "Mortality Table Builder" in out
    assert "s3cret" not in out


def test_rscript_override(monkeypatch, tmp_path):
    fake = tmp_path / "Rscript.exe"
    monkeypatch.setenv("RSCRIPT", str(fake))
    assert config.find_rscript() == fake


def test_paths_are_absolute():
    assert Path(config.get_paths().data).is_absolute()
