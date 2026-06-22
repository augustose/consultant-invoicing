# Local Agent Memory

## Change Request Notes

For every code, configuration, or documentation change made in this workspace,
create a concise change request note before the final response.

- Store notes in `docs/change-requests/`.
- Name files as `YYYY-MM-DD-short-change-slug.md`.
- Keep each note short and practical.
- Include at minimum: `Summary`, `Changed Files`, and `Verification`.
- If a change is intentionally not verified with commands, state why.

## Git Remote Safety

Work locally until the user explicitly approves publishing changes.

- Do not push to any remote branch without direct user confirmation for that
  specific push.
- Do not create or update a remote pull request unless the user explicitly asks
  for it.
- Local commits and local branches are allowed when useful, but remote
  publication requires approval every time.
