# 🗓 Personalized Timetable Extractor

A Python script that extracts and filters timetable entries from .docx files based on user-specified batch codes and outputs a clean, filtered version. Optionally exports the result as a PDF for easy sharing or printing and a .ics file to import into Google Calnedar or iCal.

---

## Features

- Parses .docx timetable documents
- Filters based on batch codes
- Exports filtered timetable to a formatted PDF
- .ics file to import directly into your calendar
- Simple to customize for your own batch or class group

---

## Demo



---

## Tech Stack

- Python 3.x
- [streamlit](https://pypi.org/project/streamlit/) – For building the web application interface
- [python-docx](https://pypi.org/project/python-docx/) – For parsing and processing .docx timetable files
- [fpdf](https://pypi.org/project/fpdf/) – For generating formatted PDF files
- [requests](https://pypi.org/project/requests/) – For making HTTP requests to GitHub API and loading remote JSON
- json, datetime, re, tempfile – Python standard libraries for data handling, date calculations, regex, and temporary file creation

---

## Getting Started

### 1. Clone the Repo

```bash
git clone https://github.com/your-username/timetable-extractor.git
cd timetable-extractor
```
### 2. Install Dependencies

```bash
pip install streamlit python-docx fpdf
```
### 3. Run the Script

```bash
streamlit run extractor.py
```

---

## Customization

- You can change the batch code or logic in the script
- Update PDF formatting (fonts,layout) inside the FPDF section
- Customize semester dates, holiday dates and event repetition rules

---

## Contributing

Pull requests are welcome! If you have any ideas for new features or improvements, feel free to fork this repo and submit a PR.
