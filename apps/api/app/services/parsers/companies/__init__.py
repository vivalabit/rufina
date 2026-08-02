from importlib import import_module
from typing import Any

from app.core.settings import Settings
from app.core.vacancy_sources import DIRECT_COMPANY_PARSERS


def create_direct_company_parsers(settings: Settings) -> dict[str, Any]:
    """Instantiate registered company parsers without a growing import switch."""

    parsers: dict[str, Any] = {}
    for definition in DIRECT_COMPANY_PARSERS:
        module_name, separator, class_name = definition.parser_path.partition(":")
        if not separator:
            raise RuntimeError(f"Invalid parser path for {definition.id}: {definition.parser_path}")
        parser_class = getattr(import_module(module_name), class_name)
        kwargs = {
            argument: getattr(settings, setting) for argument, setting in definition.settings_map
        }
        parsers[definition.id] = parser_class(**kwargs)
    return parsers


__all__ = ["create_direct_company_parsers"]
