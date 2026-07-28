from __future__ import annotations

import copy
import hashlib
import shutil
import zipfile
from pathlib import Path

from lxml import etree


REFERENCE = Path(
    "/Users/eduardishchenko/Main/Swiss Career/Intership/DE/"
    "Motivationschreiben_Ishchenko.docx"
)
OUTPUT = Path(
    "/Users/eduardishchenko/coding/tasko/output/"
    "Bewerbungsschreiben_UBS_IT-way-up_2027_Ishchenko.docx"
)
EXPECTED_SHA256 = "65e9f460c945ebdb14639243738f51497c8eba3d0254f16f13f69a6118869bd8"

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}
W = f"{{{NS['w']}}}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

REPLACEMENTS = {
    0: "UBS Switzerland AG\nRecruiting Team\nZürich\nSchweiz",
    1: "Männedorf, 28.07.2026",
    2: "Bewerbung für die 2027 IT-Lehre «IT-way-up»",
    3: (
        "Sehr geehrtes UBS Recruiting-Team,\n\n"
        "hiermit bewerbe ich mich für die zweijährige IT-Lehre «IT-way-up» 2027 "
        "in der Applikationsentwicklung bei UBS. Als Software-Engineering-Student "
        "mit praktischer Erfahrung in Python, Automatisierung, Datenverarbeitung, "
        "API-Integrationen und Backend-Entwicklung möchte ich mein technisches "
        "Wissen gezielt vertiefen und in einem professionellen Umfeld in die Praxis "
        "umsetzen. Die Verbindung aus fundierter Ausbildung, persönlicher Begleitung "
        "und Mitarbeit an realen IT-Projekten spricht mich besonders an."
    ),
    4: (
        "In meinen bisherigen Projekten habe ich Python-Backend-Services, APIs und "
        "automatisierte Datenverarbeitungsprozesse für reale Anwendungen entwickelt. "
        "Dabei habe ich gelernt, zuverlässig zu arbeiten, Fehler systematisch zu "
        "analysieren und Lösungen schrittweise zu verbessern. Zudem habe ich "
        "LLM-gestützte Funktionen mit strukturierten Ausgaben, Validierung und "
        "Fehlerbehandlung integriert. Neue Technologien eigne ich mir schnell an; "
        "gleichzeitig schätze ich den Austausch im Team und bringe mich gerne aktiv "
        "in gemeinsame Aufgaben ein."
    ),
    5: (
        "UBS reizt mich besonders, weil ich in einem internationalen Umfeld "
        "verschiedene Programmiersprachen kennenlernen und an digitalen Lösungen "
        "mitwirken kann, die im Alltag vieler Menschen eingesetzt werden. Die "
        "Möglichkeit, auch den sinnvollen Einsatz von KI mitzugestalten, passt sehr "
        "gut zu meinen Interessen und bisherigen Erfahrungen. Gerne überzeuge ich "
        "Sie in einem persönlichen Gespräch von meiner Motivation und Lernbereitschaft."
    ),
    6: "\nFreundliche Grüsse,\n",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace_paragraph_text(paragraph: etree._Element, text: str) -> None:
    runs = paragraph.findall("w:r", NS)
    if not runs:
        raise ValueError("Editable paragraph has no source run to clone.")

    template_run = runs[0]
    template_rpr = template_run.find("w:rPr", NS)

    for child in list(paragraph):
        if child.tag != W + "pPr":
            paragraph.remove(child)

    run = etree.SubElement(paragraph, W + "r")
    if template_rpr is not None:
        run.append(copy.deepcopy(template_rpr))

    pieces = text.split("\n")
    for index, piece in enumerate(pieces):
        if index:
            etree.SubElement(run, W + "br")
        if piece:
            node = etree.SubElement(run, W + "t")
            node.set(XML_SPACE, "preserve")
            node.text = piece


def main() -> None:
    if sha256(REFERENCE) != EXPECTED_SHA256:
        raise RuntimeError("Reference template changed; re-distillation is required.")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    working = OUTPUT.with_suffix(".working.docx")
    shutil.copy2(REFERENCE, working)

    with zipfile.ZipFile(working, "r") as archive:
        entries = [(item, archive.read(item.filename)) for item in archive.infolist()]

    document_bytes = dict((item.filename, data) for item, data in entries)[
        "word/document.xml"
    ]
    root = etree.fromstring(document_bytes)
    body = root.find("w:body", NS)
    if body is None:
        raise RuntimeError("Document body not found.")
    paragraphs = body.findall("w:p", NS)
    if len(paragraphs) < 11:
        raise RuntimeError(f"Unexpected template structure: {len(paragraphs)} paragraphs.")

    for index, replacement in REPLACEMENTS.items():
        replace_paragraph_text(paragraphs[index], replacement)

    updated_document = etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone="yes"
    )

    with zipfile.ZipFile(OUTPUT, "w") as archive:
        for item, data in entries:
            if item.filename == "word/document.xml":
                data = updated_document
            archive.writestr(item, data)

    working.unlink()
    print(OUTPUT)


if __name__ == "__main__":
    main()
