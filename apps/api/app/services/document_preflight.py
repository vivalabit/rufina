from typing import Any

from app.services.document_analysis import analyze_docx_source, unsupported_report
from app.services.document_security import DocumentSecurityError


def analyze_document_template(content: bytes, document_type: str) -> dict[str, Any]:
    try:
        if document_type != "cover_letter":
            return unsupported_report(
                element="documentType",
                description="Only cover-letter DOCX templates are supported",
            )
        return analyze_docx_source(content, "cover_letter").preflight_report()
    except DocumentSecurityError as exc:
        return unsupported_report(
            element="invalidDocument",
            description=str(exc),
        )
    except Exception:
        return unsupported_report(
            element="invalidDocument",
            description="DOCX could not be read safely",
        )
