import streamlit as st
import pdfplumber
from fpdf import FPDF
import tempfile
import re
from datetime import datetime, timedelta
import json
import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)))

def load_json_from_folder(filename, data_dir=DATA_DIR):
    path = os.path.join(data_dir, filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Could not find '{filename}' in '{data_dir}'.")
    with open(path, "r") as f:
        return json.load(f)

TIME_SLOTS = [
    "9.00-9.55", "10.00-10.55", "11.00-11.55", "12.00-12.55",
    "1.00-1.55", "2.00-2.55", "3.00-3.55", "4.00-4.55",
]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

def load_batch_groups(path='batch_groups.json'):
    return load_json_from_folder(path)

BATCH_GROUPS = load_batch_groups()

def load_dates(path="dates.json"):
    data = load_json_from_folder(path)
    semester_start = datetime.strptime(data["semester_start"], "%Y-%m-%d").date()
    semester_end = datetime.strptime(data["semester_end"], "%Y-%m-%d").date()
    holidays = set()
    for date_str in data.get("single_days", []):
        holidays.add(datetime.strptime(date_str, "%Y-%m-%d").date())
    for rng in data.get("ranges", []):
        start = datetime.strptime(rng["start"], "%Y-%m-%d").date()
        end = datetime.strptime(rng["end"], "%Y-%m-%d").date()
        while start <= end:
            holidays.add(start)
            start += timedelta(days=1)
    return semester_start, semester_end, holidays

SEMESTER_START, SEMESTER_END, HOLIDAYS = load_dates()

def get_groups_for_batch(batch_code):
    return [group for group, members in BATCH_GROUPS.items() if batch_code in members]

def split_batches(batch_str):
    if ',' in batch_str:
        return [b.strip() for b in batch_str.split(',')]
    elif ' ' in batch_str:
        return [b.strip() for b in batch_str.split(' ')]
    return re.findall(r'[A-Z]\d+', batch_str)

def _find_day_row_bounds(page, table):
    rows = table.rows
    sample_cell = next(
        (r.cells[0] for r in rows
         if r.cells and len(r.cells) >= len(TIME_SLOTS) + 2 and r.cells[0]
         and (r.cells[0][2] - r.cells[0][0]) < 40),
        None,
    )
    if not sample_cell:
        return None
    dx0, _, dx1, _ = sample_cell
    day_rects = sorted(
        (r for r in page.rects
         if abs(r['x0'] - dx0) < 2 and abs(r['x1'] - dx1) < 2 and r['height'] > 40),
        key=lambda r: r['top'],
    )
    if len(day_rects) != len(DAYS):
        return None
    return [(day, r['top'], r['bottom']) for day, r in zip(DAYS, day_rects)]

def _find_slot_centers(table):
    best = None
    for r in table.rows:
        if not r.cells:
            continue
        nn = [c for c in r.cells if c is not None]
        if best is None or len(nn) > len(best):
            best = nn
    if not best or len(best) < 9:
        return None
    best = sorted(best, key=lambda c: c[0])
    slot_cells = best[1:]  # drop day column (leftmost)
    if len(slot_cells) == 9:
        narrowest = min(range(len(slot_cells)), key=lambda i: slot_cells[i][2]-slot_cells[i][0])
        slot_cells = slot_cells[:narrowest] + slot_cells[narrowest+1:]
    if len(slot_cells) != 8:
        return None
    return [(c[0] + c[2]) / 2 for c in slot_cells]

def _cell_slot_index(cell, centers, tolerance=60):
    if cell is None or centers is None:
        return None
    x0, x1 = cell[0], cell[2]
    # If the cell spans multiple time-slot centers (a lab block covering 2 slots),
    # anchor to the leftmost enclosed center so carry-forward can fill the rest.
    inside = [i for i, c in enumerate(centers) if x0 - 2 <= c <= x1 + 2]
    if inside:
        return inside[0]
    mid = (x0 + x1) / 2
    best_i, best_d = None, float('inf')
    for i, c in enumerate(centers):
        d = abs(mid - c)
        if d < best_d:
            best_d, best_i = d, i
    return best_i if best_d <= tolerance else None


def _extract_cell_lines(page, cell):
    chars = page.crop(cell).chars
    if not chars:
        return []
    buckets = {}
    for ch in chars:
        key = round(ch["top"] * 2) / 2  
        buckets.setdefault(key, []).append(ch)
    keys = sorted(buckets)
    merged = []
    for k in keys:
        if merged and k - merged[-1][0] < 1.0:
            merged[-1][1].extend(buckets[k])
        else:
            merged.append([k, list(buckets[k])])
    lines = []
    for _, chs in merged:
        chs.sort(key=lambda c: c["x0"])
        s = "".join(c["text"] for c in chs)
        s = re.sub(r"\s+", "", s)
        if s:
            lines.append(s)
    return lines

def extract_timetable(pdf_file, batch_code):
    timetable = {day: [] for day in DAYS}
    group_codes = get_groups_for_batch(batch_code)
    collected = {}

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            for table in page.find_tables():
                day_bounds = _find_day_row_bounds(page, table)
                if day_bounds is None:
                    continue
                centers = _find_slot_centers(table)
                if centers is None:
                    continue

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
                    for col_idx, cell in enumerate(row.cells):
                        if cell is None or col_idx == 0:
                            continue  # skip day column
                        slot_idx = _cell_slot_index(cell, centers)
                        if slot_idx is None:
                            continue
                        lines = _extract_cell_lines(page, cell)
                        if not lines:
                            continue
                        key = (day, TIME_SLOTS[slot_idx])
                        collected.setdefault(key, [])
                        for line in lines:
                            if collected[key] and collected[key][-1].endswith('-'):
                                collected[key][-1] += line
                            elif line not in collected[key]:
                                collected[key].append(line)

    def is_lab_entry(entry):
        if not entry:
            return False
        parts = entry.split('-')
        return len(parts) > 1 and parts[1].strip().upper().startswith('P')

    for day in DAYS:
        day_slots = []
        for slot in TIME_SLOTS:
            candidates = collected.get((day, slot), [])
            match = None
            for line in candidates:
                batch_part = line.split('-')[0].strip()
                batches = split_batches(batch_part)
                if batch_code == batch_part or batch_code in batches or batch_part in group_codes:
                    match = line
                    break
            day_slots.append([slot, match])

        original = [match for _, match in day_slots]
        for i in range(len(day_slots) - 1):
            match = original[i]
            next_slot, next_match = day_slots[i + 1]
            if is_lab_entry(match) and next_match is None and next_slot != "1.00-1.55":
                day_slots[i + 1][1] = match

        timetable[day] = [tuple(x) for x in day_slots]

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
            if slot == "1.00-1.55":
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
until_str = SEMESTER_END.strftime("%Y%m%dT235959")

def generate_ics(timetable):
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".ics")
    with open(tmp_file.name, "w") as icsfile:
        icsfile.write("BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//My Timetable//EN\n")
        for day, slots in timetable.items():
            day_index = DAY_TO_INDEX[day]
            event_date = START_DATE + timedelta(days=day_index)
            blocks = []
            for time_range, class_info in slots:
                if class_info is None:
                    continue
                if blocks and blocks[-1][1] == class_info:
                    blocks[-1] = (blocks[-1][0], class_info, time_range)
                else:
                    blocks.append((time_range, class_info, time_range))
            for start_range, class_info, end_range in blocks:
                start_str = start_range.split('-')[0].replace('.', ':')
                end_str = end_range.split('-')[1].replace('.', ':')
                start_time = datetime.strptime(start_str, "%H:%M")
                end_time = datetime.strptime(end_str, "%H:%M")
                if 1 <= start_time.hour <= 4:
                    start_time = start_time.replace(hour=start_time.hour + 12)
                if 1 <= end_time.hour <= 4:
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
                        ex_dt = datetime.combine(holiday, dtstart.time())
                        ex_str = ex_dt.strftime("%Y%m%dT%H%M%S")
                        icsfile.write(f"EXDATE:{ex_str}\n")
                icsfile.write("END:VEVENT\n")
        icsfile.write("END:VCALENDAR\n")
    return tmp_file.name
