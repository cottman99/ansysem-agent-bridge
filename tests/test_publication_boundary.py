from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".md", ".py", ".toml", ".yml", ".yaml", ".json", ".txt"}
NON_PUBLIC_PARTS = {".git", ".venv", ".codex_tmp", ".pytest_cache", "__pycache__", "build", "dist"}


def _is_public_candidate(path: Path) -> bool:
    return not any(part in NON_PUBLIC_PARTS for part in path.relative_to(REPO_ROOT).parts)


def test_public_tree_excludes_private_and_vendor_payloads() -> None:
    forbidden_suffixes = {".aedt", ".aedtz", ".pdf", ".dxf", ".dwg"}
    forbidden_directory_suffix = ".aedb"
    findings = []
    for path in REPO_ROOT.rglob("*"):
        if not _is_public_candidate(path):
            continue
        if (
            path.is_dir()
            and path.name.casefold().endswith(forbidden_directory_suffix)
            or path.is_file()
            and path.suffix.casefold() in forbidden_suffixes
        ):
            findings.append(path.relative_to(REPO_ROOT).as_posix())
    assert findings == []


def test_public_text_has_no_known_private_identifiers() -> None:
    forbidden = [
        "p" + "fli",
        "DieC" + "_QFN",
        "客户" + "资料",
        "/ho" + "me/" + "p" + "fli",
        "F:" + "\\p" + "fli",
        "100." + "65.",
    ]
    findings = []
    for path in REPO_ROOT.rglob("*"):
        if (
            not path.is_file()
            or path.suffix.casefold() not in TEXT_SUFFIXES
            or not _is_public_candidate(path)
        ):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in forbidden:
            if token.casefold() in text.casefold():
                findings.append((path.relative_to(REPO_ROOT).as_posix(), token))
    assert findings == []


def test_bilingual_readmes_include_the_source_backed_live_edit_chart() -> None:
    relative_path = "docs/assets/readme/supervised-live-edit-latency.png"
    english = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    assert (REPO_ROOT / relative_path).is_file()
    assert relative_path in english
    assert relative_path in chinese
    for value in ("937", "12", "204", "296–453"):
        assert value in english
        assert value in chinese
