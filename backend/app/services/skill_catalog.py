from __future__ import annotations

import re


# ── Skill Categories ──────────────────────────────────────────────
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
        "node.js", "express", "react", "angular", "vue", "next.js",
        "nuxt", "svelte", "tailwind", "bootstrap", "jquery",
        "asp.net", "laravel", "symfony", "ruby on rails",
        "graphql", "apollo", "redux", "react native", "flutter",
        "electron", "qt", "wxwidgets", "gtk", "shiny",
        "asp.net core", "blazor", "webapi", "wcf", "wpf",
        "django rest framework", "celery", "asp.net mvc",
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
        "azure functions", "azure devops", "azure ai",
        "gcp cloud functions", "gcp cloud run", "gcp bigtable",
        "openstack", "vmware", "proxmox",
    ],
    "Databases": [
        "sql", "postgresql", "mysql", "mongodb", "redis",
        "sqlite", "oracle", "sql server", "mariadb", "cassandra",
        "elasticsearch", "dynamodb", "couchdb", "neo4j", "influxdb",
        "snowflake", "bigquery", "redshift",
        "cockroachdb", "clickhouse", "timescaledb", "couchbase",
        "supabase", "firebase", "realm", "memcached", "hbase",
        "teradata", "db2", "sap hana", "singlestore",
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

# ── All skills flat list (sorted, unique) ─────────────────────────
SKILL_KEYWORDS = sorted({
    skill
    for category in SKILL_CATEGORIES.values()
    for skill in category
})

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

    # Frameworks
    {"fastapi", "backend api", "rest api"},
    {"django", "python web", "backend"},
    {"flask", "python web", "backend"},
    {"react", "frontend", "ui development"},
    {"angular", "frontend", "typescript"},
    {"vue", "frontend", "javascript"},
    {"node.js", "javascript runtime", "backend"},
    {"spring", "spring boot", "java backend"},
    {"asp.net", "asp.net core", "c# backend"},
    {"graphql", "apollo", "api"},
    {"react native", "flutter", "mobile development"},

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
    {"azure", "microsoft cloud"},
    {"gcp", "google cloud", "google cloud platform"},
    {"aws lambda", "azure functions", "gcp cloud functions", "serverless"},

    # Databases
    {"sql", "relational database", "rdbms"},
    {"postgresql", "postgres", "relational database"},
    {"mongodb", "nosql", "document database"},
    {"redis", "cache", "caching"},
    {"elasticsearch", "search engine", "full-text search"},
    {"snowflake", "data warehouse", "cloud data platform"},
    {"bigquery", "data warehouse", "google cloud"},

    # Data Engineering
    {"apache spark", "spark", "data processing"},
    {"apache kafka", "kafka", "event streaming"},
    {"dbt", "data transformation", "analytics engineering"},
    {"delta lake", "apache iceberg", "apache hudi", "data lakehouse"},

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


def build_skill_pattern(skill: str) -> re.Pattern[str]:
    """Build a token-safe skill matcher that also handles C++, C#, CI/CD, etc."""

    normalized_skill = skill.lower().strip()
    cached = _SKILL_PATTERN_CACHE.get(normalized_skill)
    if cached:
        return cached

    escaped = re.escape(normalized_skill)
    escaped = escaped.replace(r"\ ", r"\s+")
    escaped = escaped.replace("/", r"(?:/|\s+|-)")
    escaped = escaped.replace(r"\/", r"(?:/|\s+|-)")
    pattern = re.compile(
        rf"(?<![\w+#./-]){escaped}(?![\w+#./-])",
        re.IGNORECASE,
    )
    _SKILL_PATTERN_CACHE[normalized_skill] = pattern
    return pattern


def skill_in_text(skill: str, normalized_text: str) -> bool:
    return bool(build_skill_pattern(skill).search(normalized_text))


def get_skill_category(skill: str) -> str | None:
    skill_lower = skill.lower().strip()
    for category, skills in SKILL_CATEGORIES.items():
        if skill_lower in skills:
            return category
    return None


def get_related_skills(skill: str) -> list[str]:
    skill_lower = skill.lower().strip()
    return sorted(SYNONYM_MAP.get(skill_lower, []))


def get_categories() -> dict[str, list[str]]:
    return dict(SKILL_CATEGORIES)


ARABIC_SKILL_KEYWORDS = sorted(
    {
        "بايثون", "جافا", "جافاسكريبت", "سي شارب", "بي اتش بي",
        "روبي", "سويفت", "كوتلن", "دارت",
        "قاعدة بيانات", "بوستجري", "مونجو دي بي", "ريديس",
        "دوکر", "كوبرنيتيز", "أمازون ويب", "أزور", "سحاب",
        "غيت", "لينكس", "ويندوز",
        "تعلم آلة", "تعلم عميق", "ذكاء اصطناعي", "معالجة نصوص",
        "تحليل بيانات", "تصور بيانات",
        "تطوير ويب", "تطوير تطبيقات", "أمن سيبراني", "شبكات",
        "اختبار", "ديف أوبس", "أجايل", "سكروم",
        "سبارك", "كafka", "دوكر", "بايثون", "بيانات كبيرة",
        "حوسبة سحابية", "تطوير برمجيات", "هندسة برمجيات",
    }
)
