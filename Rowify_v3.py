import re
import io
from datetime import datetime

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

# -----------------------------
# Helpers: WhatsApp parsing
# -----------------------------

TIMESTAMP_PATTERN = r"^(\d{1,2}/\d{1,2}/\d{2,4}), (\d{1,2}:\d{2} (?:AM|PM)) - "

def parse_whatsapp_line(line):
    """
    Parse a single WhatsApp line into timestamp, sender, message.
    Assumes standard export format: "DD/MM/YY, HH:MM - Sender: Message"
    """
    m = re.match(TIMESTAMP_PATTERN, line)
    if not m:
        return None, None, line.strip()

    ts_str = m.group(0)[:-3]  # "DD/MM/YY, HH:MM AM/PM -"
    rest = line[len(m.group(0)):]
    # Split sender and message
    if ": " in rest:
        sender, message = rest.split(": ", 1)
    else:
        sender, message = None, rest

    # Try to parse timestamp
    try:
        timestamp = datetime.strptime(ts_str.replace(" -", ""), "%d/%m/%y, %I:%M %p")
    except Exception:
        timestamp = ts_str.replace(" -", "")

    return timestamp, sender, message.strip()


# -----------------------------
# Helpers: Token parsing engine
# -----------------------------

def clean_token(token):
    # Remove punctuation, keep letters/digits/underscore
    cleaned = re.sub(r"[^\w]", "", token)
    return cleaned.strip()

def tokenize_message(message):
    """
    Split message into tokens, clean punctuation, drop empties.
    """
    raw_tokens = message.split()
    tokens = []
    for t in raw_tokens:
        c = clean_token(t)
        if c:
            tokens.append(c)
    return tokens

def build_dynamic_columns(tokens):
    """
    Map tokens to dynamic columns: Col1, Col2, ...
    Each token becomes its own column (fully dynamic).
    """
    data = {}
    for i, tok in enumerate(tokens, start=1):
        col_name = f"Col{i}"
        data[col_name] = tok
    return data

def parse_message_row(timestamp, sender, message):
    """
    Build a single parsed row dict:
    Sender, Timestamp, Raw Message, then dynamic Col1..ColN.
    """
    tokens = tokenize_message(message)
    cols = build_dynamic_columns(tokens)

    row = {
        "Sender": sender,
        "Timestamp": timestamp,
        "Raw Message": message,
    }
    row.update(cols)
    return row


# -----------------------------
# Analytics engine
# -----------------------------

def is_numeric_series(s):
    try:
        pd.to_numeric(s.dropna())
        return True
    except Exception:
        return False

def pick_categorical_columns(df, max_charts=3, min_unique=2, max_unique=5):
    """
    Pick up to max_charts columns that:
    - are non-numeric
    - have unique values between min_unique and max_unique
    """
    candidates = []
    for col in df.columns:
        if col in ["Sender", "Timestamp", "Raw Message"]:
            continue
        series = df[col].dropna().astype(str)
        if series.empty:
            continue
        if is_numeric_series(series):
            continue
        uniques = series.unique()
        if min_unique <= len(uniques) <= max_unique:
            candidates.append(col)
    return candidates[:max_charts]

def build_analytics_summary(df, cat_cols):
    """
    Create a small textual summary of what was identified.
    """
    lines = []
    if not cat_cols:
        return "No suitable categorical columns (with 2–5 unique values) were detected for analytics."

    lines.append(f"Detected {len(cat_cols)} categorical field(s): " + ", ".join(cat_cols) + ".")
    for col in cat_cols:
        series = df[col].dropna().astype(str)
        vc = series.value_counts()
        total = vc.sum()
        top = vc.index[0]
        pct = round(vc.iloc[0] / total * 100, 1)
        lines.append(f"- In **{col}**, '{top}' appears most often ({vc.iloc[0]} rows, {pct}%).")
    return "\n".join(lines)


# -----------------------------
# Excel export
# -----------------------------

def build_excel_file(parsed_df, cat_cols):
    """
    Create an Excel file in memory with:
    - Sheet1: Parsed data
    - Sheet2: Analytics summary
    - Sheet3: Category counts (tables)
    """
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # Sheet 1: Parsed data
        parsed_df.to_excel(writer, sheet_name="Parsed Data", index=False)

        # Sheet 2: Analytics summary
        summary_rows = []
        if cat_cols:
            for col in cat_cols:
                series = parsed_df[col].dropna().astype(str)
                vc = series.value_counts().reset_index()
                vc.columns = [col, "Count"]
                vc["Share (%)"] = (vc["Count"] / vc["Count"].sum() * 100).round(1)
                vc["Field"] = col
                summary_rows.append(vc)
            summary_df = pd.concat(summary_rows, ignore_index=True)
        else:
            summary_df = pd.DataFrame({"Info": ["No categorical columns detected."]})

        summary_df.to_excel(writer, sheet_name="Analytics Summary", index=False)

        # Sheet 3: Raw counts per categorical column (optional)
        if cat_cols:
            counts_sheets = []
            for col in cat_cols:
                series = parsed_df[col].dropna().astype(str)
                vc = series.value_counts().reset_index()
                vc.columns = [col, "Count"]
                counts_sheets.append((col, vc))
            # Put them one after another in a single sheet
            start_row = 0
            sheet_name = "Category Counts"
            for col, vc in counts_sheets:
                vc.to_excel(writer, sheet_name=sheet_name, index=False, startrow=start_row)
                start_row += len(vc) + 2

    output.seek(0)
    return output


# -----------------------------
# Streamlit UI
# -----------------------------

def main():
    st.set_page_config(page_title="Rowify", layout="wide")
    st.title("Rowify – WhatsApp Row Parser")

    st.markdown("Upload a WhatsApp chat `.txt` export and I’ll parse it into dynamic columns, "
                "then show a small analytics summary and let you download everything as Excel.")

    uploaded_file = st.file_uploader("Upload WhatsApp chat (.txt)", type=["txt"])

    if not uploaded_file:
        st.info("Please upload a WhatsApp chat export to begin.")
        return

    # Read lines
    text = uploaded_file.read().decode("utf-8", errors="ignore")
    lines = text.splitlines()

    parsed_rows = []
    for line in lines:
        ts, sender, msg = parse_whatsapp_line(line)
        # Skip system messages or empty
        if msg is None or msg.strip() == "":
            continue
        row = parse_message_row(ts, sender, msg)
        parsed_rows.append(row)

    if not parsed_rows:
        st.warning("No parsable messages were found. Please check the format of your WhatsApp export.")
        return

    df = pd.DataFrame(parsed_rows)

    st.subheader("Parsed Table")
    st.dataframe(df, use_container_width=True)

    # Analytics
    st.subheader("Analytics")
    cat_cols = pick_categorical_columns(df)
    summary_text = build_analytics_summary(df, cat_cols)
    st.markdown(summary_text)

    # Charts
    if cat_cols:
        st.markdown("### Charts")
        for col in cat_cols:
            series = df[col].dropna().astype(str)
            vc = series.value_counts()
            fig, ax = plt.subplots()
            vc.plot(kind="bar", ax=ax)
            ax.set_title(f"Distribution of {col}")
            ax.set_xlabel(col)
            ax.set_ylabel("Count")
            st.pyplot(fig)
    else:
        st.info("No charts generated because no suitable categorical columns were found.")

    # Excel download
    st.subheader("Download as Excel")
    excel_bytes = build_excel_file(df, cat_cols)
    st.download_button(
        label="Download Excel file",
        data=excel_bytes,
        file_name="rowify_output.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    main()
