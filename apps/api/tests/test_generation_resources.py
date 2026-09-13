from pathlib import Path

import pytest

from app.services.generation_resources import (
    INSTRUCTION_VERSION,
    RESOURCE_ROOT,
    UPSTREAM_SHA,
    load_instruction,
    verify_copied_resources,
)


def test_copied_upstream_resources_match_recorded_checksums() -> None:
    verified = verify_copied_resources()

    assert len(verified) == 25
    assert verified["upstream/cv/main_example.tex"]
    assert verified["upstream/cover_letters/cover.cls"]
    assert verified["upstream/tools/verify_pdf.py"]
    assert verified["upstream/tools/verify_layout.py"]


@pytest.mark.parametrize(
    "name,source",
    [
        ("trust_and_facts", "01-candidate-profile.md"),
        ("evaluate", "04-job-evaluation.md"),
        ("draft", "05-cv-templates.md"),
        ("review", "09-web-research.md"),
        ("verify", "verify_pdf.py"),
    ],
)
def test_adapted_instructions_record_source_and_upstream_sha(
    name: str,
    source: str,
) -> None:
    instruction = load_instruction(name)

    assert source in instruction
    assert UPSTREAM_SHA in instruction
    assert "Adapted from upstream" in instruction


def test_generation_resources_publish_a_version_and_license() -> None:
    assert INSTRUCTION_VERSION == "tasko-apply-1.0.0"
    assert (RESOURCE_ROOT / "upstream" / "LICENSE").read_text(
        encoding="utf-8"
    ).startswith("MIT License")
    assert Path(RESOURCE_ROOT / "PROVENANCE.md").is_file()


def test_instruction_loader_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="invalid"):
        load_instruction("../evaluate")
