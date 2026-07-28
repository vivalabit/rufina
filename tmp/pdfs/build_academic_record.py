from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


SOURCE_IMAGE = Path(
    "/var/folders/nh/mz3mk0350bg1vg6qps8km3d40000gn/T/"
    "codex-clipboard-cd3e8010-e02b-45a6-af9f-6407a72d5aef.png"
)
OUTPUT = Path(
    "/Users/eduardishchenko/coding/tasko/output/pdf/"
    "Academic_Record_Semesters_5_6_Eduard_Ishchenko.pdf"
)

PAGE_SIZE = landscape(A4)
NAVY = colors.HexColor("#18324A")
BLUE = colors.HexColor("#2C5F87")
PALE_BLUE = colors.HexColor("#EAF2F8")
PALE_GRAY = colors.HexColor("#F4F6F8")
MID_GRAY = colors.HexColor("#667482")
GRID = colors.HexColor("#CAD2D9")
INK = colors.HexColor("#1D2730")
WHITE = colors.white


semester_5 = [
    ["1", "Software Architecture and Design", "Exam", "4", "B", "82", "12 Dec 2025"],
    ["2", "Expert Systems", "Exam", "4", "B", "83", "18 Dec 2025"],
    ["3", "Empirical Methods in Software Engineering", "Exam", "4", "C", "77", "23 Dec 2025"],
    ["4", "Software Project Management", "Exam", "4", "B", "85", "09 Dec 2025"],
    ["5", "Java Technology", "Exam", "4", "C", "77", "15 Dec 2025"],
]

semester_6 = [
    ["6", "Algorithms and Data Structures", "Exam", "5", "A", "96", "04 May 2026"],
    ["7", "Databases", "Exam", "4", "B", "89", "14 May 2026"],
    ["8", "Information Systems and Network Security", "Exam", "3", "E", "66", "07 May 2026"],
    ["9", "Database Coursework", "Coursework", "4", "B", "82", "07 May 2026"],
    ["10", "Practical Training 1", "Practical training", "Pass", "A", "90", "19 Jun 2026"],
    ["11", "Software Standardization and Metrology", "Exam", "4", "C", "75", "11 May 2026"],
]


def page_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#D8DEE4"))
    canvas.setLineWidth(0.5)
    canvas.line(18 * mm, 13 * mm, PAGE_SIZE[0] - 18 * mm, 13 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MID_GRAY)
    canvas.drawString(
        18 * mm,
        8.5 * mm,
        "Unofficial English translation prepared from the attached student portal record.",
    )
    canvas.drawRightString(
        PAGE_SIZE[0] - 18 * mm,
        8.5 * mm,
        f"Page {doc.page}",
    )
    canvas.restoreState()


def translated_table(title, rows, styles):
    title_row = Table(
        [[Paragraph(title, styles["semester_title"])]],
        colWidths=[PAGE_SIZE[0] - 36 * mm],
    )
    title_row.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), NAVY),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )

    headers = ["No.", "Course", "Assessment", "National grade", "ECTS", "Score / 100", "Date"]
    table_data = [
        [Paragraph(cell, styles["table_header"]) for cell in headers]
    ]
    for row in rows:
        table_data.append(
            [
                Paragraph(str(row[0]), styles["table_center"]),
                Paragraph(row[1], styles["table_body"]),
                Paragraph(row[2], styles["table_center"]),
                Paragraph(str(row[3]), styles["table_center"]),
                Paragraph(row[4], styles["table_center"]),
                Paragraph(str(row[5]), styles["table_center"]),
                Paragraph(row[6], styles["table_center"]),
            ]
        )

    widths = [11 * mm, 92 * mm, 32 * mm, 28 * mm, 18 * mm, 25 * mm, 34 * mm]
    table = Table(table_data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PALE_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
                ("GRID", (0, 0), (-1, -1), 0.45, GRID),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, PALE_GRAY]),
            ]
        )
    )
    return KeepTogether([title_row, table])


def build():
    if not SOURCE_IMAGE.exists():
        raise FileNotFoundError(SOURCE_IMAGE)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    base = getSampleStyleSheet()
    styles = {
        "eyebrow": ParagraphStyle(
            "Eyebrow",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=BLUE,
            spaceAfter=3,
            tracking=1.2,
        ),
        "title": ParagraphStyle(
            "Title",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=25,
            textColor=NAVY,
            spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=13,
            textColor=MID_GRAY,
        ),
        "meta_label": ParagraphStyle(
            "MetaLabel",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=MID_GRAY,
            spaceAfter=1,
        ),
        "meta_value": ParagraphStyle(
            "MetaValue",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=10,
            leading=12,
            textColor=INK,
        ),
        "note": ParagraphStyle(
            "Note",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11,
            textColor=INK,
        ),
        "semester_title": ParagraphStyle(
            "SemesterTitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=12,
            textColor=WHITE,
        ),
        "table_header": ParagraphStyle(
            "TableHeader",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=9,
            alignment=TA_CENTER,
            textColor=NAVY,
        ),
        "table_body": ParagraphStyle(
            "TableBody",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=9.5,
            alignment=TA_LEFT,
            textColor=INK,
        ),
        "table_center": ParagraphStyle(
            "TableCenter",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=8,
            leading=9.5,
            alignment=TA_CENTER,
            textColor=INK,
        ),
        "source_title": ParagraphStyle(
            "SourceTitle",
            parent=base["Normal"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=21,
            textColor=NAVY,
            spaceAfter=4,
        ),
        "source_note": ParagraphStyle(
            "SourceNote",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=MID_GRAY,
        ),
    }

    doc = SimpleDocTemplate(
        str(OUTPUT),
        pagesize=PAGE_SIZE,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=15 * mm,
        bottomMargin=18 * mm,
        title="Unofficial Academic Record - Eduard Ishchenko",
        author="Eduard Ishchenko",
        subject="English translation of academic results for semesters 5 and 6",
    )

    story = []
    story.append(Paragraph("ACADEMIC RECORD", styles["eyebrow"]))
    story.append(Paragraph("Unofficial English Translation", styles["title"]))
    story.append(
        Paragraph(
            "Academic results shown in the State University of Trade and Economics student portal.",
            styles["subtitle"],
        )
    )
    story.append(Spacer(1, 7 * mm))

    meta = Table(
        [
            [
                Paragraph("STUDENT", styles["meta_label"]),
                Paragraph("UNIVERSITY", styles["meta_label"]),
                Paragraph("PERIOD", styles["meta_label"]),
                Paragraph("PROGRAMME", styles["meta_label"]),
            ],
            [
                Paragraph("Eduard Ishchenko", styles["meta_value"]),
                Paragraph(
                    "State University of Trade and Economics (SUTE), Kyiv, Ukraine",
                    styles["meta_value"],
                ),
                Paragraph("Semesters 5 and 6", styles["meta_value"]),
                Paragraph("Software Engineering", styles["meta_value"]),
            ],
        ],
        colWidths=[45 * mm, 83 * mm, 39 * mm, 73 * mm],
    )
    meta.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PALE_GRAY),
                ("BOX", (0, 0), (-1, -1), 0.6, GRID),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, 0), 6),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
                ("TOPPADDING", (0, 1), (-1, 1), 2),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 7),
            ]
        )
    )
    story.append(meta)
    story.append(Spacer(1, 4 * mm))

    note = Table(
        [
            [
                Paragraph(
                    "<b>Important:</b> This is an unofficial translation prepared from the "
                    "student portal screenshot attached on page 2. It has not been issued, "
                    "certified, stamped, or signed by the university. Official documents can "
                    "be provided upon request. Due to a change of study programme, the current "
                    "portal displays results for the two most recent semesters.",
                    styles["note"],
                )
            ]
        ],
        colWidths=[PAGE_SIZE[0] - 36 * mm],
    )
    note.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF5DB")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#E6C66A")),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(note)
    story.append(Spacer(1, 4 * mm))
    story.append(translated_table("Semester 5", semester_5, styles))
    story.append(Spacer(1, 3.5 * mm))
    story.append(translated_table("Semester 6", semester_6, styles))

    story.append(PageBreak())
    story.append(Paragraph("SOURCE RECORD", styles["eyebrow"]))
    story.append(Paragraph("Original Student Portal Screenshot", styles["source_title"]))
    story.append(
        Paragraph(
            "Original Ukrainian-language record used as the source for the English translation on page 1.",
            styles["source_note"],
        )
    )
    story.append(Spacer(1, 8 * mm))

    source_image = Image(str(SOURCE_IMAGE))
    max_width = PAGE_SIZE[0] - 36 * mm
    max_height = PAGE_SIZE[1] - 70 * mm
    scale = min(max_width / source_image.imageWidth, max_height / source_image.imageHeight)
    source_image.drawWidth = source_image.imageWidth * scale
    source_image.drawHeight = source_image.imageHeight * scale
    image_frame = Table([[source_image]], colWidths=[max_width])
    image_frame.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, GRID),
                ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(image_frame)

    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    print(OUTPUT)


if __name__ == "__main__":
    build()
