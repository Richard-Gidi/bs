import streamlit as st
import pdfplumber
import pandas as pd
import io
import re

# ==========================================
# 1. UTILITY FUNCTIONS
# ==========================================

def to_float(x):
    """Clean and convert amount string to float."""
    if not x: return 0.0
    # Handle negative numbers in (brackets) often found in statements
    clean = str(x).replace("GHS", "").replace(",", "").strip()
    if clean.startswith("(") and clean.endswith(")"):
        clean = "-" + clean[1:-1]
    try:
        return float(clean)
    except ValueError:
        return 0.0


def clean_cell(text, is_description=False):
    """Strip \n (and \r) from ALL cell values before processing.
    
    - Dates and large numbers: remove \n entirely (concatenates broken text like "01\n/01\n/2025" → "01/01/2025" or "1,234\n.56" → "1,234.56").
    - Descriptions: replace \n with space (preserves readability for wrapped lines).
    This fixes the original limitation where only descriptions were (partially) cleaned.
    """
    if text is None:
        return ""
    text_str = str(text)
    if is_description:
        cleaned = text_str.replace('\n', ' ').replace('\r', ' ')
    else:
        cleaned = text_str.replace('\n', '').replace('\r', '')
    return cleaned.strip()


# ==========================================
# 2. GCB BANK PROCESSING LOGIC
# ==========================================
def process_gcb_files(uploaded_files):
    """
    Processes a list of GCB PDF files using the 'Accounting Logic' (Balance Difference).
    Returns a combined DataFrame.
    """
    all_records = []

    # Coordinate Zones (Tuned from previous chat)
    DATE_MAX_X = 80       
    DESC_START_X = 110    
    REF_START_X = 280     

    for file in uploaded_files:
        with pdfplumber.open(file) as pdf:
            file_records = []
            
            for page in pdf.pages:
                words = page.extract_words(use_text_flow=True)
                
                # Group by Row (Y-axis)
                rows = {}
                for w in words:
                    y = round(w["top"] / 2) * 2
                    rows.setdefault(y, []).append(w)
                
                sorted_rows = sorted(rows.keys())
                last_txn_index = -1

                for y in sorted_rows:
                    row_words = sorted(rows[y], key=lambda x: x["x0"])
                    
                    row_date = []
                    row_desc = []
                    row_amounts = [] 

                    for w in row_words:
                        raw_text = w.get("text", "")
                        x = w["x0"]

                        # NEW FIX: clean \n from ALL cells before any processing
                        is_desc_zone = x >= DESC_START_X
                        text = clean_cell(raw_text, is_description=is_desc_zone)

                        # 1. Capture Date
                        if x < DATE_MAX_X:
                            if (text.isdigit() and len(text) <= 2) or \
                               (text.isalpha() and len(text) == 3) or \
                               (text.isdigit() and len(text) == 4):
                                 row_date.append(text)
                            continue

                        # 2. Capture Amounts
                        if "GHS" in text:
                            row_amounts.append((x, text))
                            continue

                        # 3. Skip Reference Number Zone
                        if x >= REF_START_X and x < 400: 
                             continue 

                        # 4. Capture Description
                        if x >= DESC_START_X:
                            if not row_desc or text != row_desc[-1]:
                                row_desc.append(text)

                    # --- PROCESS ROW ---
                    if len(row_date) == 3 and row_amounts:
                        value_date = " ".join(row_date)
                        description = " ".join(row_desc)
                        
                        row_amounts = sorted(row_amounts, key=lambda x: x[0])
                        balance = to_float(row_amounts[-1][1])
                        
                        txn_amount = 0.0
                        txn_x = 0
                        if len(row_amounts) >= 2:
                            txn_x = row_amounts[-2][0]
                            txn_amount = to_float(row_amounts[-2][1])

                        file_records.append({
                            "Value Date": value_date,
                            "Description": description,
                            "Raw_Amount": txn_amount,
                            "Balance": balance,
                            "Txn_X": txn_x,
                            "Debit": None,
                            "Credit": None
                        })
                        last_txn_index = len(file_records) - 1

                    # --- CONTINUATION LINES ---
                    elif not row_date and not row_amounts and last_txn_index >= 0:
                        if row_desc:
                            file_records[last_txn_index]["Description"] += " " + " ".join(row_desc)

            # --- APPLY ACCOUNTING LOGIC PER FILE ---
            for i in range(len(file_records)):
                current_txn = file_records[i]
                current_bal = current_txn["Balance"]
                amount = current_txn["Raw_Amount"]
                
                if amount == 0:
                    continue

                if i < len(file_records) - 1:
                    prev_row_bal = file_records[i+1]["Balance"]
                    diff = current_bal - prev_row_bal
                    
                    if diff > 0: 
                        current_txn["Credit"] = amount
                    else:
                        current_txn["Debit"] = amount
                else:
                    # Fallback for last row using Average X position
                    all_debit_xs = [r["Txn_X"] for r in file_records if r["Debit"] is not None]
                    avg_debit_x = sum(all_debit_xs) / len(all_debit_xs) if all_debit_xs else 450
                    
                    if current_txn["Txn_X"] > avg_debit_x - 20: 
                        current_txn["Debit"] = amount
                    else:
                        current_txn["Credit"] = amount

            all_records.extend(file_records)

    return pd.DataFrame(all_records)


# ==========================================
# 3. STANBIC BANK PROCESSING LOGIC
# ==========================================
def process_stanbic_files(uploaded_files):
    """
    Processes a list of Stanbic PDF files using Table Extraction.
    Returns a combined DataFrame.
    """
    all_records = []

    for file in uploaded_files:
        with pdfplumber.open(file) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                
                for table in tables:
                    if not table: continue

                    # Check for header
                    header_found = False
                    start_row = 0
                    for i, row in enumerate(table[:5]):
                        row_str = [str(x).strip() for x in row if x]
                        if "Date" in row_str and "Description" in row_str:
                            header_found = True
                            start_row = i + 1
                            break
                    
                    if not header_found: continue

                    for row in table[start_row:]:
                        if not row: continue
                        
                        # NEW FIX: strip \n from ALL cells before processing
                        # (dates/large numbers get \n removed; descriptions get \n → space)
                        row = [clean_cell(x, is_description=(idx == 2)) for idx, x in enumerate(row)]
                        
                        if len(row) < 6: continue
                        
                        date_val = row[1]
                        desc_val = row[2]
                        
                        if not date_val and not desc_val: continue

                        # Handle multiline description
                        if not re.match(r'\d{2}/\d{2}/\d{4}', date_val):
                            if all_records and desc_val:
                                all_records[-1]['Description'] += " " + desc_val
                            continue

                        debit_val = to_float(row[3])
                        credit_val = to_float(row[4])
                        balance_val = to_float(row[5])

                        all_records.append({
                            'Value Date': date_val,
                            'Description': desc_val,
                            'Credit': credit_val if credit_val != 0 else None,
                            'Debit': debit_val if debit_val != 0 else None,
                            'Balance': balance_val
                        })

    return pd.DataFrame(all_records)


# ==========================================
# 4. NEW BANKS: FIRST ATLANTIC, OMNIBSIC, FNB, CALBANK, CBG
# ==========================================

DATE_FORMATS = ["%d-%b-%Y", "%d %b %Y", "%d %b %y", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"]


def parse_date(text):
    """Turn a bank's date string into a datetime (None if it can't be read)."""
    s = re.sub(r"\s+", " ", str(text or "")).strip().title()
    s = s.replace("- ", "-")
    for fmt in DATE_FORMATS:
        try:
            return pd.to_datetime(s, format=fmt)
        except (ValueError, TypeError):
            continue
    return None


def _norm(text):
    return re.sub(r"[^a-z]", "", str(text or "").lower())


def _find_header(table, header_map):
    """Locate the header row in a pdfplumber table and map canonical field -> column index."""
    for i, row in enumerate(table[:5]):
        cells = [_norm(c) for c in row]
        mapping = {}
        for field, aliases in header_map.items():
            for j, c in enumerate(cells):
                if c in aliases:
                    mapping[field] = j
                    break
        if "date" in mapping and "desc" in mapping and "balance" in mapping:
            return i, mapping
    return None, None


def parse_table_statement(uploaded_files, header_map, newest_first=False):
    """Generic table-based parser for statements with Date / Narration / Debit / Credit / Balance.

    header_map: canonical field -> set of normalised header labels.
      Fields: post_date (optional), date (value date), desc, debit, credit, balance.
    Rows without a readable date are treated as wrapped text and appended to the previous
    transaction (this also repairs dates split across a page break, e.g. '20-Oct-' / '2026').
    """
    all_records = []
    for file in uploaded_files:
        file_records = []
        with pdfplumber.open(file) as pdf:
            mapping = None
            for page in pdf.pages:
                for table in page.extract_tables():
                    if not table:
                        continue
                    hdr_idx, found = _find_header(table, header_map)
                    if found:
                        mapping, start = found, hdr_idx + 1
                    elif mapping and len(table[0]) > max(mapping.values()):
                        start = 0  # continuation table without repeated header
                    else:
                        continue

                    for row in table[start:]:
                        if not row:
                            continue
                        get = lambda f, desc=False: clean_cell(row[mapping[f]], is_description=desc) \
                            if f in mapping and mapping[f] < len(row) else ""
                        date_txt = get("date")
                        post_txt = get("post_date")
                        desc_txt = get("desc", desc=True)
                        if _norm(row[0]) == "total" or _norm(date_txt) == "total":
                            continue
                        key_date = post_txt or date_txt

                        if not get("balance") or not key_date:
                            # wrapped line / page-split row -> extend previous transaction
                            if file_records:
                                last = file_records[-1]
                                if parse_date(last["_date_raw"]) is None and date_txt:
                                    last["_date_raw"] += date_txt
                                if parse_date(last["_post_raw"]) is None and post_txt:
                                    last["_post_raw"] += post_txt
                                if desc_txt:
                                    last["Description"] += " " + desc_txt
                            continue

                        debit = to_float(get("debit"))
                        credit = to_float(get("credit"))
                        file_records.append({
                            "_post_raw": post_txt or date_txt,
                            "_date_raw": date_txt,
                            "Description": desc_txt,
                            "Debit": debit if debit else None,
                            "Credit": credit if credit else None,
                            "Balance": to_float(get("balance")),
                        })

        if newest_first:
            file_records.reverse()
        all_records.extend(file_records)

    return _finalise(all_records, has_post="post_date" in header_map)


def _finalise(records, has_post):
    """Convert date strings to real dates, keep chronological order, tidy columns."""
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    df["Value Date"] = df["_date_raw"].map(parse_date)
    if has_post:
        df["Posting Date"] = df["_post_raw"].map(parse_date)
        df = df.sort_values("Posting Date", kind="mergesort")
    else:
        df = df.sort_values("Value Date", kind="mergesort")
    for c in ["Value Date", "Posting Date"]:
        if c in df.columns:
            df[c] = df[c].dt.date
    df["Description"] = df["Description"].str.replace(r"\s+", " ", regex=True).str.strip()
    return df.drop(columns=[c for c in ["_date_raw", "_post_raw"] if c in df.columns]).reset_index(drop=True)


FIRST_ATLANTIC_HEADERS = {
    "post_date": {"postdate"}, "date": {"valuedate"}, "desc": {"narration"},
    "debit": {"debit"}, "credit": {"credit"}, "balance": {"balance"},
}
OMNIBSIC_HEADERS = {
    "post_date": {"transactiondate"}, "date": {"valuedate"}, "desc": {"description"},
    "debit": {"debitamount"}, "credit": {"creditamount"}, "balance": {"balance"},
}
CALBANK_HEADERS = {
    "post_date": {"bookingdate"}, "date": {"valuedate"}, "desc": {"narration"},
    "debit": {"debitamount"}, "credit": {"creditamount"}, "balance": {"balance"},
}
CBG_HEADERS = {
    "post_date": {"bookingdate"}, "date": {"valuedate"}, "desc": {"description"},
    "debit": {"debit"}, "credit": {"credit"}, "balance": {"closing", "closingbalance"},
}


def process_first_atlantic_files(files):
    return parse_table_statement(files, FIRST_ATLANTIC_HEADERS)


def process_omnibsic_files(files):
    return parse_table_statement(files, OMNIBSIC_HEADERS, newest_first=True)


def process_calbank_files(files):
    return parse_table_statement(files, CALBANK_HEADERS)


def process_cbg_files(files):
    return parse_table_statement(files, CBG_HEADERS)


def process_fnb_files(uploaded_files):
    """First National Bank 'Transactions history statement'.

    The PDF has no ruled table and no running balance, so words are bucketed into columns
    using the x-positions of the header on each page (Book date | Value date | Reference |
    Description | Debit | Credit). Statement is newest-first.
    """
    date_re = re.compile(r"^\d{2}/\d{2}/\d{4}$")
    all_records = []
    for file in uploaded_files:
        file_records = []
        with pdfplumber.open(file) as pdf:
            cols = None
            for page in pdf.pages:
                words = page.extract_words()
                lines = {}
                for w in words:
                    lines.setdefault(round(w["top"]), []).append(w)
                for y in sorted(lines):
                    line = sorted(lines[y], key=lambda w: w["x0"])
                    texts = [w["text"] for w in line]
                    joined = " ".join(texts)

                    if "Reference" in texts and "Description" in texts and "Debit" in texts:
                        pos = {w["text"]: w["x0"] for w in line}
                        cols = {
                            "value": pos.get("Value", line[0]["x0"] + 60) - 2,
                            "ref": pos["Reference"] - 2,
                            "desc": pos["Description"] - 2,
                            "debit": pos["Debit"] - 2,
                            "credit": pos.get("Credit", pos["Debit"] + 60) - 2,
                        }
                        continue
                    if cols is None or re.match(r"^Page \d+ of \d+$", joined):
                        continue

                    book, value, desc, debit, credit = [], [], [], [], []
                    for w in line:
                        x = w["x0"]
                        if x < cols["value"]:
                            book.append(w["text"])
                        elif x < cols["ref"]:
                            value.append(w["text"])
                        elif x < cols["desc"]:
                            continue  # reference column (dropped, like the other banks)
                        elif x < cols["debit"]:
                            desc.append(w["text"])
                        elif x < cols["credit"]:
                            debit.append(w["text"])
                        else:
                            credit.append(w["text"])

                    book_txt = "".join(book)
                    if date_re.match(book_txt):
                        d = to_float("".join(debit))
                        c = to_float("".join(credit))
                        file_records.append({
                            "_post_raw": book_txt,
                            "_date_raw": "".join(value) or book_txt,
                            "Description": " ".join(desc),
                            "Debit": abs(d) if d else None,
                            "Credit": abs(c) if c else None,
                        })
                    elif file_records and desc and not book and not debit and not credit:
                        file_records[-1]["Description"] += " " + " ".join(desc)
        file_records.reverse()
        all_records.extend(file_records)
    df = _finalise(all_records, has_post=True)
    if not df.empty:
        df["Balance"] = None  # FNB transaction history carries no running balance
    return df


def reconcile(df):
    """Check every running balance against previous balance + credit - debit."""
    if df.empty or "Balance" not in df.columns or df["Balance"].isna().all():
        return None
    cr = pd.to_numeric(df["Credit"], errors="coerce").fillna(0)
    dr = pd.to_numeric(df["Debit"], errors="coerce").fillna(0)
    bal = pd.to_numeric(df["Balance"], errors="coerce")
    expected = bal.shift(1) + cr - dr
    bad = ((expected - bal).abs() > 0.01) & expected.notna()
    opening = bal.iloc[0] - cr.iloc[0] + dr.iloc[0]
    return {
        "opening": opening, "closing": bal.iloc[-1],
        "credits": cr.sum(), "debits": dr.sum(), "breaks": int(bad.sum()),
        "break_rows": df.index[bad].tolist(),
    }


# ==========================================
# 5. STREAMLIT APP UI
# ==========================================

st.set_page_config(page_title="Bank Statement Converter", layout="centered")

st.title("📂 Bank Statement to Excel")
st.markdown("Upload multiple PDF statements and convert them into a single, clean Excel file.")

# 1. Select Bank
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

bank_choice = st.selectbox("Select Your Bank", list(BANKS.keys()))

# 2. Upload Files
uploaded_files = st.file_uploader(
    "Upload PDF Statements", 
    type=["pdf"], 
    accept_multiple_files=True
)

if uploaded_files:
    st.write(f"📄 **{len(uploaded_files)} files uploaded.** Ready to process.")
    
    if st.button("Convert to Excel"):
        with st.spinner(f"Processing {len(uploaded_files)} files for {bank_choice}..."):
            try:
                df = BANKS[bank_choice](uploaded_files)

                if not df.empty:
                    # Reverse Order (Oldest on Top) for parsers that read newest-first
                    if bank_choice in LEGACY_NEWEST_FIRST:
                        df = df.iloc[::-1].reset_index(drop=True)

                    check = None if bank_choice in LEGACY_NEWEST_FIRST else reconcile(df)

                    # Final Cleanup
                    df['Credit'] = df['Credit'].fillna('')
                    df['Debit'] = df['Debit'].fillna('')
                    df['Description'] = df['Description'].str.strip()
                    if 'Balance' in df.columns and df['Balance'].isna().all():
                        df = df.drop(columns=['Balance'])

                    # Ensure Columns Order
                    cols = ['Posting Date', 'Value Date', 'Description', 'Credit', 'Debit', 'Balance']
                    final_cols = [c for c in cols if c in df.columns]
                    df = df[final_cols]

                    # Show Preview
                    st.success(f"✅ Conversion Successful! {len(df)} transactions extracted.")
                    if check:
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("Opening", f"{check['opening']:,.2f}")
                        c2.metric("Total Credits", f"{check['credits']:,.2f}")
                        c3.metric("Total Debits", f"{check['debits']:,.2f}")
                        c4.metric("Closing", f"{check['closing']:,.2f}")
                        if check['breaks'] == 0:
                            st.caption("✔ Every running balance agrees with the previous balance ± the transaction.")
                        else:
                            st.warning(f"⚠️ {check['breaks']} row(s) where the running balance doesn't follow "
                                       f"from the previous one — check rows {check['break_rows'][:10]}.")
                    elif bank_choice.startswith("First National"):
                        cr = pd.to_numeric(df['Credit'], errors='coerce').sum()
                        dr = pd.to_numeric(df['Debit'], errors='coerce').sum()
                        st.caption(f"FNB statements carry no running balance. Total credits {cr:,.2f} · "
                                   f"total debits {dr:,.2f}.")
                    st.dataframe(df.head(5))

                    # Download Button
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df.to_excel(writer, index=False, sheet_name='Sheet1')
                    output.seek(0)

                    safe_name = re.sub(r"[^A-Za-z0-9]+", "_", bank_choice).strip("_")
                    file_name = f"{safe_name}_Statement_Combined.xlsx"
                    
                    st.download_button(
                        label="📥 Download Excel File",
                        data=output,
                        file_name=file_name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.warning("⚠️ No transactions found. Please check if the PDFs are correct and the right bank is selected.")

            except Exception as e:
                st.error(f"❌ An error occurred: {e}")
