from pathlib import Path

from ansysem_agent_bridge.skill_installer import install_skills, skill_status, uninstall_skills


def _by_name(payload: dict) -> dict[str, dict]:
    return {item["skill"]: item for item in payload["skills"]}


def test_install_both_skills_and_uninstall_owned_content(tmp_path: Path) -> None:
    installed = install_skills("all", root=tmp_path)
    assert installed["status"] == "ready"
    assert set(_by_name(installed)) == {"ansysem-agent-bridge", "ansysem-kb-docs"}
    assert skill_status("all", root=tmp_path)["status"] == "ready"
    removed = uninstall_skills("all", root=tmp_path)
    assert removed["status"] == "removed"
    assert not (tmp_path / "ansysem-agent-bridge").exists()


def test_full_install_preserves_complete_unmanaged_docs_skill(tmp_path: Path) -> None:
    destination = tmp_path / "ansysem-kb-docs"
    (destination / "agents").mkdir(parents=True)
    (destination / "SKILL.md").write_text(
        "---\n"
        "name: ansysem-kb-docs\n"
        'description: "A complete Harness docs Skill used for tests."\n'
        "---\n\n"
        "# Docs\n",
        encoding="utf-8",
    )
    (destination / "agents" / "openai.yaml").write_text(
        'interface:\n  display_name: "Harness Docs"\n', encoding="utf-8"
    )
    result = install_skills("all", root=tmp_path)
    docs = _by_name(result)["ansysem-kb-docs"]
    assert docs["status"] == "preserved"
    assert docs["satisfied_by_existing"] is True


def test_unknown_operator_skill_fails_closed(tmp_path: Path) -> None:
    destination = tmp_path / "ansysem-agent-bridge"
    destination.mkdir()
    (destination / "SKILL.md").write_text("unmanaged", encoding="utf-8")
    result = install_skills("bridge", root=tmp_path)
    assert result["status"] == "conflict"
    assert result["reused"] is False
