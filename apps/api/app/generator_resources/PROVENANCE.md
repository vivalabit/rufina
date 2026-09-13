# Application generator provenance

The application workflow is adapted from
[`MadsLorentzen/ai-job-search`](https://github.com/MadsLorentzen/ai-job-search/tree/c7bd494f11e792508534c1c795e24694498395c4)
at commit `c7bd494f11e792508534c1c795e24694498395c4`.

Copied verbatim under the upstream MIT license:

- `upstream/cv/main_example.tex`
- `upstream/cover_letters/cover.cls`
- `upstream/cover_letters/cover_example.tex`
- `upstream/cover_letters/OpenFonts/fonts/**`
- `upstream/tools/verify_pdf.py`
- `upstream/tools/verify_layout.py`
- `upstream/LICENSE`

The Markdown files in `instructions/` are Tasko-specific adaptations. They
preserve the upstream workflow order, trust boundary, grounding rules,
drafter/reviewer separation, writing guidance, and verification method while
replacing slash commands and a CLI workspace with server-owned stages,
structured model responses, application data, versioned templates, and worker
tools. `candidate-profile.md` is not copied: Tasko's immutable Master Resume
version is the canonical fact source.

`CHECKSUMS.sha256` records every copied file. Run
`python -m app.services.generation_resources` from `apps/api` to verify it.

