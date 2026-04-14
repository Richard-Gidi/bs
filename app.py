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
# 4. STREAMLIT APP UI
# ==========================================

st.set_page_config(page_title="Bank Statement Converter", layout="centered")

st.title("📂 Bank Statement to Excel")
st.markdown("Upload multiple PDF statements and convert them into a single, clean Excel file.")

# 1. Select Bank
bank_choice = st.selectbox("Select Your Bank", ["GCB Bank", "Stanbic Bank"])

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
                # Process based on selection
                if bank_choice == "GCB Bank":
                    df = process_gcb_files(uploaded_files)
                else:
                    df = process_stanbic_files(uploaded_files)

                if not df.empty:
                    # Final Cleanup
                    df['Credit'] = df['Credit'].fillna('')
                    df['Debit'] = df['Debit'].fillna('')
                    df['Description'] = df['Description'].str.strip()
                    
                    # Ensure Columns Order
                    cols = ['Value Date', 'Description', 'Credit', 'Debit', 'Balance']
                    # Only keep columns that actually exist (Stanbic/GCB might differ slightly internally)
                    final_cols = [c for c in cols if c in df.columns]
                    df = df[final_cols]

                    # Reverse Order (Oldest on Top) - As requested previously
                    df = df.iloc[::-1]

                    # Show Preview
                    st.success("✅ Conversion Successful!")
                    st.dataframe(df.head(5))

                    # Download Button
                    output = io.BytesIO()
                    with pd.ExcelWriter(output, engine='openpyxl') as writer:
                        df.to_excel(writer, index=False, sheet_name='Sheet1')
                    output.seek(0)

                    file_name = f"{bank_choice.replace(' ', '_')}_Statement_Combined.xlsx"
                    
                    st.download_button(
                        label="📥 Download Excel File",
                        data=output,
                        file_name=file_name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.warning("⚠️ No transactions found. Please check if the PDFs are correct.")

            except Exception as e:
                st.error(f"❌ An error occurred: {e}")