"""Load and verify the versioned application-generation resources."""

from __future__ import annotations

import hashlib
from pathlib import Path

RESOURCE_ROOT = Path(__file__).resolve().parent.parent / "generator_resources"
INSTRUCTION_ROOT = RESOURCE_ROOT / "instructions"
UPSTREAM_SHA = "c7bd494f11e792508534c1c795e24694498395c4"
INSTRUCTION_VERSION = "tasko-apply-1.4.2"


def load_instruction(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError("instruction name is invalid")
    path = INSTRUCTION_ROOT / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"generation instruction not found: {name}")
    return path.read_text(encoding="utf-8")


def verify_copied_resources() -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in (RESOURCE_ROOT / "CHECKSUMS.sha256").read_text(
        encoding="utf-8"
    ).splitlines():
        expected, relative_path = line.split("  ", 1)
        path = RESOURCE_ROOT / relative_path
        if not path.is_file():
            raise RuntimeError(f"copied generation resource is missing: {relative_path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(
                f"copied generation resource checksum mismatch: {relative_path}"
            )
        checksums[relative_path] = actual
    return checksums


def main() -> None:
    checksums = verify_copied_resources()
    print(
        f"Verified {len(checksums)} copied resources from upstream {UPSTREAM_SHA}."
    )


if __name__ == "__main__":
    main()
