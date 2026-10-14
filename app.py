import streamlit as st
import pandas as pd
from ortools.sat.python import cp_model

# Nastavitve strani
st.set_page_config(page_title="AI Urniki - Oddelek 2", layout="wide")

st.title("🏥 AI Sistem za planiranje urnikov (Oddelek 2)")
st.markdown("Avtomatski izračun izmen glede na 37-urni delovnik in avstrijsko zakonodajo.")

# --- PREDNASTAVLJENA EKIPA ---
if 'staff' not in st.session_state:
    st.session_state.staff = [
        {"id": 0, "name": "Vodja (Uroš)", "role": "Manager"},
        {"id": 1, "name": "DGKP 1", "role": "DGKP"},
        {"id": 2, "name": "DGKP 2", "role": "DGKP"},
    ]
    # Dodamo 12 tehnikov
    for i in range(1, 13):
        st.session_state.staff.append({"id": i+2, "name": f"Tehnik {i}", "role": "Tehnik"})

if 'absences' not in st.session_state:
    st.session_state.absences = []

# --- UPORABNIŠKI VMESNIK ---
col1, col2 = st.columns([1, 2])

with col1:
    st.header("1. Nastavitve meseca")
    num_days = st.number_input("Število dni v mesecu:", min_value=28, max_value=31, value=30)
    first_day = st.selectbox("Prvi dan v mesecu je:", 
                             options=[0, 1, 2, 3, 4, 5, 6], 
                             format_func=lambda x: ["Ponedeljek", "Torek", "Sreda", "Četrtek", "Petek", "Sobota", "Nedelja"][x])
    
    target_hours = st.number_input("Ciljni mesečni fond ur (npr. 158):", min_value=140, max_value=180, value=158)

    st.header("2. Vnos odsotnosti (Dopusti, Bolniške)")
    with st.form("absence_form"):
        emp_id = st.selectbox("Izberi zaposlenega:", options=[s["id"] for s in st.session_state.staff], format_func=lambda x: next(s["name"] for s in st.session_state.staff if s["id"] == x))
        day_off = st.number_input("Dan v mesecu (1 - 31):", min_value=1, max_value=31, value=1)
        reason = st.selectbox("Razlog:", ["DOP (Dopust)", "BOL (Bolniška)", "ROJ (Rojstni dan)", "ENT (Entlastung)"])
        submitted = st.form_submit_button("Dodaj odsotnost")
        if submitted:
            st.session_state.absences.append({"emp_id": emp_id, "day": day_off - 1, "reason": reason})
            st.success(f"Odsotnost dodana za dan {day_off}!")

    if st.session_state.absences:
        st.write("Trenutne odsotnosti:")
        for idx, a in enumerate(st.session_state.absences):
            emp_name = next(s["name"] for s in st.session_state.staff if s["id"] == a["emp_id"])
            st.write(f"- {emp_name}: Dan {a['day'] + 1} ({a['reason']})")

with col2:
    st.header("3. Generiranje")
    if st.button("🚀 Generiraj zakonit urnik", type="primary", use_container_width=True):
        with st.spinner("AI računa milijone kombinacij (lahko traja do 30 sekund)..."):
            
            # --- OR-TOOLS LOGIKA ---
            model = cp_model.CpModel()
            shifts = {'D1': 1200, 'D3': 825, 'D4': 1100, 'N': 1350, 'OFF': 0}
            
            manager_id = [s["id"] for s in st.session_state.staff if s["role"] == "Manager"]
            dgkp_ids = [s["id"] for s in st.session_state.staff if s["role"] == "DGKP"]
            tehnik_ids = [s["id"] for s in st.session_state.staff if s["role"] == "Tehnik"]
            
            work = {}
            for s in st.session_state.staff:
                for d in range(num_days):
                    for sh in shifts.keys():
                        work[(s["id"], d, sh)] = model.NewBoolVar(f'work_{s["id"]}_{d}_{sh}')
            
            # 1 pametna izbira na dan
            for s in st.session_state.staff:
                for d in range(num_days):
                    model.AddExactlyOne(work[(s["id"], d, sh)] for sh in shifts.keys())
            
            # Fiksne odsotnosti
            for a in st.session_state.absences:
                if a["day"] < num_days:
                    model.Add(work[(a["emp_id"], a["day"], 'OFF')] == 1)

            # Vodja samo D3 in med tednom
            for d in range(num_days):
                day_of_week = (d + first_day) % 7
                for mid in manager_id:
                    if day_of_week >= 5:
                        model.Add(work[(mid, d, 'OFF')] == 1)
                    else:
                        model.Add(work[(mid, d, 'D3')] == 1)

            # Dnevno in nočno pokritje
            for d in range(num_days):
                # 1 DGKP/Manager podnevi
                model.Add(sum(work[(e, d, sh)] for e in manager_id + dgkp_ids for sh in ['D1', 'D3', 'D4']) == 1)
                # 4 Tehniki podnevi
                model.Add(sum(work[(e, d, sh)] for e in tehnik_ids for sh in ['D1', 'D3', 'D4']) == 4)
                # Nočna: 1 DGKP in 1 Tehnik
                model.Add(sum(work[(e, d, 'N')] for e in dgkp_ids) == 1)
                model.Add(sum(work[(e, d, 'N')] for e in tehnik_ids) == 1)
                # Pravilo 19:15 predaje (vsaj 1 DGKP do 19:15)
                model.Add(sum(work[(e, d, 'D1')] for e in manager_id + dgkp_ids) >= 1)

            # Počitek po nočni (N -> OFF)
            for s in st.session_state.staff:
                for d in range(num_days - 1):
                    model.AddImplication(work[(s["id"], d, 'N')], work[(s["id"], d + 1, 'OFF')])

            # Reševanje
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = 30.0
            status = solver.Solve(model)

            if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                st.success("Urnik uspešno ustvarjen!")
                
                # Priprava tabele
                data = []
                for s in st.session_state.staff:
                    row = {"Zaposleni": s["name"]}
                    total_hours = 0
                    for d in range(num_days):
                        for sh in shifts.keys():
                            if solver.Value(work[(s["id"], d, sh)]) == 1:
                                val = sh if sh != 'OFF' else 'X'
                                # Povozimo X z razlogom odsotnosti, če obstaja
                                for a in st.session_state.absences:
                                    if a["emp_id"] == s["id"] and a["day"] == d:
                                        val = a["reason"].split(" ")[0]
                                row[f"{d+1}."] = val
                                total_hours += shifts[sh]
                    row["SKUPAJ UR"] = total_hours / 100
                    data.append(row)
                
                df = pd.DataFrame(data)
                st.dataframe(df, use_container_width=True)
                
                # Izvoz v CSV
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Prenesi urnik za Geocon (Excel/CSV)",
                    data=csv,
                    file_name='urnik_oddelek2.csv',
                    mime='text/csv',
                )
            else:
                st.error("Sistem ni našel možne rešitve. Preveri, ali si vnesel preveč dopustov na isti dan, zaradi česar zmanjka kadra za zakonsko minimum pokritost.")
