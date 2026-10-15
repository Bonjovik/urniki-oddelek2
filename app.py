import streamlit as st
import pandas as pd
import calendar
from datetime import date
from ortools.sat.python import cp_model

st.set_page_config(page_title="AI Urniki PRO 6.1", layout="wide")

st.title("🏥 Centralni AI Sistem (Verzija 6.1)")
st.markdown("Dodano: Namenski vnosnik za točne delovne dni (želje) za vsakega posameznika.")

# --- 1. KOLEDAR IN NASTAVITVE MESECA ---
st.header("1. Izbira meseca in leta")
col_date1, col_date2 = st.columns(2)
with col_date1:
    leto = st.selectbox("Leto:", [2026, 2027, 2028], index=0)
with col_date2:
    mesec = st.selectbox("Mesec:", list(range(1, 13)), format_func=lambda x: ["Januar", "Februar", "Marec", "April", "Maj", "Junij", "Julij", "Avgust", "September", "Oktober", "November", "December"][x-1])

first_day_of_month_weekday, num_days = calendar.monthrange(leto, mesec)

# --- 2. UPRAVLJANJE ZAPOSLENIH IN ODDELKOV ---
st.header("2. Ekipa (Nastavitve)")
st.info("💡 V tabeli lahko na hitro nastaviš vzorce, v koraku 3 in 4 pa dodajaš točne datume.")

if 'staff_df' not in st.session_state:
    initial_staff = []
    
    initial_staff.append({"ID": 0, "Ime": "Vodja (Uroš)", "Oddelek": "Oddelek H", "Vloga": "Manager", "Ure": 40.0, "Max_Nocnih": 0, "Dnevi_dela": "Samo Pon-Pet", "Posebno": "Brez"})
    
    for i in range(1, 4):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"DGKP F-{i} (Bazen)", "Oddelek": "Oddelek F", "Vloga": "DGKP", "Ure": 37.0, "Max_Nocnih": 4, "Dnevi_dela": "Vsi dnevi", "Posebno": "Samo nočne (brez dnevnih)"})
        
    for i in range(1, 5):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"DGKP B-{i}", "Oddelek": "Oddelek B", "Vloga": "DGKP", "Ure": 37.0, "Max_Nocnih": 0, "Dnevi_dela": "Vsi dnevi", "Posebno": "Brez"})
        
    initial_staff.append({"ID": len(initial_staff), "Ime": "DGKP H-1 (SM izmena)", "Oddelek": "Oddelek H", "Vloga": "DGKP", "Ure": 37.0, "Max_Nocnih": 0, "Dnevi_dela": "Vsi dnevi", "Posebno": "SM (7:45-18:15)"})
    for i in range(2, 5):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"DGKP H-{i}", "Oddelek": "Oddelek H", "Vloga": "DGKP", "Ure": 37.0, "Max_Nocnih": 0, "Dnevi_dela": "Vsi dnevi", "Posebno": "Brez"})

    for i in range(1, 4):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"Bolničar B-{i} (Jedilnica)", "Oddelek": "Oddelek B", "Vloga": "Bolničar", "Ure": 37.0, "Max_Nocnih": 0, "Dnevi_dela": "Vsi dnevi", "Posebno": "Jedilnica JED (6:30-18:00)"})
        
    initial_staff.append({"ID": len(initial_staff), "Ime": "Tehnik B-1 (Noseča)", "Oddelek": "Oddelek B", "Vloga": "Tehnik", "Ure": 37.0, "Max_Nocnih": 0, "Dnevi_dela": "Samo Pon-Pet", "Posebno": "Mutterschutz (7:30-15:00)"})
    for i in range(2, 12):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"Tehnik B-{i}", "Oddelek": "Oddelek B", "Vloga": "Tehnik", "Ure": 37.0, "Max_Nocnih": 5, "Dnevi_dela": "Vsi dnevi", "Posebno": "Brez"})

    for i in range(1, 15):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"Tehnik H-{i}", "Oddelek": "Oddelek H", "Vloga": "Tehnik", "Ure": 37.0, "Max_Nocnih": 5, "Dnevi_dela": "Vsi dnevi", "Posebno": "Brez"})
    
    st.session_state.staff_df = pd.DataFrame(initial_staff)

edited_df = st.data_editor(
    st.session_state.staff_df, 
    num_rows="dynamic",
    key="tabela_zaposlenih_v61",
    column_config={
        "Oddelek": st.column_config.SelectboxColumn("Oddelek", options=["Oddelek B", "Oddelek H", "Oddelek F"], required=True),
        "Vloga": st.column_config.SelectboxColumn("Vloga", options=["Manager", "DGKP", "Tehnik", "Bolničar"], required=True),
        "Ure": st.column_config.NumberColumn("Tedenske ure", min_value=10.0, max_value=40.0, required=True),
        "Max_Nocnih": st.column_config.NumberColumn("Max nočnih", min_value=0, max_value=15, default=0),
        "Dnevi_dela": st.column_config.SelectboxColumn("Splošni vzorec", options=["Vsi dnevi", "Samo Pon-Pet", "Samo Vikendi", "Tor-Sre-Čet"], required=True),
        "Posebno": st.column_config.SelectboxColumn("Posebni urnik", options=["Brez", "Jedilnica JED (6:30-18:00)", "Mutterschutz (7:30-15:00)", "SM (7:45-18:15)", "Samo nočne (brez dnevnih)"], required=True)
    },
    use_container_width=True
)

if 'absences' not in st.session_state:
    st.session_state.absences = []
if 'work_rules' not in st.session_state:
    st.session_state.work_rules = []

st.divider()

# --- 3. TOČEN VNOS ODSOTNOSTI IN ŽELJA ---
col_abs, col_work = st.columns(2)

with col_abs:
    st.header("3. Vnos odsotnosti (Dopusti)")
    with st.form("absence_form"):
        emp_name = st.selectbox("Zaposleni:", options=edited_df["Ime"].tolist(), key="abs_emp")
        izbrani_datumi = st.multiselect("Izberi datume odsotnosti:", options=list(range(1, num_days + 1)), key="abs_dates")
        reason = st.selectbox("Razlog:", ["DOP (Dopust)", "BOL (Bolniška)", "ROJ", "ENT"], key="abs_reason")
        
        if st.form_submit_button("Shrani odsotnosti") and izbrani_datumi:
            emp_id = edited_df.loc[edited_df["Ime"] == emp_name, "ID"].values[0]
            for d in izbrani_datumi:
                st.session_state.absences.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "reason": reason})
            st.success("Odsotnosti shranjene!")
            
    if st.session_state.absences:
        if st.button("🗑️ Izbriši vse odsotnosti"):
            st.session_state.absences = []
            st.rerun()
        abs_df = pd.DataFrame(st.session_state.absences)
        abs_df["Datum"] = abs_df["day"].apply(lambda x: f"{x+1}.")
        st.dataframe(abs_df[["emp_name", "Datum", "reason"]], use_container_width=True)

with col_work:
    st.header("4. Vnos delovnih dni (Želje)")
    with st.form("work_form"):
        emp_name_w = st.selectbox("Zaposleni:", options=edited_df["Ime"].tolist(), key="work_emp")
        izbrani_datumi_w = st.multiselect("Izberi točne delovne dni:", options=list(range(1, num_days + 1)), key="work_dates")
        rule_w = st.selectbox("Pravilo izbranih dni:", ["MORA delati na te izbrane dni", "Sme delati SAMO na te izbrane dni"], key="work_rule")
        
        if st.form_submit_button("Shrani delovne dni") and izbrani_datumi_w:
            emp_id_w = edited_df.loc[edited_df["Ime"] == emp_name_w, "ID"].values[0]
            for d in izbrani_datumi_w:
                st.session_state.work_rules.append({"emp_id": emp_id_w, "emp_name": emp_name_w, "day": d - 1, "rule": rule_w})
            st.success("Pravila za delo shranjena!")

    if st.session_state.work_rules:
        if st.button("🗑️ Izbriši vse delovne želje"):
            st.session_state.work_rules = []
            st.rerun()
        work_df = pd.DataFrame(st.session_state.work_rules)
        work_df["Datum"] = work_df["day"].apply(lambda x: f"{x+1}.")
        st.dataframe(work_df[["emp_name", "Datum", "rule"]], use_container_width=True)

st.divider()

# --- 5. GENERIRANJE URNIKA ---
st.header("5. Avtomatska generacija")
if st.button("🚀 Izračunaj urnik", type="primary", use_container_width=True):
    staff_list = edited_df.to_dict('records')
    
    try:
        with st.spinner("Računam urnik z vsemi vnesenimi željami..."):
            model = cp_model.CpModel()
            
            shifts = {
                'X4': 825, 'X6': 1100, 'X7': 1200, 'N1': 1350, 'N2': 1350, 
                'JED': 1050, 'MS': 700, 'SM': 1000, 'OFF': 0
            }
            
            work = {}
            for s in staff_list:
                for d in range(num_days):
                    for sh in shifts.keys():
                        work[(s["ID"], d, sh)] = model.NewBoolVar(f'work_{s["ID"]}_{d}_{sh}')
            
            for s in staff_list:
                for d in range(num_days):
                    model.Add(sum(work[(s["ID"], d, sh)] for sh in shifts.keys()) == 1)
            
            # --- OBDELAVA SPECIFIČNIH DELOVNIH DNI (Zavihek 4) ---
            only_work_days = {s["ID"]: set() for s in staff_list}
            must_work_days = {s["ID"]: set() for s in staff_list}
            has_only_rule = {s["ID"]: False for s in staff_list}
            
            for r in st.session_state.work_rules:
                if "SAMO" in r["rule"]:
                    only_work_days[r["emp_id"]].add(r["day"])
                    has_only_rule[r["emp_id"]] = True
                elif "MORA" in r["rule"]:
                    must_work_days[r["emp_id"]].add(r["day"])

            for s in staff_list:
                e_id = s["ID"]
                # 1. Pravilo: SAMO izbrani dnevi (vsi ostali so OFF)
                if has_only_rule[e_id]:
                    for d in range(num_days):
                        if d not in only_work_days[e_id]:
                            model.Add(work[(e_id, d, 'OFF')] == 1)
                
                # 2. Pravilo: MORA delati
                for d in must_work_days[e_id]:
                    model.Add(work[(e_id, d, 'OFF')] == 0)

            # DOLOČITEV DOVOLJENIH IZMEN ZA POSAMEZNIKA
            for s in staff_list:
                allowed_shifts = ['OFF']
                
                if s["Posebno"] == "Jedilnica JED (6:30-18:00)":
                    allowed_shifts.append('JED')
                elif s["Posebno"] == "Mutterschutz (7:30-15:00)":
                    allowed_shifts.append('MS')
                elif s["Posebno"] == "SM (7:45-18:15)":
                    allowed_shifts.append('SM')
                elif s["Posebno"] == "Samo nočne (brez dnevnih)":
                    if s["Vloga"] == "DGKP": allowed_shifts.append('N1')
                    else: allowed_shifts.append('N2')
                elif s["Vloga"] == "Manager":
                    allowed_shifts.append('X4') 
                else:
                    allowed_shifts.extend(['X4', 'X6', 'X7']) 
                    if s["Max_Nocnih"] > 0:
                        if s["Vloga"] == "DGKP": allowed_shifts.append('N1')
                        elif s["Vloga"] in ["Tehnik", "Bolničar"]: allowed_shifts.append('N2')
                
                unallowed = [sh for sh in shifts.keys() if sh not in allowed_shifts]
                for d in range(num_days):
                    for sh in unallowed:
                        model.Add(work[(s["ID"], d, sh)] == 0)

                # MAX NOČNIH
                if s["Max_Nocnih"] >=
