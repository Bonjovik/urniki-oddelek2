import streamlit as st
import pandas as pd
import calendar
from datetime import date
from ortools.sat.python import cp_model

st.set_page_config(page_title="AI Urniki PRO 5.1", layout="wide")

st.title("🏥 Centralni AI Sistem (40 zaposlenih)")
st.markdown("Popolnoma prilagodljive šifre (X4, X6, X7, N1, N2), vnos izjem in predizpolnjena ekipa.")

# --- 1. KOLEDAR IN NASTAVITVE MESECA ---
st.header("1. Izbira meseca in leta")
col_date1, col_date2 = st.columns(2)
with col_date1:
    leto = st.selectbox("Leto:", [2026, 2027, 2028], index=0)
with col_date2:
    mesec = st.selectbox("Mesec:", list(range(1, 13)), format_func=lambda x: ["Januar", "Februar", "Marec", "April", "Maj", "Junij", "Julij", "Avgust", "September", "Oktober", "November", "December"][x-1])

first_day_of_month_weekday, num_days = calendar.monthrange(leto, mesec)

# --- 2. UPRAVLJANJE ZAPOSLENIH IN ODDELKOV ---
st.header("2. Ekipa (Prednastavljenih 40 oseb)")
st.info("💡 Preprosto prepiši generična imena v prava imena tvojih zaposlenih. Kljukica določa, kdo sme delati nočno.")

if 'staff_df' not in st.session_state:
    initial_staff = []
    
    # 1. VODJA
    initial_staff.append({"ID": len(initial_staff), "Ime": "Vodja (Uroš)", "Oddelek": "Oddelek H", "Vloga": "Manager", "Ure": 40.0, "Nocne": False, "Posebno": "Brez"})
    
    # 2. ODDELEK F (Nočni bazen) - 3 osebe (DGKP)
    for i in range(1, 4):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"DGKP F-{i} (Bazen)", "Oddelek": "Oddelek F", "Vloga": "DGKP", "Ure": 37.0, "Nocne": True, "Posebno": "Brez"})
        
    # 3. ODDELEK B (DGKP) - 4 osebe
    for i in range(1, 5):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"DGKP B-{i}", "Oddelek": "Oddelek B", "Vloga": "DGKP", "Ure": 37.0, "Nocne": False, "Posebno": "Brez"})
        
    # 4. ODDELEK H (DGKP) - 4 osebe (ena naj bo SM)
    initial_staff.append({"ID": len(initial_staff), "Ime": "DGKP H-1 (SM izmena)", "Oddelek": "Oddelek H", "Vloga": "DGKP", "Ure": 37.0, "Nocne": False, "Posebno": "SM (7:45-18:15)"})
    for i in range(2, 5):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"DGKP H-{i}", "Oddelek": "Oddelek H", "Vloga": "DGKP", "Ure": 37.0, "Nocne": False, "Posebno": "Brez"})
        
    # 5. ODDELEK B (Tehniki) - 14 oseb (ena naj bo noseča)
    initial_staff.append({"ID": len(initial_staff), "Ime": "Tehnik B-1 (Noseča)", "Oddelek": "Oddelek B", "Vloga": "Tehnik", "Ure": 37.0, "Nocne": False, "Posebno": "Mutterschutz (7:30-15:00)"})
    for i in range(2, 15):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"Tehnik B-{i}", "Oddelek": "Oddelek B", "Vloga": "Tehnik", "Ure": 37.0, "Nocne": True, "Posebno": "Brez"})

    # 6. ODDELEK H (Tehniki) - 14 oseb
    for i in range(1, 15):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"Tehnik H-{i}", "Oddelek": "Oddelek H", "Vloga": "Tehnik", "Ure": 37.0, "Nocne": True, "Posebno": "Brez"})
    
    st.session_state.staff_df = pd.DataFrame(initial_staff)

edited_df = st.data_editor(
    st.session_state.staff_df, 
    num_rows="dynamic",
    key="urejanje_tabele",
    column_config={
        "Oddelek": st.column_config.SelectboxColumn("Oddelek", options=["Oddelek B", "Oddelek H", "Oddelek F"], required=True),
        "Vloga": st.column_config.SelectboxColumn("Vloga", options=["Manager", "DGKP", "Tehnik"], required=True),
        "Ure": st.column_config.NumberColumn("Tedenske ure", min_value=10.0, max_value=40.0, required=True),
        "Nocne": st.column_config.CheckboxColumn("Dela nočne?", default=False),
        "Posebno": st.column_config.SelectboxColumn("Posebni urnik", options=["Brez", "Mutterschutz (7:30-15:00)", "SM (7:45-18:15)"], required=True)
    },
    use_container_width=True
)
st.session_state.staff_df = edited_df

if 'absences' not in st.session_state:
    st.session_state.absences = []

# --- 3. TOČEN VNOS ODSOTNOSTI ---
st.header("3. Vnos odsotnosti")
with st.form("absence_form"):
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        emp_name = st.selectbox("Zaposleni:", options=edited_df["Ime"].tolist())
    with col_f2:
        izbrani_datumi = st.multiselect("Izberi dneve v mesecu:", options=list(range(1, num_days + 1)))
    with col_f3:
        reason = st.selectbox("Razlog:", ["DOP (Dopust)", "BOL (Bolniška)", "ROJ", "ENT"])
    
    if st.form_submit_button("Shrani odsotnosti") and izbrani_datumi:
        emp_id = edited_df.loc[edited_df["Ime"] == emp_name, "ID"].values[0]
        for d in izbrani_datumi:
            st.session_state.absences.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "reason": reason})
        st.success("Odsotnosti shranjene!")

if st.session_state.absences:
    abs_df = pd.DataFrame(st.session_state.absences)
    abs_df["Datum"] = abs_df["day"].apply(lambda x: f"{x+1}. {mesec}. {leto}")
    if st.button("🗑️ Izbriši vse odsotnosti"):
        st.session_state.absences = []
        st.rerun()

st.divider()

# --- 4. GENERIRANJE URNIKA ---
st.header("4. Avtomatska generacija")
if st.button("🚀 Izračunaj urnik s šiframi", type="primary", use_container_width=True):
    staff_list = edited_df.to_dict('records')
    
    with st.spinner("Preračunavam stroga pravila izmen za 40 zaposlenih (lahko traja 30 sekund)..."):
        model = cp_model.CpModel()
        
        # ŠIFRE IN VREDNOSTI (ure * 100)
        shifts = {
            'X4': 825,   # do 15:30
            'X6': 1100,  # do 18:15
            'X7': 1200,  # do 19:15
            'N1': 1350,  # Nočna DGKP (11.5 + 2)
            'N2': 1350,  # Nočna Tehnik (11.5 + 2)
            'MS': 700,   # Mutterschutz 7:30-15:00
            'SM': 1000,  # SM 7:45-18:15
            'OFF': 0
        }
        
        work = {}
        for s in staff_list:
            for d in range(num_days):
                for sh in shifts.keys():
                    work[(s["ID"], d, sh)] = model.NewBoolVar(f'work_{s["ID"]}_{d}_{sh}')
        
        # 1 izmena na dan
        for s in staff_list:
            for d in range(num_days):
                model.AddExactly
