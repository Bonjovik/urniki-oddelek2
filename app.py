import streamlit as st
import pandas as pd
from ortools.sat.python import cp_model

st.set_page_config(page_title="AI Urniki PRO - Oddelek 2", layout="wide")

st.title("🏥 AI Sistem za planiranje urnikov (PRO VERZIJA)")
st.markdown("Napreden sistem z upoštevanjem različnih pogodb o zaposlitvi in zakonskih počitkov.")

# --- 1. UPRAVLJANJE ZAPOSLENIH (Tabela) ---
st.header("1. Ekipa in pogodbe (Tedenske ure)")
st.info("💡 V tabeli lahko poljubno popravljaš imena, spreminjaš tedenske ure in dodajaš/brišeš zaposlene. Izberi vlogo: Manager, DGKP ali Tehnik.")

# Začetni podatki (če jih še ni v spominu)
if 'staff_df' not in st.session_state:
    initial_staff = [
        {"ID": 0, "Ime": "Vodja (Uroš)", "Vloga": "Manager", "Tedenske_ure": 40.0},
        {"ID": 1, "Ime": "DGKP 1 (Polni)", "Vloga": "DGKP", "Tedenske_ure": 37.0},
        {"ID": 2, "Ime": "DGKP 2 (Nočne)", "Vloga": "DGKP", "Tedenske_ure": 37.0},
    ]
    # Dodamo nekaj tehnikov za primer (en s 32 urami)
    initial_staff.append({"ID": 3, "Ime": "Tehnik 1 (Skrajšan)", "Vloga": "Tehnik", "Tedenske_ure": 32.0})
    for i in range(4, 15):
        initial_staff.append({"ID": i, "Ime": f"Tehnik {i-2}", "Vloga": "Tehnik", "Tedenske_ure": 37.0})
    
    st.session_state.staff_df = pd.DataFrame(initial_staff)

# Uporabnik lahko ureja tabelo na ekranu
edited_df = st.data_editor(
    st.session_state.staff_df, 
    num_rows="dynamic",
    column_config={
        "Vloga": st.column_config.SelectboxColumn("Vloga", options=["Manager", "DGKP", "Tehnik"], required=True),
        "Tedenske_ure": st.column_config.NumberColumn("Tedenske ure (npr. 37)", min_value=10.0, max_value=40.0, required=True)
    },
    use_container_width=True
)

# Shranimo popravke
st.session_state.staff_df = edited_df

if 'absences' not in st.session_state:
    st.session_state.absences = []

# --- 2. NASTAVITVE MESECA IN DOPUSTOV ---
col1, col2 = st.columns([1, 1])

with col1:
    st.header("2. Nastavitve meseca")
    num_days = st.number_input("Število dni v mesecu:", min_value=28, max_value=31, value=30)
    first_day = st.selectbox("Prvi dan v mesecu je:", 
                             options=[0, 1, 2, 3, 4, 5, 6], 
                             format_func=lambda x: ["Ponedeljek", "Torek", "Sreda", "Četrtek", "Petek", "Sobota", "Nedelja"][x])

with col2:
    st.header("3. Vnos odsotnosti")
    with st.form("absence_form"):
        emp_name = st.selectbox("Izberi zaposlenega:", options=edited_df["Ime"].tolist())
        # Sedaj lahko uporabnik izbere več dni hkrati!
        days_off = st.multiselect("Izberi dneve v mesecu:", options=list(range(1, num_days + 1)))
        reason = st.selectbox("Razlog:", ["DOP (Dopust)", "BOL (Bolniška)", "ROJ (Rojstni dan)", "ENT (Entlastung)"])
        
        submitted = st.form_submit_button("Dodaj odsotnosti")
        if submitted and days_off:
            emp_id = edited_df.loc[edited_df["Ime"] == emp_name, "ID"].values[0]
            for d in days_off:
                st.session_state.absences.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "reason": reason})
            st.success(f"Odsotnosti dodane za {emp_name}!")

# Prikaz in brisanje odsotnosti
if st.session_state.absences:
    st.write("📋 **Trenutno vpisane odsotnosti:**")
    abs_df = pd.DataFrame(st.session_state.absences)
    abs_df["Dan v mesecu"] = abs_df["day"] + 1
    st.dataframe(abs_df[["emp_name", "Dan v mesecu", "reason"]], use_container_width=True)
    if st.button("🗑️ Izbriši vse odsotnosti"):
        st.session_state.absences = []
        st.rerun()

st.divider()

# --- 3. GENERIRANJE URNIKA ---
st.header("4. Generiranje")
if st.button("🚀 Izračunaj zakonit urnik", type="primary", use_container_width=True):
    
    # Pridobivanje podatkov iz tabele
    staff_list = edited_df.to_dict('records')
    manager_ids = [s["ID"] for s in staff_list if s["Vloga"] == "Manager"]
    dgkp_ids = [s["ID"] for s in staff_list if s["Vloga"] == "DGKP"]
    tehnik_ids = [s["ID"] for s in staff_list if s["Vloga"] == "Tehnik"]
    
    if len(manager_ids) + len(dgkp_ids) + len(tehnik_ids) == 0:
        st.error("Tabela zaposlenih je prazna ali vloge niso pravilno nastavljene!")
        st.stop()

    with st.spinner("Matematični model preračunava optimalne kombinacije (traja do 30 sek)..."):
        model = cp_model.CpModel()
        shifts = {'D1': 1200, 'D3': 825, 'D4': 1100, 'N': 1350, 'OFF': 0}
        
        work = {}
        for s in staff_list:
            for d in range(num_days):
                for sh in shifts.keys():
                    work[(s["ID"], d, sh)] = model.NewBoolVar(f'work_{s["ID"]}_{d}_{sh}')
        
        # 1 izmena na dan
        for s in staff_list:
            for d in range(num_days):
                model.AddExactlyOne(work[(s["ID"], d, sh)] for sh in shifts.keys())
        
        # Odsotnosti
        for a in st.session_state.absences:
            if a["day"] < num_days:
                model.Add(work[(a["emp_id"], a["day"], 'OFF')] == 1)

        # Vodja pravilo
        for d in range(num_days):
            day_of_week = (d + first_day) % 7
            for mid in manager_ids:
                if day_of_week >= 5:
                    model.Add(work[(mid, d, 'OFF')] == 1)
                else:
                    model.Add(work[(mid, d, 'D3')] == 1)

        # Pokritje
        for d in range(num_days):
            model.Add(sum(work[(e, d, sh)] for e in manager_ids + dgkp_ids for sh in ['D1', 'D3', 'D4']) == 1)
            model.Add(sum(work[(e, d, sh)] for e in tehnik_ids for sh in ['D1', 'D3', 'D4']) == 4)
            if dgkp_ids: model.Add(sum(work[(e, d, 'N')] for e in dgkp_ids) == 1)
            if tehnik_ids: model.Add(sum(work[(e, d, 'N')] for e in tehnik_ids) == 1)
            # Predaja 19:15
            model.Add(sum(work[(e, d, 'D1')] for e in manager_ids + dgkp_ids) >= 1)

        # Počitek po nočni
        for s in staff_list:
            for d in range(num_days - 1):
                model.AddImplication(work[(s["ID"], d, 'N')], work[(s["ID"], d + 1, 'OFF')])

        # Ciljne ure glede na zaposlitev
        hour_deviations = []
        for s in staff_list:
            # Izračun ciljnih ur: (tedenske ure / 7 dni) * število dni v mesecu
            # Npr. (37 / 7) * 30 = 158.5 ur. Množimo s 100 za matematiko v kodi.
            target = int((s["Tedenske_ure"] / 7.0) * num_days * 100)
            
            total_hours = model.NewIntVar(0, 35000, f'tot_{s["ID"]}')
            model.Add(total_hours == sum(work[(s["ID"], d, sh)] * shifts[sh] for d in range(num_days) for sh in shifts.keys()))
            
            dev = model.NewIntVar(0, 15000, f'dev_{s["ID"]}')
            model.Add(dev >= total_hours - target)
            model.Add(dev >= target - total_hours)
            hour_deviations.append(dev)

        # Želimo čim manjša odstopanja od ciljnih ur vseh delavcev
        model.Minimize(sum(hour_deviations))

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 30.0
        status = solver.Solve(model)

        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            st.success("🎉 Urnik uspešno zgeneriran!")
            
            data = []
            for s in staff_list:
                row = {"Vloga": s["Vloga"], "Zaposleni": s["Ime"]}
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
                row["FOND UR"] = round(target_hrs, 1)
                row["PLANIRANO"] = total_hours / 100
                row["RAZLIKA"] = round((total_hours / 100) - target_hrs, 1)
                data.append(row)
            
            df_rezultat = pd.DataFrame(data)
            
            # Barvanje razlik (preveč/premalo ur)
            def color_diff(val):
                if isinstance(val, (int, float)):
                    if val > 10: return 'background-color: #ffcccc; color: black'
                    elif val < -10: return 'background-color: #ccccff; color: black'
                return ''
            
            st.dataframe(df_rezultat.style.applymap(color_diff, subset=['RAZLIKA']), use_container_width=True)
            
            csv = df_rezultat.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Prenesi urnik za Geocon (CSV)",
                data=csv,
                file_name='napredni_urnik_oddelek2.csv',
                mime='text/csv',
            )
        else:
            st.error("🚨 Sistem ni našel možne rešitve. Verjetno si planiral preveč dopustov in zmanjka kadra za dnevni minimum! Zmanjšaj število odsotnosti ali dodaj delavce v tabelo.")
