# Template execution contract

## Reference

- Source: `/Users/eduardishchenko/Main/Swiss Career/Intership/DE/Motivationschreiben_Ishchenko.docx`
- SHA-256: `65e9f460c945ebdb14639243738f51497c8eba3d0254f16f13f69a6118869bd8`
- Pages: 1
- Sections: 1
- Visual evidence: `template-render/page-1.png`
- Structural evidence: `template-style-evidence.json` and `section_audit.py` output

## Page system

- A4 portrait, 8.27 x 11.69 inches.
- Margins: left/right 0.98 inches, top/bottom 0.71 inches.
- One section, no distinct first/odd/even header or footer, no columns.
- Preserve the existing section properties and page geometry byte-for-byte.

## Typography and rhythm

- Restrained Swiss business-letter layout with all content left aligned.
- Body/address/contact: Times New Roman inherited from the source Normal style, approximately 11 pt, 1.1 line spacing.
- Subject: source custom style `isselectedend`, 16 pt, regular weight.
- Salutation and body: source custom style `isselectedend`, 10.5 pt, regular weight.
- Address block at top; date block separated below; subject separated by a larger vertical interval.
- Three body units: the first shares a paragraph with the salutation and is separated by a blank line; the second and third use the same source body paragraph pattern.
- Closing uses source `Normal (Web)` styling and existing line-break rhythm.

## Components and slot map

- `word/document.xml`, body paragraph 1: recipient block; rewrite.
- `word/document.xml`, body paragraph 2: place/date; rewrite.
- `word/document.xml`, body paragraph 3: subject; rewrite.
- `word/document.xml`, body paragraph 4: salutation plus first motivation paragraph; rewrite while preserving paragraph/run properties.
- `word/document.xml`, body paragraphs 5-6: experience and UBS-fit paragraphs; rewrite while preserving paragraph/run properties.
- `word/document.xml`, body paragraph 7: closing formula; rewrite only to retain exact desired Swiss wording.
- `word/document.xml`, body paragraphs 8-10: applicant name, phone, and email; preserve content and formatting.
- `word/document.xml`, body paragraph 11: signature drawing; preserve exactly, including relationship and anchor geometry.
- Remaining trailing empty paragraphs: preserve.

No tables, lists, headers, footers, footnotes, fields, comments, content controls, or alternate page patterns are present.

## Package preservation

- Only text content in the specified `word/document.xml` paragraph slots may change.
- Preserve `[Content_Types].xml`, relationships, `customXml`, properties, settings, styles, numbering, fonts, theme, web settings, and `word/media/image1.png` byte-for-byte.
- Preserve all paragraph properties, run properties, drawing XML, bookmarks, relationships, and section properties.
- Signature asset SHA-256: `f234d31ac2388e01df8dcdb4cfe9acb3b01bac044e9a6641ce1cd834c9a82c1b`.

## Content flow

1. UBS recipient block.
2. Männedorf and application date.
3. Concise subject naming the 2027 IT apprenticeship.
4. Motivation for the two-year IT-way-up apprenticeship and practical learning.
5. Evidence from Python/backend/API/automation and LLM work, plus learning and teamwork.
6. Fit with UBS's international projects and AI direction, followed by a conversation request.
7. Swiss closing, applicant contact details, and retained signature.

## Fidelity gates

- Reference file must retain its recorded SHA-256.
- Final must remain one clean A4 page with no clipping, overlap, awkward title wrap, or signature displacement.
- All package parts except `word/document.xml` must match the reference byte-for-byte.
- Within `word/document.xml`, section properties, paragraph properties, drawing, and relationship references must remain unchanged.
- Render and visually inspect the final at 100% zoom; compare against the reference for unexplained layout drift.
