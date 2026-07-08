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
# TIMESTAMP PARSING + MERGING
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
# NORMALIZATION + TOKEN RULES
# ------------------------------------------------------------

PREF_WORDS = {"VEG", "NONVEG", "VEGAN", "VEGETARIAN", "D", "ND"}
NOTICE_WORDS = {"MESSAGE", "WAS", "DELETED", "EDITED", "MEDIA", "OMITTED"}

def normalize_text(text):
    return text.upper().strip()

def tokenize(text):
    return [t for t in text.split() if t]

def is_alpha_word(token):
    return re.fullmatch(r"[A-Z]+", token) is not None

def extract_age_from_token(token):
    m = re.search(r"\d+", token)
    if m:
        num = int(m.group())
        if 1 <= num <= 120:
            return num
    return None

def is_pref_token(token):
    if token in PREF_WORDS:
        return True
    return bool(re.search(r"[A-Z]", token) and re.search(r"[-_,;:]", token))

def is_blood_group(token):
    return re.fullmatch(r"(A|B|AB|O)[+-]", token) is not None

def is_notice(msg_norm):
    return msg_norm.startswith(("OMITTED", "MEDIA", "THIS MESSAGE WAS DELETED", "EDITED"))

# ------------------------------------------------------------
# PERSON PARSING (FINAL LOGIC)
# ------------------------------------------------------------

def parse_people_from_message(msg):
    msg_norm = normalize_text(msg)
    if is_notice(msg_norm):
        return []

    tokens = tokenize(msg_norm)

    people = []
    current = {
        "name_tokens": [],
        "age": None,
        "pref_tokens": [],
        "other_tokens": []
    }

    skip_total_number = False

    def finalize_current():
        if current["name_tokens"]:
            people.append({
                "Name": " ".join(current["name_tokens"]),
                "Age": current["age"],
                "Preference": " ".join(current["pref_tokens"]) if current["pref_tokens"] else None,
                "Other": " ".join(current["other_tokens"]) if current["other_tokens"] else None
            })

    i = 0
    while i < len(tokens):
        tok = tokens[i]

        # SYSTEM NOTICE WORDS INSIDE MESSAGE
        if tok in NOTICE_WORDS:
            current["other_tokens"].append(tok)
            i += 1
            continue

        # TOTAL handling
        if tok.startswith("TOTAL"):
            skip_total_number = True
            i += 1
            continue

        # AGE detection (even inside punctuation)
        age_val = extract_age_from_token(tok)
        if age_val is not None:
            if skip_total_number:
                skip_total_number = False
                i += 1
                continue
            if current["age"] is None:
                current["age"] = age_val
            else:
                current["other_tokens"].append(tok)
            i += 1
            continue

        # SINGLE LETTER AFTER AGE/PREF → preference, not name
        if len(tok) == 1 and (current["age"] is not None or current["pref_tokens"]):
            current["pref_tokens"].append(tok)
            i += 1
            continue

        # NAME DETECTION (supports middle initials)
        if is_alpha_word(tok) and tok not in PREF_WORDS:

            # STOP name chain if age or preference already found
            if current["age"] is not None or current["pref_tokens"]:
                finalize_current()
                current = {
                    "name_tokens": [tok],
                    "age": None,
                    "pref_tokens": [],
                    "other_tokens": []
                }
                i += 1
                continue

            # Single-letter middle initial allowed ONLY inside name chain
            if len(tok) == 1:
                if current["name_tokens"]:
                    current["name_tokens"].append(tok)
                else:
                    current["other_tokens"].append(tok)
                i += 1
                continue

            # Normal name word
            current["name_tokens"].append(tok)
            i += 1
            continue

        # PREFERENCE
        if is_pref_token(tok):
            current["pref_tokens"].append(tok)
            i += 1
            continue

        # BLOOD GROUP → Other
        if is_blood_group(tok):
            current["other_tokens"].append(tok)
            i += 1
            continue

        # ANYTHING ELSE → Other
        current["other_tokens"].append(tok)
        i += 1

    finalize_current()
    return people

# ------------------------------------------------------------
# AGE GROUP
# ------------------------------------------------------------

def age_group(age):
    if age is None:
        return None
    if age <= 12:
        return "0–12"
    if age <= 19:
        return "13–19"
    if age <= 40:
        return "20–40"
    if age <= 60:
        return "41–60"
    return "60+"

# ------------------------------------------------------------
# STREAMLIT UI
# ------------------------------------------------------------

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
            rows.append({
                "Sender": sender,
                "Timestamp": dt,
                "Raw Message": msg,
                "Name": p["Name"],
                "Age": p["Age"],
                "Preference": p["Preference"],
                "Other": p["Other"]
            })

    if rows:
        df = pd.DataFrame(rows)

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

        # --- DOWNLOAD AS EXCEL ---
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df_filtered.to_excel(writer, index=False, sheet_name="Parsed Data")
        
        st.download_button(
            label="📥 Download as Excel",
            data=output.getvalue(),
            file_name="parsed_whatsapp_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        df_filtered["Age Group"] = df_filtered["Age"].apply(age_group)

        st.subheader("Age Group Summary")
        age_counts = df_filtered["Age Group"].value_counts().reset_index()
        age_counts.columns = ["Age Group", "Count"]

        chart = alt.Chart(age_counts).mark_bar(
            cornerRadiusTopLeft=6,
            cornerRadiusTopRight=6
        ).encode(
            x="Age Group:N",
            y="Count:Q",
            color=alt.value("#A5D6A7")
        )

        st.altair_chart(chart, use_container_width=True)
