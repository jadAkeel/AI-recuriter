from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── All known skills grouped by category ──────────────────────────
SKILL_CATEGORIES: dict[str, list[str]] = {
    "Programming Languages": [
        "python", "java", "c++", "c#", "javascript", "typescript",
        "go", "rust", "kotlin", "swift", "ruby", "php", "scala",
        "r", "perl", "dart", "elixir", "haskell", "lua", "solidity",
        "assembly", "vhdl", "verilog", "zig", "objective-c", "groovy",
        "clojure", "erlang", "f#", "fortran", "cobol", "pascal",
    ],
    "Frameworks": [
        "fastapi", "django", "flask", "spring", "spring boot",
        "node.js", "express", "react", "angular", "vue.js", "next.js",
        "nuxt", "svelte", "tailwind", "bootstrap", "jquery",
        "asp.net", "laravel", "symfony", "ruby on rails",
        "graphql", "apollo", "redux", "react native", "flutter",
        "rest api",
        "electron", "qt", "wxwidgets", "gtk", "shiny",
        "asp.net core", "blazor", "webapi", "wcf", "wpf",
        "django rest framework", "celery", "asp.net mvc", "mern",
    ],
    "AI/ML Tools": [
        "pytorch", "tensorflow", "scikit-learn", "pandas", "numpy",
        "keras", "jax", "hugging face", "transformers", "langchain",
        "llama", "openai", "llm", "prompt engineering", "rag",
        "machine learning", "deep learning", "nlp", "computer vision",
        "reinforcement learning", "mlops", "spacy", "nltk",
        "xgboost", "lightgbm", "catboost", "gensim",
        "stable diffusion", "onnx", "tensorrt", "mlflow",
        "kubeflow", "weka", "oracle data mining", "databricks",
        "airflow", "feature store", "model registry", "drift detection",
        "llamaindex", "vector database", "embedding", "fine tuning",
        "lora", "qlora", "rlhf", "langsmith", "haystack",
    ],
    "Cloud Platforms": [
        "aws", "azure", "gcp", "oracle cloud", "ibm cloud",
        "digitalocean", "heroku", "vercel", "netlify", "cloudflare",
        "aws lambda", "aws ec2", "aws s3", "aws rds", "aws dynamodb",
        "aws sqs", "aws sns", "aws cloudwatch", "aws iam",
        "aws certificate",
        "azure functions", "azure devops", "azure ai",
        "gcp cloud functions", "gcp cloud run", "gcp bigtable",
        "openstack", "vmware", "proxmox",
    ],
    "Databases": [
        "database", "sql", "postgresql", "mysql", "mongodb", "redis",
        "sqlite", "oracle", "sql server", "mariadb", "cassandra",
        "elasticsearch", "dynamodb", "couchdb", "neo4j", "influxdb",
        "snowflake", "bigquery", "redshift",
        "cockroachdb", "clickhouse", "timescaledb", "couchbase",
        "supabase", "firebase", "realm", "memcached", "hbase",
        "teradata", "db2", "sap hana", "singlestore", "sqlalchemy",
        "mongoose",
    ],
    "DevOps Tools": [
        "docker", "kubernetes", "terraform", "ansible", "jenkins",
        "ci/cd", "github actions", "gitlab ci", "argocd",
        "prometheus", "grafana", "helm", "istio", "nginx",
        "linux", "git", "devops", "bash", "unix",
        "vagrant", "packer", "vault", "consul", "nomad",
        "pulumi", "crossplane", "atlantis", "sonarqube",
        "nexus", "artifactory", "elk stack", "loki", "tempo",
        "datadog", "new relic", "splunk", "opentelemetry",
        "powershell", "makefile", "circleci", "travis ci",
    ],
    "Soft Skills": [
        "communication", "teamwork", "leadership", "problem solving",
        "critical thinking", "time management", "agile", "scrum",
        "project management", "presentation", "mentoring",
        "negotiation", "conflict resolution", "decision making",
        "emotional intelligence", "adaptability", "creativity",
        "collaboration", "stakeholder management", "coaching",
        "kanban", "sprint planning", "retrospective",
    ],
    "Data Engineering": [
        "etl", "data pipeline", "data warehouse", "data lake",
        "apache spark", "apache kafka", "apache flink", "apache beam",
        "hadoop", "hive", "pig", "sqoop", "oozie",
        "airbyte", "fivetran", "dbt", "dagster", "prefect",
        "delta lake", "apache iceberg", "apache hudi", "parquet",
        "avro", "protobuf", "data modeling", "dimensional modeling",
        "star schema", "snowflake schema", "oltp", "olap",
    ],
    "Testing/QA": [
        "unit testing", "integration testing", "e2e testing",
        "pytest", "junit", "jest", "mocha", "cypress",
        "selenium", "playwright", "cucumber", "gherkin",
        "load testing", "performance testing", "security testing",
        "mockito", "unittest", "tdd", "bdd",
    ],
    "Security": [
        "cybersecurity", "penetration testing", "ethical hacking",
        "owasp", "sdlc", "siem", "soar", "zero trust",
        "encryption", "authentication", "authorization", "oauth",
        "jwt", "saml", "oidc", "ssl/tls", "iso 27001",
        "compliance", "gdpr", "hipaa", "pci dss", "soc 2",
    ],
}

is_catalog_exhaustive = False


def _resolve_data_path(path_value: str) -> Path:
    """
    Resolves data paths from either the workspace root or the backend directory.
    """
    path = Path(path_value)
    if path.is_absolute() or path.exists():
        return path
    project_root = Path(__file__).resolve().parents[3]
    return project_root / path


def load_extra_skills(path: str | None = None) -> int:
    """
    Loads optional generated skills and merges them into the base catalog.
    """
    data_path = _resolve_data_path(path or settings.extra_skills_path)
    if not data_path.exists():
        return 0

    try:
        with data_path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        logger.warning("Failed to load extra skills", extra={"path": str(data_path), "error_type": type(exc).__name__})
        return 0

    categories = data.get("categories", data) if isinstance(data, dict) else {}
    if not isinstance(categories, dict):
        return 0

    added = 0
    for category, skills in categories.items():
        if not isinstance(skills, list):
            continue
        target = SKILL_CATEGORIES.setdefault(str(category), [])
        seen = {str(skill).lower().strip() for skill in target}
        for skill in skills:
            normalized = " ".join(str(skill or "").strip().lower().split())
            if not normalized or normalized in seen:
                continue
            target.append(normalized)
            seen.add(normalized)
            added += 1
    return added


load_extra_skills()

# ── Flat master list of all known skills ──────────────────────────
SKILL_KEYWORDS = sorted({
    skill
    for category in SKILL_CATEGORIES.values()
    for skill in category
})
ALLOWED_SKILLS = frozenset(SKILL_KEYWORDS)

NON_SKILL_JOB_TERMS = {
    "project",
    "projects",
    "project experience",
    "personal projects",
}

# ── Synonym groups for semantic matching ──────────────────────────
SYNONYM_GROUPS: list[set[str]] = [
    # AI/ML synonyms
    {"pytorch", "deep learning", "neural networks"},
    {"tensorflow", "deep learning", "neural networks"},
    {"keras", "deep learning"},
    {"scikit-learn", "machine learning", "ml"},
    {"pandas", "data analysis", "data manipulation"},
    {"numpy", "numerical computing"},
    {"transformers", "hugging face", "nlp", "llm"},
    {"langchain", "rag", "llm", "prompt engineering"},
    {"spacy", "nlp", "text processing"},
    {"nltk", "nlp", "text processing"},
    {"llamaindex", "rag", "vector database"},
    {"haystack", "rag", "nlp pipeline"},
    {"onnx", "model optimization", "inference"},
    {"mlflow", "mlops", "model registry"},
    {"airflow", "data pipeline", "workflow"},
    {"databricks", "spark", "data engineering"},
    {"fine tuning", "lora", "qlora", "transfer learning"},
    {"vector database", "vector databases", "vector db", "vector store", "pinecone", "faiss", "chroma", "chroma db", "qdrant", "weaviate", "milvus"},

    # Frameworks
    {"fastapi", "backend api", "rest api", "rest apis", "restful api", "restful apis", "restful api development"},
    {"django", "python web", "backend"},
    {"flask", "python web", "backend"},
    {"react", "frontend", "ui development"},
    {"angular", "frontend", "typescript"},
    {"vue.js", "frontend", "javascript"},
    {"node.js", "javascript runtime", "backend"},
    {"spring", "spring boot", "java backend"},
    {"asp.net", "asp.net core", "c# backend"},
    {"graphql", "apollo", "api"},
    {"react native", "flutter", "mobile development"},
    {"c++", "c/c++", "cpp", "c plus plus"},

    # DevOps
    {"docker", "containerization", "containers"},
    {"kubernetes", "k8s", "container orchestration"},
    {"terraform", "iac", "infrastructure as code"},
    {"ansible", "configuration management"},
    {"ci/cd", "github actions", "gitlab ci", "circleci", "automation"},
    {"prometheus", "grafana", "monitoring"},
    {"linux", "unix", "bash"},
    {"elk stack", "elasticsearch", "loki", "logging"},
    {"datadog", "new relic", "splunk", "observability"},
    {"opentelemetry", "observability", "tracing"},

    # Cloud
    {"aws", "amazon web services", "cloud computing"},
    {"aws", "amazon web services", "aws certificate", "aws certification", "aws certified", "aws cloud practitioner", "aws certified cloud practitioner"},
    {"azure", "microsoft cloud"},
    {"gcp", "google cloud", "google cloud platform"},
    {"aws lambda", "azure functions", "gcp cloud functions", "serverless"},

    # Databases
    {"sql", "relational database", "rdbms"},
    {"sql", "sqlalchemy", "orm", "relational database"},
    {"postgresql", "postgres", "relational database"},
    {"mongodb", "nosql", "document database"},
    {"database", "sql", "relational database", "rdbms"},
    {"database", "sql", "sqlalchemy", "orm", "relational database"},
    {"database", "postgresql", "postgres", "relational database"},
    {"database", "mongodb", "nosql", "document database"},
    {"mern", "mongodb", "express", "react", "node.js"},
    {"redis", "cache", "caching"},
    {"elasticsearch", "search engine", "full-text search"},
    {"snowflake", "data warehouse", "cloud data platform"},
    {"bigquery", "data warehouse", "google cloud"},

    # Data Engineering
    {"apache spark", "spark", "data processing"},
    {"apache kafka", "kafka", "event streaming"},
    {"dbt", "data transformation", "analytics engineering"},
    {"delta lake", "apache iceberg", "apache hudi", "data lakehouse"},
    {"hadoop", "apache hadoop", "big data"},

    # Testing
    {"pytest", "unit testing", "testing"},
    {"cypress", "playwright", "e2e testing"},
    {"tdd", "bdd", "test driven development"},

    # Security
    {"oauth", "jwt", "authentication", "authorization"},
    {"cybersecurity", "penetration testing", "ethical hacking"},

    # Soft skills
    {"communication", "interpersonal"},
    {"agile", "scrum", "kanban", "project management"},
    {"leadership", "mentoring", "coaching"},
]

# ── Build synonym mapping (skill → set of related skills) ─────────
SYNONYM_MAP: dict[str, set[str]] = {}
for group in SYNONYM_GROUPS:
    for skill in group:
        if skill not in SYNONYM_MAP:
            SYNONYM_MAP[skill] = set()
        SYNONYM_MAP[skill].update(group - {skill})


_SKILL_PATTERN_CACHE: dict[str, re.Pattern[str]] = {}


SKILL_SYNONYMS: dict[str, str] = {
    "deep learnign": "deep learning",
    "deep learing": "deep learning",
    "deeplearning": "deep learning",
    "py torch": "pytorch",
    "torch": "pytorch",
    "vector databse": "vector database",
    "vector databases": "vector database",
    "vector db": "vector database",
    "vector dbs": "vector database",
    "vectordb": "vector database",
    "vector store": "vector database",
    "vector stores": "vector database",
    "pinecone": "vector database",
    "faiss": "vector database",
    "chroma": "vector database",
    "chroma db": "vector database",
    "qdrant": "vector database",
    "weaviate": "vector database",
    "milvus": "vector database",
    "bigdata": "big data",
    "big-data": "big data",
    "apache hadoop": "hadoop",
    "c/c++": "c++",
    "c / c++": "c++",
    "c and c++": "c++",
    "cpp": "c++",
    "c plus plus": "c++",
    "python3": "python",
    "golang": "go",
    "js": "javascript",
    "react.js": "react",
    "reactjs": "react",
    "vue": "vue.js",
    "vuejs": "vue.js",
    "vue js": "vue.js",
    "node": "node.js",
    "nodejs": "node.js",
    "nextjs": "next.js",
    "next js": "next.js",
    "express.js": "express",
    "expressjs": "express",
    "k8s": "kubernetes",
    "tf": "tensorflow",
    "sklearn": "scikit-learn",
    "postgres": "postgresql",
    "postgresql db": "postgresql",
    "aws cert": "aws certificate",
    "aws certified": "aws certificate",
    "aws certification": "aws certificate",
    "aws cloud practitioner": "aws certificate",
    "aws certified cloud practitioner": "aws certificate",
    "sql alchemy": "sqlalchemy",
    "databsae": "database",
    "mern stack": "mern",
    "porble solving": "problem solving",
    "mongose": "mongoose",
    "rest apis": "rest api",
    "restful api": "rest api",
    "restful apis": "rest api",
    "restful api development": "rest api",
}
SKILL_ALIASES = SKILL_SYNONYMS


def _normalized_skill_token(skill: str) -> str:
    """
    Normalizes a skill token for catalog lookup.
    """
    return " ".join(str(skill or "").strip().lower().split())


def normalize_skill_name(skill: str) -> str:
    """
    Maps aliases and typo variants to canonical skill names.
    """
    normalized = _normalized_skill_token(skill)
    return SKILL_SYNONYMS.get(normalized, normalized)


def canonicalize_skill_name(skill: str) -> str | None:
    """
    Returns a canonical skill only when it exists in the allowed catalog.
    """
    normalized = normalize_skill_name(skill)
    return normalized if normalized in ALLOWED_SKILLS else None


def is_allowed_skill(skill: str) -> bool:
    """
    Checks whether a skill belongs to the allowed catalog.
    """
    return canonicalize_skill_name(skill) is not None


def is_job_skill_name(skill: str) -> bool:
    """
    Checks whether a normalized skill is valid for job requirements.
    """
    return normalize_skill_name(skill) not in NON_SKILL_JOB_TERMS


def normalize_skill_list(skills: list[str]) -> list[str]:
    """
    Normalizes and de-duplicates a list of skills.
    """
    result: list[str] = []
    seen: set[str] = set()
    for skill in skills or []:
        normalized = normalize_skill_name(skill)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def add_dynamic_synonym(skill_a: str, skill_b: str) -> None:
    """
    Adds a runtime synonym relationship learned from recruiter feedback.
    """
    first = normalize_skill_name(skill_a)
    second = normalize_skill_name(skill_b)
    if not first or not second or first == second:
        return
    SYNONYM_MAP.setdefault(first, set()).add(second)
    SYNONYM_MAP.setdefault(second, set()).add(first)
    SKILL_MATCH_VARIANTS.setdefault(first, {first}).add(second)
    SKILL_MATCH_VARIANTS.setdefault(second, {second}).add(first)
    _SKILL_PATTERN_CACHE.pop(first, None)
    _SKILL_PATTERN_CACHE.pop(second, None)


def validate_catalog_skill_list(skills: list[str]) -> list[str]:
    """
    Keeps only known catalog skills from a list.
    """
    result: list[str] = []
    seen: set[str] = set()
    for skill in skills or []:
        canonical = canonicalize_skill_name(skill)
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def normalize_text_for_skill_matching(text: str) -> str:
    """
    Normalizes free text before token-safe skill matching.
    """
    lowered = str(text or "").lower()
    lowered = lowered.replace("/", " ")
    lowered = re.sub(r"[^a-z0-9+#.\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _build_match_variants() -> dict[str, set[str]]:
    """
    Builds alias variants used by skill matching regexes.
    """
    variants = {skill: {skill} for skill in SKILL_KEYWORDS}
    for alias, canonical in SKILL_SYNONYMS.items():
        if canonical in variants:
            variants[canonical].add(alias)
    return variants


SKILL_MATCH_VARIANTS = _build_match_variants()


def build_skill_pattern(skill: str) -> re.Pattern[str]:
    """Build a token-safe skill matcher that also handles C++, C#, CI/CD, etc."""

    normalized_skill = normalize_skill_name(skill)
    cached = _SKILL_PATTERN_CACHE.get(normalized_skill)
    if cached:
        return cached

    if normalized_skill == "c++":
        pattern = re.compile(
            r"(?<![\w+#./-])(?:c\+\+|c\s*(?:/|and)\s*c\+\+|cpp|c\s+plus\s+plus)(?![\w+#./-])",
            re.IGNORECASE,
        )
        _SKILL_PATTERN_CACHE[normalized_skill] = pattern
        return pattern

    if normalized_skill == "vector database":
        pattern = re.compile(
            r"(?<![\w+#./-])(?:vector\s+(?:database|databases|db|dbs|store|stores)|pinecone|faiss|chroma(?:\s+db)?|qdrant|weaviate|milvus)(?![\w+#./-])",
            re.IGNORECASE,
        )
        _SKILL_PATTERN_CACHE[normalized_skill] = pattern
        return pattern

    if normalized_skill == "rest api":
        pattern = re.compile(
            r"(?<![\w+#./-])rest(?:ful)?\s+apis?(?:\s+development)?(?![\w+#/-]|\.(?=\w))",
            re.IGNORECASE,
        )
        _SKILL_PATTERN_CACHE[normalized_skill] = pattern
        return pattern

    variant_patterns: list[str] = []
    for variant in sorted(SKILL_MATCH_VARIANTS.get(normalized_skill, {normalized_skill}), key=len, reverse=True):
        escaped = re.escape(variant)
        escaped = escaped.replace(r"\ ", r"\s+")
        escaped = escaped.replace(r"\-", r"(?:-|\s+)")
        escaped = escaped.replace("/", r"(?:/|\s+|-)")
        escaped = escaped.replace(r"\/", r"(?:/|\s+|-)")
        variant_patterns.append(escaped)
    pattern_body = "|".join(variant_patterns)
    pattern = re.compile(
        rf"(?<![\w+#./-])(?:{pattern_body})(?![\w+#/-]|\.(?=\w))",
        re.IGNORECASE,
    )
    _SKILL_PATTERN_CACHE[normalized_skill] = pattern
    return pattern


def skill_in_text(skill: str, normalized_text: str) -> bool:
    """
    Checks whether a skill appears in normalized text.
    """
    return bool(build_skill_pattern(skill).search(normalized_text))


def extract_catalog_skills(text: str) -> list[str]:
    """
    Extracts all catalog skills found in free text.
    """
    normalized_text = normalize_text_for_skill_matching(text)
    return [skill for skill in SKILL_KEYWORDS if skill_in_text(skill, normalized_text)]


_UNCATALOGUED_STOPWORDS = {
    "built",
    "candidate",
    "education",
    "experience",
    "professional",
    "projects",
    "skills",
    "summary",
    "technologies",
    "tools",
    "using",
    "workflows",
}


def extract_uncatalogued_skills(text: str, known_skills: list[str] | None = None) -> list[str]:
    """
    Finds grounded technical-looking terms that are not in the curated catalog.
    """
    known = {normalize_skill_name(skill) for skill in known_skills or []}
    known.update(SKILL_KEYWORDS)
    candidates: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\b[A-Za-z][A-Za-z0-9+#.-]{2,}(?:\s+[A-Za-z][A-Za-z0-9+#.-]{2,}){0,2}\b", text or ""):
        raw = " ".join(match.group(0).split())
        normalized = normalize_skill_name(raw)
        if not normalized or normalized in known or normalized in seen:
            continue
        tokens = normalized.split()
        if any(token in _UNCATALOGUED_STOPWORDS for token in tokens):
            continue
        has_tech_shape = any(char.isupper() for char in raw[1:]) or any(char in raw for char in "+#.-")
        near_skill_header = (text or "")[max(0, match.start() - 80):match.start()].lower()
        if not has_tech_shape and not any(header in near_skill_header for header in ("skills", "technologies", "tools")):
            continue
        seen.add(normalized)
        candidates.append(normalized[:120])
        if len(candidates) >= 50:
            break
    return candidates


def get_skill_category(skill: str) -> str | None:
    """
    Returns the catalog category for a skill.
    """
    skill_lower = normalize_skill_name(skill)
    for category, skills in SKILL_CATEGORIES.items():
        if skill_lower in skills:
            return category
    return None


def get_related_skills(skill: str) -> list[str]:
    """
    Returns curated related skills for a skill.
    """
    skill_lower = normalize_skill_name(skill)
    return sorted(SYNONYM_MAP.get(skill_lower, []))


def get_categories() -> dict[str, list[str]]:
    """
    Returns the skill catalog grouped by category.
    """
    return dict(SKILL_CATEGORIES)
