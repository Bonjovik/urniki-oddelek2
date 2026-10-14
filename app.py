import streamlit as st
import pandas as pd
import calendar
from datetime import date
from ortools.sat.python import cp_model

st.set_page_config(page_title="AI Urniki PRO 5.0", layout="wide")

st.title("🏥 Centralni AI Sistem (Verzija 5.0)")
st.markdown("Popolnoma prilagodljive šifre (X4, X6, X7, N1, N2), vnos izjem in izbira nočnih delavcev.")

# --- 1. KOLEDAR IN NASTAVITVE MESECA ---
st.header("1. Izbira meseca in leta")
col_date1, col_date2 = st.columns(2)
with col_date1:
    leto = st.selectbox("Leto:", [2026, 2027, 2028], index=0)
with col_date2:
    mesec = st.selectbox("Mesec:", list(range(1, 13)), format_func=lambda x: ["Januar", "Februar", "Marec", "April", "Maj", "Junij", "Julij", "Avgust", "September", "Oktober", "November", "December"][x-1])

first_day_of_month_weekday, num_days = calendar.monthrange(leto, mesec)

# --- 2. UPRAVLJANJE ZAPOSLENIH IN ODDELKOV ---
st.header("2. Ekipa in posebnosti")
st.info("💡 Označi kljukico pri tistih, ki delajo nočne. Če izbereš 'Mutterschutz', bo delavka dobila izključno te ure.")

if 'staff_df' not in st.session_state:
    # Predizpolnjeno z generičnimi osebami za takojšen test!
    initial_staff = [
        {"ID": 0, "Ime": "Oseba 1 (Vodja)", "Oddelek": "Oddelek H", "Vloga": "Manager", "Ure": 40.0, "Nocne": False, "Posebno": "Brez"},
        {"ID": 1, "Ime": "Oseba 2 (Bazen)", "Oddelek": "Oddelek F", "Vloga": "DGKP", "Ure": 37.0, "Nocne": True, "Posebno": "Brez"},
        {"ID": 2, "Ime": "Oseba 3 (SM izmena)", "Oddelek": "Oddelek H", "Vloga": "DGKP", "Ure": 37.0, "Nocne": False, "Posebno": "SM (7:45-18:15)"},
        {"ID": 3, "Ime": "Oseba 4 (Odd B)", "Oddelek": "Oddelek B", "Vloga": "DGKP", "Ure": 37.0, "Nocne": False, "Posebno": "Brez"},
        {"ID": 4, "Ime": "Oseba 5 (Noseča)", "Oddelek": "Oddelek B", "Vloga": "Tehnik", "Ure": 37.0, "Nocne": False, "Posebno": "Mutterschutz (7:30-15:00)"},
    ]
    # Dodamo generične tehnike
    for i in range(1, 5):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"Generični T-B{i}", "Oddelek": "Oddelek B", "Vloga": "Tehnik", "Ure": 37.0, "Nocne": True, "Posebno": "Brez"})
    for i in range(1, 5):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"Generični T-H{i}", "Oddelek": "Oddelek H", "Vloga": "Tehnik", "Ure": 37.0, "Nocne": True, "Posebno": "Brez"})
    
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
    
    with st.spinner("Preračunavam stroga pravila izmen in posebnosti..."):
        model = cp_model.CpModel()
        
        # NOVE ŠIFRE IN VREDNOSTI (ure * 100)
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
        
        # Omejitev na točno eno izmeno na dan
        for s in staff_list:
            for d in range(num_days):
                model.AddExactlyOne(work[(s["ID"], d, sh)] for sh in shifts.keys())
        
        # Odsotnosti in stroga pravila ZA VSAKEGA POSAMEZNIKA
        for s in staff_list:
            allowed_shifts = ['OFF']
            
            # Kaj lahko dela ta oseba?
            if s["Posebno"] == "Mutterschutz (7:30-15:00)":
                allowed_shifts.append('MS')
            elif s["Posebno"] == "SM (7:45-18:15)":
                allowed_shifts.append('SM')
            elif s["Vloga"] == "Manager":
                allowed_shifts.append('X4') # Manager dela X4
            else:
                allowed_shifts.extend(['X4', 'X6', 'X7']) # Navadne dnevne
                
                # Dodajanje nočnih samo tistim, ki imajo kljukico!
                if s["Nocne"]:
                    if s["Vloga"] == "DGKP":
                        allowed_shifts.append('N1')
                    elif s["Vloga"] == "Tehnik":
                        allowed_shifts.append('N2')
            
            # Prepoved vseh ostalih izmen, ki niso v "allowed_shifts"
            unallowed = [sh for sh in shifts.keys() if sh not in allowed_shifts]
            for d in range(num_days):
                for sh in unallowed:
                    model.Add(work[(s["ID"], d, sh)] == 0)

        # Uporaba dopustov (povozi vse)
        for a in st.session_state.absences:
            if a["day"] < num_days:
                model.Add(work[(a["emp_id"], a["day"], 'OFF')] == 1)

        # Skupine za pravila
        oB_tehniki = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek B" and s["Vloga"] == "Tehnik"]
        oH_tehniki = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek H" and s["Vloga"] == "Tehnik"]
        all_dgkp = [s["ID"] for s in staff_list if s["Vloga"] in ["DGKP", "Manager"]]

        day_shifts = ['X4', 'X6', 'X7', 'MS', 'SM']

        for d in range(num_days):
            day_of_week = (d + first_day_of_month_weekday) % 7
            
            # Manager ne dela vikendov
            for s in staff_list:
                if s["Vloga"] == "Manager" and day_of_week >= 5:
                    model.Add(work[(s["ID"], d, 'OFF')] == 1)

            # Minimalno pokritje
            # Oddelek B (vsaj 2-3 tehniki in vsaj nekdo izmed DGKP)
            if len(oB_tehniki) >= 3: model.Add(sum(work[(e, d, sh)] for e in oB_tehniki for sh in day_shifts) >= 3)
            # Oddelek H
            if len(oH_tehniki) >= 3: model.Add(sum(work[(e, d, sh)] for e in oH_tehniki for sh in day_shifts) >= 3)
            
            # Nočne
            # Vsako noč točno 1 DGKP na N1
            dgkp_nocni = [s["ID"] for s in staff_list if s["Vloga"] == "DGKP" and s["Nocne"]]
            if len(dgkp_nocni) > 0: model.Add(sum(work[(e, d, 'N1')] for e in dgkp_nocni) == 1)
            
            # Vsako noč 1 tehnik na Odd B in 1 na Odd H na N2
            tech_nocni_B = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek B" and s["Vloga"] == "Tehnik" and s["Nocne"]]
            if len(tech_nocni_B) > 0: model.Add(sum(work[(e, d, 'N2')] for e in tech_nocni_B) == 1)
            
            tech_nocni_H = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek H" and s["Vloga"] == "Tehnik" and s["Nocne"]]
            if len(tech_nocni_H) > 0: model.Add(sum(work[(e, d, 'N2')] for e in tech_nocni_H) == 1)
            
            # Predaja do 19:15 (X7) - Vsaj en DGKP mora imeti izmeno X7!
            if len(all_dgkp) > 0: model.Add(sum(work[(e, d, 'X7')] for e in all_dgkp) >= 1)

        # Počitek po nočni
        for s in staff_list:
            for d in range(num_days - 1):
                model.AddImplication(work[(s["ID"], d, 'N1')], work[(s["ID"], d + 1, 'OFF')])
                model.AddImplication(work[(s["ID"], d, 'N2')], work[(s["ID"], d + 1, 'OFF')])

        # Prilagoditev ur
        hour_deviations = []
        for s in staff_list:
            target = int((s["Ure"] / 7.0) * num_days * 100)
            total_hours = model.NewIntVar(0, 35000, f'tot_{s["ID"]}')
            model.Add(total_hours == sum(work[(s["ID"], d, sh)] * shifts[sh] for d in range(num_days) for sh in shifts.keys()))
            
            dev = model.NewIntVar(0, 20000, f'dev_{s["ID"]}')
            model.Add(dev >= total_hours - target)
            model.Add(dev >= target - total_hours)
            
            hour_deviations.append(dev)

        model.Minimize(sum(hour_deviations))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 45.0
        status = solver.Solve(model)

        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            st.success("🎉 Urnik s specifičnimi kodami je zgeneriran!")
            
            data = []
            for s in staff_list:
                row = {"Oddelek": s["Oddelek"], "Vloga": s["Vloga"], "Zaposleni": s["Ime"]}
                total_hours = 0
                for d in range(num_days):
                    for sh in shifts.keys():
                        if solver.Value(work[(s["ID"], d, sh)]) == 1:
                            val = sh if sh != 'OFF' else '...'
                            for a in st.session_state.absences:
                                if a["emp_id"] == s["ID"] and a["day"] == d:
                                    val = a["reason"].split(" ")[0]
                            row[f"{d+1}."] = val
                            total_hours += shifts[sh]
                
                target_hrs = (s["Ure"] / 7.0) * num_days
                row["FOND"] = round(target_hrs, 1)
                row["PLANIRANO"] = total_hours / 100
                row["RAZLIKA"] = round((total_hours / 100) - target_hrs, 1)
                data.append(row)
            
            df_rezultat = pd.DataFrame(data)
            
            def highlight_hours(val):
                if isinstance(val, (int, float)):
                    if val > 12: return 'background-color: #ffcccc; color: #990000; font-weight: bold'
                    elif val < -12: return 'background-color: #ccccff; color: #000099; font-weight: bold'
                return ''
            
            # --- PRIKAZ V LOČENIH TABELAH ---
            st.subheader("🔵 Oddelek B")
            df_b = df_rezultat[df_rezultat["Oddelek"] == "Oddelek B"].drop(columns=["Oddelek"])
            st.dataframe(df_b.style.applymap(highlight_hours, subset=['RAZLIKA']), use_container_width=True)
            
            st.subheader("🟢 Oddelek H")
            df_h = df_rezultat[df_rezultat["Oddelek"] == "Oddelek H"].drop(columns=["Oddelek"])
            st.dataframe(df_h.style.applymap(highlight_hours, subset=['RAZLIKA']), use_container_width=True)
            
            st.subheader("🟣 Oddelek F (Nočni bazen)")
            df_f = df_rezultat[df_rezultat["Oddelek"] == "Oddelek F"].drop(columns=["Oddelek"])
            st.dataframe(df_f.style.applymap(highlight_hours, subset=['RAZLIKA']), use_container_width=True)
            
        else:
            st.error("🚨 Sistem ni našel rešitve. Preveri, ali si določil dovolj ljudi s kljukico 'Dela nočne'!")
