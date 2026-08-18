"""Portfolio landing page and the owner-only admin panel.

Rendered by ui/streamlit_app.py. Kept in a separate module because the admin editor is
long and has nothing to do with retrieval.

Design rule for the PUBLIC page: use the resume, don't reproduce it. A wall of resume
markdown is not a portfolio page - it's a text dump. Every section here is a condensed,
scannable summary; the original file (PDF/DOCX) is offered as a download for anyone who
wants the full document.
"""
from __future__ import annotations

import base64

import streamlit as st

from app import adminstore

CALENDLY_FALLBACK = "https://calendly.com/ashishpathak1005/30min"


def _calendly_url(profile: dict) -> str:
    return (profile.get("calendly_url") or "").strip() or CALENDLY_FALLBACK


def contact_banner(content: dict, key: str) -> None:
    """A single-line CTA repeated across pages. This is the answer to 'how do I reach him'."""
    profile = content["profile"]
    url = _calendly_url(profile)
    st.markdown(
        "<div style='display:flex;align-items:center;justify-content:space-between;"
        "gap:12px;flex-wrap:wrap;background:rgba(99,102,241,0.10);"
        "border:1px solid rgba(99,102,241,0.25);border-radius:10px;"
        "padding:10px 16px;margin-bottom:14px;'>"
        "<span style='font-size:0.92rem;'>Questions about this project or how it applies "
        "to your team? Reach out to <strong>" + profile.get("name", "the author")
        + "</strong>.</span>"
        "<a href='" + url + "' target='_blank' style='background:#4f46e5;color:#fff;"
        "padding:7px 16px;border-radius:8px;font-weight:600;font-size:0.88rem;"
        "text-decoration:none;white-space:nowrap;'>Book 30 minutes &rarr;</a>"
        "</div>",
        unsafe_allow_html=True,
    )


# ==========================================================================
# Public portfolio (Home)
# ==========================================================================
def render_portfolio(content: dict) -> None:
    profile = content["profile"]

    st.markdown(
        "<div style='padding:8px 0 4px;'>"
        "<div style='font-size:2.4rem;font-weight:700;line-height:1.15;'>"
        + profile["name"] + "</div>"
        "<div style='font-size:1.1rem;opacity:0.75;margin-top:4px;'>"
        + profile["headline"] + "</div></div>",
        unsafe_allow_html=True,
    )

    bits = [b for b in (profile.get("location"), profile.get("email")) if b]
    if bits:
        st.caption("  ·  ".join(bits))

    links = [
        ("Portfolio", profile.get("portfolio_url", "")),
        ("LinkedIn", profile.get("linkedin_url", "")),
        ("GitHub", profile.get("github_url", "")),
    ]
    active = [(label, url) for label, url in links if url.strip()]
    if active:
        st.markdown("  ·  ".join("[" + label + "](" + url + ")" for label, url in active))

    st.write("")
    contact_banner(content, "home_top")

    if adminstore.is_placeholder(profile.get("headline", "")) or adminstore.is_placeholder(profile.get("summary", "")):
        st.caption("Site content not filled in yet - open the hidden admin panel to add it.")
        return

    # -- about (short, not the full resume)
    summary = profile.get("summary", "")
    st.markdown(summary.split("\n\n")[0] if summary else "")
    if "\n\n" in summary:
        with st.expander("Read more"):
            st.markdown(summary)

    st.write("")

    # -- resume file, offered as a download, never reproduced as page text
    resume = content.get("resume", {})
    col1, col2 = st.columns([1, 3])
    with col1:
        if resume.get("file_b64") and resume.get("file_name"):
            try:
                fname = resume["file_name"]
                mime = "application/pdf" if fname.lower().endswith(".pdf") else (
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    if fname.lower().endswith(".docx") else "application/octet-stream"
                )
                st.download_button(
                    "Download resume",
                    data=base64.b64decode(resume["file_b64"]),
                    file_name=fname,
                    mime=mime,
                    type="primary",
                    use_container_width=True,
                )
            except Exception:  # noqa: BLE001
                st.caption("Resume file could not be read.")
        else:
            st.button("Resume (not uploaded)", disabled=True, use_container_width=True)
    with col2:
        if resume.get("file_name"):
            st.caption("PDF/DOCX  ·  updated " + (resume.get("updated", "") or "")[:10])
        else:
            st.caption("The owner can upload the original PDF/DOCX in the admin panel.")

    st.divider()

    # -- skills, capped so this stays a summary, not a list dump
    if content.get("skills"):
        shown = content["skills"][:18]
        remainder = len(content["skills"]) - len(shown)
        st.markdown("**Core skills**")
        st.markdown(
            " ".join(
                "<span style='display:inline-block;background:rgba(128,128,128,0.15);"
                "padding:3px 11px;border-radius:12px;margin:3px 4px 3px 0;font-size:0.85rem;'>"
                + s + "</span>"
                for s in shown
            )
            + (
                "<span style='opacity:0.6;font-size:0.85rem;'> +" + str(remainder) + " more</span>"
                if remainder > 0 else ""
            ),
            unsafe_allow_html=True,
        )
        st.write("")

    # -- experience, condensed: title/company/period + top highlight only, rest collapsed
    if content.get("experience"):
        st.markdown("**Experience**")
        for i, role in enumerate(content["experience"]):
            st.markdown(
                "**" + role.get("title", "") + "**  ·  " + role.get("company", "")
                + "  ·  *" + role.get("period", "") + "*"
            )
            highlights = role.get("highlights", [])
            if highlights:
                st.markdown("- " + highlights[0])
                if len(highlights) > 1:
                    with st.expander("More from this role"):
                        for point in highlights[1:]:
                            st.markdown("- " + point)
            if i < len(content["experience"]) - 1:
                st.write("")
        st.write("")

    # -- projects
    if content.get("projects"):
        st.markdown("**Projects**")
        for project in content["projects"]:
            title = project.get("name", "")
            if project.get("link"):
                title = "[" + title + "](" + project["link"] + ")"
            st.markdown("**" + title + "**")
            if project.get("summary"):
                st.caption(project["summary"])
        st.write("")

    # -- certifications + education, compact single line each
    tail = []
    if content.get("certifications"):
        tail.append("**Certifications:** " + "  ·  ".join(content["certifications"]))
    if content.get("education"):
        tail.append(
            "**Education:** "
            + "  ·  ".join(e.get("qualification", "") for e in content["education"])
        )
    if tail:
        st.divider()
        for line in tail:
            st.markdown(line)


# ==========================================================================
# Admin
# ==========================================================================
def _login_panel() -> None:
    st.markdown("## Admin")

    if not adminstore.is_registered():
        st.warning(
            "No account exists yet. Register now - the first registration claims this panel, "
            "and only the owner address is accepted.",
        )
        with st.form("register"):
            st.markdown("**Create the owner account**")
            email = st.text_input("Email", placeholder="the owner address")
            pw1 = st.text_input("Password", type="password")
            pw2 = st.text_input("Confirm password", type="password")
            st.caption(
                "At least " + str(adminstore.MIN_PASSWORD_LENGTH)
                + " characters, mixing letters with digits or symbols."
            )
            if st.form_submit_button("Register", type="primary"):
                if pw1 != pw2:
                    st.error("Passwords do not match.")
                else:
                    ok, message = adminstore.register(email, pw1)
                    if ok:
                        st.session_state["admin_authed"] = True
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)
        return

    with st.form("login"):
        st.markdown("**Sign in**")
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        if st.form_submit_button("Sign in", type="primary"):
            ok, message = adminstore.authenticate(email, password)
            if ok:
                st.session_state["admin_authed"] = True
                st.rerun()
            else:
                st.error(message)

    st.caption(
        "Sessions are held server-side and are not persisted in a cookie, so refreshing "
        "the page signs you out."
    )


def _list_editor(label: str, items: list[dict], fields: list[tuple[str, str]], key: str) -> list[dict]:
    """Generic repeating-record editor. `fields` is [(key, widget)] where widget is text|area|list."""
    st.markdown("#### " + label)
    updated: list[dict] = []

    for i, item in enumerate(list(items)):
        with st.expander(item.get(fields[0][0]) or f"{label} {i + 1}", expanded=False):
            record: dict = {}
            for fname, widget in fields:
                if widget == "area":
                    record[fname] = st.text_area(
                        fname.replace("_", " ").title(), value=item.get(fname, ""),
                        key=f"{key}_{i}_{fname}", height=90,
                    )
                elif widget == "list":
                    raw = st.text_area(
                        fname.replace("_", " ").title() + " (one per line)",
                        value="\n".join(item.get(fname, []) or []),
                        key=f"{key}_{i}_{fname}", height=110,
                    )
                    record[fname] = [ln.strip() for ln in raw.splitlines() if ln.strip()]
                else:
                    record[fname] = st.text_input(
                        fname.replace("_", " ").title(), value=item.get(fname, ""),
                        key=f"{key}_{i}_{fname}",
                    )
            if not st.checkbox("Delete this entry", key=f"{key}_{i}_del"):
                updated.append(record)

    if st.button("Add " + label.rstrip("s"), key=f"{key}_add"):
        blank = {fname: ([] if widget == "list" else "") for fname, widget in fields}
        updated.append(blank)

    return updated


def render_admin() -> None:
    if not st.session_state.get("admin_authed"):
        _login_panel()
        return

    content = adminstore.load_content()

    col1, col2 = st.columns([4, 1])
    col1.markdown("## Admin - edit site content")
    if col2.button("Sign out", use_container_width=True):
        st.session_state["admin_authed"] = False
        st.rerun()

    meta = content.get("meta", {})
    if meta.get("updated"):
        st.caption("Last saved " + meta["updated"] + "  ·  revision " + str(meta.get("version", 1)))

    st.warning(
        "On Hugging Face Spaces and Render the filesystem is ephemeral: edits survive until "
        "the container restarts. Use Export below after editing and commit the file to "
        "the repo to make changes permanent.",
    )

    tabs = st.tabs(["Profile", "Resume file", "Experience", "Skills", "Projects", "Blog", "Export", "Password"])

    with tabs[0]:
        p = content["profile"]
        p["name"] = st.text_input("Name", value=p.get("name", ""))
        p["headline"] = st.text_input("Headline", value=p.get("headline", ""))
        c1, c2 = st.columns(2)
        p["location"] = c1.text_input("Location", value=p.get("location", ""))
        p["email"] = c2.text_input("Public email", value=p.get("email", ""))
        p["summary"] = st.text_area(
            "Summary (first paragraph shown by default; rest goes under 'Read more')",
            value=p.get("summary", ""), height=140,
        )
        st.markdown("**Links**")
        c1, c2 = st.columns(2)
        p["portfolio_url"] = c1.text_input("Portfolio URL", value=p.get("portfolio_url", ""))
        p["calendly_url"] = c2.text_input(
            "Calendly URL", value=p.get("calendly_url", ""),
            placeholder=CALENDLY_FALLBACK,
        )
        p["linkedin_url"] = c1.text_input("LinkedIn URL", value=p.get("linkedin_url", ""))
        p["github_url"] = c2.text_input("GitHub URL", value=p.get("github_url", ""))

    with tabs[1]:
        resume = content.setdefault("resume", {})
        st.markdown(
            "**Upload the original resume file.** This is what the Home page's Download "
            "button serves - the site never reproduces the full text inline."
        )
        uploaded = st.file_uploader("Resume file (PDF or DOCX, max 5 MB)", type=["pdf", "docx"])
        if uploaded is not None:
            raw = uploaded.getvalue()
            if len(raw) > 5 * 1024 * 1024:
                st.error("File exceeds 5 MB.")
            else:
                import base64 as _b64
                from datetime import datetime, timezone

                resume["file_b64"] = _b64.b64encode(raw).decode("ascii")
                resume["file_name"] = uploaded.name
                resume["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                st.success("Loaded " + uploaded.name + " - press Save changes below.")

        if resume.get("file_name"):
            st.caption("Currently stored: " + resume["file_name"])
            if st.button("Remove stored file"):
                resume["file_b64"], resume["file_name"] = "", ""
        else:
            st.caption("No file uploaded yet - the Home page shows a disabled placeholder button.")

    with tabs[2]:
        content["experience"] = _list_editor(
            "Experience", content.get("experience", []),
            [("title", "text"), ("company", "text"), ("period", "text"),
             ("summary", "area"), ("highlights", "list")],
            "exp",
        )
        st.markdown("---")
        content["education"] = _list_editor(
            "Education", content.get("education", []),
            [("qualification", "text"), ("institution", "text"), ("period", "text")],
            "edu",
        )

    with tabs[3]:
        raw = st.text_area(
            "Skills (one per line - first 18 shown on Home, rest summarised as '+N more')",
            value="\n".join(content.get("skills", [])), height=220,
        )
        content["skills"] = [s.strip() for s in raw.splitlines() if s.strip()]
        st.markdown("---")
        raw_certs = st.text_area(
            "Certifications (one per line)",
            value="\n".join(content.get("certifications", [])), height=100,
        )
        content["certifications"] = [c.strip() for c in raw_certs.splitlines() if c.strip()]

    with tabs[4]:
        content["projects"] = _list_editor(
            "Projects", content.get("projects", []),
            [("name", "text"), ("period", "text"), ("summary", "area"), ("link", "text")],
            "proj",
        )

    with tabs[5]:
        content["blog"] = _list_editor(
            "Posts", content.get("blog", []),
            [("title", "text"), ("date", "text"), ("summary", "area"), ("link", "text")],
            "blog",
        )

    with tabs[6]:
        import json as _json

        st.markdown(
            "Because container filesystems are ephemeral, the durable copy of your content "
            "is the file in the repository. Export after editing, commit "
            "`data/portfolio.json`, and redeploy."
        )
        st.download_button(
            "Export portfolio.json",
            data=_json.dumps(content, indent=2, ensure_ascii=False),
            file_name="portfolio.json",
            mime="application/json",
            type="primary",
        )
        st.markdown("---")
        imported = st.file_uploader("Import a portfolio.json", type=["json"], key="import_json")
        if imported is not None and st.button("Replace content with this file"):
            try:
                new_content = _json.loads(imported.getvalue().decode("utf-8"))
                ok, message = adminstore.save_content(new_content)
                st.success(message) if ok else st.error(message)
                st.rerun()
            except _json.JSONDecodeError as exc:
                st.error("Not valid JSON: " + str(exc))

    with tabs[7]:
        with st.form("change_pw"):
            current = st.text_input("Current password", type="password")
            new1 = st.text_input("New password", type="password")
            new2 = st.text_input("Confirm new password", type="password")
            if st.form_submit_button("Change password"):
                if new1 != new2:
                    st.error("New passwords do not match.")
                else:
                    ok, message = adminstore.change_password(current, new1)
                    st.success(message) if ok else st.error(message)

    st.divider()
    if st.button("Save changes", type="primary", use_container_width=True):
        ok, message = adminstore.save_content(content)
        if ok:
            st.success(message + " Remember to Export and commit if this is a hosted deploy.")
        else:
            st.error(message)
