# Screenshot workspace

The screenshot workspace is an isolated local Rufina installation populated
with synthetic data. It uses its own Docker Compose project, PostgreSQL, Redis,
browser origin, and empty OpenClaw volumes. AI actions are disabled in this
environment, so it never writes to the primary workspace database or personal
OpenClaw files.

Start it and restore the fixture:

```bash
pnpm screenshots:up
```

Open `http://localhost:3001`. The fixture contains the fictional candidate
Maya Keller, six vacancies with match results, four applications, calendar
events, and a generated one-page demo resume.

Useful commands:

```bash
pnpm screenshots:seed
pnpm screenshots:logs
pnpm screenshots:down
pnpm screenshots:reset
```

`screenshots:seed` restores the known demo records without deleting the
workspace volumes. `screenshots:down` stops the environment and preserves its
data. `screenshots:reset` removes only the `tasko-screenshots` project volumes,
starts fresh containers, and restores the fixture.

The default ports are:

- Web: `3001`
- API: `8001`
- PostgreSQL: `5433`
- Redis: `6380`

Override them with `SCREENSHOT_WEB_PORT`, `SCREENSHOT_API_PORT`,
`SCREENSHOT_POSTGRES_PORT`, and `SCREENSHOT_REDIS_PORT`. Primary workspace ports
are rejected as a safety check.

The seed script refuses to run unless the API container has
`RUFINA_SCREENSHOT_MODE=1`; invoke it through the package command instead of
running it against an arbitrary database.
