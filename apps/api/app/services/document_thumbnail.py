from __future__ import annotations

from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import tempfile

from PIL import Image


THUMBNAIL_WIDTH = 360
THUMBNAIL_HEIGHT = 640
THUMBNAIL_TIMEOUT_SECONDS = 30
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PdfThumbnailRenderError(RuntimeError):
    pass


def render_pdf_first_page_thumbnail(pdf: bytes) -> bytes:
    rasterizer = shutil.which("pdftoppm")
    if not rasterizer:
        raise PdfThumbnailRenderError(
            "PDF thumbnail rendering is unavailable: pdftoppm is required"
        )

    with tempfile.TemporaryDirectory(prefix="document-thumbnail-") as directory:
        workdir = Path(directory)
        pdf_path = workdir / "preview.pdf"
        output_prefix = workdir / "thumbnail"
        output_path = workdir / "thumbnail.png"
        pdf_path.write_bytes(pdf)
        try:
            result = subprocess.run(
                [
                    rasterizer,
                    "-png",
                    "-f",
                    "1",
                    "-l",
                    "1",
                    "-singlefile",
                    "-scale-to-x",
                    str(THUMBNAIL_WIDTH),
                    "-scale-to-y",
                    "-1",
                    str(pdf_path),
                    str(output_prefix),
                ],
                capture_output=True,
                text=True,
                timeout=THUMBNAIL_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PdfThumbnailRenderError("PDF thumbnail rendering failed") from exc

        if result.returncode != 0 or not output_path.exists():
            detail = (
                result.stderr
                or result.stdout
                or "pdftoppm did not create a PNG image"
            ).strip()
            raise PdfThumbnailRenderError(
                f"PDF thumbnail rendering failed: {detail[:240]}"
            )
        thumbnail = output_path.read_bytes()
        if len(thumbnail) < 24 or not thumbnail.startswith(PNG_SIGNATURE):
            raise PdfThumbnailRenderError(
                "PDF thumbnail rendering produced an invalid PNG image"
            )
        return fit_thumbnail_to_portrait_canvas(thumbnail)


def fit_thumbnail_to_portrait_canvas(thumbnail: bytes) -> bytes:
    try:
        with Image.open(BytesIO(thumbnail)) as source:
            page = source.convert("RGB")
    except (OSError, ValueError) as exc:
        raise PdfThumbnailRenderError(
            "PDF thumbnail rendering produced an unreadable PNG image"
        ) from exc

    scale = min(
        THUMBNAIL_WIDTH / page.width,
        THUMBNAIL_HEIGHT / page.height,
    )
    rendered_width = max(1, round(page.width * scale))
    rendered_height = max(1, round(page.height * scale))
    if (rendered_width, rendered_height) != page.size:
        page = page.resize(
            (rendered_width, rendered_height),
            Image.Resampling.LANCZOS,
        )

    canvas = Image.new(
        "RGB",
        (THUMBNAIL_WIDTH, THUMBNAIL_HEIGHT),
        "#ffffff",
    )
    canvas.paste(
        page,
        (
            (THUMBNAIL_WIDTH - rendered_width) // 2,
            (THUMBNAIL_HEIGHT - rendered_height) // 2,
        ),
    )
    output = BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()


__all__ = [
    "PdfThumbnailRenderError",
    "THUMBNAIL_HEIGHT",
    "THUMBNAIL_WIDTH",
    "render_pdf_first_page_thumbnail",
]
