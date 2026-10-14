import streamlit as st
import pandas as pd
import calendar
from datetime import date
from ortools.sat.python import cp_model

st.set_page_config(page_title="AI Urniki PRO 5.2", layout="wide")

st.title("🏥 Centralni AI Sistem (40 zaposlenih)")
st.markdown("Gladko vnašanje, prilagodljive šifre (X4, X6, X7, N1, N2) in popolna stabilnost.")

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
st.info("💡 Tipkanje sedaj deluje gladko. Prepiši generična imena in označi kljukice za nočne.")

if 'staff_df' not in st.session_state:
    initial_staff = []
    
    initial_staff.append({"ID": len(initial_staff), "Ime": "Vodja (Uroš)", "Oddelek": "Oddelek H", "Vloga": "Manager", "Ure": 40.0, "Nocne": False, "Posebno": "Brez"})
    
    for i in range(1, 4):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"DGKP F-{i} (Bazen)", "Oddelek": "Oddelek F", "Vloga": "DGKP", "Ure": 37.0, "Nocne": True, "Posebno": "Brez"})
        
    for i in range(1, 5):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"DGKP B-{i}", "Oddelek": "Oddelek B", "Vloga": "DGKP", "Ure": 37.0, "Nocne": False, "Posebno": "Brez"})
        
    initial_staff.append({"ID": len(initial_staff), "Ime": "DGKP H-1 (SM izmena)", "Oddelek": "Oddelek H", "Vloga": "DGKP", "Ure": 37.0, "Nocne": False, "Posebno": "SM (7:45-18:15)"})
    for i in range(2, 5):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"DGKP H-{i}", "Oddelek": "Oddelek H", "Vloga": "DGKP", "Ure": 37.0, "Nocne": False, "Posebno": "Brez"})
        
    initial_staff.append({"ID": len(initial_staff), "Ime": "Tehnik B-1 (Noseča)", "Oddelek": "Oddelek B", "Vloga": "Tehnik", "Ure": 37.0, "Nocne": False, "Posebno": "Mutterschutz (7:30-15:00)"})
    for i in range(2, 15):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"Tehnik B-{i}", "Oddelek": "Oddelek B", "Vloga": "Tehnik", "Ure": 37.0, "Nocne": True, "Posebno": "Brez"})

    for i in range(1, 15):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"Tehnik H-{i}", "Oddelek": "Oddelek H", "Vloga": "Tehnik", "Ure": 37.0, "Nocne": True, "Posebno": "Brez"})
    
    st.session_state.staff_df = pd.DataFrame(initial_staff)

# Prikaz tabele (odstranjena problematična vrstica za prepisovanje spomina)
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
    
    with st.spinner("Preračunavam stroga pravila izmen za 40 zaposlenih (lahko traja 30-45 sekund)..."):
        model = cp_model.CpModel()
        
        # ŠIFRE IN VREDNOSTI (ure * 100)
        shifts = {
            'X4': 825,   
            'X6': 1100,  
            'X7': 1200,  
            'N1': 1350,  
            'N2': 1350,  
            'MS': 700,   
            'SM': 1000,  
            'OFF': 0
        }
        
        work = {}
        for s in staff_list:
            for d in range(num_days):
                for sh in shifts.keys():
                    work[(s["ID"], d, sh)] = model.NewBoolVar(f'work_{s["ID"]}_{d}_{sh}')
        
        # POPRAVLJENA NAPAKA: Klasičen način seštevanja namesto AddExactlyOne
        for s in staff_list:
            for d in range(num_days):
                model.Add(sum(work[(s["ID"], d, sh)] for sh in shifts.keys()) == 1)
        
        # Omejitve posameznika
        for s in staff_list:
            allowed_shifts = ['OFF']
            
            if s["Posebno"] == "Mutterschutz (7:30-15:00)":
                allowed_shifts.append('MS')
            elif s["Posebno"] == "SM (7:45-18:15)":
                allowed_shifts.append('SM')
            elif s["Vloga"] == "Manager":
                allowed_shifts.append('X4') 
            else:
                allowed_shifts.extend(['X4', 'X6', 'X7']) 
                if s["Nocne"]:
                    if s["Vloga"] == "DGKP":
                        allowed_shifts.append('N1')
                    elif s["Vloga"] == "Tehnik":
                        allowed_shifts.append('N2')
            
            unallowed = [sh for sh in shifts.keys() if sh not in allowed_shifts]
            for d in range(num_days):
                for sh in unallowed:
                    model.Add(work[(s["ID"], d, sh)] == 0)

        # Dopusti
        for a in st.session_state.absences:
            if a["day"] < num_days:
                model.Add(work[(a["emp_id"], a["day"], 'OFF')] == 1)

        oB_tehniki = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek B" and s["Vloga"] == "Tehnik"]
        oH_tehniki = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek H" and s["Vloga"] == "Tehnik"]
        all_dgkp = [s["ID"] for s in staff_list if s["Vloga"] in ["DGKP", "Manager"]]

        day_shifts = ['X4', 'X6', 'X7', 'MS', 'SM']

        for d in range(num_days):
            day_of_week = (d + first_day_of_month_weekday) % 7
