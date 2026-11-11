# Draft CV and cover letter

Version: 1.4.2

Create both documents from the immutable Master Resume snapshot and the full
saved vacancy. Determine the document language from the predominant language
of vacancy.fullDescription, not the Master Resume, candidate location, or the
languages listed as job requirements. "Auto" means detect from that vacancy
text; requestedLanguage may validly remain "Auto" throughout the run. It is not
a language to write into the output. Write both the CV and cover
letter in the detected language and set each document's language field to its
actual language. For multilingual postings, use the language of the main duties
and requirements; if equally balanced, use the first substantive description.
Translate generated prose faithfully without changing facts, proper names,
source evidence, or protected structured fields. Address every stated requirement
either with cited evidence or as an honest gap; do not silently omit hard requirements.

For the CV, tailor the summary and rewrite experience bullets without losing
substance. Every generated factual text must carry canonical evidence IDs.
Preserve each role's distinct key achievements, concrete technical details,
technologies, and outcomes or metrics from the Master Resume. Adapt emphasis,
ordering within a role, and wording to the vacancy. Do not drop achievements
merely because they are less relevant to the vacancy. There is no default cap
of two or three bullets per role. A source text item may contain several
achievements or visual bullet points: preserve its semantic content, not just
the number of source items or their evidence IDs. Combine bullets only when
each distinct achievement, technical detail, and outcome or metric remains
explicit in the visible CV text. Remove exact repetition and shorten prose
without replacing concrete results with generic claims.
Use experienceContentPolicy.sourceAchievements as the per-role source checklist;
its source text can contain multiple achievements. Keep the result readable:
preserve substantive facts, not every redundant or decorative source phrase.

- Keep every experience entry in exactly the order supplied by masterResume.
  Do not rank employers by vacancy relevance, remove roles, or independently
  sort dates. Prioritize relevant achievements within each role instead.
- Keep every spoken language and its original proficiency, including native
  languages, even when the vacancy does not mention it.
- Retain every skill in skillPolicy.requiredSkills with its specified category;
  this is the same core membership the server enforces after every revision.
  Use these groups, with exactly these
  headings and in this order: Languages, Frameworks, Databases, Tools / DevOps.
  Languages here means programming languages; spoken languages remain in their
  separate section. Keep broader core skills, including other programming
  languages and Python frameworks, even when the vacancy does not name them.
  Within each group, put the skills most relevant to this vacancy first.

Do not remove or reclassify a skillPolicy.requiredSkills entry even if a review
mistakenly calls it optional. Classify additional skills by their actual meaning.
Additional groups such as AI &
Automation belong after the core groups and should contain only source-backed
skills relevant to the vacancy's requirements, tasks, or keywords. Omit
irrelevant optional skills and empty groups. Do not dump remaining skills into
Other skills or use Tools / DevOps as a catch-all. Do not relabel optional
concepts as core technologies just to keep them. Use semantic relevance, not
only exact keyword matching. Consolidate only exact duplicates; keep distinct
languages, frameworks, and technologies explicitly named. Never invent skills.

Use the selected template's full permitted page budget; there is no one-page
CV goal when more pages are allowed. Follow experienceContentPolicy:
when allowContentReduction is false, retain the key experience content and
shorten wording or remove repetition only. New content reductions are permitted
only when allowContentReduction is true, verifiedOverflow records a measured CV
overflow, and currentResumePages is greater than maxResumePages. When
currentResumePages is null or within the limit, do not make further content
reductions, including during visual-only repairs. A recorded overflow from an
earlier render in this run may justify retaining prior minimal reductions needed
to fit; it does not authorize new cuts after the CV fits. First shorten the
summary and bullet wording and remove repetition. Only if that is insufficient, reduce the least
relevant experience detail as little as necessary to fit, retaining the most
substantive achievements, technologies, and metrics. Never remove protected
roles, languages, or core skills to fit. Estimated length, letter overflow,
vacancy relevance, or a visual-only finding does not authorize CV content loss.

Return document content with evidenceIds only. The masterResume.evidence catalog
is read-only input: never return an evidence array, evidence objects, or rewritten
source records. The server resolves cited IDs to the original facts from the
frozen snapshot. You may shorten and rephrase the visible CV text while citing
the supporting original IDs. This applies to initial drafts, reviewer revisions,
and PDF repairs.

For the cover letter, write a warm, direct, professional one-page letter. Avoid
em dashes, clichés, generic unsupported claims, apologetic phrasing, and claims
about the company that were not verified. Make it forward-looking and connect
specific candidate evidence to the employer's work.

Adapted from upstream `/apply` Step 2, `03-writing-style.md`,
`05-cv-templates.md`, and `06-cover-letter-templates.md` at commit
`c7bd494f11e792508534c1c795e24694498395c4`. Tasko emits structured document
data and renders server-owned, versioned templates instead of letting the model
write arbitrary files.
