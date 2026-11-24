import hmac
import io
import os
import re
import time

import pandas as pd
import streamlit as st

import altair as alt

import db
import ui
from parsers import (process_calbank_files, process_cbg_files, process_first_atlantic_files,
                     process_fnb_files, process_gcb_files, process_omnibsic_files,
                     process_stanbic_files, reconcile)

st.set_page_config(page_title=f"{ui.APP_NAME} · Bank Statement Converter", page_icon="📒", layout="wide")
ui.apply_theme()


# ==========================================
# CONFIG (environment variables on Render, st.secrets on Streamlit Cloud)
# ==========================================
def _clean(value):
    """Undo common paste mistakes: surrounding quotes, whitespace, Neon's `psql '...'` wrapper."""
    if value is None:
        return None
    v = str(value).strip()
    if v.lower().startswith("psql "):
        v = v[5:].strip()
    while len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
        v = v[1:-1].strip()
    return v or None


def setting(name, default=None):
    if os.environ.get(name):
        return _clean(os.environ[name])
    try:
        return _clean(st.secrets.get(name, default))
    except Exception:
        return default


@st.cache_resource
def get_store():
    url = setting("DATABASE_URL")
    Session, is_sqlite = db.make_session_factory(url)
    admin_user, admin_pass = setting("ADMIN_USERNAME"), setting("ADMIN_PASSWORD")
    if admin_user and admin_pass:
        db.ensure_admin(Session, admin_user, admin_pass)
    return Session, is_sqlite, bool(admin_user and admin_pass)


try:
    Session, USING_SQLITE, ADMIN_CONFIGURED = get_store()
except Exception as exc:
    ui.page_header("Setup", ui.APP_NAME)
    st.error("The app couldn't connect to its database, so it can't start.")
    reason = str(exc).splitlines()[0]
    reason = re.sub(r"://[^@\s]+@", "://***@", reason)  # never show the DB password
    st.code(f"{type(exc).__name__}: {reason}", language=None)
    st.caption("Check DATABASE_URL in the app settings: it should be the plain "
               "postgresql://… string from Neon, with no quotes or 'psql' in front.")
    st.stop()

BANK_SHORT = {
    "GCB Bank": "GCB", "Stanbic Bank": "Stanbic", "First Atlantic Bank": "First Atlantic",
    "OmniBSIC Bank": "OmniBSIC", "First National Bank (FNB)": "FNB", "CalBank": "CalBank",
    "Consolidated Bank Ghana (CBG)": "CBG",
}
BANKS = {
    "GCB Bank": process_gcb_files,
    "Stanbic Bank": process_stanbic_files,
    "First Atlantic Bank": process_first_atlantic_files,
    "OmniBSIC Bank": process_omnibsic_files,
    "First National Bank (FNB)": process_fnb_files,
    "CalBank": process_calbank_files,
    "Consolidated Bank Ghana (CBG)": process_cbg_files,
}
# GCB and Stanbic parsers return newest-first; the newer parsers already return oldest-first.
LEGACY_NEWEST_FIRST = {"GCB Bank", "Stanbic Bank"}

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")
MAX_FAILED, LOCKOUT_SECONDS = 5, 60
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ==========================================
# LOGIN / SIGN-UP
# ==========================================
def login_screen():
    st.markdown("<style>section[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl']"
                "{display:none}</style>", unsafe_allow_html=True)
    if not ADMIN_CONFIGURED:
        ui.page_header("Setup", ui.APP_NAME)
        st.error("The administrator account isn't configured yet. Set ADMIN_USERNAME and "
                 "ADMIN_PASSWORD in the app's settings, then restart it.")
        st.stop()

    left, right = st.columns([1.1, 1], gap="large")
    with left:
        banks = " · ".join(BANK_SHORT.values())
        st.markdown(f"""
<div class="bs-hero">
  <div class="bs-brand"><div class="bs-mark">{ui.APP_NAME[0]}</div>
    <div><div class="name" style="color:#FFFDF8">{ui.APP_NAME}</div><div class="sub">Statement converter</div></div></div>
  <h1>Statements in.<br>Clean ledgers out.</h1>
  <p>Turn bank PDF statements into one tidy Excel workbook, checked line by line against the running balance.</p>
  <ul>
    <li><b>01</b>Pick the bank and drop in one or many PDFs</li>
    <li><b>02</b>Every balance is reconciled before you download</li>
    <li><b>03</b>Each result is kept in your history to re-open later</li>
  </ul>
  <div class="bs-banks">{banks}</div>
</div>""", unsafe_allow_html=True)

    with right:
        st.markdown("<div style='height:1.2rem'></div>", unsafe_allow_html=True)
        ui.page_header("Welcome", "Sign in to continue")
        tab_login, tab_signup = st.tabs(["Log in", "Create account"])

        with tab_login:
            locked_until = st.session_state.get("locked_until", 0)
            with st.form("login"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Log in", width="stretch")
            if submitted:
                if time.time() < locked_until:
                    st.error(f"Too many failed attempts. Try again in "
                             f"{int(locked_until - time.time())} seconds.")
                else:
                    # The admin password configured on THIS host always works; re-sync it into the
                    # shared database first (another host may have written a different one).
                    adm_u, adm_p = setting("ADMIN_USERNAME"), setting("ADMIN_PASSWORD")
                    if (adm_u and adm_p and username.strip().lower() == adm_u.strip().lower()
                            and hmac.compare_digest(password.encode(), adm_p.encode())):
                        db.ensure_admin(Session, adm_u, adm_p)
                    user, msg = db.authenticate(Session, username, password)
                    if user:
                        st.session_state.update(user_id=user.id, username=user.username,
                                                is_admin=user.is_admin, failed=0)
                        st.rerun()
                    else:
                        st.session_state["failed"] = st.session_state.get("failed", 0) + 1
                        if st.session_state["failed"] >= MAX_FAILED:
                            st.session_state.update(locked_until=time.time() + LOCKOUT_SECONDS, failed=0)
                        st.error(msg)

        with tab_signup:
            st.caption("New accounts are approved once by the administrator before first login.")
            with st.form("signup"):
                new_user = st.text_input("Choose a username", help="3–32 characters: letters, numbers, . _ -")
                new_pass = st.text_input("Choose a password", type="password", help="At least 8 characters")
                new_pass2 = st.text_input("Confirm password", type="password")
                created = st.form_submit_button("Request access", width="stretch")
            if created:
                u = new_user.strip().lower()
                if not USERNAME_RE.match(u):
                    st.error("Username must be 3–32 characters using letters, numbers, . _ or -")
                elif len(new_pass) < 8:
                    st.error("Password must be at least 8 characters.")
                elif new_pass != new_pass2:
                    st.error("Passwords don't match.")
                else:
                    ok, msg = db.register(Session, u, new_pass)
                    (st.success if ok else st.error)(msg)


# ==========================================
# SHARED RESULT VIEW
# ==========================================
def flow_chart(df):
    """Monthly money in vs money out."""
    date_col = "Posting Date" if "Posting Date" in df.columns else "Value Date"
    d = pd.DataFrame({
        "date": pd.to_datetime(df[date_col], errors="coerce", dayfirst=True),
        "In": pd.to_numeric(df["Credit"], errors="coerce").fillna(0),
        "Out": pd.to_numeric(df["Debit"], errors="coerce").fillna(0),
    }).dropna(subset=["date"])
    if d.empty:
        return None
    d["Month"] = d["date"].dt.to_period("M").dt.to_timestamp()
    m = d.groupby("Month")[["In", "Out"]].sum().reset_index().melt("Month", var_name="Flow", value_name="GHS")
    return (alt.Chart(m).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(x=alt.X("yearmonth(Month):O", title=None, axis=alt.Axis(labelAngle=0)),
                    xOffset="Flow:N",
                    y=alt.Y("GHS:Q", title=None, axis=alt.Axis(format="~s", grid=True, gridColor=ui.RULE)),
                    color=alt.Color("Flow:N", scale=alt.Scale(domain=["In", "Out"], range=[ui.CREDIT, ui.DEBIT]),
                                    legend=alt.Legend(orient="top", title=None)),
                    tooltip=[alt.Tooltip("yearmonth(Month):O", title="Month"), "Flow",
                             alt.Tooltip("GHS:Q", format=",.2f")])
            .properties(height=280)
            .configure_view(strokeWidth=0).configure_legend(labelFont="IBM Plex Sans, sans-serif")
            .configure_axis(labelFont="IBM Plex Sans, sans-serif", labelColor=ui.MUTED, domain=False, ticks=False))


def show_result(df, meta, excel_bytes, file_name, key):
    credits, debits, check = meta["credits"], meta["debits"], meta.get("check")

    if check and check["breaks"] == 0:
        ui.badge("✓ Balanced — every running balance agrees with the line before it", "ok")
    elif check:
        ui.badge(f"⚠ {check['breaks']} balance break(s) — check rows {check['break_rows'][:10]}", "warn")
    elif meta.get("no_balance"):
        ui.badge("This bank's statement has no running balance — totals only", "info")

    items = []
    if meta.get("opening") is not None:
        items.append(("Opening · GHS", ui.money(meta["opening"]), ui.INK))
    items += [("Money in · GHS", ui.money(credits), ui.CREDIT), ("Money out · GHS", ui.money(debits), ui.DEBIT)]
    if meta.get("closing") is not None:
        items.append(("Closing · GHS", ui.money(meta["closing"]), ui.BRASS))
    items.append(("Transactions", f"{meta['rows']:,}", ui.INK_SOFT))
    ui.stats(items)

    st.download_button("⬇  Download Excel workbook", data=excel_bytes, file_name=file_name,
                       mime=XLSX_MIME, key=f"dl_{key}", type="primary")

    view = df.copy()
    money_cols = [c for c in ["Credit", "Debit", "Balance"] if c in view.columns]
    for c in money_cols:
        view[c] = pd.to_numeric(view[c], errors="coerce").map(lambda x: "" if pd.isna(x) else f"{x:,.2f}")
    date_cols = [c for c in ["Posting Date", "Value Date"] if c in view.columns]
    for c in date_cols:
        parsed = pd.to_datetime(view[c], errors="coerce", dayfirst=True)
        view[c] = parsed.dt.strftime("%d %b %Y").where(parsed.notna(), view[c].astype(str).replace("nan", ""))
    cfg = {c: st.column_config.TextColumn(c, width="small", alignment="right") for c in money_cols}
    cfg.update({c: st.column_config.TextColumn(c, width="small") for c in date_cols})
    cfg["Description"] = st.column_config.TextColumn("Description", width="large")

    t1, t2 = st.tabs(["Transactions", "Monthly flow"])
    with t1:
        st.dataframe(view, hide_index=True, width="stretch", height=420, column_config=cfg)
    with t2:
        chart = flow_chart(df)
        if chart is not None:
            st.altair_chart(chart, width="stretch")
        else:
            st.caption("No dated transactions to chart.")


# ==========================================
# PAGE: CONVERT
# ==========================================
def page_convert():
    ui.page_header("Convert", "Bank statement to Excel",
                   "Combine one or more PDF statements from the same bank into a single, reconciled workbook.")

    ui.step(1, "Choose the bank")
    names = list(BANKS.keys())
    short = st.pills("Bank", [BANK_SHORT[n] for n in names], default="GCB", label_visibility="collapsed")
    if not short:
        st.caption("Select a bank to continue.")
        return
    bank_choice = next(n for n in names if BANK_SHORT[n] == short)

    ui.step(2, "Upload the PDF statements")
    uploaded_files = st.file_uploader("PDF statements", type=["pdf"], accept_multiple_files=True,
                                      label_visibility="collapsed", key=f"up_{bank_choice}")

    ui.step(3, "Convert")
    go = st.button(f"Convert {len(uploaded_files or [])} file(s) from {short}", type="primary",
                   disabled=not uploaded_files)

    if go:
        with st.spinner(f"Reading {len(uploaded_files)} statement(s) from {bank_choice}…"):
            try:
                df = BANKS[bank_choice](uploaded_files)
            except Exception as e:
                st.error(f"Couldn't read these files: {e}")
                return
        if df.empty:
            st.session_state.pop("last_result", None)
            st.warning("No transactions found. Check that the PDFs are statements from the selected bank.")
            return

        if bank_choice in LEGACY_NEWEST_FIRST:
            df = df.iloc[::-1].reset_index(drop=True)
        check = None if bank_choice in LEGACY_NEWEST_FIRST else reconcile(df)
        credits = float(pd.to_numeric(df["Credit"], errors="coerce").sum())
        debits = float(pd.to_numeric(df["Debit"], errors="coerce").sum())

        df["Description"] = df["Description"].str.strip()
        no_balance = "Balance" in df.columns and df["Balance"].isna().all()
        if no_balance:
            df = df.drop(columns=["Balance"])
        cols = ["Posting Date", "Value Date", "Description", "Credit", "Debit", "Balance"]
        df = df[[c for c in cols if c in df.columns]]

        export = df.copy()
        export["Credit"] = export["Credit"].fillna("")
        export["Debit"] = export["Debit"].fillna("")
        out = io.BytesIO()
        with pd.ExcelWriter(out, engine="openpyxl") as writer:
            export.to_excel(writer, index=False, sheet_name="Sheet1")
        excel_bytes = out.getvalue()
        file_name = f"{re.sub(r'[^A-Za-z0-9]+', '_', bank_choice).strip('_')}_Statement_Combined.xlsx"

        meta = {"credits": credits, "debits": debits, "check": check, "rows": len(df),
                "no_balance": no_balance,
                "opening": float(check["opening"]) if check else None,
                "closing": float(check["closing"]) if check else None}
        try:
            db.save_conversion(
                Session, user_id=st.session_state["user_id"], bank=bank_choice,
                source_files=", ".join(f.name for f in uploaded_files), rows=len(df),
                total_credits=credits, total_debits=debits, opening=meta["opening"],
                closing=meta["closing"], excel_name=file_name, excel_bytes=excel_bytes)
            meta["saved"] = True
        except Exception as e:
            meta["saved"] = False
            st.warning(f"Converted, but couldn't save to history: {e}")
        st.session_state["last_result"] = (bank_choice, df, meta, excel_bytes, file_name)

    res = st.session_state.get("last_result")
    if res:
        bank, df, meta, excel_bytes, file_name = res
        st.divider()
        ui.page_header("Result", bank, "Saved to your history." if meta.get("saved") else "")
        show_result(df, meta, excel_bytes, file_name, key="current")


# ==========================================
# PAGE: HISTORY
# ==========================================
def page_history():
    is_admin = st.session_state.get("is_admin")
    ui.page_header("History", "Past conversions", "Every workbook you've produced, ready to open or download again.")
    scope_all = st.toggle("Show every user's conversions", value=False) if is_admin else False
    owner = None if is_admin else st.session_state["user_id"]
    records = db.list_conversions(Session, user_id=None if scope_all else st.session_state["user_id"])

    if not records:
        ui.empty("No conversions yet — results appear here after your first conversion.")
        return

    ui.stats([
        ("Conversions", f"{len(records):,}", ui.INK),
        ("Transactions", f"{sum(r['rows'] for r in records):,}", ui.INK_SOFT),
        ("Banks", f"{len({r['bank'] for r in records})}", ui.BRASS),
        ("Last run", f"{pd.to_datetime(records[0]['created_at']):%d %b %Y}", ui.INK),
    ])

    banks_used = sorted({r["bank"] for r in records})
    pick_bank = st.selectbox("Filter by bank", ["All banks"] + banks_used)
    shown = [r for r in records if pick_bank == "All banks" or r["bank"] == pick_bank][:60]

    for r in shown:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([4.2, 2.4, 1.1, 1.1], vertical_alignment="center")
            who = f" · {r['username']}" if scope_all else ""
            c1.markdown(f"<div class='bs-row-title'>{BANK_SHORT.get(r['bank'], r['bank'])} · "
                        f"{r['rows']:,} transactions</div><div class='bs-row-meta'>"
                        f"{pd.to_datetime(r['created_at']):%d %b %Y, %H:%M} UTC{who} · {r['source_files'][:80]}</div>",
                        unsafe_allow_html=True)
            c2.markdown(f"<div class='bs-row-meta'>In <span class='bs-num' style='color:{ui.CREDIT}'>"
                        f"{(r['total_credits'] or 0):,.2f}</span><br>Out <span class='bs-num' style='color:{ui.DEBIT}'>"
                        f"{(r['total_debits'] or 0):,.2f}</span></div>", unsafe_allow_html=True)
            if c3.button("Open", key=f"open_{r['id']}", width="stretch"):
                st.session_state["open_conv"] = r["id"]
                st.session_state.pop("confirm_del", None)
            if st.session_state.get("confirm_del") == r["id"]:
                if c4.button("Confirm", key=f"cdel_{r['id']}", type="primary", width="stretch"):
                    db.delete_conversion(Session, r["id"], user_id=owner)
                    st.session_state.pop("confirm_del", None)
                    if st.session_state.get("open_conv") == r["id"]:
                        st.session_state.pop("open_conv", None)
                    st.rerun()
            elif c4.button("Delete", key=f"del_{r['id']}", width="stretch"):
                st.session_state["confirm_del"] = r["id"]
                st.rerun()

    open_id = st.session_state.get("open_conv")
    rec = next((r for r in records if r["id"] == open_id), None)
    if rec:
        got = db.get_conversion_file(Session, open_id, user_id=owner)
        if got:
            name, data = got
            df = pd.read_excel(io.BytesIO(data))
            st.divider()
            ui.page_header("Opened", f"{rec['bank']} · {pd.to_datetime(rec['created_at']):%d %b %Y, %H:%M}",
                           rec["source_files"])
            meta = {"credits": rec["total_credits"] or 0.0, "debits": rec["total_debits"] or 0.0,
                    "rows": rec["rows"], "opening": rec["opening"], "closing": rec["closing"],
                    "no_balance": "Balance" not in df.columns}
            show_result(df, meta, data, name, key=f"hist_{open_id}")


# ==========================================
# PAGE: APPROVALS (admin only)
# ==========================================
def page_approvals():
    ui.page_header("Administration", "Account approvals",
                   "People who signed up wait here until you approve them. Approval is needed only once.")
    pending = db.pending_users(Session)
    users = db.approved_users(Session)
    ui.stats([("Waiting", f"{len(pending)}", ui.BRASS), ("Active users", f"{len(users)}", ui.CREDIT)])

    if not pending:
        ui.empty("Nobody is waiting for approval.")
    for u in pending:
        with st.container(border=True):
            c1, c2, c3 = st.columns([5, 1.3, 1.3], vertical_alignment="center")
            c1.markdown(f"<div class='bs-row-title'>{u.username}</div>"
                        f"<div class='bs-row-meta'>Requested {u.created_at:%d %b %Y, %H:%M} UTC</div>",
                        unsafe_allow_html=True)
            if c2.button("Approve", key=f"ap_{u.id}", type="primary", width="stretch"):
                db.approve(Session, u.id)
                st.toast(f"{u.username} can now log in.")
                st.rerun()
            if c3.button("Reject", key=f"rj_{u.id}", width="stretch"):
                db.reject(Session, u.id)
                st.rerun()

    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)
    members = [u for u in users if not u.is_admin]
    if members:
        with st.expander("Reset a member's password"):
            with st.form("reset_pw", clear_on_submit=True):
                who = st.selectbox("Member", members, format_func=lambda u: u.username)
                p1 = st.text_input("New password", type="password", help="At least 8 characters")
                p2 = st.text_input("Confirm new password", type="password")
                go = st.form_submit_button("Set new password")
            if go:
                if len(p1) < 8:
                    st.error("Password must be at least 8 characters.")
                elif p1 != p2:
                    st.error("Passwords don't match.")
                elif db.set_password(Session, who.id, p1):
                    st.success(f"Password updated for {who.username}. Give it to them directly.")

    st.subheader("Active users")
    st.dataframe(pd.DataFrame([{
        "Username": u.username, "Role": "Administrator" if u.is_admin else "Member",
        "Approved (UTC)": f"{u.approved_at:%d %b %Y %H:%M}" if u.approved_at else ""} for u in users]),
        hide_index=True, width="stretch")


# ==========================================
# ROUTER
# ==========================================
if "user_id" not in st.session_state:
    login_screen()
    st.stop()

pages = {"Convert": page_convert, "History": page_history}
if st.session_state.get("is_admin"):
    n = len(db.pending_users(Session))
    pages[f"Approvals  ·  {n} waiting" if n else "Approvals"] = page_approvals

with st.sidebar:
    ui.sidebar_brand(st.session_state["username"], st.session_state.get("is_admin"))
    choice = st.radio("Menu", list(pages.keys()), label_visibility="collapsed")
    st.markdown("<div style='height:2rem'></div>", unsafe_allow_html=True)
    if st.button("Log out"):
        for k in ["user_id", "username", "is_admin", "last_result", "open_conv", "confirm_del"]:
            st.session_state.pop(k, None)
        st.rerun()
    if USING_SQLITE and st.session_state.get("is_admin"):
        st.warning("No DATABASE_URL set — accounts and history are in a local file that is "
                   "wiped on every redeploy/restart.")

pages[choice]()
