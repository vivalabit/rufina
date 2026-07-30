![Logo](images/rufina_blogo.png)

<h1 align="center">Personal AI Job Assistant</h1>

Rufina is a personal AI assistant for job hunting. It finds suitable job openings, assesses how well they match your profile, and tailors your resume and cover letters. The app also helps you store your documents and track the entire application process in one place.

![Rufina](images/scr_1.png)

## Key Features

<img src="https://api.iconify.design/tabler/search.svg?color=%23FF5A00" width="22" alt="Search icon" /> **Smart Job Search**: Automatically finds relevant opportunities on <img src="https://api.iconify.design/tabler/brand-linkedin.svg?color=%23FF5A00" width="16" alt="LinkedIn" /> LinkedIn, <img src="https://cdn.simpleicons.org/indeed/FF5A00" width="15" alt="Indeed" /> Indeed, and other based on your preferences.

<img src="https://api.iconify.design/tabler/sparkles.svg?color=%23FF5A00" width="22" alt="AI matching icon" /> **AI-Powered Matching**: Evaluates how well each vacancy matches your experience, skills, and career goals.

<img src="https://api.iconify.design/tabler/file-cv.svg?color=%23FF5A00" width="22" alt="Resume icon" /> **Tailored Resumes**: Adapts your resume to each position while keeping your professional background accurate.

<img src="https://api.iconify.design/tabler/mail.svg?color=%23FF5A00" width="22" alt="Cover letter icon" /> **Cover Letter Generation**: Creates personalized cover letters based on the vacancy, company, and your experience.

<img src="https://api.iconify.design/tabler/clipboard-check.svg?color=%23FF5A00" width="22" alt="Application tracking icon" /> **Application Tracking**: Keeps vacancies, documents, and application statuses organized in one workspace.

<img src="https://api.iconify.design/tabler/user-circle.svg?color=%23FF5A00" width="22" alt="Candidate profile icon" /> **Candidate Profile**: Centralizes your professional experience, skills, and master resume.

<img src="https://api.iconify.design/tabler/robot.svg?color=%23FF5A00" width="22" alt="AI assistant icon" /> **Personal AI Assistant**: Supports you throughout the job search, from finding vacancies to preparing application documents.


## How It Works 


1. <img src="https://api.iconify.design/tabler/user-circle.svg?color=%23FF5A00" width="22" alt="Profile icon" /> **Build Your Candidate Profile**  
   Add your experience, skills, job preferences, and confirm your Master Resume.

2. <img src="https://api.iconify.design/tabler/search.svg?color=%23FF5A00" width="22" alt="Job search icon" /> **Discover Relevant Vacancies**  
   Search opportunities across LinkedIn, Indeed, jobs.ch, and other supported sources.

3. <img src="https://api.iconify.design/tabler/target-arrow.svg?color=%23FF5A00" width="22" alt="AI match icon" /> **Review Your AI Match**  
   See how each vacancy matches your profile, including strengths, gaps, and key requirements.

4. <img src="https://api.iconify.design/tabler/files.svg?color=%23FF5A00" width="22" alt="Application documents icon" /> **Prepare Your Application**  
   Confirm important details, tailor your CV, generate a cover letter, and complete the final review.

5. <img src="https://api.iconify.design/tabler/clipboard-check.svg?color=%23FF5A00" width="22" alt="Application tracking icon" /> **Track Your Progress**  
   Manage application statuses, next steps, interviews, assessments, and offers in one workspace.

![Rufina](images/scr_2.png)

## Getting Started

### Requirements

Choose one of the following setups:

- **Docker:** Docker Desktop or Docker Engine with Docker Compose.
- **Local development:** Node.js 22+, pnpm 9.15.0, Python 3.12+, PostgreSQL 16 with pgvector, and Redis 7.

Document processing also requires LibreOffice Writer, Poppler, Tesseract, and Playwright Chromium. These dependencies are installed automatically when using Docker.

### Clone the Repository

```bash
git clone https://github.com/vivalabit/rufina.git
cd rufina
```

### Configure Environment Variables

Create a `.env` file in the repository root:

```env
# AI backend
AI_BACKEND=openai_api
OPENAI_API_KEY=your_openai_api_key
OPENAI_API_MODEL=gpt-5.6-terra
OPENAI_API_REASONING_EFFORT=medium

# LinkedIn and Indeed job search — optional
BRIGHTDATA_API_KEY=your_brightdata_api_key

# Local ports — optional
WEB_PORT=3000
API_PORT=8000
POSTGRES_PORT=5432
REDIS_PORT=6379
```

`OPENAI_API_KEY` is required when `AI_BACKEND=openai_api`. `BRIGHTDATA_API_KEY` is only required for LinkedIn and Indeed searches.

### Run with Docker

Start the complete application stack:

```bash
docker compose up --build
```

Alternatively, use the project script:

```bash
pnpm docker:up
```

Open the application at [http://localhost:3000](http://localhost:3000). The API is available at [http://localhost:8000](http://localhost:8000).

To stop the stack:

```bash
docker compose down
```

### Run Locally with pnpm

Install the frontend dependencies:

```bash
corepack enable
corepack prepare pnpm@9.15.0 --activate
pnpm install --frozen-lockfile
```

Start PostgreSQL and Redis:

```bash
docker compose up -d postgres redis
```

Set up and start the API:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e apps/api
python -m playwright install chromium
cd apps/api
uvicorn app.main:app --reload --port 8000
```

In a separate terminal, start the web application from the repository root:

```bash
pnpm dev
```

The application will be available at [http://localhost:3000](http://localhost:3000).

## Configuration

Rufina reads configuration from the `.env` file in the repository root.

### API Keys

- `OPENAI_API_KEY` — required when using the OpenAI API directly.
- `BRIGHTDATA_API_KEY` — required for LinkedIn and Indeed vacancy search.
- jobs.ch and manually added vacancies do not require an API key.

### AI Providers

Rufina supports two AI backends:

- `openai_api` — OpenAI Responses API using your API key.
- `openclaw_codex` — Codex through a configured OpenClaw agent.

```env
AI_BACKEND=openai_api
OPENAI_API_KEY=your_openai_api_key
OPENAI_API_MODEL=gpt-5.6-terra

BRIGHTDATA_API_KEY=your_brightdata_api_key
```

For OpenClaw and Codex:

```env
AI_BACKEND=openclaw_codex
OPENCLAW_COMMAND=openclaw
OPENCLAW_AGENT_ID=rufina-assistant
```

```bash
pnpm openclaw:setup
```

### Vacancy Sources

- LinkedIn — through Bright Data
- Indeed — through Bright Data
- jobs.ch — direct public search
- Manual vacancy entry

## Stack

- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS
- **Backend:** Python 3.12, FastAPI, SQLAlchemy, Alembic
- **Database:** PostgreSQL 16 with pgvector
- **Queue and Cache:** Redis 7
- **AI:** OpenAI Responses API or Codex through OpenClaw
- **Documents:** LibreOffice, Poppler, Tesseract, Playwright
- **Infrastructure:** Docker Compose, pnpm workspaces


## Privacy & Security

- **Local storage:** Profiles, resumes, applications, and generated documents are stored in PostgreSQL. Docker keeps the database in the local `postgres-data` volume. Some workspace data is also cached in the browser’s local storage.
- **API keys:** OpenAI and Bright Data keys are stored server-side in `.env`, which is excluded from Git. Keys must never be exposed through `NEXT_PUBLIC_*` variables.
- **AI processing:** AI features require explicit consent. Relevant profile and resume text, vacancy details, confirmations, and document templates are sent to the selected provider: OpenAI directly or through OpenClaw/Codex.
- **Retention:** AI-generated data is kept for a configurable period of 1–365 days, with 30 days as the default. Users can revoke consent or delete stored AI data.
- **Provider policies:** Direct OpenAI requests use `store: false`, but external processing remains subject to the selected provider’s privacy and retention policies.