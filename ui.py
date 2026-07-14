import extractor
import streamlit as st

st.set_page_config(page_title="Timextract", layout="centered")
st.title("Personalized Timetable Extractor")

uploaded_file = st.file_uploader("Upload your official master timetable (.pdf)", type="pdf")
st.write("Please enter your batch code as B1 or B9 and not BX or BZ.")
# st.write("A1 batch is requested to enter as 2A1.")
batch_input = st.text_input("Enter your batch code (e.g., B4, B9, B21)")

with st.sidebar:
    st.markdown("### About")
    st.write("""This application extracts your personalized timetable from college master timetables in .pdf format.      
    If you find any discrepancies or have suggestions, please reach out!  
    [GitHub](https://github.com/shwetakkk21)
    """)

if uploaded_file and batch_input:
    with st.spinner("Extracting your timetable..."):
        timetable = extractor.extract_timetable(uploaded_file, batch_input.upper())
        st.success("Timetable extracted!")

        for day, entries in timetable.items():
            st.markdown(f"### {day}")
            for slot, entry in entries:
                if(slot=="1.00-1.55"):
                    st.write(f"{slot}: {'Lunch'}")
                else:
                    st.write(f"{slot}: {entry if entry else 'No class'}")

        pdf_path = extractor.generate_pdf(timetable, batch_input.upper())
        with open(pdf_path, "rb") as f:
            st.download_button("Download Timetable PDF", f, file_name=f"{batch_input.capitalize()} Timetable.pdf")
        ics_path = extractor.generate_ics(timetable)
        with open(ics_path, "rb") as f:
            st.download_button("Download Timetable .ics", f, file_name=f"{batch_input.capitalize()} Timetable.ics")
        st.write('Import downloaded .ics file to your Google Calendar or iCal (Web only).')