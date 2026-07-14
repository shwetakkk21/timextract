import streamlit as st
import pdfplumber
from fpdf import FPDF
import tempfile
import re
from datetime import datetime,timedelta
import json
import requests

def get_req(key):
    return st.secrets[key]

GITHUB_TOKEN=get_req("GITHUB_TOKEN")
REPO_NAME=get_req("REPO")

if not REPO_NAME or not GITHUB_TOKEN:
    raise Exception("Environment not configured properly")

HEADERS={
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": f"application/vnd.github.v3.raw"
}

def load_json_from_github(path,repo=REPO_NAME):
    url=f"https://api.github.com/repos/{repo}/contents/{path}"
    r=requests.get(url,headers=HEADERS)
    if r.status_code!=200:
        raise Exception(f"Github API failed: {r.status_code} - {r.text}")
    return json.loads(r.text)

TIME_SLOTS = [
    "9.00-9.55", "10.00-10.55", "11.00-11.55", "12.00-12.55",
    "1.00-1.55", "2.00-2.55", "3.00-3.55", "4.00-4.55"
]

DAYS= ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

def load_batch_groups(path='batch_groups.json'):
    return load_json_from_github(path)
    
BATCH_GROUPS = load_batch_groups()

def load_dates(path="dates.json"):
    data=load_json_from_github(path)
    semester_start = datetime.strptime(data["semester_start"], "%Y-%m-%d").date()
    semester_end = datetime.strptime(data["semester_end"], "%Y-%m-%d").date()
    #single days
    holidays=set()
    for date_str in data.get("single_days",[]):
        holidays.add(datetime.strptime(date_str,"%Y-%m-%d").date())
    #ranges
    for rng in data.get("ranges",[]):
        start=datetime.strptime(rng["start"],"%Y-%m-%d").date()
        end=datetime.strptime(rng["end"],"%Y-%m-%d").date()
        while(start<=end):
            holidays.add(start)
            start+=timedelta(days=1)
    return semester_start, semester_end, holidays

SEMESTER_START, SEMESTER_END, HOLIDAYS = load_dates()
#print(HOLIDAYS)

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

def _find_day_row_bounds(page, table):
    """
    In this timetable format the day name (Mon/Tue/...) sits in a cell that's
    merged/spans the entire day's block of rows, so its text only shows up on
    whichever physical row happens to be near the vertical center of that
    merge -- it is NOT reliably the first row of the day's block.

    Instead we find the actual merged rectangle behind the day-name column
    (it's taller than a normal single-slot row) and use its exact top/bottom
    to figure out which physical grid rows belong to which day.

    Returns a list of (day, top, bottom) tuples in top-to-bottom order, or
    None if this table doesn't look like the weekly day/time grid (e.g. a
    legend/faculty table elsewhere in the PDF).
    """
    rows = table.rows
    # find a full-width data row to read off the (narrow) day-label column's x-range
    sample_cell = next(
        (r.cells[0] for r in rows
         if r.cells and len(r.cells) >= len(TIME_SLOTS) + 2 and r.cells[0]
         and (r.cells[0][2] - r.cells[0][0]) < 40),
        None
    )
    if not sample_cell:
        return None
    dx0, _, dx1, _ = sample_cell
    day_rects = sorted(
        (r for r in page.rects
         if abs(r['x0'] - dx0) < 2 and abs(r['x1'] - dx1) < 2 and r['height'] > 40),
        key=lambda r: r['top']
    )
    if len(day_rects) != len(DAYS):
        return None
    return [(day, r['top'], r['bottom']) for day, r in zip(DAYS, day_rects)]


# Maps physical table-column index -> index into TIME_SLOTS.
# Column 0 is the day-name column; column 5 is an empty spacer column with
# no real content in this timetable layout (between 12.00-12.55 and 1.00-1.55).
_COLUMN_TO_SLOT = {1: 0, 2: 1, 3: 2, 4: 3, 6: 4, 7: 5, 8: 6, 9: 7}


def extract_timetable(pdf_file, batch_code):
    """
    pdf_file: path or file-like object pointing to the timetable PDF.

    The PDF's table has a variable number of physical rows per day (rows are
    driven by real cell geometry, not a fixed 2-rows-per-day pattern like the
    old docx version), and multi-line class entries can wrap across two
    physical rows. Both are handled below.
    """
    timetable = {day: [] for day in DAYS}
    group_code = get_group_for_batch(batch_code)

    # collected[(day, slot)] = ordered list of distinct class-entry strings
    collected = {}

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            for table in page.find_tables():
                day_bounds = _find_day_row_bounds(page, table)
                if day_bounds is None:
                    continue  # not the weekly grid table, skip (e.g. legend page)

                def find_day(mid_y):
                    for day, top, bottom in day_bounds:
                        if top - 1 <= mid_y <= bottom + 1:
                            return day
                    return None

                for row in table.rows:
                    if not row.cells or not row.bbox:
                        continue
                    mid_y = (row.bbox[1] + row.bbox[3]) / 2
                    day = find_day(mid_y)
                    if day is None:
                        continue
                    for col_idx, slot_idx in _COLUMN_TO_SLOT.items():
                        if col_idx >= len(row.cells) or row.cells[col_idx] is None:
                            continue
                        text = (page.crop(row.cells[col_idx]).extract_text() or "").strip()
                        if not text:
                            continue
                        key = (day, TIME_SLOTS[slot_idx])
                        collected.setdefault(key, [])
                        for line in text.split('\n'):
                            # collapse spurious kerning-induced spaces (real
                            # entries never contain intentional spaces)
                            line = re.sub(r'\s+', '', line.strip())
                            if not line:
                                continue
                            # an entry ending in '-' means it wrapped onto the
                            # next physical row -- stitch it back together
                            if collected[key] and collected[key][-1].endswith('-'):
                                collected[key][-1] += line
                            elif line not in collected[key]:
                                collected[key].append(line)

    for day in DAYS:
        for slot in TIME_SLOTS:
            candidates = collected.get((day, slot), [])
            match = None
            for line in candidates:
                batch_part = line.split('-')[0].strip()
                batches = split_batches(batch_part)
                if batch_code in batches or (group_code and batch_part == group_code):
                    match = line
                    break
            timetable[day].append((slot, match))

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

START_DATE = datetime.combine(SEMESTER_START, datetime.min.time())
until_str= SEMESTER_END.strftime("%Y%m%dT235959")

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
                icsfile.write(f"RRULE:FREQ=WEEKLY;UNTIL={until_str}\n")

                for holiday in HOLIDAYS:
                    if holiday.weekday() == dtstart.weekday():
                        ex_dt=datetime.combine(holiday, dtstart.time())
                        ex_str=ex_dt.strftime("%Y%m%dT%H%M%S")
                        # print(f"Adding EXDATE for {class_info} on {ex_dt} because {holiday} matches weekday {dtstart.strftime('%A')}")
                        icsfile.write(f"EXDATE:{ex_str}\n")
                icsfile.write("END:VEVENT\n")
        icsfile.write("END:VCALENDAR\n")
    return tmp_file.name