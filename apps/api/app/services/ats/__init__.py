"""ATS-oriented resume tailoring used by the generation pipeline.

- `job_target`: vacancy analysis (model plus skill dictionary), cached per posting.
- `profile_index` and `planner`: deterministic statement ranking, skill order,
  headline, gaps and the coverage score.
- `wording`: prompts for rewording and translation and the fact checks every
  model text passes.
- `tailoring`: one run as a pure session that builds requests, checks responses
  and assembles the resume from the profile; `cover_letter` does the same for
  the letter.

`app.services.generation_workflow` drives the session and sends its requests;
the session itself never calls a model.
"""
