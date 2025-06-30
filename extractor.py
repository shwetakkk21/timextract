import streamlit as st
from docx import Document
from fpdf import FPDF
import tempfile
import re
from datetime import datetime,timedelta

TIME_SLOTS = [
    "9.00-9.55", "10.00-10.55", "11.00-11.55", "12.00-12.55",
    "1.00-1.55", "2.00-2.55", "3.00-3.55", "4.00-4.55"
]

BATCH_GROUPS = {
    "BX": ["B1", "B2", "B3", "B4"],
    "BY": ["B5", "B6", "B7", "B8"],
    "BZ": ["B9", "B10", "B11", "B12"],
    "BX1": ["B13", "B14", "A1"]
}

DAYS= ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

# modify holiday, break and test days here

HOLIDAYS=[
    datetime(2025,7,21).date(),
    datetime(2025,8,9).date(),
    datetime(2025,8,15).date(),
    datetime(2025,8,16).date(),
    datetime(2025,10,2).date(),
]

midsem_start=datetime(2025,10,18).date()
midsem_end=datetime(2025,10,25).date()

t1_start=datetime(2025,9,1).date()
t1_end=datetime(2025,9,6).date()

t2_start=datetime(2025,10,13).date()
t2_end=datetime(2025,10,17).date()

def add_holidays(HOLIDAYS,start_date,end_date):
    delta= timedelta(days=1)
    current=start_date
    while current <= end_date:
        HOLIDAYS.append(current)
        current += delta

add_holidays(HOLIDAYS, midsem_start, midsem_end)
add_holidays(HOLIDAYS, t1_start, t1_end)
add_holidays(HOLIDAYS, t2_start, t2_end)

def get_group_for_batch(batch_code):
    for group, members in BATCH_GROUPS.items():
        if batch_code in members:
            return group
    return None

def split_batches(batch_str):
    #if comma-separated, use that
    if ',' in batch_str:
        return [b.strip() for b in batch_str.split(',')]
    #if contains space, split by space
    elif ' ' in batch_str:
        return [b.strip() for b in batch_str.split(' ')]
    #else, split by capital letter + number pattern (e.g., B7B8 -> [B7,B8])
    return re.findall(r'[A-Z]\d+', batch_str)

def extract_timetable(docx_file, batch_code):
    doc = Document(docx_file)
    timetable = {day: [] for day in DAYS}
    group_code = get_group_for_batch(batch_code)

    for table in doc.tables:
        rows = table.rows
        i = 0
        while i < len(rows) - 1:
            row1 = rows[i].cells
            row2 = rows[i + 1].cells
            day = row1[0].text.strip()[:3]
            if day not in timetable:
                i += 1
                continue
            for col in range(1, min(len(TIME_SLOTS) + 1, len(row1))):
                slot = TIME_SLOTS[col - 1]
                entry1 = row1[col].text.strip()
                entry2 = row2[col].text.strip()
                added = False
                for line in entry1.split('\n') + entry2.split('\n'):
                    if not line:
                        continue
                    batch_part = line.split('-')[0].strip()
                    batches = split_batches(batch_part)

                    if batch_code in batches or (group_code and batch_part == group_code):
                        timetable[day].append((slot, line))
                        added = True
                        break
                if not added:
                    timetable[day].append((slot, None))
            i += 2
    return timetable

def generate_pdf(timetable, batch_code):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.set_title(f"{batch_code} Timetable")
    pdf.cell(200, 10, txt=f"Timetable for Batch: {batch_code}", ln=True, align="C")
    pdf.ln(10)
    for day in timetable:
        pdf.set_font("Arial", "B", 12)
        pdf.cell(200, 10, txt=day, ln=True)
        pdf.set_font("Arial", size=12)
        for slot, entry in timetable[day]:  
            if(slot=="1.00-1.55"):
                line = f"{slot}: Lunch"
            else:
                line = f"{slot}: {entry if entry else 'No class'}"
            pdf.cell(200, 8, txt=line, ln=True)
        pdf.ln(5)
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(tmp_file.name)
    return tmp_file.name

DAY_TO_INDEX = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5}
START_DATE = datetime(2025, 7, 21)  #first day of the semester

def generate_ics(timetable):
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".ics")
    with open(tmp_file.name, "w") as icsfile:
        icsfile.write("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//My Timetable//EN\n")
        for day, slots in timetable.items():
            day_index = DAY_TO_INDEX[day]
            event_date = START_DATE + timedelta(days=day_index)
            for time_range, class_info in slots:
                if class_info is None:
                    continue
                start_str, end_str = [t.replace('.', ':') for t in time_range.split('-')]
                start_time = datetime.strptime(start_str, "%H:%M")
                end_time = datetime.strptime(end_str, "%H:%M")

                # adjust for PM slots
                if 1 <= start_time.hour <= 4:
                    start_time = start_time.replace(hour=start_time.hour + 12)
                    end_time = end_time.replace(hour=end_time.hour + 12)

                dtstart = event_date.replace(hour=start_time.hour, minute=start_time.minute)
                dtend = event_date.replace(hour=end_time.hour, minute=end_time.minute)
                dtstart_str = dtstart.strftime("%Y%m%dT%H%M%S")
                dtend_str = dtend.strftime("%Y%m%dT%H%M%S")

                icsfile.write("BEGIN:VEVENT\n")
                icsfile.write(f"SUMMARY:{class_info}\n")
                icsfile.write(f"DTSTART:{dtstart_str}\n")
                icsfile.write(f"DTEND:{dtend_str}\n")
                icsfile.write(f"RRULE:FREQ=WEEKLY;UNTIL=20251122T235959\n")

                for holiday in HOLIDAYS:
                    if holiday.weekday() == dtstart.weekday():
                        ex_dt=datetime.combine(holiday, dtstart.time())
                        ex_str=ex_dt.strftime("%Y%m%dT%H%M%S")
                        icsfile.write(f"EXDATE:{ex_str}\n")
                icsfile.write("END:VEVENT\n")
        icsfile.write("END:VCALENDAR\n")
    return tmp_file.name


# ---------- Streamlit UI ----------
st.set_page_config(page_title="Timextract", layout="centered")
st.title("Personalized Timetable Extractor")

uploaded_file = st.file_uploader("Upload your master timetable (.docx)", type="docx")
st.write("Please enter your batch code as B1 or B9 and not BX or BZ.")
# st.write("A1 batch is requested to enter as 2A1.")
batch_input = st.text_input("Enter your batch code (e.g., B4, B9, B13)")

with st.sidebar:
    st.markdown("### About")
    st.write("""This application extracts your personalized timetable from college master timetables in .docx format.    
    Built by **Shweta Kumari**, 2025.  
    If you find any discrepancies or have suggestions, please reach out!  
    [GitHub](https://github.com/shwetakkk21)
    """)

if uploaded_file and batch_input:
    with st.spinner("Extracting your timetable..."):
        timetable = extract_timetable(uploaded_file, batch_input.upper())
        st.success("✅ Timetable extracted!")

        for day, entries in timetable.items():
            st.markdown(f"### {day}")
            for slot, entry in entries:
                if(slot=="1.00-1.55"):
                    st.write(f"{slot}: {'Lunch'}")
                else:
                    st.write(f"{slot}: {entry if entry else 'No class'}")

        pdf_path = generate_pdf(timetable, batch_input.upper())
        with open(pdf_path, "rb") as f:
            st.download_button("Download Timetable PDF", f, file_name=f"{batch_input.capitalize()} Timetable.pdf")
        ics_path = generate_ics(timetable)
        with open(ics_path, "rb") as f:
            st.download_button("Download Timetable .ics", f, file_name=f"{batch_input.capitalize()} Timetable.ics")
        st.write('Import downloaded .ics file to your Google Calendar or iCal')


st.markdown("""
<style>
.footer{
    width: 100%;
    color: #888;
    text-align: center;
    font-size: small;

    }
</style>
<hr>
<div class="footer">
© 2025 Timextract. All Rights Reserved.
By using this application, you agree not to reproduce, distribute, or exploit any part of this service without explicit written permission.
</div>
""",unsafe_allow_html=True)