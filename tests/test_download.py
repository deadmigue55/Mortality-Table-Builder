import pytest
import requests

from mortality.config import Paths
from mortality.ingest import download


@pytest.fixture
def paths(tmp_path):
    return Paths(root=tmp_path, data=tmp_path / "data").ensure()


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"HTTP {self.status}")

    def iter_content(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i : i + size]


class FakeSession:
    def __init__(self, body: bytes = b"hello world", status: int = 200):
        self.body, self.status, self.calls = body, status, 0

    def get(self, url, **kwargs):
        self.calls += 1
        return FakeResponse(self.body, self.status)


def test_safe_name():
    assert download.safe_name("a b/c?.csv") == "a_b_c_.csv"
    with pytest.raises(ValueError):
        download.safe_name("///")


def test_fetch_saves_file_and_manifest(paths):
    result = download.fetch(
        "https://example.org/data/file.csv", source="demo", session=FakeSession(), paths=paths
    )
    assert result.path == paths.raw / "demo" / "file.csv"
    assert result.path.read_bytes() == b"hello world"
    assert result.sha256 == download.sha256_file(result.path)
    rows = download.read_manifest(paths)
    assert len(rows) == 1
    assert rows[0]["source"] == "demo"
    assert rows[0]["file"] == "demo/file.csv"
    assert rows[0]["bytes"] == "11"


def test_fetch_reuses_existing_file(paths):
    session = FakeSession()
    download.fetch("https://example.org/f.csv", source="demo", session=session, paths=paths)
    again = download.fetch("https://example.org/f.csv", source="demo", session=session, paths=paths)
    assert again.skipped
    assert session.calls == 1
    assert len(download.read_manifest(paths)) == 1


def test_fetch_force_redownloads(paths):
    session = FakeSession()
    download.fetch("https://example.org/f.csv", source="demo", session=session, paths=paths)
    again = download.fetch(
        "https://example.org/f.csv", source="demo", session=session, force=True, paths=paths
    )
    assert not again.skipped
    assert session.calls == 2
    assert len(download.read_manifest(paths)) == 1  # replaced, not duplicated


def test_failed_download_leaves_no_partial_file(paths):
    with pytest.raises(requests.HTTPError):
        download.fetch(
            "https://example.org/missing.csv",
            source="demo",
            session=FakeSession(status=404),
            paths=paths,
        )
    folder = paths.raw / "demo"
    assert not list(folder.glob("*"))
    assert download.read_manifest(paths) == []


def test_html_page_is_rejected_as_zip(paths):
    html = FakeSession(body=b"<!DOCTYPE html><title>Pagina no encontrada</title>")
    with pytest.raises(download.NotAFileError):
        download.fetch("https://example.org/data.zip", source="demo", session=html, paths=paths)
    assert not list((paths.raw / "demo").glob("*"))
    assert download.read_manifest(paths) == []


def test_register_local(paths):
    folder = paths.raw / "demo"
    folder.mkdir(parents=True)
    extracted = folder / "inner.csv"
    extracted.write_text("a,b\n1,2\n")
    result = download.register_local(
        extracted, source="demo", url="https://example.org/x.zip", paths=paths
    )
    assert result.bytes == extracted.stat().st_size
    assert download.read_manifest(paths)[0]["url"] == "https://example.org/x.zip"
