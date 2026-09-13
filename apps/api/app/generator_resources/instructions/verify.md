# Render and verify

Version: 1.0.0

Render the selected CV and cover-letter template to PDF. Tie every check to
the exact document version and invalidate it when that version changes.

Required checks:

- PDF opens, has an extractable text layer, and contains the candidate's name.
- CV and letter obey their selected page-count policies.
- contact details and role dates survive text extraction.
- no replacement glyphs or `(cid:NNN)` runs appear.
- section reading order is sensible and no page has a suspicious internal hole,
  orphaned heading, footer collision, or very thin final page.
- required/preferred vacancy terms are reported as covered, synonym-only,
  supported-but-missing, or genuine gap.
- render every page to PNG and inspect those exact images in the reviewer
  context before marking visual review complete.

Adapted from upstream `/apply` Steps 5-6 and the copied `verify_pdf.py` and
`verify_layout.py` at commit `c7bd494f11e792508534c1c795e24694498395c4`.
Tasko parameterizes page limits per selected template instead of hard-coding
the upstream 2-page CV and 1-page letter rules.

