"""
Regenerates public/about.html and public/sitemap.xml from data/portfolio.json.

Run on every container boot (wired into start.sh) so the static, crawler-visible
profile page never drifts out of sync with the resume data. Streamlit renders
client-side, which most AI/search crawlers do not execute JavaScript for — this
script produces the plain-HTML fallback those crawlers actually read.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_PATH = ROOT / "data" / "portfolio.json"
PUBLIC_DIR = ROOT / "public"
SITE_URL = "https://rag-arena.fly.dev"


def _load() -> dict:
    if not PORTFOLIO_PATH.exists():
        raise SystemExit(f"missing {PORTFOLIO_PATH}")
    return json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))


def _person_jsonld(p: dict) -> dict:
    profile = p.get("profile", {})
    same_as = [u for u in (profile.get("linkedin_url"), profile.get("github_url")) if u]
    education = [
        {"@type": "EducationalOrganization", "name": ed.get("institution", "")}
        for ed in p.get("education", [])
    ]
    return {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": profile.get("name", ""),
        "jobTitle": profile.get("headline", ""),
        "description": (profile.get("summary", "").split("\n\n") or [""])[0],
        "email": "mailto:" + profile.get("email", ""),
        "url": SITE_URL + "/about.html",
        "sameAs": same_as,
        "knowsAbout": p.get("skills", []),
        "alumniOf": education,
        "address": {"@type": "PostalAddress", "addressLocality": profile.get("location", "")},
    }


def render_about_html(p: dict) -> str:
    profile = p.get("profile", {})
    name = escape(profile.get("name", "Ashish Pathak"))
    headline = escape(profile.get("headline", ""))
    summary_paras = [s for s in profile.get("summary", "").split("\n\n") if s.strip()]
    description = escape(summary_paras[0] if summary_paras else headline)[:300]

    summary_html = "\n".join(f"<p>{escape(para)}</p>" for para in summary_paras)
    skills_html = "\n".join(f"<li>{escape(s)}</li>" for s in p.get("skills", []))

    experience_html = ""
    for job in p.get("experience", []):
        highlights = "".join(f"<li>{escape(h)}</li>" for h in job.get("highlights", []))
        experience_html += (
            f"<article>\n<h3>{escape(job.get('title', ''))} "
            f"&mdash; {escape(job.get('company', ''))}</h3>\n"
            f"<p><em>{escape(job.get('period', ''))}</em></p>\n"
            f"<ul>{highlights}</ul>\n</article>\n"
        )

    education_html = "\n".join(
        f"<li>{escape(ed.get('qualification', ''))}, {escape(ed.get('institution', ''))} "
        f"({escape(ed.get('period', ''))})</li>"
        for ed in p.get("education", [])
    )
    certifications_html = "\n".join(f"<li>{escape(c)}</li>" for c in p.get("certifications", []))

    projects_html = ""
    for proj in p.get("projects", []):
        link = f' &mdash; <a href="{escape(proj["link"])}">{escape(proj["link"])}</a>' if proj.get("link") else ""
        projects_html += f"<li><strong>{escape(proj.get('name', ''))}</strong>: {escape(proj.get('summary', ''))}{link}</li>\n"

    jsonld = json.dumps(_person_jsonld(p), indent=2)
    email = profile.get("email", "")
    github = profile.get("github_url", "")
    linkedin = profile.get("linkedin_url", "")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{name} &mdash; {headline}</title>
<meta name="description" content="{description}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{SITE_URL}/about.html">

<meta property="og:type" content="profile">
<meta property="og:title" content="{name} &mdash; {headline}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="{SITE_URL}/about.html">

<meta name="twitter:card" content="summary">
<meta name="twitter:title" content="{name}">
<meta name="twitter:description" content="{description}">

<script type="application/ld+json">
{jsonld}
</script>

<style>
  body {{ font-family: system-ui, sans-serif; max-width: 760px; margin: 40px auto; padding: 0 20px; line-height: 1.6; color: #111; }}
  h1 {{ margin-bottom: 4px; }}
  h2 {{ margin-top: 40px; border-bottom: 1px solid #ddd; padding-bottom: 6px; }}
  .headline {{ color: #555; font-size: 1.1rem; margin-top: 0; }}
  ul {{ padding-left: 20px; }}
  footer {{ margin-top: 50px; font-size: 0.9rem; color: #666; }}
</style>
</head>
<body>
<h1>{name}</h1>
<p class="headline">{headline}</p>

<h2>Summary</h2>
{summary_html}

<h2>Skills</h2>
<ul>{skills_html}</ul>

<h2>Experience</h2>
{experience_html}

<h2>Education</h2>
<ul>{education_html}</ul>

<h2>Certifications</h2>
<ul>{certifications_html}</ul>

<h2>Projects</h2>
<ul>{projects_html}</ul>

<footer>
<p>Full interactive site: <a href="{SITE_URL}/">{SITE_URL}</a></p>
<p>Contact: <a href="mailto:{email}">{email}</a>{" | GitHub: " + f'<a href=\"{github}\">{github}</a>' if github else ""}{" | LinkedIn: " + f'<a href=\"{linkedin}\">{linkedin}</a>' if linkedin else ""}</p>
</footer>
</body>
</html>
"""


def render_sitemap(lastmod: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{SITE_URL}/</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{SITE_URL}/about.html</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
  </url>
</urlset>
"""


def main() -> None:
    portfolio = _load()
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)

    about_html = render_about_html(portfolio)
    (PUBLIC_DIR / "about.html").write_text(about_html, encoding="utf-8")

    lastmod = portfolio.get("meta", {}).get("updated", "")[:10] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    (PUBLIC_DIR / "sitemap.xml").write_text(render_sitemap(lastmod), encoding="utf-8")

    print(f"[generate_static_profile] wrote public/about.html and public/sitemap.xml (lastmod={lastmod})")


if __name__ == "__main__":
    main()
