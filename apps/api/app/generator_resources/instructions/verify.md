# Render and verify

Version: 1.2.2

Render the selected CV and cover-letter template to PDF. Tie every check to
the exact document version and invalidate it when that version changes.

Required checks:

- Evaluate actual documentLanguages and visible prose. requestedLanguage="Auto"
  is a valid saved preference; it must not fail verification when the document
  language metadata is resolved. Only an actual document language field of
  "Auto" is unresolved output.
- PDF opens, has an extractable text layer, and contains the candidate's name.
- CV and letter obey their selected page-count policies.
- CV contact details and role dates survive text extraction; do not require
  CV-only fields in the cover letter.
- all source experience entries appear in their original order; all spoken
  languages and proficiencies, including native languages, and source core
  technical skills remain visible in the CV. Their absence from vacancy
  keywords is not a reason to omit them.
- distinct key experience achievements, technical details, named technologies,
  and outcomes or metrics from the frozen Master Resume remain visible in the
  actual PDF. Use experienceContentPolicy.sourceAchievements as the per-role
  checklist. Compare semantic content rather than source element counts or
  evidence IDs alone: a single source text item may contain several achievements.
  Combining bullets must not hide concrete facts behind generic claims. Material
  missing key content is a blocking finding requiring restoration unless the
  policy permits the minimum reduction necessary for measured CV overflow.
- skillPolicy.requiredSkills defines the exact required skill names and their
  canonical categories, including skills normalized from blank or legacy source
  categories. Do not reject policy-listed skills as optional, move them to other
  groups, or derive a competing core membership from raw source labels.
- core skill groups use the headings Languages, Frameworks, Databases, Tools /
  DevOps in that order, with vacancy-relevant skills first inside each group.
  Languages contains programming languages. Additional groups, such as AI &
  Automation, follow the core groups and contain only supported skills relevant
  to the vacancy. Empty groups and irrelevant optional skills are omitted;
  there is no Other skills dumping or incorrect classification into core groups.
- no replacement glyphs or `(cid:NNN)` runs appear.
- section reading order is sensible and there is no clipped or overlapping
  text, footer collision, or heading separated from all of its following content.
  These are blocking when visible in the supplied page images.
- moderate bottom or internal whitespace, uneven page balance, and a thin final
  page alone are advisory. Preserved source content with unused page space is
  not a content failure. Do not turn deterministic whitespace warnings into
  blocking findings based only on aesthetics; identify a separate concrete
  usability or source-content defect on the affected page before blocking.
- required/preferred vacancy terms are reported as covered, synonym-only,
  supported-but-missing, or genuine gap. Exact keyword absence is advisory:
  synonyms, translated wording, and semantically equivalent qualifications
  must not fail an otherwise valid PDF.
- render every page to PNG and inspect those exact images in the reviewer
  context before marking visual review complete.
- Mark `approved` true after every supplied image has been inspected and no
  blocking visual, structural, or source-content preservation finding remains.
  Warnings and suggestions do not block approval by themselves.
- Base `approved` on visual and structural usability and preservation of key
  source content. Keyword coverage warnings must not make the visual review
  fail; missing source achievements or metrics are content findings, not
  keyword warnings.

For any PDF repair, preserve experience entries and their source order, all
spoken languages and proficiencies, and source core technical skills. Keep the
fixed core group order and prioritize skills by vacancy relevance within each
group. Keep optional groups selective and correctly classified. Preserve each
role's distinct key achievements, technical details, technologies, and outcomes
or metrics when experienceContentPolicy.allowContentReduction is false. Shorten
wording and remove repetition without losing these facts. New content reductions
are permitted only when allowContentReduction is true, verifiedOverflow records
a measured CV overflow, and currentResumePages is greater than maxResumePages.
When currentResumePages is null or within the limit, no further content reduction
is permitted, including during visual-only repairs. Recorded overflow may come
from an earlier render in the same run: keep only the prior minimal reductions
needed to fit, without restoring them solely because the repair fits or making
new cuts after it fits.
First shorten the summary and bullet wording and remove repetition; only if
that is insufficient, reduce the least relevant experience detail as little as
necessary while retaining the most substantive achievements, technologies, and
metrics. Letter overflow or visual findings alone do not authorize CV content
loss. Use the full permitted page budget; there is no default two- or three-bullet
cap or one-page CV goal. Preserve substantive facts without copying redundant or
decorative source phrases.

Adapted from upstream `/apply` Steps 5-6 and the copied `verify_pdf.py` and
`verify_layout.py` at commit `c7bd494f11e792508534c1c795e24694498395c4`.
Tasko parameterizes page limits per selected template instead of hard-coding
the upstream 2-page CV and 1-page letter rules.
