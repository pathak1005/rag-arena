"""Portfolio landing page and the owner-only admin panel.

Rendered by ui/streamlit_app.py. Kept in a separate module because the admin editor is
long and has nothing to do with retrieval.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import streamlit as st

from app import adminstore


# ==========================================================================
# Public portfolio
# ==========================================================================
def render_portfolio() -> None:
    content = adminstore.load_content()
    profile = content["profile"]

    unfilled = sum(
        1 for v in profile.values() if adminstore.is_placeholder(v)
    ) + (0 if content["experience"] else 1) + (0 if content["skills"] else 1)

    st.markdown(
        "<div style='padding:26px 0 10px;'>"
        "<div style='font-size:2.6rem;font-weight:700;line-height:1.1;'>"
        + profile["name"] + "</div>"
        "<div style='font-size:1.15rem;opacity:0.75;margin-top:6px;'>"
        + profile["headline"] + "</div></div>",
        unsafe_allow_html=True,
    )

    bits = [b for b in (profile.get("location"), profile.get("email")) if b]
    if bits:
        st.caption("  ·  ".join(bits))

    links = [
        ("Portfolio", profile.get("portfolio_url", "")),
        ("Book a call", profile.get("calendly_url", "")),
        ("LinkedIn", profile.get("linkedin_url", "")),
        ("GitHub", profile.get("github_url", "")),
    ]
    active = [(label, url) for label, url in links if url.strip()]
    if active:
        st.markdown("  ·  ".join("[" + label + "](" + url + ")" for label, url in active))

    if unfilled:
        st.info(
            "This portfolio is not filled in yet. Open the admin panel and add your real "
            "details - the placeholders are deliberately visible so nothing invented ever "
            "ships here.",
            icon=":",
        )

    st.divider()

    # -- summary
    st.markdown("### About")
    st.markdown(profile["summary"])

    # -- resume
    resume = content.get("resume", {})
    if resume.get("file_b64") or resume.get("markdown"):
        st.markdown("### Resume")
        cols = st.columns([1, 1, 2])
        if resume.get("file_b64") and resume.get("file_name"):
            try:
                cols[0].download_button(
                    "Download resume",
                    data=base64.b64decode(resume["file_b64"]),
                    file_name=resume["file_name"],
                    mime="application/pdf" if resume["file_name"].lower().endswith(".pdf")
                    else "application/octet-stream",
                    type="primary",
                    use_container_width=True,
                )
            except Exception:  # noqa: BLE001
                cols[0].caption("Stored resume file could not be decoded.")
        if resume.get("markdown"):
            cols[1].download_button(
                "Download as .md",
                data=resume["markdown"],
                file_name="ashish_pathak_resume.md",
                mime="text/markdown",
                use_container_width=True,
            )
        if resume.get("updated"):
            cols[2].caption("Updated " + resume["updated"][:10])

        if resume.get("markdown"):
            with st.expander("Read resume inline", expanded=False):
                st.markdown(resume["markdown"])

    # -- skills
    if content.get("skills"):
        st.markdown("### Skills")
        st.markdown(
            " ".join(
                "<span style='display:inline-block;background:rgba(128,128,128,0.15);"
                "padding:3px 11px;border-radius:12px;margin:3px 4px 3px 0;font-size:0.88rem;'>"
                + s + "</span>"
                for s in content["skills"]
            ),
            unsafe_allow_html=True,
        )

    # -- experience
    if content.get("experience"):
        st.markdown("### Experience")
        for role in content["experience"]:
            st.markdown(
                "**" + role.get("title", "") + "**  ·  " + role.get("company", "")
                + "  \n*" + role.get("period", "") + "*"
            )
            if role.get("summary"):
                st.markdown(role["summary"])
            for point in role.get("highlights", []):
                st.markdown("- " + point)
            st.markdown("")

    # -- projects
    if content.get("projects"):
        st.markdown("### Projects")
        for project in content["projects"]:
            title = project.get("name", "")
            if project.get("link"):
                title = "[" + title + "](" + project["link"] + ")"
            st.markdown("**" + title + "**  ·  *" + project.get("period", "") + "*")
            if project.get("summary"):
                st.markdown(project["summary"])
            st.markdown("")

    # -- education
    if content.get("education"):
        st.markdown("### Education")
        for item in content["education"]:
            st.markdown(
                "**" + item.get("qualification", "") + "**  ·  " + item.get("institution", "")
                + "  \n*" + item.get("period", "") + "*"
            )

    # -- blog
    if content.get("blog"):
        st.markdown("### Writing")
        for post in content["blog"]:
            title = post.get("title", "")
            if post.get("link"):
                title = "[" + title + "](" + post["link"] + ")"
            st.markdown("**" + title + "**  ·  *" + post.get("date", "") + "*")
            if post.get("summary"):
                st.markdown(post["summary"])
            st.markdown("")

    st.divider()
    st.caption(
        "This site is served by the same FastAPI + Streamlit application as the RAG Arena "
        "demo in the other tabs."
    )


# ==========================================================================
# Admin
# ==========================================================================
def _login_panel() -> None:
    st.markdown("## Admin")

    if not adminstore.is_registered():
        st.warning(
            "No account exists yet. Register now - the first registration claims this panel, "
            "and only the owner address is accepted.",
            icon="!",
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
    """Generic repeating-record editor. `fields` is [(key, widget)] where widget is text|area."""
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
        st.session_state[f"{key}_pending"] = True

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
        "the container restarts. Use **Export** below after editing and commit the file to "
        "the repo to make changes permanent.",
        icon="!",
    )

    tabs = st.tabs(["Profile", "Resume", "Experience", "Skills", "Projects", "Blog", "Export", "Password"])

    # ---- profile
    with tabs[0]:
        p = content["profile"]
        p["name"] = st.text_input("Name", value=p.get("name", ""))
        p["headline"] = st.text_input("Headline", value=p.get("headline", ""))
        c1, c2 = st.columns(2)
        p["location"] = c1.text_input("Location", value=p.get("location", ""))
        p["email"] = c2.text_input("Public email", value=p.get("email", ""))
        p["summary"] = st.text_area("Summary", value=p.get("summary", ""), height=140)
        st.markdown("**Links**")
        c1, c2 = st.columns(2)
        p["portfolio_url"] = c1.text_input("Portfolio URL", value=p.get("portfolio_url", ""))
        p["calendly_url"] = c2.text_input("Calendly URL", value=p.get("calendly_url", ""))
        p["linkedin_url"] = c1.text_input("LinkedIn URL", value=p.get("linkedin_url", ""))
        p["github_url"] = c2.text_input("GitHub URL", value=p.get("github_url", ""))

    # ---- resume
    with tabs[1]:
        resume = content.setdefault("resume", {})
        st.markdown("**Upload a resume file** (PDF or DOCX, max 5 MB)")
        uploaded = st.file_uploader("Resume file", type=["pdf", "docx", "md", "txt"])
        if uploaded is not None:
            raw = uploaded.getvalue()
            if len(raw) > 5 * 1024 * 1024:
                st.error("File exceeds 5 MB.")
            else:
                resume["file_b64"] = base64.b64encode(raw).decode("ascii")
                resume["file_name"] = uploaded.name
                resume["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                st.success("Loaded " + uploaded.name + " - press Save changes below.")

        if resume.get("file_name"):
            st.caption("Currently stored: " + resume["file_name"])
            if st.button("Remove stored file"):
                resume["file_b64"], resume["file_name"] = "", ""

        st.markdown("**Resume as markdown** (shown inline on the portfolio page)")
        resume["markdown"] = st.text_area(
            "Markdown", value=resume.get("markdown", ""), height=340,
            placeholder="## Experience\n\n**Role** - Company (2020-2024)\n- Achievement...",
        )

    # ---- experience
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

    # ---- skills
    with tabs[3]:
        raw = st.text_area(
            "Skills (one per line)", value="\n".join(content.get("skills", [])), height=260
        )
        content["skills"] = [s.strip() for s in raw.splitlines() if s.strip()]

    # ---- projects
    with tabs[4]:
        content["projects"] = _list_editor(
            "Projects", content.get("projects", []),
            [("name", "text"), ("period", "text"), ("summary", "area"), ("link", "text")],
            "proj",
        )

    # ---- blog
    with tabs[5]:
        content["blog"] = _list_editor(
            "Posts", content.get("blog", []),
            [("title", "text"), ("date", "text"), ("summary", "area"), ("link", "text")],
            "blog",
        )

    # ---- export / import
    with tabs[6]:
        st.markdown(
            "Because container filesystems are ephemeral, the durable copy of your content "
            "is the file in the repository. Export after editing, commit "
            "`data/portfolio.json`, and redeploy."
        )
        st.download_button(
            "Export portfolio.json",
            data=json.dumps(content, indent=2, ensure_ascii=False),
            file_name="portfolio.json",
            mime="application/json",
            type="primary",
        )
        st.markdown("---")
        imported = st.file_uploader("Import a portfolio.json", type=["json"], key="import_json")
        if imported is not None and st.button("Replace content with this file"):
            try:
                new_content = json.loads(imported.getvalue().decode("utf-8"))
                ok, message = adminstore.save_content(new_content)
                st.success(message) if ok else st.error(message)
                st.rerun()
            except json.JSONDecodeError as exc:
                st.error("Not valid JSON: " + str(exc))

    # ---- password
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
