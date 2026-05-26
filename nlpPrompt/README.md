# NLP Prompts — الفهرس الكامل

هذا المجلد يحوي **5 برومبتس** تمثل **مراحل تطوير المشروع** كاملة، من التخطيط مروراً بالتنفيذ وصولاً للمراجعة.

---

## هرمية الـ Prompts (من الأعلى للأسفل)

```
                    ┌──────────────────────┐
                    │  01_STRATEGY         │  ← ماذا نبني؟ (Product Vision)
                    │  prompt_0.txt        │
                    ├──────────────────────┤
                    │  02_ARCHITECTURE     │  ← كيف نصممه؟ (Multi-department)
                    │  prompt.txt          │
                    ├──────────────────────┤
                    │  03_PRODUCTION_PLAN  │  ← كيف نجهزه للإنتاج؟ (Readiness)
                    │  prompt_1.txt        │
                    ├──────────────────────┤
                    │  04_IMPLEMENTATION   │  ← نكتب الكود (Execution)
                    │  prompt_2.txt        │
                    ├──────────────────────┤
                    │  05_QA_AUDIT         │  ← نراجع ونختبر (Validation)
                    │  prompt_3.txt        │
                    └──────────────────────┘
```

---

## تفصيل كل برومبت

### المستوى 1 — استراتيجية المنتج (Product Strategy)
**الملف:** `01_strategy_product_vision.md` ← كان `prompt_0.txt`
- **الهدف:** تحويل المشروع من demo تقني إلى منتج SaaS قابل للبيع
- **الجمهور:** CTO, Product Manager, B2B SaaS strategist
- **المخرجات:** Product vision, 10 product modules, expanded data model, roadmap من 4 milestones
- **التركيز:** "كيف نبيع هذا المنتج؟"

### المستوى 2 — تصميم الـ Architecture (System Redesign)
**الملف:** `02_architecture_job_families.md` ← كان `prompt.txt`
- **الهدف:** إعادة تصميم الـ architecture لدعم 10 job families (engineering, marketing, finance, HR, operations, sales, support, design, logistics, admin)
- **الجمهور:** Principal architect, NLP systems designer
- **المخرجات:** Job Family taxonomy, scoring policies, evidence types, interview templates لكل family
- **التركيز:** "كيف ندعم التوظيف لكل الأقسام وليس فقط التقني؟"

### المستوى 3 — خطة الجاهزية للإنتاج (Production Readiness)
**الملف:** `03_production_readiness_plan.md` ← كان `prompt_1.txt`
- **الهدف:** تجهيز المشروع لـ paid pilot و enterprise deployment
- **الجمهور:** Technical program manager, AI product readiness lead
- **المخرجات:** 8 "Must before selling" + 8 "Must before enterprise" + gap analysis
- **التركيز:** "ما الذي يجب أن نصلحه قبل أن نبيع؟"

### المستوى 4 — التنفيذ (Implementation)
**الملف:** `04_implementation_blueprint.md` ← كان `prompt_2.txt`
- **الهدف:** تنفيذ خطة الـ production readiness في الكود مباشرة
- **الجمهور:** Senior backend engineer (AI/NLP)
- **المخرجات:** Code changes, migrations, tests, Docker updates
- **التركيز:** "اكتب الكود الآن"

### المستوى 5 — مراجعة و QA (Audit & Validation)
**الملف:** `05_qa_audit_validation.md` ← كان `prompt_3.txt`
- **الهدف:** التحقق من أن التغييرات صحيحة ومتوافقة مع القديم وآمنة للإنتاج
- **الجمهور:** Senior QA engineer
- **المخرجات:** Verdict (READY/NOT READY), findings, regression tests
- **التركيز:** "هل هذا يعمل حقاً؟ هل كسرنا شيئاً؟"

---

## كيف تستخدمهم؟ (سير العمل الصحيح)

```
الخطوة 1: ابدأ بـ 01_strategy_product_vision.md
         → يحدد الرؤية والمنتج

الخطوة 2: استخدم 02_architecture_job_families.md
         → يصمم الـ architecture بناءً على الرؤية

الخطوة 3: استخدم 03_production_readiness_plan.md
         → يحدد خطة الجاهزية

الخطوة 4: شغّل 04_implementation_blueprint.md
         → ينفذ التغييرات في الكود

الخطوة 5: اختبر بـ 05_qa_audit_validation.md
         → يراجع ويختبر كل شيء
```

## العلاقات بين الـ Prompts

| # | البرومبت | يعتمد على | ينتج |
|---|----------|-----------|------|
| 01 | استراتيجية المنتج | تحليل الوضع الحالي | Product vision + 10 modules |
| 02 | Architecture | الرؤية من 01 | Job family taxonomy + data model |
| 03 | Production plan | التحليل من 01 + 02 | Readiness checklist + phases |
| 04 | Implementation | الخطة من 03 | Code + migrations + tests |
| 05 | QA Audit | التنفيذ من 04 | Validation report + fixes |
