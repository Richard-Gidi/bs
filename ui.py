"""Look and feel: theme CSS and small HTML components."""
import html

import streamlit as st

APP_NAME = "Ledgerline"
INK = "#14233A"
INK_SOFT = "#2A3B55"
BRASS = "#B9832F"
PAPER = "#F6F2EA"
CARD = "#FFFDF8"
RULE = "#E4DCCB"
MUTED = "#6B7280"
CREDIT = "#2F7D5B"
DEBIT = "#B4483A"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,650&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@500&display=swap');

html, body, [class*="css"], .stMarkdown, .stText, input, textarea, button, label {{
  font-family: 'IBM Plex Sans', system-ui, sans-serif;
}}
.stApp {{
  background:
    repeating-linear-gradient(0deg, transparent 0 31px, rgba(20,35,58,.035) 31px 32px),
    {PAPER};
}}
.block-container {{ max-width: 1080px; padding-top: 2.2rem; padding-bottom: 4rem; }}
h1, h2, h3 {{ font-family: 'Fraunces', Georgia, serif !important; color: {INK}; letter-spacing: -.01em; }}
header[data-testid="stHeader"] {{ background: transparent; }}
#MainMenu, footer {{ visibility: hidden; }}

/* ---------- sidebar ---------- */
section[data-testid="stSidebar"] {{ background: {INK}; border-right: 3px solid {BRASS}; }}
section[data-testid="stSidebar"] * {{ color: #E9E4D8 !important; }}
section[data-testid="stSidebar"] [role="radiogroup"] label {{
  padding: .55rem .8rem; border-radius: 8px; margin-bottom: .2rem; transition: background .15s;
}}
section[data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background: {INK_SOFT}; }}
section[data-testid="stSidebar"] [data-testid="stRadio"] {{ width: 100%; }}
section[data-testid="stSidebar"] [role="radiogroup"] {{ display:flex; flex-direction:column; align-items:stretch; width:100%; }}
section[data-testid="stSidebar"] [data-testid="stRadioOption"] {{ width: 100%; }}
section[data-testid="stSidebar"] [data-testid="stRadioOption"][data-selected="true"] {{
  background: {INK_SOFT}; box-shadow: inset 3px 0 0 {BRASS};
}}
section[data-testid="stSidebar"] [data-testid="stRadioOption"] > div > div:first-child {{ display: none; }}
section[data-testid="stSidebar"] [data-testid="stAlertContainer"] {{
  background: rgba(185,131,47,.14); border: 1px solid {BRASS};
}}
section[data-testid="stSidebar"] .stButton button {{
  background: transparent; border: 1px solid #45566F; width: 100%;
}}
section[data-testid="stSidebar"] .stButton button:hover {{ border-color: {BRASS}; }}

/* ---------- buttons ---------- */
.stButton button[kind="primary"], .stDownloadButton button, .stFormSubmitButton button {{
  background: {INK}; color: #fff; border: 0; border-radius: 8px; font-weight: 600;
  padding: .6rem 1.3rem; box-shadow: 0 2px 0 {BRASS};
}}
.stButton button[kind="primary"]:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover {{
  background: {INK_SOFT}; color: #fff;
}}
.stButton button {{ border-radius: 8px; }}

/* ---------- inputs, uploader, tabs ---------- */
[data-testid="stForm"] {{ background: {CARD}; border: 1px solid {RULE}; border-radius: 14px; padding: 1.4rem 1.4rem .6rem; }}
[data-testid="stFileUploaderDropzone"] {{ background: {CARD}; border: 1.5px dashed {BRASS}; border-radius: 12px; }}
.stTabs [data-baseweb="tab-list"] {{ gap: .3rem; border-bottom: 1px solid {RULE}; }}
.stTabs [data-baseweb="tab"] {{ font-weight: 600; }}
.stTabs [aria-selected="true"] {{ color: {INK} !important; }}
.stTabs [data-baseweb="tab-highlight"] {{ background: {BRASS}; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ background: {CARD}; border-color: {RULE} !important; border-radius: 12px; }}
[data-testid="stDataFrame"] {{ border: 1px solid {RULE}; border-radius: 10px; overflow: hidden; }}
[data-testid="stButtonGroup"] button[data-variant="pills"] {{
  border-radius: 999px; background: {CARD}; border: 1px solid {RULE}; padding: .35rem 1rem;
}}
[data-testid="stButtonGroup"] button[data-variant="pills"]:hover {{ border-color: {BRASS}; }}
[data-testid="stButtonGroup"] button[data-variant="pills"][aria-checked="true"],
[data-testid="stButtonGroup"] button[data-variant="pills"][aria-checked="true"]:hover {{
  background: {INK} !important; border-color: {INK} !important;
}}
[data-testid="stButtonGroup"] button[aria-checked="true"] p {{ color: #FFFDF8 !important; font-weight: 600; }}
.stButton button:disabled {{ opacity: .45; box-shadow: none; }}

/* ---------- custom components ---------- */
.bs-brand {{ display:flex; align-items:center; gap:.7rem; margin-bottom: 1.2rem; }}
.bs-mark {{ width:38px; height:38px; border-radius:9px; background:{BRASS}; color:{INK} !important;
  display:flex; align-items:center; justify-content:center; font-family:'Fraunces',serif; font-weight:650; font-size:1.25rem; }}
.bs-brand .name {{ font-family:'Fraunces',serif; font-size:1.15rem; line-height:1.1; }}
.bs-brand .sub {{ font-size:.72rem; letter-spacing:.14em; text-transform:uppercase; opacity:.65; }}
.bs-user {{ font-size:.82rem; opacity:.75; margin:.2rem 0 1rem; }}

.bs-eyebrow {{ font-size:.74rem; letter-spacing:.16em; text-transform:uppercase; color:{BRASS}; font-weight:600; margin-bottom:.25rem; }}
.bs-title {{ font-family:'Fraunces',serif; font-size:2.25rem; color:{INK}; margin:0 0 .35rem; line-height:1.1; }}
.bs-lede {{ color:{MUTED}; font-size:1rem; margin-bottom:1.6rem; max-width:44rem; }}

.bs-step {{ display:flex; align-items:center; gap:.6rem; margin:1.4rem 0 .5rem; }}
.bs-step .n {{ width:26px; height:26px; border-radius:50%; border:1.5px solid {INK}; color:{INK};
  display:flex; align-items:center; justify-content:center; font-size:.8rem; font-weight:600; }}
.bs-step .t {{ font-weight:600; color:{INK}; }}

.bs-stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:.8rem; margin:1rem 0 1.2rem; }}
.bs-stat {{ background:{CARD}; border:1px solid {RULE}; border-radius:12px; padding:.9rem 1rem; position:relative; overflow:hidden; }}
.bs-stat::before {{ content:""; position:absolute; left:0; top:0; bottom:0; width:4px; background:var(--accent,{INK}); }}
.bs-stat .k {{ font-size:.72rem; letter-spacing:.12em; text-transform:uppercase; color:{MUTED}; }}
.bs-stat .v {{ font-family:'IBM Plex Mono',monospace; font-size:1.08rem; letter-spacing:-.02em; color:{INK}; margin-top:.25rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}

.bs-badge {{ display:inline-flex; align-items:center; gap:.4rem; padding:.3rem .75rem; border-radius:999px; font-size:.84rem; font-weight:500; }}
.bs-badge.ok {{ background:#E5F1EA; color:{CREDIT}; }}
.bs-badge.warn {{ background:#F8E6E2; color:{DEBIT}; }}
.bs-badge.info {{ background:#ECE7DA; color:{INK}; }}

.bs-hero {{ background:{INK}; border-radius:18px; padding:2.4rem 2.2rem; color:#E9E4D8; min-height:420px;
  position:relative; overflow:hidden; border-bottom:4px solid {BRASS}; }}
.bs-hero::after {{ content:""; position:absolute; inset:0;
  background: repeating-linear-gradient(0deg, transparent 0 27px, rgba(233,228,216,.06) 27px 28px); pointer-events:none; }}
.bs-hero h1 {{ color:#FFFDF8 !important; font-size:2.4rem; line-height:1.08; margin:.6rem 0 1rem; }}
.bs-hero p {{ color:#C9C2B3; font-size:1rem; }}
.bs-hero ul {{ list-style:none; padding:0; margin:1.6rem 0 0; }}
.bs-hero li {{ padding:.45rem 0; border-top:1px solid rgba(233,228,216,.12); font-size:.92rem; color:#E9E4D8; }}
.bs-hero li b {{ color:{BRASS}; font-family:'IBM Plex Mono',monospace; font-weight:500; margin-right:.6rem; }}
.bs-banks {{ margin-top:1.4rem; font-size:.78rem; letter-spacing:.08em; text-transform:uppercase; color:#9FA8B8; }}

.bs-row-title {{ font-weight:600; color:{INK}; }}
.bs-row-meta {{ font-size:.85rem; color:{MUTED}; }}
.bs-num {{ font-family:'IBM Plex Mono',monospace; }}
.bs-empty {{ text-align:center; padding:2.5rem 1rem; color:{MUTED}; border:1.5px dashed {RULE}; border-radius:14px; background:{CARD}; }}
</style>
"""


def apply_theme():
    st.markdown(CSS, unsafe_allow_html=True)


def page_header(eyebrow, title, lede=""):
    st.markdown(
        f'<div class="bs-eyebrow">{html.escape(eyebrow)}</div>'
        f'<div class="bs-title">{html.escape(title)}</div>'
        + (f'<div class="bs-lede">{html.escape(lede)}</div>' if lede else ""),
        unsafe_allow_html=True)


def step(n, text):
    st.markdown(f'<div class="bs-step"><span class="n">{n}</span><span class="t">{html.escape(text)}</span></div>',
                unsafe_allow_html=True)


def stats(items):
    """items: list of (label, value_str, accent_color or None)."""
    cells = "".join(
        f'<div class="bs-stat" style="--accent:{a or INK}"><div class="k">{html.escape(k)}</div>'
        f'<div class="v" title="{html.escape(v)}">{html.escape(v)}</div></div>'
        for k, v, a in items)
    st.markdown(f'<div class="bs-stats">{cells}</div>', unsafe_allow_html=True)


def badge(text, kind="info"):
    st.markdown(f'<span class="bs-badge {kind}">{html.escape(text)}</span>', unsafe_allow_html=True)


def sidebar_brand(username, is_admin):
    role = "Administrator" if is_admin else "Member"
    st.markdown(
        f'<div class="bs-brand"><div class="bs-mark">{APP_NAME[0]}</div><div>'
        f'<div class="name">{APP_NAME}</div><div class="sub">Statement converter</div></div></div>'
        f'<div class="bs-user">{html.escape(username)} · {role}</div>',
        unsafe_allow_html=True)


def empty(text):
    st.markdown(f'<div class="bs-empty">{html.escape(text)}</div>', unsafe_allow_html=True)


def money(x):
    return "—" if x is None else f"{x:,.2f}"
