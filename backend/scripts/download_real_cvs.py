#!/usr/bin/env python
from __future__ import annotations

import re
from pathlib import Path

try:
    from datasets import load_dataset
except ImportError:
    print("[ERROR] 'datasets' library not installed.")
    print("Run: pip install datasets reportlab")
    import sys
    sys.exit(1)

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.colors import black
except ImportError:
    print("[ERROR] 'reportlab' library not installed.")
    print("Run: pip install reportlab")
    import sys
    sys.exit(1)


OUTPUT_DIR = Path(__file__).parent / "cvs_to_upload"
MAX_CVS = 100

DESIRED_CATEGORIES = {
    "INFORMATION-TECHNOLOGY",
    "ENGINEERING",
    "DESIGNER",
    "CONSULTANT",
    "DIGITAL-MEDIA",
    "FINANCE",
}

CS_KEYWORDS = {
    "python", "java", "javascript", "react", "node", "sql", "database",
    "software", "developer", "engineer", "programmer", "coding",
    "machine learning", "data science", "ml", "ai", "nlp",
    "git", "docker", "kubernetes", "aws", "azure", "cloud",
    "html", "css", "angular", "vue", "django", "flask", "api",
    "computer science", "computer engineering", "information technology",
}


def sanitize_filename(name: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*]', '_', name)
    clean = re.sub(r'\s+', '_', clean)
    return clean.strip('_')[:80]


def extract_name(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    for line in lines[:8]:
        if re.match(r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4}$', line):
            email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', line)
            phone_match = re.search(r'\+?\d[\d\s\-().]{8,}\d', line)
            if not email_match and not phone_match:
                return line

    for line in lines[:5]:
        if len(line.split()) <= 5 and len(line) <= 50:
            if '@' not in line and 'http' not in line.lower():
                email_match = re.search(r'[\w.+-]+@[\w-]+\.[\w.-]+', line)
                if not email_match:
                    return line

    return None


def has_cs_skills(text: str) -> bool:
    text_lower = text.lower()
    count = 0
    for keyword in CS_KEYWORDS:
        if keyword.lower() in text_lower:
            count += 1
            if count >= 2:
                return True
    return False


def text_to_pdf(text: str, output_path: Path) -> None:
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
        if stripped.startswith('===') or stripped.startswith('___'):
            story.append(Spacer(1, 6))
        elif stripped:
            story.append(Paragraph(stripped.replace('  ', '&nbsp;&nbsp;'), style))
        else:
            story.append(Spacer(1, 8))

    doc.build(story)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    existing = list(OUTPUT_DIR.glob("*.pdf"))
    print(f"Output dir: {OUTPUT_DIR}")
    print(f"Existing PDFs: {len(existing)}")

    print("\n" + "=" * 60)
    print(f"Loading CV dataset from Hugging Face...")
    print("=" * 60)

    try:
        ds = load_dataset("Divyaamith/Kaggle-Resume", split="train")
        print(f"[OK] Loaded {len(ds)} CVs total")
    except Exception as e:
        print(f"[WARN] Failed to load Divyaamith/Kaggle-Resume: {e}")
        print("[INFO] Trying opensporks/resumes...")
        try:
            ds = load_dataset("opensporks/resumes", split="train")
            print(f"[OK] Loaded {len(ds)} CVs total")
        except Exception as e2:
            print(f"[ERROR] Failed to load both datasets: {e2}")
            return

    total_processed = 0
    saved = 0
    seen_names = set()

    for idx, item in enumerate(ds):
        total_processed += 1

        if total_processed % 100 == 0:
            print(f"Processed {total_processed}/{len(ds)} CVs...")

        category = None
        if "Category" in item:
            category = str(item["Category"]).strip().upper()
        elif "category" in item:
            category = str(item["category"]).strip().upper()

        if category and category not in DESIRED_CATEGORIES:
            continue

        text = None
        if "Resume_str" in item:
            text = str(item["Resume_str"])
        elif "resume_str" in item:
            text = str(item["resume_str"])
        elif "text" in item:
            text = str(item["text"])
        elif "content" in item:
            text = str(item["content"])

        if not text or len(text.strip()) < 200:
            continue

        if not has_cs_skills(text):
            continue

        name = extract_name(text)
        if not name:
            name = f"IT_Professional_{idx}"

        base_name = sanitize_filename(name)
        if base_name in seen_names:
            counter = 1
            while f"{base_name}_{counter}" in seen_names:
                counter += 1
            base_name = f"{base_name}_{counter}"

        seen_names.add(base_name)

        pdf_path = OUTPUT_DIR / f"Real_{base_name}.pdf"

        try:
            text_to_pdf(text, pdf_path)
            saved += 1

            cat_info = f"[{category}]" if category else ""
            print(f"[{saved}/{MAX_CVS}] {name} {cat_info}")

            if saved >= MAX_CVS:
                break

        except Exception as e:
            print(f"[WARN] Failed to save {name}: {e}")
            continue

    print("\n" + "=" * 60)
    print(f"Results:")
    print(f"  - Total CVs in dataset: {len(ds)}")
    print(f"  - Processed: {total_processed}")
    print(f"  - Saved CS/IT CVs: {saved}")
    print(f"  - Location: {OUTPUT_DIR}")
    print("=" * 60)

    if saved == 0:
        print("\n[INFO] No CS/IT CVs found or saved.")
        print("Fallback: Run 'python generate_cs_cvs.py' to generate quality CS CVs.")


if __name__ == "__main__":
    main()
