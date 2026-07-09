import streamlit as st
import pandas as pd
import re
from datetime import datetime
import altair as alt
import io

# ------------------------------------------------------------
# PAGE CONFIG + HEADER
# ------------------------------------------------------------

st.set_page_config(
    page_title="🌼 WhatsApp Data Parser — Final Edition",
    layout="wide"
)

st.title("🌼 WhatsApp Data Parser — Final Edition")

st.markdown("""
<div style="
    padding: 15px;
    border-radius: 10px;
    background-color: #e8f5e9;
    border-left: 6px solid #66BB6A;
    font-size: 16px;
    margin-bottom: 20px;
">
<b>🔒 Your Data Is Safe</b><br>
This tool processes your WhatsApp messages <i>only on your device</i>.
Nothing is stored, uploaded, or shared.
</div>
""", unsafe_allow_html=True)

# ------------------------------------------------------------
# TIMESTAMP PARSING + MERGING (UNCHANGED)
# ------------------------------------------------------------

TS_PATTERN = r"^\d{1,2}/\d{1,2}/\d{2,4},\s\d{1,2}:\d{2}"

TS_FORMATS = [
    "%d/%m/%y, %H:%M",
    "%d/%m/%Y, %H:%M",
    "%d/%m/%y, %I:%M %p",
    "%d/%m/%Y, %I:%M %p",
]

def parse_ts(ts_str):
    for fmt in TS_FORMATS:
        try:
            return datetime.strptime(ts_str, fmt)
        except:
            continue
    return None

def parse_whatsapp_line(line):
    if re.match(TS_PATTERN, line):
        try:
            ts_part, rest = line.split(" - ", 1)
            sender, msg = rest.split(": ", 1)
            return ts_part.strip(), sender.strip(), msg.strip()
        except:
            return None, None, None
    return None, None, None

def merge_messages(lines):
    merged = []
    current_ts = None
    current_sender = None
    current_msg = []

    for line in lines:
        ts_str, sender, msg = parse_whatsapp_line(line)
        if ts_str and sender and msg:
            if current_ts is not None:
                merged.append((current_ts, current_sender, " ".join(current_msg)))
            current_ts = ts_str
            current_sender = sender
            current_msg = [msg]
        else:
            if current_ts is not None and line.strip():
                current_msg.append(line.strip())

    if current_ts is not None:
        merged.append((current_ts, current_sender, " ".join(current_msg)))

    return merged

# ------------------------------------------------------------
# NEW: DYNAMIC TOKEN PARSING
# ------------------------------------------------------------

def clean_token(token):
    cleaned = re.sub(r"[^\w]", "", token)
    return cleaned.strip()

def tokenize_dynamic(msg):
    raw_tokens = msg.split()
    tokens = []
    for t in raw_tokens:
        c = clean_token(t)
        if c:
            tokens.append(c)
    return tokens

def parse_people_from_message(msg):
    tokens = tokenize_dynamic(msg)
    if not tokens:
        return []

    row = {}
    for i, tok in enumerate(tokens, start=1):
        row[f"Col{i}"] = tok

    return [row]

# ------------------------------------------------------------
# STREAMLIT UI
# ------------------------------------------------------------

def main():
    uploaded = st.file_uploader("Upload WhatsApp .txt file", type=["txt"])

    if uploaded:
        raw_lines = uploaded.read().decode("utf-8", errors="ignore").split("\n")
        merged = merge_messages(raw_lines)

        rows = []
        timestamps = []

        for ts_str, sender, msg in merged:
            dt = parse_ts(ts_str)
            if not dt:
                continue
            timestamps.append(dt)

            people = parse_people_from_message(msg)
            for p in people:
                base = {
                    "Sender": sender,
                    "Timestamp": dt,
                    "Raw Message": msg,
                }
                base.update(p)
                rows.append(base)

        if rows:
            df = pd.DataFrame(rows)

            # ------------------------------------------------------------
            # DATE FILTERS (UNCHANGED)
            # ------------------------------------------------------------
            st.subheader("Select Date & Time Range")
            col1, col2 = st.columns(2)

            start_date = col1.date_input("Start Date", min(timestamps))
            start_time = col1.time_input("Start Time", min(timestamps).time())

            end_date = col2.date_input("End Date", max(timestamps))
            end_time = col2.time_input("End Time", max(timestamps).time())

            start_dt = datetime.combine(start_date, start_time)
            end_dt = datetime.combine(end_date, end_time)

            mask = (df["Timestamp"] >= start_dt) & (df["Timestamp"] <= end_dt)
            df_filtered = df[mask].copy()

            st.subheader("Parsed Data")
            st.dataframe(df_filtered, use_container_width=True)

            # ------------------------------------------------------------
            # PRELIMINARY ANALYTICS (NEW)
            # ------------------------------------------------------------

            st.subheader("Preliminary Analysis Summary")

            cat_cols = []
            for col in df_filtered.columns:
                if col.startswith("Col"):
                    uniques = df_filtered[col].dropna().unique()
                    if 2 <= len(uniques) <= 5:
                        cat_cols.append(col)
            cat_cols = cat_cols[:2]

            if cat_cols:
                chart_cols = st.columns(2)

                for idx, col in enumerate(cat_cols):
                    vc = df_filtered[col].value_counts().reset_index()
                    vc.columns = [col, "Count"]

                    chart = alt.Chart(vc).mark_bar(
                        cornerRadiusTopLeft=6,
                        cornerRadiusTopRight=6
                    ).encode(
                        x=f"{col}:N",
                        y="Count:Q",
                        color=alt.value("#81C784")
                    )

                    chart_cols[idx].altair_chart(chart, use_container_width=True)

                st.markdown(
                    f"**Detected categorical fields:** {', '.join(cat_cols)} — useful for early pattern insights."
                )
            else:
                st.info("No suitable categorical columns found for preliminary charts.")

            # ------------------------------------------------------------
            # DOWNLOAD AS EXCEL (NEW)
            # ------------------------------------------------------------

            def build_excel(df):
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine="openpyxl") as writer:
                    df.to_excel(writer, sheet_name="Parsed Data", index=False)

                    if cat_cols:
                        all_counts = []
                        for col in cat_cols:
                            vc = df[col].value_counts().reset_index()
                            vc.columns = [col, "Count"]
                            vc["Share (%)"] = (vc["Count"] / vc["Count"].sum() * 100).round(1)
                            vc["Field"] = col
                            all_counts.append(vc)

                        summary_df = pd.concat(all_counts, ignore_index=True)
                    else:
                        summary_df = pd.DataFrame({"Info": ["No categorical columns detected."]})

                    summary_df.to_excel(writer, sheet_name="Analytics Summary", index=False)

                output.seek(0)
                return output

            excel_file = build_excel(df_filtered)

            st.download_button(
                label="📥 Download Excel File",
                data=excel_file,
                file_name="whatsapp_parsed.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )


# ------------------------------------------------------------
# ENTRYPOINT
# ------------------------------------------------------------

if __name__ == "__main__":
    main()
