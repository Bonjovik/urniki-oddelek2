import streamlit as st
import pandas as pd
import calendar
from datetime import date
from ortools.sat.python import cp_model

st.set_page_config(page_title="AI Urniki PRO 3.0", layout="wide")

st.title("🏥 Centralni AI Sistem (Več oddelkov & Koledar)")
st.markdown("Združevanje kadra, avtomatski koledar in fleksibilne ure z barvnimi opozorili.")

# --- 1. KOLEDAR IN NASTAVITVE MESECA ---
st.header("1. Izbira meseca in leta")
col_date1, col_date2 = st.columns(2)
with col_date1:
    leto = st.selectbox("Leto:", [2026, 2027, 2028], index=0)
with col_date2:
    mesec = st.selectbox("Mesec:", list(range(1, 13)), format_func=lambda x: ["Januar", "Februar", "Marec", "April", "Maj", "Junij", "Julij", "Avgust", "September", "Oktober", "November", "December"][x-1])

# Avtomatski izračun dni in prvega dne v tednu (0=Ponedeljek, 6=Nedelja)
first_day_of_month_weekday, num_days = calendar.monthrange(leto, mesec)

# --- 2. UPRAVLJANJE ZAPOSLENIH IN ODDELKOV ---
st.header("2. Ekipa (Oddelek 1, Oddelek 2 in Nočna ekipa)")
st.info("💡 Dodeli vsakemu zaposlenemu njegov oddelek. Ekipa 'Nočni bazen' krije oba oddelka ponoči.")

if 'staff_df' not in st.session_state:
    initial_staff = [
        {"ID": 0, "Ime": "Vodja (Uroš)", "Oddelek": "Oddelek 2", "Vloga": "Manager", "Tedenske_ure": 40.0},
        {"ID": 1, "Ime": "DGKP Nočna (Dežurna)", "Oddelek": "Nočni bazen", "Vloga": "DGKP", "Tedenske_ure": 37.0},
        {"ID": 2, "Ime": "DGKP 1 (Odd 2)", "Oddelek": "Oddelek 2", "Vloga": "DGKP", "Tedenske_ure": 37.0},
        {"ID": 3, "Ime": "DGKP 1 (Odd 1)", "Oddelek": "Oddelek 1", "Vloga": "DGKP", "Tedenske_ure": 37.0},
        {"ID": 4, "Ime": "DGKP 2 (Odd 1)", "Oddelek": "Oddelek 1", "Vloga": "DGKP", "Tedenske_ure": 37.0},
    ]
    # Dodamo nekaj tehnikov za Odd 1 in Odd 2
    for i in range(1, 6):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"Tehnik O1-{i}", "Oddelek": "Oddelek 1", "Vloga": "Tehnik", "Tedenske_ure": 37.0})
    for i in range(1, 6):
        initial_staff.append({"ID": len(initial_staff), "Ime": f"Tehnik O2-{i}", "Oddelek": "Oddelek 2", "Vloga": "Tehnik", "Tedenske_ure": 37.0})
    
    st.session_state.staff_df = pd.DataFrame(initial_staff)

edited_df = st.data_editor(
    st.session_state.staff_df, 
    num_rows="dynamic",
    column_config={
        "Oddelek": st.column_config.SelectboxColumn("Oddelek", options=["Oddelek 1", "Oddelek 2", "Nočni bazen"], required=True),
        "Vloga": st.column_config.SelectboxColumn("Vloga", options=["Manager", "DGKP", "Tehnik"], required=True),
        "Tedenske_ure": st.column_config.NumberColumn("Tedenske ure", min_value=10.0, max_value=40.0, required=True)
    },
    use_container_width=True
)
st.session_state.staff_df = edited_df

if 'absences' not in st.session_state:
    st.session_state.absences = []

# --- 3. TOČEN VNOS ODSOTNOSTI (S KOLEDARJEM) ---
st.header("3. Vnos odsotnosti")
with st.form("absence_form"):
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        emp_name = st.selectbox("Zaposleni:", options=edited_df["Ime"].tolist())
    with col_f2:
        # Sedaj lahko uporabnik izbere točne datume na pravem koledarju
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
    st.write("📋 Trenutne odsotnosti:")
    st.dataframe(abs_df[["emp_name", "Datum", "reason"]], use_container_width=True)
    if st.button("🗑️ Izbriši vse odsotnosti"):
        st.session_state.absences = []
        st.rerun()

st.divider()

# --- 4. GENERIRANJE URNIKA ---
st.header("4. Avtomatska generacija")
if st.button("🚀 Izračunaj urnik (Fleksibilne ure)", type="primary", use_container_width=True):
    
    staff_list = edited_df.to_dict('records')
    
    with st.spinner("AI išče najboljšo kombinacijo in razporeja nadure..."):
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

        # Kategorizacija
        o1_tehniki = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek 1" and s["Vloga"] == "Tehnik"]
        o2_tehniki = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek 2" and s["Vloga"] == "Tehnik"]
        o1_dgkp = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek 1" and s["Vloga"] in ["DGKP", "Manager"]]
        o2_dgkp = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek 2" and s["Vloga"] in ["DGKP", "Manager"]]
        nocni_dgkp = [s["ID"] for s in staff_list if s["Vloga"] == "DGKP"] # Vsi DGKP lahko delajo nočno (sistem bo sam izbral)

        # Pravila pokritja za vsak dan
        for d in range(num_days):
            day_of_week = (d + first_day_of_month_weekday) % 7
            
            # --- DNEVNA IZMena ---
            # Oddelek 1: 2 DGKP in 4 Tehniki (prilagojeno za testiranje)
            if len(o1_dgkp) >= 2: model.Add(sum(work[(e, d, sh)] for e in o1_dgkp for sh in ['D1', 'D3', 'D4']) >= 2)
            if len(o1_tehniki) >= 4: model.Add(sum(work[(e, d, sh)] for e in o1_tehniki for sh in ['D1', 'D3', 'D4']) >= 4)
            
            # Oddelek 2: 1 DGKP in 4 Tehniki
            if len(o2_dgkp) >= 1: model.Add(sum(work[(e, d, sh)] for e in o2_dgkp for sh in ['D1', 'D3', 'D4']) >= 1)
            if len(o2_tehniki) >= 4: model.Add(sum(work[(e, d, sh)] for e in o2_tehniki for sh in ['D1', 'D3', 'D4']) >= 4)
            
            # --- NOČNA IZMena ---
            # Skupno 1 DGKP za oba oddelka (izbere izmed vseh razpoložljivih DGKP, preferenčno iz Nočnega bazena)
            model.Add(sum(work[(e, d, 'N')] for e in nocni_dgkp) == 1)
            
            # 1 Tehnik iz O1 in 1 Tehnik iz O2
            if len(o1_tehniki) > 0: model.Add(sum(work[(e, d, 'N')] for e in o1_tehniki) == 1)
            if len(o2_tehniki) > 0: model.Add(sum(work[(e, d, 'N')] for e in o2_tehniki) == 1)
            
        # Počitek po nočni
        for s in staff_list:
            for d in range(num_days - 1):
                model.AddImplication(work[(s["ID"], d, 'N')], work[(s["ID"], d + 1, 'OFF')])

        # MEHKE OMEJITVE ZA URE (Soft Constraints)
        hour_deviations = []
        for s in staff_list:
            target = int((s["Tedenske_ure"] / 7.0) * num_days * 100)
            total_hours = model.NewIntVar(0, 35000, f'tot_{s["ID"]}')
            model.Add(total_hours == sum(work[(s["ID"], d, sh)] * shifts[sh] for d in range(num_days) for sh in shifts.keys()))
            
            dev = model.NewIntVar(0, 20000, f'dev_{s["ID"]}')
            model.Add(dev >= total_hours - target)
            model.Add(dev >= target - total_hours)
            
            # Zaposlene v 'Nočnem bazenu' silimo, da raje delajo nočne, tako da kaznujemo dnevne
            if s["Oddelek"] == "Nočni bazen":
                penalty = model.NewIntVar(0, 10000, f'pen_{s["ID"]}')
                model.Add(penalty == sum(work[(s["ID"], d, sh)] for d in range(num_days) for sh in ['D1', 'D3', 'D4']) * 100)
                hour_deviations.append(penalty)
                
            hour_deviations.append(dev)

        # Minimiziramo odstopanja od ur in kazni (To zagotovi, da vedno zgenerira urnik!)
        model.Minimize(sum(hour_deviations))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 45.0
        status = solver.Solve(model)

        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            st.success("🎉 Urnik je zgeneriran!")
            
            data = []
            for s in staff_list:
                row = {"Oddelek": s["Oddelek"], "Vloga": s["Vloga"], "Zaposleni": s["Ime"]}
                total_hours = 0
                for d in range(num_days):
                    for sh in shifts.keys():
                        if solver.Value(work[(s["ID"], d, sh)]) == 1:
                            val = sh if sh != 'OFF' else 'X'
                            for a in st.session_state.absences:
                                if a["emp_id"] == s["ID"] and a["day"] == d:
                                    val = a["reason"].split(" ")[0]
                            row[f"{d+1}."] = val
                            total_hours += shifts[sh]
                
                target_hrs = (s["Tedenske_ure"] / 7.0) * num_days
                row["FOND"] = round(target_hrs, 1)
                row["PLANIRANO"] = total_hours / 100
                row["RAZLIKA"] = round((total_hours / 100) - target_hrs, 1)
                data.append(row)
            
            df_rezultat = pd.DataFrame(data)
            
            # Funkcija za barvanje presežkov in mankov
            def highlight_hours(val):
                if isinstance(val, (int, float)):
                    if val > 12: return 'background-color: #ffcccc; color: #990000; font-weight: bold' # Rdeča (Preveč ur)
                    elif val < -12: return 'background-color: #ccccff; color: #000099; font-weight: bold' # Modra (Premalo ur)
                return ''
            
            st.dataframe(df_rezultat.style.applymap(highlight_hours, subset=['RAZLIKA']), use_container_width=True)
            
            csv = df_rezultat.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Prenesi urnik (CSV)",
                data=csv,
                file_name=f'urnik_{mesec}_{leto}.csv',
                mime='text/csv',
            )
        else:
            st.error("🚨 Kljub popuščanju pravil sistem fizično nima dovolj ljudi. Dodaj tehnike v tabelo zgoraj!")
