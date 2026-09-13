from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.models.generation_workflow import CoverLetterDraft, DraftBundle
from app.models.resume import FinalResume, ResumeBasics
from app.services.generation_resources import RESOURCE_ROOT

LatexEngine = Literal["lualatex", "xelatex"]
LatexRunner = Callable[..., subprocess.CompletedProcess[str]]
UPSTREAM_ROOT = RESOURCE_ROOT / "upstream"


class GenerationLatexError(RuntimeError):
    pass


@dataclass(frozen=True)
class CompiledDocument:
    document_type: Literal["tailored_resume", "cover_letter"]
    engine: LatexEngine
    file_name: str
    tex_source: str
    pdf: bytes
    compile_log: str


def render_generation_bundle(
    bundle: DraftBundle,
    *,
    runner: LatexRunner = subprocess.run,
) -> tuple[CompiledDocument, ...]:
    rendered: list[CompiledDocument] = []
    if bundle.resume is not None:
        rendered.append(
            compile_latex_document(
                document_type="tailored_resume",
                engine="lualatex",
                file_name="cv.pdf",
                tex_source=build_resume_tex(bundle.resume),
                runner=runner,
            )
        )
    if bundle.cover_letter is not None:
        rendered.append(
            compile_latex_document(
                document_type="cover_letter",
                engine="xelatex",
                file_name="cover-letter.pdf",
                tex_source=build_cover_letter_tex(bundle.cover_letter),
                runner=runner,
                include_cover_assets=True,
            )
        )
    return tuple(rendered)


def compile_latex_document(
    *,
    document_type: Literal["tailored_resume", "cover_letter"],
    engine: LatexEngine,
    file_name: str,
    tex_source: str,
    runner: LatexRunner = subprocess.run,
    include_cover_assets: bool = False,
) -> CompiledDocument:
    executable = shutil.which(engine)
    if executable is None:
        raise GenerationLatexError(f"Required TeX engine is unavailable: {engine}")
    with tempfile.TemporaryDirectory(prefix="tasko-generation-") as temp_directory:
        workdir = Path(temp_directory)
        source_path = workdir / "document.tex"
        source_path.write_text(tex_source, encoding="utf-8")
        if include_cover_assets:
            shutil.copy2(UPSTREAM_ROOT / "cover_letters" / "cover.cls", workdir / "cover.cls")
            shutil.copytree(
                UPSTREAM_ROOT / "cover_letters" / "OpenFonts",
                workdir / "OpenFonts",
            )
        command = [
            executable,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-no-shell-escape",
            "document.tex",
        ]
        logs: list[str] = []
        for _ in range(2):
            try:
                result = runner(
                    command,
                    cwd=workdir,
                    capture_output=True,
                    check=True,
                    text=True,
                    timeout=60,
                )
            except FileNotFoundError as exc:
                raise GenerationLatexError(f"Required TeX engine is unavailable: {engine}") from exc
            except subprocess.TimeoutExpired as exc:
                raise GenerationLatexError(f"{engine} timed out") from exc
            except subprocess.CalledProcessError as exc:
                detail = (exc.stdout or "") + "\n" + (exc.stderr or "")
                raise GenerationLatexError(
                    f"{engine} could not compile the server-owned template: {detail[-4000:]}"
                ) from exc
            logs.append((result.stdout or "") + (result.stderr or ""))
        pdf_path = workdir / "document.pdf"
        if not pdf_path.is_file():
            raise GenerationLatexError(f"{engine} completed without producing a PDF")
        pdf = pdf_path.read_bytes()
        if not pdf.startswith(b"%PDF-"):
            raise GenerationLatexError(f"{engine} produced an invalid PDF")
        return CompiledDocument(
            document_type=document_type,
            engine=engine,
            file_name=file_name,
            tex_source=tex_source,
            pdf=pdf,
            compile_log="\n".join(logs)[-20_000:],
        )


def build_resume_tex(resume: FinalResume) -> str:
    first_name, last_name = _split_name(resume.basics.full_name)
    lines = [
        r"\documentclass[11pt,a4paper,sans]{moderncv}",
        r"\moderncvstyle{banking}",
        r"\moderncvcolor{blue}",
        r"\usepackage[utf8]{inputenc}",
        r"\usepackage[scale=0.80]{geometry}",
        rf"\name{{{latex_escape(first_name)}}}{{{latex_escape(last_name)}}}",
    ]
    _append_resume_contacts(lines, resume.basics)
    lines.extend([r"\begin{document}", r"\makecvtitle"])
    for section in resume.section_order:
        if section == "summary" and resume.summary is not None:
            lines.extend([r"\section{Profile}", rf"\small{{{latex_escape(resume.summary.text)}}}"])
        elif section == "skills" and resume.skills:
            lines.extend([r"\section{Core Competencies}", r"\begin{itemize}"])
            lines.extend(
                rf"\item \textbf{{{latex_escape(item.category or 'Skills')}}}: "
                rf"{latex_escape(item.name)}"
                for item in resume.skills
            )
            lines.append(r"\end{itemize}")
        elif section == "experience" and resume.experiences:
            lines.extend([r"\section{Professional Experience}", r"\begin{itemize}"])
            for experience in resume.experiences:
                lines.append(
                    rf"\item{{\cventry{{{latex_escape(experience.period)}}}"
                    rf"{{{latex_escape(experience.title)}}}"
                    rf"{{{latex_escape(experience.company)}}}"
                    rf"{{{latex_escape(experience.location)}}}{{}}{{\begin{{itemize}}"
                )
                lines.extend(rf"\item {latex_escape(item.text)}" for item in experience.bullets)
                lines.append(r"\end{itemize}}}")
            lines.append(r"\end{itemize}")
        elif section == "education" and resume.education:
            lines.extend([r"\section{Education}", r"\begin{itemize}"])
            for item in resume.education:
                period = " -- ".join(value for value in (item.start_date, item.end_date) if value)
                credential = " in ".join(
                    value for value in (item.credential, item.field_of_study) if value
                )
                lines.append(
                    rf"\item{{\cventry{{{latex_escape(period)}}}"
                    rf"{{{latex_escape(credential)}}}{{{latex_escape(item.institution)}}}"
                    rf"{{{latex_escape(item.location)}}}{{}}{{}}}}"
                )
            lines.append(r"\end{itemize}")
        elif section == "projects" and resume.projects:
            _append_bullet_section(
                lines,
                "Projects",
                [
                    f"{item.name}: " + " ".join(bullet.text for bullet in item.bullets)
                    for item in resume.projects
                ],
            )
        elif section == "certifications" and resume.certifications:
            _append_bullet_section(
                lines,
                "Certifications",
                [f"{item.name}, {item.issuer}" for item in resume.certifications],
            )
        elif section == "languages" and resume.languages:
            _append_bullet_section(
                lines,
                "Languages",
                [f"{item.name} ({item.proficiency})" for item in resume.languages],
            )
        elif section == "additional" and resume.additional_sections:
            for extra in resume.additional_sections:
                _append_bullet_section(lines, extra.title, [item.text for item in extra.items])
    lines.append(r"\end{document}")
    return "\n".join(lines) + "\n"


def build_cover_letter_tex(letter: CoverLetterDraft) -> str:
    lines = [
        r"\documentclass[]{cover}",
        r"\usepackage{fancyhdr}",
        r"\pagestyle{fancy}",
        r"\fancyhf{}",
        r"\rfoot{Page \thepage}",
        r"\thispagestyle{empty}",
        r"\renewcommand{\headrulewidth}{0pt}",
        r"\begin{document}",
        rf"\namesection{{}}{{\Huge{{{latex_escape(letter.signature)}}}}}{{}}",
        r"\currentdate{\today}",
    ]
    if letter.recipient:
        lines.append(rf"\companyname{{{latex_escape(letter.recipient)}}}")
    lines.extend(
        [
            rf"\lettercontent{{\textbf{{{latex_escape(letter.subject)}}}}}",
            rf"\lettercontent{{{latex_escape(letter.salutation)}}}",
        ]
    )
    lines.extend(rf"\lettercontent{{{latex_escape(item.text)}}}" for item in letter.paragraphs)
    lines.extend(
        [
            r"\begin{flushright}",
            rf"\closing{{{latex_escape(letter.closing)}}}",
            rf"\signature{{{latex_escape(letter.signature)}}}",
            r"\end{flushright}",
            r"\end{document}",
        ]
    )
    return "\n".join(lines) + "\n"


def latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "_": r"\_",
        "%": r"\%",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in value)


def _split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.rsplit(maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else (parts[0], "")


def _append_resume_contacts(lines: list[str], basics: ResumeBasics) -> None:
    if basics.location:
        lines.append(rf"\address{{{latex_escape(basics.location)}}}{{}}{{}}")
    if basics.phone:
        lines.append(rf"\phone[mobile]{{{latex_escape(basics.phone)}}}")
    if basics.email:
        lines.append(rf"\email{{{latex_escape(basics.email)}}}")
    extras = [value for value in (basics.linkedin, basics.github, basics.portfolio) if value]
    if extras:
        lines.append(rf"\extrainfo{{{latex_escape(' | '.join(extras))}}}")


def _append_bullet_section(lines: list[str], title: str, items: list[str]) -> None:
    lines.extend([rf"\section{{{latex_escape(title)}}}", r"\begin{itemize}"])
    lines.extend(rf"\item {latex_escape(item)}" for item in items)
    lines.append(r"\end{itemize}")


def safe_document_stem(value: str) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return stem[:80] or "application"


__all__ = [
    "CompiledDocument",
    "GenerationLatexError",
    "build_cover_letter_tex",
    "build_resume_tex",
    "compile_latex_document",
    "latex_escape",
    "render_generation_bundle",
    "safe_document_stem",
]
