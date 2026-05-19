#!/usr/bin/env python
from __future__ import annotations

import re
import random
from datetime import datetime
from pathlib import Path

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.colors import black, darkblue
except ImportError:
    print("[ERROR] 'reportlab' library not installed.")
    print("Run: pip install reportlab")
    import sys
    sys.exit(1)


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "cvs_to_upload"
MAX_CVS = 100

CS_SKILLS = [
    "Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "Go", "Rust",
    "React", "Angular", "Vue.js", "Next.js", "Node.js", "Express", "Django", "Flask", "FastAPI",
    "SQL", "PostgreSQL", "MongoDB", "Redis", "MySQL", "Elasticsearch",
    "Machine Learning", "Deep Learning", "NLP", "Computer Vision", "TensorFlow", "PyTorch", "scikit-learn",
    "Git", "Docker", "Kubernetes", "AWS", "Azure", "GCP", "Linux",
    "REST API", "GraphQL", "CI/CD", "Agile", "TDD", "Microservices",
    "Data Structures", "Algorithms", "System Design", "OOP", "Functional Programming",
]

LEVELS = {
    "graduate": {"weight": 25, "label": "Fresh Graduate", "years_range": (0, 1), "jobs": 0, "intern_prob": 0.9, "seniority_tag": "entry"},
    "junior":   {"weight": 20, "label": "Junior",          "years_range": (1, 3), "jobs": 1, "intern_prob": 0.5, "seniority_tag": "junior"},
    "mid":      {"weight": 25, "label": "Mid-Level",       "years_range": (3, 6), "jobs": 2, "intern_prob": 0.3, "seniority_tag": "mid"},
    "senior":   {"weight": 20, "label": "Senior",          "years_range": (6, 10), "jobs": 3, "intern_prob": 0.1, "seniority_tag": "senior"},
    "lead":     {"weight": 10, "label": "Lead/Principal",  "years_range": (10, 18), "jobs": 4, "intern_prob": 0.0, "seniority_tag": "lead"},
}

JOB_TEMPLATES = [
    {"title": "Junior Software Engineer",          "min_years": 0, "max_years": 2, "desc": [
        "Developed and maintained web application features using {tech}.",
        "Implemented unit tests and participated in code reviews.",
        "Fixed bugs and contributed to sprint planning and daily standups.",
    ]},
    {"title": "Software Engineer",                 "min_years": 1, "max_years": 5, "desc": [
        "Designed and implemented RESTful APIs using {tech} serving {x} requests/day.",
        "Built scalable microservices and improved system reliability to {x}% uptime.",
        "Mentored junior developers and conducted technical interviews.",
        "Optimized database queries reducing average latency by {x}%.",
        "Led migration of legacy monolith to microservices architecture.",
    ]},
    {"title": "Senior Software Engineer",          "min_years": 4, "max_years": 10, "desc": [
        "Architected and led development of a {x}-service platform handling {x}M users.",
        "Designed system architecture and tech roadmap for {x} engineering teams.",
        "Reduced infrastructure costs by {x}% through optimization and cloud migration.",
        "Established coding standards, CI/CD pipelines, and engineering best practices.",
        "Led cross-team initiatives and drove adoption of {tech} across the organization.",
    ]},
    {"title": "Lead Software Engineer",            "min_years": 7, "max_years": 15, "desc": [
        "Managed a team of {x} engineers, driving delivery of critical platform features.",
        "Defined technical strategy and architecture for {x} product lines.",
        "Drove adoption of {tech} org-wide, resulting in {x}% improvement in developer velocity.",
        "Owned production SLAs and led incident response for high-availability systems.",
        "Partnered with product and design leadership to align technical roadmap with business goals.",
    ]},
    {"title": "Principal Engineer",                "min_years": 10, "max_years": 20, "desc": [
        "Set technical vision and engineering strategy for the entire organization.",
        "Designed large-scale distributed systems processing {x} TB of data daily.",
        "Led architectural reviews and mentored senior engineers across {x} teams.",
        "Drove {x}% cost reduction through infrastructure redesign and vendor consolidation.",
        "Founded internal platform that reduced time-to-market for new features by {x}%.",
    ]},
    {"title": "Backend Developer",                 "min_years": 0, "max_years": 5, "desc": [
        "Developed and maintained server-side logic and APIs using {tech}.",
        "Designed database schemas and optimized complex queries for performance.",
        "Implemented authentication, authorization, and data validation layers.",
    ]},
    {"title": "Senior Backend Developer",          "min_years": 4, "max_years": 10, "desc": [
        "Architected distributed backend systems serving {x} concurrent users.",
        "Led migration from monolith to event-driven microservices architecture.",
        "Optimized system throughput by {x}% through caching and async processing.",
    ]},
    {"title": "Frontend Developer",                "min_years": 0, "max_years": 4, "desc": [
        "Built responsive UI components using {tech} following design mockups.",
        "Integrated REST APIs and managed application state with {tech}.",
        "Improved Core Web Vitals achieving {x}% Lighthouse performance score.",
    ]},
    {"title": "Senior Frontend Developer",         "min_years": 4, "max_years": 10, "desc": [
        "Led frontend architecture for a {x}-page SaaS application with {x}K daily users.",
        "Built reusable component library used across {x} product teams.",
        "Reduced bundle size by {x}% through code splitting and lazy loading.",
    ]},
    {"title": "Full Stack Developer",              "min_years": 1, "max_years": 6, "desc": [
        "Built end-to-end features spanning React frontend and {tech} backend.",
        "Owned product lifecycle from requirements gathering to production deployment.",
        "Implemented CI/CD pipeline reducing deployment time from hours to minutes.",
    ]},
    {"title": "Senior Full Stack Developer",       "min_years": 5, "max_years": 12, "desc": [
        "Architected and built full-stack platform serving {x} enterprise clients.",
        "Led technical design reviews and mentored {x} full-stack developers.",
        "Drove migration from jQuery monolith to React + microservices architecture.",
    ]},
    {"title": "DevOps Engineer",                   "min_years": 1, "max_years": 6, "desc": [
        "Managed Kubernetes clusters across {x} environments with {x} microservices.",
        "Automated infrastructure provisioning using Terraform and CI/CD pipelines.",
        "Reduced deployment failure rate by {x}% through improved monitoring and rollback strategies.",
    ]},
    {"title": "Senior DevOps Engineer",            "min_years": 5, "max_years": 12, "desc": [
        "Designed and managed multi-cloud infrastructure on AWS/GCP serving {x}M users.",
        "Built internal developer platform reducing environment setup from days to minutes.",
        "Led incident response and established SRE practices achieving {x}% uptime.",
    ]},
    {"title": "ML Engineer",                       "min_years": 1, "max_years": 6, "desc": [
        "Designed and deployed ML models for {task} with {x}% accuracy.",
        "Built ML pipelines for data collection, training, and model serving.",
        "Optimized inference latency by {x}ms through model quantization and distillation.",
    ]},
    {"title": "Senior ML Engineer",                "min_years": 5, "max_years": 12, "desc": [
        "Led ML platform development serving {x} models in production.",
        "Designed feature store and model registry infrastructure for {x} data science teams.",
        "Drove MLOps adoption reducing model deployment time from weeks to hours.",
    ]},
    {"title": "Data Scientist",                    "min_years": 1, "max_years": 5, "desc": [
        "Analyzed large datasets to extract business insights using {tech}.",
        "Built predictive models improving customer retention by {x}%.",
        "Created dashboards and reports for executive decision-making.",
    ]},
    {"title": "Engineering Manager",               "min_years": 6, "max_years": 15, "desc": [
        "Managed and coached {x} software engineers across {x} teams.",
        "Owned quarterly OKRs and delivery roadmap for the engineering org.",
        "Improved engineering productivity by {x}% through process improvements and tooling.",
        "Led hiring, onboarding, and career development for the team.",
    ]},
    {"title": "Tech Lead",                         "min_years": 5, "max_years": 12, "desc": [
        "Provided technical leadership for {x} squads working on {domain}.",
        "Designed system architecture and ensured alignment with engineering standards.",
        "Unblocked teams through technical decision-making and cross-team collaboration.",
    ]},
    {"title": "Cloud Architect",                   "min_years": 7, "max_years": 18, "desc": [
        "Designed multi-region cloud architecture on {tech} for {x}% availability.",
        "Led cloud migration of {x} services from on-premises to cloud infrastructure.",
        "Established cloud governance and cost optimization saving ${x}K annually.",
    ]},
]

COMPANIES = [
    "TechNova Solutions", "DataPulse Inc.", "CloudForge Systems", "NexGen Digital",
    "Quantum Labs", "Apex Innovations", "Pioneer Tech", "BrightHire Technologies",
    "Vertex Software", "OmniStack Corp", "BayanLabs", "Sidra Technologies",
    "Beehive Systems", "ArcGate Software", "MintLayer Inc.", "Rising Star Tech",
    "EvolveX", "DeepBlue AI", "PixelCraft Studios", "Nebula Cloud Services",
    "LuminAI", "RedRock Engineering", "SkyBridge Technologies", "IronClad Systems",
]

FIRST_NAMES = ["Omar", "Ali", "Khaled", "Hassan", "Karim", "Youssef", "Bilal", "Tarek", "Rami",
               "Sarah", "Layla", "Nour", "Hana", "Mira", "Zeina", "Jana", "Lama", "Tala",
               "Ahmed", "Mohammad", "Amir", "Samer", "Fadi", "Marwan", "Zaid",
               "Hadi", "Jad", "Elie", "Georges", "Pierre", "Charbel", "Antoine",
               "Rita", "Maria", "Christina", "Racha", "Nadia", "Nisrine", "Maya",
               "Ralph", "Tony", "Elias", "Wassim", "Mahmoud", "Hussein", "Moustafa",
               "Dima", "Reem", "Lina", "Nada", "Mona", "Samar", "Rima", "Rola",
               "Fouad", "Ghassan", "Adnan", "Walid", "Nabil", "Raymond", "Camille"]

LAST_NAMES = ["Khalil", "Hassan", "Khoury", "Gemayel", "Aoun", "Hariri", "Jumblatt", "Geagea",
              "Rizk", "Haddad", "Choueiri", "Moussawi", "Berri", "Suleiman", "Frangieh",
              "Alameddine", "Chalhoub", "Fares", "Ghosn", "Kanaan", "Makhoul", "Saliba",
              "Hobeika", "Hayek", "Karam", "Saadeh", "Mansour", "Shahin", "Maalouf",
              "Hanna", "Ibrahim", "Abboud", "Awwad", "Fakhry", "Helou", "Najjar",
              "Torbey", "Renauld", "Saade", "Yared", "Hage", "Mattar", "Farah",
              "Sarkis", "Tawk", "Mazloum", "Feghali", "Abou Jaoude", "Nader"]

UNIVERSITIES = [
    ("American University of Beirut", "AUB"),
    ("Lebanese American University", "LAU"),
    ("Saint Joseph University", "USJ"),
    ("University of Balamand", "UOB"),
    ("Beirut Arab University", "BAU"),
    ("Lebanese University", "LU"),
    ("Notre Dame University", "NDU"),
    ("Lebanese International University", "LIU"),
    ("Jinan University", "Jinan"),
    ("Al-Mustafa University", "Mustafa"),
]

INTERNSHIPS = [
    {"company": "Tech Solutions Inc.", "role": "Software Engineering Intern",
     "desc": "Developed internal tools using React and Python. Participated in code reviews and agile ceremonies."},
    {"company": "DataFlow AI", "role": "Machine Learning Intern",
     "desc": "Worked on NLP pipelines and model optimization. Improved inference time by 40% through quantization."},
    {"company": "CloudNine Systems", "role": "Backend Development Intern",
     "desc": "Built RESTful APIs using Node.js and Express. Implemented caching strategies with Redis."},
    {"company": "Digital Innovations", "role": "Full Stack Intern",
     "desc": "Maintained customer-facing applications. Fixed critical bugs and improved test coverage from 60% to 85%."},
]

GRAD_PROJECTS = [
    {
        "name": "Full-Stack E-Commerce Platform",
        "desc": "Built a complete e-commerce solution with React frontend and Node.js backend. Implemented user authentication, product catalog, shopping cart, and Stripe payment integration.",
        "tech": ["React", "Node.js", "Express", "MongoDB", "Stripe", "JWT"]
    },
    {
        "name": "AI Chatbot with RAG",
        "desc": "Developed an intelligent chatbot using Retrieval-Augmented Generation. Uses LangChain for document processing, OpenAI embeddings, and Pinecone vector database for semantic search.",
        "tech": ["Python", "LangChain", "OpenAI", "FastAPI", "RAG", "LLM"]
    },
    {
        "name": "Real-Time Collaborative Editor",
        "desc": "Created a Google Docs-like collaborative editor with real-time synchronization. Uses WebSocket for live updates, operational transformation for conflict resolution.",
        "tech": ["React", "Node.js", "WebSocket", "MongoDB", "Redis", "Docker"]
    },
    {
        "name": "Sentiment Analysis Dashboard",
        "desc": "Built a dashboard that analyzes social media sentiment in real-time. Uses Twitter API, VADER for sentiment analysis, and Dash for interactive visualizations.",
        "tech": ["Python", "scikit-learn", "NLP", "Dash", "Plotly", "Pandas"]
    },
    {
        "name": "Task Management API",
        "desc": "Designed and implemented a RESTful API for task management with role-based access control, JWT authentication, and PostgreSQL database.",
        "tech": ["FastAPI", "PostgreSQL", "SQLAlchemy", "JWT", "Docker", "Pytest"]
    },
    {
        "name": "Image Classification CNN",
        "desc": "Trained a convolutional neural network for multi-class image classification on CIFAR-10 dataset. Achieved 92% accuracy using data augmentation and transfer learning.",
        "tech": ["Python", "PyTorch", "TensorFlow", "CNN", "Deep Learning", "NumPy"]
    },
]

EXP_PROJECTS = [
    {
        "name": "Real-Time Data Pipeline Platform",
        "desc": "Architected a streaming data pipeline processing 50K events/sec using Kafka, Spark, and Cassandra. Built monitoring dashboards and automated scaling policies.",
        "tech": {"Kafka", "Spark", "Cassandra", "Python", "Docker", "Kubernetes", "Prometheus"}
    },
    {
        "name": "Multi-Tenant SaaS Platform",
        "desc": "Led development of a multi-tenant SaaS platform serving 500+ enterprise clients. Implemented tenant isolation, usage metering, and self-service admin portal.",
        "tech": {"React", "Node.js", "PostgreSQL", "Redis", "Docker", "AWS"}
    },
    {
        "name": "Microservices Migration Initiative",
        "desc": "Led migration of 50+ services from monolith to event-driven microservices. Reduced deployment time by 80% and improved fault isolation.",
        "tech": {"Kubernetes", "Docker", "Kafka", "gRPC", "Terraform", "AWS"}
    },
    {
        "name": "AI-Powered Recommendation Engine",
        "desc": "Built a real-time recommendation system using collaborative filtering and deep learning. Improved click-through rate by 35% and user engagement by 50%.",
        "tech": {"Python", "PyTorch", "TensorFlow", "Redis", "Kubernetes", "PostgreSQL"}
    },
    {
        "name": "Cloud Cost Optimization Platform",
        "desc": "Developed an internal platform for cloud cost tracking, anomaly detection, and automated rightsizing. Saved $2M annually in cloud infrastructure costs.",
        "tech": {"Python", "AWS", "Terraform", "Grafana", "Prometheus", "Go"}
    },
    {
        "name": "Developer Experience Portal",
        "desc": "Built an internal developer portal with service catalog, documentation, CI/CD templates, and environment management. Adopted by 200+ engineers across 15 teams.",
        "tech": {"React", "Go", "Docker", "Kubernetes", "PostgreSQL", "GraphQL"}
    },
    {
        "name": "Global CDN & Edge Computing Platform",
        "desc": "Designed a multi-region CDN platform with edge computing capabilities. Reduced global latency by 60% and handled 100TB daily traffic.",
        "tech": {"Go", "Kubernetes", "AWS", "Cloudflare", "Redis", "gRPC"}
    },
    {
        "name": "Enterprise Search Engine",
        "desc": "Built a distributed search engine indexing 1B+ documents with sub-100ms query latency. Implemented semantic search using transformer-based embeddings.",
        "tech": {"Python", "Elasticsearch", "Kubernetes", "TensorFlow", "FastAPI", "Docker"}
    },
    {
        "name": "ML Model Serving Platform",
        "desc": "Created a platform for deploying and serving ML models at scale. Supported A/B testing, canary deployments, and automatic rollback for 50+ production models.",
        "tech": {"Python", "Kubernetes", "TensorFlow", "PyTorch", "FastAPI", "Prometheus"}
    },
    {
        "name": "Real-Time Analytics Dashboard",
        "desc": "Built a real-time analytics dashboard processing 10M+ events daily. Implemented sub-second query performance using materialized views and pre-aggregations.",
        "tech": {"React", "Python", "PostgreSQL", "Redis", "Docker", "ClickHouse"}
    },
]


def sanitize_filename(name: str) -> str:
    """
    Converts text into a safe filename.
    """
    clean = re.sub(r'[<>:"/\\|?*]', '_', name)
    clean = re.sub(r'\s+', '_', clean)
    return clean.strip('_')[:80]


def pick_level() -> tuple[str, dict]:
    """
    Chooses an experience level for a generated resume.
    """
    total_weight = sum(LEVELS[l]["weight"] for l in LEVELS)
    r = random.randint(1, total_weight)
    cumulative = 0
    for lvl_name, cfg in LEVELS.items():
        cumulative += cfg["weight"]
        if r <= cumulative:
            return lvl_name, cfg
    return "graduate", LEVELS["graduate"]


def pick_job_templates(exp_years: int, count: int) -> list[dict]:
    """
    Selects job templates that fit generated experience years.
    """
    suitable = [j for j in JOB_TEMPLATES if j["min_years"] <= exp_years and j["max_years"] >= exp_years * 0.5]
    if len(suitable) < count:
        suitable = sorted(JOB_TEMPLATES, key=lambda j: abs((j["min_years"] + j["max_years"]) / 2 - exp_years))
    selected = random.sample(suitable, min(count, len(suitable)))
    selected.sort(key=lambda j: j["min_years"])
    return selected


def fill_template(text: str, tech: list[str], job_index: int = 0) -> str:
    """
    Fills a resume template with selected technologies.
    """
    x_values = [random.randint(2, 9), random.randint(10, 99), random.randint(100, 999), random.randint(1000, 9999)]
    replacements = {
        "{tech}": random.choice(tech) if tech else "Python",
        "{x}": str(random.choice(x_values)),
        "{task}": random.choice(["classification", "regression", "NLP", "recommendation", "anomaly detection"]),
        "{domain}": random.choice(["backend", "infrastructure", "data platform", "ML platform", "developer tools"]),
    }
    result = text
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value, 1)
    return result


def generate_resume(index: int) -> dict:
    """
    Generates one synthetic computer science resume record.
    """
    current_year = datetime.now().year
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    full_name = f"{first} {last}"
    email = f"{first.lower()}.{last.lower()}{random.randint(1,999)}@gmail.com"
    phone = f"+961-{random.randint(3,81)}-{random.randint(100000,999999)}"

    lvl_name, level_cfg = pick_level()
    exp_years = random.randint(*level_cfg["years_range"])
    university, uni_short = random.choice(UNIVERSITIES)

    base_skill_count = random.randint(4, 8)
    extra_skills = min(exp_years // 2, 8)
    num_skills = min(base_skill_count + extra_skills, len(CS_SKILLS))
    skills = random.sample(CS_SKILLS, num_skills)

    job_count = min(level_cfg["jobs"], exp_years)
    job_templates = pick_job_templates(exp_years, job_count) if job_count > 0 else []
    jobs = []
    total_years_covered = 0
    for idx, jt in enumerate(job_templates):
        years_in_role = max(1, exp_years // len(job_templates) + random.randint(-1, 1))
        if idx == len(job_templates) - 1:
            years_in_role = exp_years - total_years_covered
        if years_in_role <= 0:
            continue
        total_years_covered += years_in_role
        end_year = current_year - (0 if idx == 0 else sum(
            max(1, exp_years // len(job_templates) + random.randint(-1, 1)) for _ in range(idx)
        ))
        start_year = end_year - years_in_role
        desc = fill_template(random.choice(jt["desc"]), skills, idx)
        company = random.choice(COMPANIES)
        jobs.append({
            "title": jt["title"],
            "company": company,
            "start_year": start_year,
            "end_year": end_year,
            "years": years_in_role,
            "description": desc,
        })

    years_since_grad = max(0, exp_years - 1)
    has_internship = random.random() < level_cfg["intern_prob"]
    internship = random.choice(INTERNSHIPS) if has_internship else None

    if lvl_name == "graduate":
        num_projects = random.randint(2, 4)
        projects = random.sample(GRAD_PROJECTS, min(num_projects, len(GRAD_PROJECTS)))
    else:
        num_projects = random.randint(1, 3)
        projects = random.sample(EXP_PROJECTS, min(num_projects, len(EXP_PROJECTS)))

    gpa = round(random.uniform(2.8, 4.0), 2)
    grad_year = current_year - years_since_grad

    return {
        "level": lvl_name,
        "seniority_tag": level_cfg["seniority_tag"],
        "level_label": level_cfg["label"],
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "university": university,
        "uni_short": uni_short,
        "degree": "Bachelor of Science" if lvl_name in ("graduate", "junior", "mid") else random.choice(["Bachelor of Science", "Master of Science", "Bachelor of Engineering"]),
        "major": "Computer Science",
        "gpa": gpa,
        "grad_year": grad_year,
        "total_years_experience": exp_years,
        "skills": skills,
        "jobs": jobs,
        "internship": internship,
        "projects": projects,
    }


def resume_to_text(resume: dict) -> str:
    """
    Formats a generated resume record as plain text.
    """
    lines = []
    lines.append(f"{resume['full_name']}")
    lines.append(f"Email: {resume['email']}")
    lines.append(f"Phone: {resume['phone']}")
    lines.append("")

    lines.append("=" * 50)
    lines.append("PROFESSIONAL SUMMARY")
    lines.append("=" * 50)
    if resume["total_years_experience"] <= 1:
        lines.append(f"Recent Computer Science graduate from {resume['university']} seeking an entry-level")
        lines.append("software engineering position. Eager to apply academic knowledge and hands-on experience")
        lines.append(f"in {', '.join(resume['skills'][:3])} to contribute to innovative projects.")
    else:
        job_titles = [j["title"] for j in resume["jobs"]]
        top_skills = ", ".join(resume["skills"][:4])
        lines.append(f"Experienced {job_titles[-1] if job_titles else 'Software Engineer'} with")
        lines.append(f"{resume['total_years_experience']}+ years of experience building and scaling production")
        lines.append(f"systems. Proficient in {top_skills}. Passionate about solving complex")
        lines.append("technical challenges and delivering high-quality software solutions.")
    lines.append("")

    lines.append("=" * 50)
    lines.append("EDUCATION")
    lines.append("=" * 50)
    lines.append(f"{resume['degree']} in {resume['major']}")
    lines.append(f"{resume['university']} ({resume['uni_short']})")
    lines.append(f"GPA: {resume['gpa']}/4.0 | Class of {resume['grad_year']}")
    lines.append("")
    lines.append("Relevant Coursework:")
    courses = ["Data Structures & Algorithms", "Operating Systems", "Database Systems",
               "Computer Networks", "Machine Learning", "Software Engineering",
               "Web Development", "Compiler Design", "Artificial Intelligence",
               "Computer Architecture", "Cloud Computing", "Cybersecurity"]
    lines.append(", ".join(random.sample(courses, 6)))
    lines.append("")

    if resume["jobs"]:
        lines.append("=" * 50)
        lines.append("PROFESSIONAL EXPERIENCE")
        lines.append("=" * 50)
        for job in resume["jobs"]:
            lines.append(f"{job['title']}")
            lines.append(f"{job['company']} | {job['start_year']} - {job['end_year']} ({job['years']} years)")
            lines.append("")
            lines.append(f"  \u2022 {job['description']}")
            lines.append("")
    elif resume["internship"]:
        lines.append("=" * 50)
        lines.append("PROFESSIONAL EXPERIENCE")
        lines.append("=" * 50)
        intern = resume["internship"]
        lines.append(f"{intern['role']}")
        lines.append(f"{intern['company']} | Summer {resume['grad_year']}")
        lines.append("")
        lines.append(f"  \u2022 {intern['desc']}")
        lines.append("")

    lines.append("=" * 50)
    lines.append("PROJECTS")
    lines.append("=" * 50)
    for i, project in enumerate(resume["projects"]):
        if isinstance(project.get("tech"), set):
            tech_str = ", ".join(project["tech"])
        else:
            tech_str = ", ".join(project.get("tech", []))
        lines.append(f"[{i+1}] {project['name']}")
        lines.append(f"    Technologies: {tech_str}")
        lines.append(f"    {project['desc']}")
        lines.append("")

    lines.append("=" * 50)
    lines.append("TECHNICAL SKILLS")
    lines.append("=" * 50)
    skills = resume["skills"]

    languages = [s for s in skills if s in ["Python", "JavaScript", "TypeScript", "Java", "C++", "C#", "Go", "Rust"]]
    frontend = [s for s in skills if s in ["React", "Angular", "Vue.js", "Next.js", "HTML", "CSS"]]
    backend = [s for s in skills if s in ["Node.js", "Express", "Django", "Flask", "FastAPI", "REST API", "GraphQL"]]
    databases = [s for s in skills if s in ["SQL", "PostgreSQL", "MongoDB", "Redis", "MySQL", "Elasticsearch"]]
    ml_ai = [s for s in skills if s in ["Machine Learning", "Deep Learning", "NLP", "Computer Vision", "TensorFlow", "PyTorch", "scikit-learn"]]
    devops = [s for s in skills if s in ["Git", "Docker", "Kubernetes", "AWS", "Azure", "GCP", "Linux", "CI/CD"]]
    fundamentals = [s for s in skills if s in ["Data Structures", "Algorithms", "System Design", "OOP", "Agile", "TDD", "Microservices", "Functional Programming"]]

    if languages:
        lines.append(f"Languages: {', '.join(languages)}")
    if frontend:
        lines.append(f"Frontend: {', '.join(frontend)}")
    if backend:
        lines.append(f"Backend: {', '.join(backend)}")
    if databases:
        lines.append(f"Databases: {', '.join(databases)}")
    if ml_ai:
        lines.append(f"AI/ML: {', '.join(ml_ai)}")
    if devops:
        lines.append(f"DevOps: {', '.join(devops)}")
    if fundamentals:
        lines.append(f"Fundamentals: {', '.join(fundamentals)}")

    other = [s for s in skills if s not in languages + frontend + backend + databases + ml_ai + devops + fundamentals]
    if other:
        lines.append(f"Other: {', '.join(other)}")

    lines.append("")
    lines.append("=" * 50)
    return "\n".join(lines)


def text_to_pdf(text: str, output_path: Path) -> None:
    """
    Writes plain resume text into a simple PDF file.
    """
    doc = SimpleDocTemplate(str(output_path), pagesize=letter)
    styles = getSampleStyleSheet()
    style = styles['BodyText']
    style.fontName = 'Courier'
    style.fontSize = 9
    style.leading = 12
    style.textColor = black

    story = []
    for para in text.split('\n'):
        stripped = para.strip()
        if stripped.startswith('==='):
            story.append(Spacer(1, 6))
            p = Paragraph(stripped, style)
            p.textColor = darkblue
            story.append(p)
        elif stripped:
            story.append(Paragraph(stripped.replace('  ', '&nbsp;&nbsp;'), style))
        else:
            story.append(Spacer(1, 8))
    doc.build(story)


def main() -> None:
    """
    Runs this script from the command line.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    existing = list(OUTPUT_DIR.glob("*.pdf"))
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"Existing PDFs: {len(existing)}")

    level_counts = {lvl: 0 for lvl in LEVELS}

    print("\n" + "=" * 70)
    print(f"Generating {MAX_CVS} CVs with mixed experience levels...")
    print("=" * 70)

    saved = 0
    used_emails = set()

    for i in range(MAX_CVS * 2):
        if saved >= MAX_CVS:
            break

        resume = generate_resume(i)
        if resume['email'] in used_emails:
            continue
        used_emails.add(resume['email'])

        text = resume_to_text(resume)
        lvl = resume["level"]
        level_counts[lvl] += 1

        base_name = sanitize_filename(f"{resume['level_label']}_{resume['full_name']}")
        pdf_path = OUTPUT_DIR / f"{base_name}.pdf"
        counter = 1
        while pdf_path.exists():
            pdf_path = OUTPUT_DIR / f"{base_name}_{counter}.pdf"
            counter += 1

        text_to_pdf(text, pdf_path)
        saved += 1

        jobs_str = f"Jobs: {len(resume['jobs'])}" if resume['jobs'] else "No exp"
        print(f"[{saved}/{MAX_CVS}] {resume['full_name']:25s} | {resume['level_label']:15s} | "
              f"Exp: {resume['total_years_experience']}y | Skills: {len(resume['skills']):2d} | {jobs_str}")

    print("\n" + "=" * 70)
    print(f"Done! Generated {saved} CVs")
    print(f"Location: {OUTPUT_DIR}")
    print(f"\nExperience Distribution:")
    for lvl_name, cfg in LEVELS.items():
        count = level_counts[lvl_name]
        pct = count / saved * 100 if saved else 0
        print(f"  {cfg['label']:20s}: {count:3d} ({pct:5.1f}%)")
    print(f"\n  {'TOTAL':20s}: {saved:3d}")
    total = len(list(OUTPUT_DIR.glob("*.pdf")))
    print(f"\nTotal PDFs in folder: {total}")


if __name__ == "__main__":
    main()
