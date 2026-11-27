from pathlib import Path

import pytest

from app.reader import ASSETS_DIR
from tools.gen_version import generate, version_info_text, version_parts


def test_version_parts_accepts_semver_and_pads_windows_version():
    assert version_parts("1.1.0") == (1, 1, 0, 0)
    assert version_parts("2.3.4.5") == (2, 3, 4, 5)


@pytest.mark.parametrize("version", ["1.1", "v1.1.0", "1.1.0.0.0", "1.1.-1", "1.70000.0"])
def test_version_parts_rejects_invalid_windows_versions(version):
    with pytest.raises(ValueError):
        version_parts(version)


def test_generated_version_files_share_one_version(tmp_path: Path):
    version_path = tmp_path / "version_info.txt"
    inno_path = tmp_path / "installer" / "version.iss"

    generate("1.2.3", version_path, inno_path)

    assert "filevers=(1, 2, 3, 0)" in version_path.read_text(encoding="utf-8")
    inno = inno_path.read_text(encoding="utf-8")
    assert '#define AppVersion "1.2.3"' in inno
    assert '#define AppVersionQuad "1.2.3.0"' in inno


def test_reader_assets_ship_foliate_kernel():
    html = (ASSETS_DIR / "reader.html").read_text(encoding="utf-8")
    assert "vendor/foliate-js/foliate.bundle.js" in html
    bundle = ASSETS_DIR / "vendor" / "foliate-js" / "foliate.bundle.js"
    assert bundle.is_file() and bundle.stat().st_size > 100_000
    assert (ASSETS_DIR / "vendor" / "foliate-js" / "LICENSE").is_file()
    assert "foliate-view" in (ASSETS_DIR / "reader.js").read_text(encoding="utf-8")


def test_version_info_contains_required_windows_fields():
    content = version_info_text("1.1.0")
    for field in ("FileDescription", "ProductName", "CompanyName", "LegalCopyright"):
        assert field in content
    assert 'StringStruct("FileVersion", "1.1.0.0")' in content
    assert 'StringStruct("ProductVersion", "1.1.0.0")' in content
