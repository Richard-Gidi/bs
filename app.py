import io
import os
import re
import time

import pandas as pd
import streamlit as st

import db
from parsers import (process_calbank_files, process_cbg_files, process_first_atlantic_files,
                     process_fnb_files, process_gcb_files, process_omnibsic_files,
                     process_stanbic_files, reconcile)

st.set_page_config(page_title="Bank Statement Converter", layout="centered")


# ==========================================
# CONFIG (environment variables on Render, st.secrets on Streamlit Cloud)
# ==========================================
def setting(name, default=None):
    if os.environ.get(name):
        return os.environ[name]
    try:
        return st.secrets.get(name, default)
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


Session, USING_SQLITE, ADMIN_CONFIGURED = get_store()

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
    st.title("📂 Bank Statement to Excel")
    if not ADMIN_CONFIGURED:
        st.error("The administrator account isn't configured yet. Set ADMIN_USERNAME and "
                 "ADMIN_PASSWORD in the app's settings, then restart it.")
        st.stop()

    tab_login, tab_signup = st.tabs(["Log in", "Create account"])

    with tab_login:
        locked_until = st.session_state.get("locked_until", 0)
        with st.form("login"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Log in")
        if submitted:
            if time.time() < locked_until:
                st.error(f"Too many failed attempts. Try again in "
                         f"{int(locked_until - time.time())} seconds.")
            else:
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
        st.caption("New accounts need a one-time approval from the administrator before first login.")
        with st.form("signup"):
            new_user = st.text_input("Choose a username", help="3–32 characters: letters, numbers, . _ -")
            new_pass = st.text_input("Choose a password", type="password", help="At least 8 characters")
            new_pass2 = st.text_input("Confirm password", type="password")
            created = st.form_submit_button("Create account")
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
# PAGE: CONVERT
# ==========================================
def page_convert():
    st.title("📂 Bank Statement to Excel")
    st.markdown("Upload multiple PDF statements and convert them into a single, clean Excel file.")

    bank_choice = st.selectbox("Select Your Bank", list(BANKS.keys()))
    uploaded_files = st.file_uploader("Upload PDF Statements", type=["pdf"], accept_multiple_files=True)

    if not uploaded_files:
        return
    st.write(f"📄 **{len(uploaded_files)} files uploaded.** Ready to process.")
    if not st.button("Convert to Excel"):
        return

    with st.spinner(f"Processing {len(uploaded_files)} files for {bank_choice}..."):
        try:
            df = BANKS[bank_choice](uploaded_files)
        except Exception as e:
            st.error(f"❌ An error occurred: {e}")
            return

    if df.empty:
        st.warning("⚠️ No transactions found. Please check if the PDFs are correct and the right bank is selected.")
        return

    if bank_choice in LEGACY_NEWEST_FIRST:
        df = df.iloc[::-1].reset_index(drop=True)
    check = None if bank_choice in LEGACY_NEWEST_FIRST else reconcile(df)

    credits = float(pd.to_numeric(df["Credit"], errors="coerce").sum())
    debits = float(pd.to_numeric(df["Debit"], errors="coerce").sum())

    df["Credit"] = df["Credit"].fillna("")
    df["Debit"] = df["Debit"].fillna("")
    df["Description"] = df["Description"].str.strip()
    if "Balance" in df.columns and df["Balance"].isna().all():
        df = df.drop(columns=["Balance"])
    cols = ["Posting Date", "Value Date", "Description", "Credit", "Debit", "Balance"]
    df = df[[c for c in cols if c in df.columns]]

    st.success(f"✅ Conversion Successful! {len(df)} transactions extracted.")
    if check:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Opening", f"{check['opening']:,.2f}")
        c2.metric("Total Credits", f"{check['credits']:,.2f}")
        c3.metric("Total Debits", f"{check['debits']:,.2f}")
        c4.metric("Closing", f"{check['closing']:,.2f}")
        if check["breaks"] == 0:
            st.caption("✔ Every running balance agrees with the previous balance ± the transaction.")
        else:
            st.warning(f"⚠️ {check['breaks']} row(s) where the running balance doesn't follow "
                       f"from the previous one — check rows {check['break_rows'][:10]}.")
    else:
        note = " (FNB statements carry no running balance)" if bank_choice.startswith("First National") else ""
        st.caption(f"Total credits {credits:,.2f} · total debits {debits:,.2f}{note}.")
    st.dataframe(df.head(5))

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sheet1")
    excel_bytes = output.getvalue()
    safe_name = re.sub(r"[^A-Za-z0-9]+", "_", bank_choice).strip("_")
    file_name = f"{safe_name}_Statement_Combined.xlsx"

    try:
        db.save_conversion(
            Session, user_id=st.session_state["user_id"], bank=bank_choice,
            source_files=", ".join(f.name for f in uploaded_files), rows=len(df),
            total_credits=credits, total_debits=debits,
            opening=float(check["opening"]) if check else None,
            closing=float(check["closing"]) if check else None,
            excel_name=file_name, excel_bytes=excel_bytes)
        st.caption("Saved to your history.")
    except Exception as e:
        st.warning(f"Converted, but couldn't save to history: {e}")

    st.download_button("📥 Download Excel File", data=excel_bytes, file_name=file_name, mime=XLSX_MIME)


# ==========================================
# PAGE: HISTORY
# ==========================================
def page_history():
    st.title("🕘 History")
    is_admin = st.session_state.get("is_admin")
    scope_all = st.toggle("Show all users' conversions", value=False) if is_admin else False
    owner = None if is_admin else st.session_state["user_id"]
    records = db.list_conversions(Session, user_id=None if scope_all else st.session_state["user_id"])

    if not records:
        st.info("No conversions yet. Converted statements will appear here.")
        return

    table = pd.DataFrame(records)
    table["When (UTC)"] = pd.to_datetime(table["created_at"]).dt.strftime("%d %b %Y %H:%M")
    show = ["When (UTC)", "bank", "source_files", "rows", "total_credits", "total_debits", "opening", "closing"]
    if scope_all:
        show.insert(1, "username")
    view = table[show].rename(columns={
        "username": "User", "bank": "Bank", "source_files": "Files", "rows": "Rows",
        "total_credits": "Credits", "total_debits": "Debits", "opening": "Opening", "closing": "Closing"})
    st.dataframe(view, hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.2f")
                                for c in ["Credits", "Debits", "Opening", "Closing"]})

    labels = {r["id"]: f"{pd.to_datetime(r['created_at']):%d %b %Y %H:%M} · {r['bank']} · {r['rows']} rows"
              + (f" · {r['username']}" if scope_all else "") for r in records}
    pick = st.selectbox("Open a past result", list(labels.keys()), format_func=labels.get)
    got = db.get_conversion_file(Session, pick, user_id=owner)
    if not got:
        return
    name, data = got
    c1, c2 = st.columns([3, 1])
    c1.download_button("📥 Download this Excel file", data=data, file_name=name, mime=XLSX_MIME, key=f"dl_{pick}")
    if c2.button("Delete", key=f"del_{pick}"):
        db.delete_conversion(Session, pick, user_id=owner)
        st.rerun()
    with st.expander("Preview", expanded=True):
        st.dataframe(pd.read_excel(io.BytesIO(data)), hide_index=True)


# ==========================================
# PAGE: APPROVALS (admin only)
# ==========================================
def page_approvals():
    st.title("✅ Account approvals")
    pending = db.pending_users(Session)
    if not pending:
        st.info("No accounts waiting for approval.")
    for u in pending:
        c1, c2, c3 = st.columns([3, 1, 1])
        c1.write(f"**{u.username}** — requested {u.created_at:%d %b %Y %H:%M} UTC")
        if c2.button("Approve", key=f"ap_{u.id}"):
            db.approve(Session, u.id)
            st.rerun()
        if c3.button("Reject", key=f"rj_{u.id}"):
            db.reject(Session, u.id)
            st.rerun()

    st.subheader("Approved users")
    users = db.approved_users(Session)
    st.dataframe(pd.DataFrame([{
        "Username": u.username, "Admin": "Yes" if u.is_admin else "",
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
    pages[f"Approvals ({n})" if n else "Approvals"] = page_approvals

with st.sidebar:
    st.write(f"Signed in as **{st.session_state['username']}**")
    choice = st.radio("Menu", list(pages.keys()), label_visibility="collapsed")
    if st.button("Log out"):
        for k in ["user_id", "username", "is_admin"]:
            st.session_state.pop(k, None)
        st.rerun()
    if USING_SQLITE and st.session_state.get("is_admin"):
        st.warning("No DATABASE_URL set — accounts and history are in a local file that is "
                   "wiped on every redeploy/restart.")

pages[choice]()
