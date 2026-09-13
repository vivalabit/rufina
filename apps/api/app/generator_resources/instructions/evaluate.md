# Evaluate fit

Version: 1.0.0

Evaluate the full saved vacancy against the selected Master Resume snapshot.
Run eligibility and language gates first. Then report skills, experience,
behavioral/culture evidence (without inventing personality traits), logistics,
career alignment, an overall score from 0 to 100, and a concise recommendation.
List required and preferred terms for later ATS coverage and mark every gap
honestly. The output must be structured data.

After evaluation, pause and ask the user whether to continue with the CV and
cover letter. A negative answer ends the run without drafting.

Adapted from upstream `/apply` Step 1 and `04-job-evaluation.md` at commit
`c7bd494f11e792508534c1c795e24694498395c4`. Salary lookup and re-fetching the
vacancy are intentionally omitted because Tasko starts from a complete saved
vacancy and has no salary dataset in this workflow.

