"""Seed data/portfolio.json from the owner's resume.

Kept as a script rather than a one-off paste so the content is reproducible and
reviewable in git. The admin panel edits the same file at runtime; this just
establishes the committed baseline.

Deliberately omitted from the public page: phone number and street address. The Space
is public and indexable, and a scraped phone number is permanent spam. Contact routes
through email, LinkedIn, and Calendly instead.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "portfolio.json"

NOW = datetime.now(timezone.utc).isoformat(timespec="seconds")

SUMMARY = (
    "I engineer wisdom for both humans and machines. In practice that means building "
    "AI-ready information and knowledge systems, documentation, conversational interfaces, "
    "and automated pipelines — systems that reduce manual authoring load, keep knowledge "
    "bases current through built-in revalidation, and help AI strategy survive compliance "
    "and security review.\n\n"
    "Over 12+ years across enterprise SaaS, AEC/manufacturing, and consulting, I have turned "
    "manual, high-effort content workflows into structured, governed pipelines that improve "
    "speed to market, consistency, and reuse.\n\n"
    "I lead cross-functional AI and knowledge strategy end to end — translating business "
    "objectives into repeatable, compliant solution patterns, driving adoption, and aligning "
    "senior stakeholders around long-term roadmaps."
)

EXPERIENCE = [
    {
        "title": "Staff Technical Writer — AI Knowledge Platform & Content Strategy",
        "company": "ServiceNow India Pvt Ltd., Hyderabad",
        "period": "Jun 2024 – Jul 2026",
        "summary": "",
        "highlights": [
            "Designed an AI-driven knowledge architecture combining RAG pipelines, multi-agentic "
            "systems, LLMs, and metadata-driven retrieval to automate structured, AI-ingestible "
            "and agentic task documentation. Defined strategies for identifying, organising, "
            "sharing, storing, and maintaining organisational knowledge that is Findable, "
            "Accessible, Interoperable, and Reusable.",
            "Co-defined the AI documentation platform roadmap with Product, Engineering, and UX, "
            "prototyping a content automation pipeline that generated draft documentation directly "
            "from live product demo interactions using agentic AI — reducing manual authoring "
            "effort while preserving governance and quality standards.",
            "Established content governance standards, taxonomy, and metadata models for the "
            "knowledge base, defining review and revalidation cycles aligned to ITIL-style "
            "knowledge lifecycle practices to keep content current and reduce stale articles.",
        ],
    },
    {
        "title": "Sr. Content Designer — Content Strategy & Adoption",
        "company": "Autodesk India Pvt Ltd. (Remote, Pune)",
        "period": "Mar 2022 – Jun 2024",
        "summary": "",
        "highlights": [
            "Developed content strategy and adoption resources (API documentation, instructional "
            "video, graphics) for AEC and manufacturing software including Revit and Fusion, "
            "serving technical and non-technical audiences.",
            "Documented federated data and taxonomy models that unified metadata schemas across "
            "Autodesk products, helping users understand consistent cross-product content "
            "classification and discovery.",
        ],
    },
    {
        "title": "Consultant, Content Strategy",
        "company": "Capgemini Engineering Ltd., Gurugram (IBM project)",
        "period": "Jan 2021 – Mar 2022",
        "summary": "",
        "highlights": [
            "Built clear, concise content plans supporting enterprise software implementations, "
            "aligning documentation deliverables with rollout timelines.",
        ],
    },
    {
        "title": "Senior Content Lead (Associate Consultant)",
        "company": "Infosys Ltd., Hyderabad",
        "period": "May 2019 – Jan 2021",
        "summary": "",
        "highlights": [
            "Authored how-to manuals and API documentation; built and drove cross-business-line "
            "adoption of DigiTran, the internal SOP documentation tool at Infosys.",
        ],
    },
    {
        "title": "Technical Writer — User & API Documentation",
        "company": "DSV Logistics (formerly Agility Logistics), Hyderabad",
        "period": "May 2018 – May 2019",
        "summary": "",
        "highlights": [
            "Developed user manuals, training videos, conversational interfaces, help "
            "documentation, and API documentation using Postman and Sphinx.",
            "Built a Python-based conversational assistant integrating the Wolfram Alpha API and "
            "Elasticsearch to answer common FAQs, deployed via Slack.",
        ],
    },
    {
        "title": "Technical Writer — Engineering User & API Documentation",
        "company": "Wipro Ltd., Hyderabad",
        "period": "Jan 2016 – May 2018",
        "summary": "",
        "highlights": [
            "Produced user manuals, training video, help content, and API documentation for "
            "engineering products (CATIA V5, PTC Arbortext/Windchill, S1000D, ATA100).",
        ],
    },
    {
        "title": "Content Developer",
        "company": "Apex CoVantage, Hyderabad",
        "period": "Jun 2015 – Jan 2016",
        "summary": "",
        "highlights": ["Developed parts catalogs and SEO content."],
    },
    {
        "title": "Technical Officer",
        "company": "PCRI, Hyderabad",
        "period": "Sep 2013 – Mar 2015",
        "summary": "",
        "highlights": [
            "Developed and tested packaging solutions across food, chemicals, agri, pharma, and "
            "FMCG; authored technical test reports.",
        ],
    },
]

SKILLS = [
    "Knowledge Management", "Information Architecture", "Taxonomy & Metadata Design",
    "Content Governance & Lifecycle (ITIL-aligned)", "Ontology Modelling", "Knowledge Graphs",
    "DITA & Structured Authoring", "Developer & API Documentation", "Controlled Vocabularies",
    "Multi-language Content Operations", "Content Migration",
    "Enterprise RAG Pipeline Design", "GraphRAG", "Neo4j", "Vector Databases",
    "Retrieval Evaluation (RAGAS)", "Multi-Agent Orchestration", "Prompt Engineering",
    "LLM-Assisted Authoring", "NLP & OCR Pipelines", "MCP", "Claude",
    "Microsoft Copilot Studio", "Word2Vec", "Python Automation", "Azure AI Foundry", "Docker",
    "Cloud (Azure/AWS/GCP/IBM/Oracle)", "ISO 42001", "ISO 27701",
    "Data Loss Prevention (DLP)", "PII Detection & Compliance",
    "Content Pipeline Automation", "Metadata-Driven Personalisation",
    "Product & Program Management", "Roadmap Definition", "Agile/Scrum Coaching",
    "Oxygen XML", "MadCap Flare", "PTC Arbortext / Windchill", "Confluence", "JIRA",
    "Postman", "Sphinx", "Power BI", "Looker", "Google Analytics", "Figma", "Drupal",
    "Veeva Vault", "SharePoint", "Git", "WalkMe",
]

PROJECTS = [
    {
        "name": "RAG Arena — Lexical vs Vector vs Graph retrieval, measured",
        "period": "2026",
        "summary": (
            "Three retrieval strategies over one identical chunk set with a shared prompt, so "
            "score differences are attributable to retrieval alone. Deterministic evaluation with "
            "no LLM in the scoring path, a self-correcting LangGraph agent loop, PII redaction "
            "before embedding, Neo4j and ChromaDB backends, and a RAG-readiness analyser."
        ),
        "link": "https://github.com/pathak1005/rag-arena",
    },
    {
        "name": "PII / Compliance Scanning Service",
        "period": "",
        "summary": (
            "Presidio-based PII detection service on Azure Container Apps, flagging "
            "ISO / DPDP / GDPR-relevant content across documents and published pages."
        ),
        "link": "",
    },
    {
        "name": "mygrowthpitch.org",
        "period": "",
        "summary": (
            "GPT-powered text and voice interview preparation tool applying the SOAR, GROW, and "
            "STAR coaching frameworks."
        ),
        "link": "https://mygrowthpitch.org",
    },
]

EDUCATION = [
    {"qualification": "PGDBM — Masters in Marketing Management (68.5%)",
     "institution": "NMIMS, Mumbai (SVKM Narsee Monjee Institute)",
     "period": "Jan 2021 – Jan 2023"},
    {"qualification": "B.Tech — Mechanical Engineering (72.77%)",
     "institution": "Arjun College of Technology and Sciences, JNTU Hyderabad",
     "period": "Jun 2009 – Jun 2013"},
]

CERTIFICATIONS = [
    "Certified System Administrator, ServiceNow (CSA)",
    "Certified Scrum Product Owner (CSPO)",
    "ICAgile Certified Professional, Agile Coaching (ICP-ACC)",
]


def build_markdown(content: dict) -> str:
    p = content["profile"]
    out = [
        "# " + p["name"], "", p["headline"], "",
        p["location"] + "  ·  " + p["email"],
        p["linkedin_url"] + "  ·  " + p["github_url"], "",
        "## Professional Summary", "", p["summary"], "", "## Experience", "",
    ]
    for role in content["experience"]:
        out += ["### " + role["title"],
                "**" + role["company"] + "**  ·  *" + role["period"] + "*", ""]
        out += ["- " + h for h in role["highlights"]] + [""]
    out += ["## Independent Projects", ""]
    for proj in content["projects"]:
        title = "**" + proj["name"] + "**"
        if proj["period"]:
            title += "  ·  *" + proj["period"] + "*"
        out += [title, proj["summary"], ""]
    out += ["## Certifications", ""] + ["- " + c for c in content["certifications"]]
    out += ["", "## Education", ""]
    for edu in content["education"]:
        out += ["**" + edu["qualification"] + "** — " + edu["institution"]
                + "  ·  *" + edu["period"] + "*", ""]
    out += ["## Core Skills", "", ", ".join(content["skills"]), ""]
    return "\n".join(out)


def main() -> int:
    content = {
        "profile": {
            "name": "Ashish Kumar Pathak",
            "headline": "Enterprise Information & KM Architect  ·  AI Strategy & Governance  ·  GenAI Solutions",
            "location": "Hyderabad, India",
            "email": "ashishpathak1005@gmail.com",
            "summary": SUMMARY,
            "portfolio_url": "",
            "calendly_url": "",
            "linkedin_url": "https://www.linkedin.com/in/ashish-kumar-pathak-b5716a16/",
            "github_url": "https://github.com/pathak1005",
        },
        "skills": SKILLS,
        "experience": EXPERIENCE,
        "education": EDUCATION,
        "certifications": CERTIFICATIONS,
        "projects": PROJECTS,
        "blog": [],
        "resume": {"markdown": "", "file_name": "", "file_b64": "", "updated": NOW},
        "meta": {"updated": NOW, "version": 2},
    }
    content["resume"]["markdown"] = build_markdown(content)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"  {len(EXPERIENCE)} roles, {len(SKILLS)} skills, {len(PROJECTS)} projects, "
          f"{len(CERTIFICATIONS)} certifications")
    print(f"  resume markdown: {len(content['resume']['markdown'])} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
