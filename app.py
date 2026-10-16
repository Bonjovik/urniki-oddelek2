import calendar
from datetime import date
import holidays
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KI-Dienstplan PRO 11.0", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 11.0 - Ultimate Soft-Constraints)")
st.markdown(
    "Das System findet **immer** eine Lösung! Wenn Personal fehlt, wird der Tag in der "
    "untersten Zeile (**🚨 FEHLT**) rot markiert, anstatt abzubrechen."
)

# --- ZAVIHKA ZA PREGLEDNOST ---
tab1, tab2, tab3 = st.tabs(["⚙️ 1. Einstellungen & Team", "📅 2. Dienstplan & KI", "🚑 3. SOS Ausfallmanagement"])

with tab1:
    st.header("Monat und Jahr auswählen")
    col_date1, col_date2 = st.columns(2)
    with col_date1:
        leto = st.selectbox("Jahr:", [2026, 2027, 2028], index=0)
    with col_date2:
        mesec = st.selectbox(
            "Monat:",
            list(range(1, 13)),
            format_func=lambda x: [
                "Januar", "Februar", "März", "April", "Mai", "Juni",
                "Juli", "August", "September", "Oktober", "November", "Dezember"
            ][x - 1],
        )

    first_day_of_month_weekday, num_days = calendar.monthrange(leto, mesec)
    
    # Pridobi avstrijske praznike (Štajerska - koda 6)
    at_holidays = holidays.Austria(years=leto, subdiv='6')

    st.header("Team (Stundenübertrag und %-Anstellung)")
    st.info("💡 Trage bei 'Saldo Alt' die Plus/Minus-Stunden aus dem Vormonat ein.")

    if "staff_df_v11" not in st.session_state:
        initial_staff = []

        initial_staff.append({
            "ID": 0, "Name": "WBL (Uroš)", "Abteilung": "Abteilung H", "Rolle": "Leitung",
            "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
            "FR": True, "SA": False, "SO": False, "Spezialdienst": "Ohne", "Ue42_ENT": False, "Geb_Monat": "März"
        })

        for i in range(1, 4):
            initial_staff.append({
                "ID": len(initial_staff), "Name": f"DGKP F-{i} (Pool)", "Abteilung": "Abteilung F", "Rolle": "DGKP",
                "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 4, "MO": True, "DI": True, "MI": True, "DO": True, 
                "FR": True, "SA": True, "SO": True, "Spezialdienst": "Nur Nachtdienste", "Ue42_ENT": False, "Geb_Monat": "Ohne"
            })

        for i in range(1, 5):
            initial_staff.append({
                "ID": len(initial_staff), "Name": f"DGKP B-{i}", "Abteilung": "Abteilung B", "Rolle": "DGKP",
                "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
                "FR": True, "SA": True, "SO": True, "Spezialdienst": "Ohne", "Ue42_ENT": False, "Geb_Monat": "Ohne"
            })

        initial_staff.append({
            "ID": len(initial_staff), "Name": "DGKP H-1 (SM Dienst)", "Abteilung": "Abteilung H", "Rolle": "DGKP",
            "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
            "FR": True, "SA": True, "SO": True, "Spezialdienst": "SM (7:45-18:15)", "Ue42_ENT": False, "Geb_Monat": "Ohne"
        })
        for i in range(2, 5):
            initial_staff.append({
                "ID": len(initial_staff), "Name": f"DGKP H-{i}", "Abteilung": "Abteilung H", "Rolle": "DGKP",
                "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
                "FR": True, "SA": True, "SO": True, "Spezialdienst": "Ohne", "Ue42_ENT": False, "Geb_Monat": "Ohne"
            })

        for i in range(1, 4):
            initial_staff.append({
                "ID": len(initial_staff), "Name": f"Heimhelfer B-{i} (JED)", "Abteilung": "Abteilung B", "Rolle": "Heimhelfer",
                "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
                "FR": True, "SA": True, "SO": True, "Spezialdienst": "JED (Speisesaal 6:30-18:00)", "Ue42_ENT": True, "Geb_Monat": "Januar"
            })

        for i in range(1, 10):
            initial_staff.append({
                "ID": len(initial_staff), "Name": f"PA B-{i}", "Abteilung": "Abteilung B", "Rolle": "Pflegeassistenz",
                "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 5, "MO": True, "DI": True, "MI": True, "DO": True, 
                "FR": True, "SA": True, "SO": True, "Spezialdienst": "Ohne",
