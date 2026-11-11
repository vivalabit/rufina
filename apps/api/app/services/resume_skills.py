"""Shared CV skill categories; relevance within them is selected by the author."""

from app.models.resume import MasterResume, MasterSkill

CORE_SKILL_CATEGORIES = ("Languages", "Frameworks", "Databases", "Tools / DevOps")

_CATEGORY_ALIASES = {
    "languages": "Languages",
    "programming languages": "Languages",
    "programming / scripting": "Languages",
    "frameworks": "Frameworks",
    "python frameworks": "Frameworks",
    "frameworks / libraries": "Frameworks",
    "frameworks & libraries": "Frameworks",
    "libraries / frameworks": "Frameworks",
    "databases": "Databases",
    "database": "Databases",
    "databases / storage": "Databases",
    "databases & storage": "Databases",
    "tools / devops": "Tools / DevOps",
    "tools/devops": "Tools / DevOps",
    "devops / tools": "Tools / DevOps",
    "tools": "Tools / DevOps",
    "devops": "Tools / DevOps",
    "cloud / devops": "Tools / DevOps",
    "cloud & devops": "Tools / DevOps",
}

# Older/free-text profiles may have missing or broad labels such as "Data".
# Classify recognizable technologies by meaning; use source metadata for unknown
# technologies, without making every unclassified concept a core skill.
_CORE_TECHNOLOGIES = {
    "Languages": (
        "Python", "JavaScript", "TypeScript", "Java", "C", "C++", "C#", "Go", "Golang",
        "Rust", "Ruby", "PHP", "Swift", "Kotlin", "Scala", "R", "SQL", "HTML", "CSS",
        "HTML/CSS", "Bash", "Shell", "PowerShell", "Perl", "Elixir", "Dart", "Julia", "Lua",
    ),
    "Frameworks": (
        "Django", "FastAPI", "Flask", "Starlette", "Tornado", "Pyramid", "Sanic", "Bottle",
        "Pydantic", "SQLAlchemy", "Celery", "React", "Next.js", "Angular", "Vue", "Vue.js",
        "Spring", "Spring Boot", ".NET", "ASP.NET Core", "Rails", "Laravel", "Express",
        "NestJS", "PyTorch", "TensorFlow", "scikit-learn", "Spark",
    ),
    "Databases": (
        "PostgreSQL", "Postgres", "MySQL", "MariaDB", "SQLite", "MongoDB", "Redis",
        "DynamoDB", "Cassandra", "Elasticsearch", "OpenSearch", "Oracle", "SQL Server", "Neo4j",
    ),
    "Tools / DevOps": (
        "Docker", "Git", "GitHub", "GitHub Actions", "Linux", "AWS", "Azure", "GCP",
        "Kubernetes", "Terraform", "Ansible", "Jenkins", "CI/CD", "Nginx", "Node.js",
        "RabbitMQ", "Kafka", "Prometheus", "Grafana", "Helm", "Poetry", "pip", "uv",
        "Conda", "Pytest", "Ruff", "mypy", "Black", "Playwright", "Selenium",
    ),
}
_CORE_TECHNOLOGY_CATEGORIES = {
    name.casefold(): category
    for category, names in _CORE_TECHNOLOGIES.items()
    for name in names
}


def normalize_skill_category(category: str) -> str:
    cleaned = " ".join(category.split())
    return _CATEGORY_ALIASES.get(cleaned.casefold(), cleaned)


def source_skill_category(skill: MasterSkill) -> str:
    return _CORE_TECHNOLOGY_CATEGORIES.get(skill.name.casefold()) or normalize_skill_category(
        skill.category
    )


def source_skill_policy(master: MasterResume) -> dict[str, object]:
    """Expose the grounding rules using only the run's frozen source skills.

    Source labels can be blank or legacy labels. Authors and reviewers must see
    the same canonical membership that grounding restores after every revision.
    """
    return {
        "categoryOrder": list(CORE_SKILL_CATEGORIES),
        "requiredSkills": [
            {"id": skill.id, "name": skill.name, "category": category}
            for skill in master.skills
            if (category := source_skill_category(skill)) in CORE_SKILL_CATEGORIES
        ],
        "exactDuplicatesMayBeConsolidated": True,
    }


def order_skill_categories(skills: list[MasterSkill]) -> list[MasterSkill]:
    """Keep vacancy priority inside groups while putting core groups first."""
    categories = dict.fromkeys(CORE_SKILL_CATEGORIES)
    for item in skills:
        categories.setdefault(normalize_skill_category(item.category), None)
    rank = {category: index for index, category in enumerate(categories)}
    return sorted(skills, key=lambda item: rank[normalize_skill_category(item.category)])
