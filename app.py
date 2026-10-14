import streamlit as st
import pandas as pd
import calendar
from datetime import date
from ortools.sat.python import cp_model

st.set_page_config(page_title="AI Urniki PRO 4.0", layout="wide")

st.title("🏥 Centralni AI Sistem (Več oddelkov)")
st.markdown("Prikaz ločenih tabel za Oddelek B, Oddelek H in Oddelek F.")

# --- 1. KOLEDAR IN NASTAVITVE MESECA ---
st.header("1. Izbira meseca in leta")
col_date1, col_date2 = st.columns(2)
with col_date1:
    leto = st.selectbox("Leto:", [2026, 2027, 2028], index=0)
with col_date2:
    mesec = st.selectbox("Mesec:", list(range(1, 13)), format_func=lambda x: ["Januar", "Februar", "Marec", "April", "Maj", "Junij", "Julij", "Avgust", "September", "Oktober", "November", "December"][x-1])

first_day_of_month_weekday, num_days = calendar.monthrange(leto, mesec)

# --- 2. UPRAVLJANJE ZAPOSLENIH IN ODDELKOV ---
st.header("2. Ekipa (Oddelek B, Oddelek H, Oddelek F)")
st.info("💡 Oddelek F primarno služi kot bazen za nočne izmene, ki pokrivajo celotno enoto.")

if 'staff_df' not in st.session_state:
    initial_staff = [
        {"ID": 0, "Ime": "Vodja (Uroš)", "Oddelek": "Oddelek H", "Vloga": "Manager", "Tedenske_ure": 40.0},
        {"ID": 1, "Ime": "DGKP Nočna", "Oddelek": "Oddelek F", "Vloga": "DGKP", "Tedenske_ure": 37.0},
        {"ID": 2, "Ime": "DGKP 1 (Odd H)", "Oddelek": "Oddelek H", "Vloga": "DGKP", "Tedenske_ure": 37.0},
        {"ID": 3, "Ime": "DGKP 1 (Odd B)", "Oddelek": "Oddelek B", "Vloga": "DGKP", "Tedenske_ure": 37.0},
        {"ID": 4, "Ime": "DGKP 2 (Odd B)", "Oddelek": "Oddelek B", "Vloga": "DGKP", "Tedenske_ure": 37.0},
    ]
    # Dodamo nekaj tehnikov
    for i in range(1, 6):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"Tehnik B-{i}", "Oddelek": "Oddelek B", "Vloga": "Tehnik", "Tedenske_ure": 37.0})
    for i in range(1, 6):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"Tehnik H-{i}", "Oddelek": "Oddelek H", "Vloga": "Tehnik", "Tedenske_ure": 37.0})
    
    st.session_state.staff_df = pd.DataFrame(initial_staff)

edited_df = st.data_editor(
    st.session_state.staff_df, 
    num_rows="dynamic",
    key="urejanje_tabele", # <--- TA KLJUČ REŠI TEŽAVO S TIPKANJEM!
    column_config={
        "Oddelek": st.column_config.SelectboxColumn("Oddelek", options=["Oddelek B", "Oddelek H", "Oddelek F"], required=True),
        "Vloga": st.column_config.SelectboxColumn("Vloga", options=["Manager", "DGKP", "Tehnik"], required=True),
        "Tedenske_ure": st.column_config.NumberColumn("Tedenske ure", min_value=10.0, max_value=40.0, required=True)
    },
    use_container_width=True
)
st.session_state.staff_df = edited_df # <--- TO VRNEMA, DA GUMB ZNA IZRAČUNATI!
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
        reason = st.selectbox("Razlog:", ["DOP (Dopust)", "BOL (Bolniška)", "ROJ (Rojstni)", "ENT (Entlastung)"])
    
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
if st.button("🚀 Izračunaj urnik", type="primary", use_container_width=True):
    staff_list = edited_df.to_dict('records')
    
    with st.spinner("Preračunavam izmene po oddelkih..."):
        model = cp_model.CpModel()
        shifts = {'D1': 1200, 'D3': 825, 'D4': 1100, 'N': 1350, 'OFF': 0}
        
        work = {}
        for s in staff_list:
            for d in range(num_days):
                for sh in shifts.keys():
                    work[(s["ID"], d, sh)] = model.NewBoolVar(f'work_{s["ID"]}_{d}_{sh}')
        
        for s in staff_list:
            for d in range(num_days):
                model.AddExactlyOne(work[(s["ID"], d, sh)] for sh in shifts.keys())
        
        # Odsotnosti
        for a in st.session_state.absences:
            if a["day"] < num_days:
                model.Add(work[(a["emp_id"], a["day"], 'OFF')] == 1)

        # Kategorizacija po novih oddelkih
        oB_tehniki = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek B" and s["Vloga"] == "Tehnik"]
        oH_tehniki = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek H" and s["Vloga"] == "Tehnik"]
        
        oB_dgkp = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek B" and s["Vloga"] in ["DGKP", "Manager"]]
        oH_dgkp = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek H" and s["Vloga"] in ["DGKP", "Manager"]]
        
        nocni_dgkp = [s["ID"] for s in staff_list if s["Vloga"] == "DGKP"] # Vsi DGKP vključno z Oddelkom F

        for d in range(num_days):
            day_of_week = (d + first_day_of_month_weekday) % 7
            
            # --- DNEVNA IZMena ---
            # Oddelek B (Pričakovanja: vsaj 1-2 DGKP in ustrezno število tehnikov)
            if len(oB_dgkp) >= 1: model.Add(sum(work[(e, d, sh)] for e in oB_dgkp for sh in ['D1', 'D3', 'D4']) >= 1)
            if len(oB_tehniki) >= 4: model.Add(sum(work[(e, d, sh)] for e in oB_tehniki for sh in ['D1', 'D3', 'D4']) >= 4)
            
            # Oddelek H (Pričakovanja: vsaj 1 DGKP in ustrezno število tehnikov)
            if len(oH_dgkp) >= 1: model.Add(sum(work[(e, d, sh)] for e in oH_dgkp for sh in ['D1', 'D3', 'D4']) >= 1)
            if len(oH_tehniki) >= 3: model.Add(sum(work[(e, d, sh)] for e in oH_tehniki for sh in ['D1', 'D3', 'D4']) >= 3)
            
            # --- NOČNA IZMena ---
            # 1 DGKP za celotno področje
            if len(nocni_dgkp) > 0: model.Add(sum(work[(e, d, 'N')] for e in nocni_dgkp) == 1)
            
            # 1 Tehnik iz Oddelka B in 1 Tehnik iz Oddelka H v nočni izmeni
            if len(oB_tehniki) > 0: model.Add(sum(work[(e, d, 'N')] for e in oB_tehniki) == 1)
            if len(oH_tehniki) > 0: model.Add(sum(work[(e, d, 'N')] for e in oH_tehniki) == 1)
            
        # Počitek po nočni
        for s in staff_list:
            for d in range(num_days - 1):
                model.AddImplication(work[(s["ID"], d, 'N')], work[(s["ID"], d + 1, 'OFF')])

        # MEHKE OMEJITVE (Prekoračitve)
        hour_deviations = []
        for s in staff_list:
            target = int((s["Tedenske_ure"] / 7.0) * num_days * 100)
            total_hours = model.NewIntVar(0, 35000, f'tot_{s["ID"]}')
            model.Add(total_hours == sum(work[(s["ID"], d, sh)] * shifts[sh] for d in range(num_days) for sh in shifts.keys()))
            
            dev = model.NewIntVar(0, 20000, f'dev_{s["ID"]}')
            model.Add(dev >= total_hours - target)
            model.Add(dev >= target - total_hours)
            
            # Preferiramo, da Oddelek F dela nočne izmene
           # Preferiramo, da Oddelek F dela nočne izmene
            if s["Oddelek"] == "Oddelek F":
                penalty = model.NewIntVar(0, 10000, f'pen_{s["ID"]}')
                model.Add(penalty == sum(work[(s["ID"], d, sh)] for d in range(num_days) for sh in ['D1', 'D3', 'D4']) * 100)
                hour_deviations.append(penalty)
