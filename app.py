import streamlit as st
import pandas as pd
import calendar
from datetime import date
from ortools.sat.python import cp_model

st.set_page_config(page_title="AI Urniki PRO 6.0", layout="wide")

st.title("🏥 Centralni AI Sistem (Verzija 6.0)")
st.markdown("Prilagodljive izmene, določanje števila nočnih, delovnih dni in posebne izmene (Jedilnica).")

# --- 1. KOLEDAR IN NASTAVITVE MESECA ---
st.header("1. Izbira meseca in leta")
col_date1, col_date2 = st.columns(2)
with col_date1:
    leto = st.selectbox("Leto:", [2026, 2027, 2028], index=0)
with col_date2:
    mesec = st.selectbox("Mesec:", list(range(1, 13)), format_func=lambda x: ["Januar", "Februar", "Marec", "April", "Maj", "Junij", "Julij", "Avgust", "September", "Oktober", "November", "December"][x-1])

first_day_of_month_weekday, num_days = calendar.monthrange(leto, mesec)

# --- 2. UPRAVLJANJE ZAPOSLENIH IN ODDELKOV ---
st.header("2. Ekipa in individualne nastavitve")
st.info("💡 Nastavi želene dneve dela, največje število nočnih ali posebne izmene (npr. Jedilnica za bolničarje ali Samo nočne za Oddelek F).")

if 'staff_df' not in st.session_state:
    initial_staff = []
    
    # Vodja
    initial_staff.append({
        "ID": 0, "Ime": "Vodja (Uroš)", "Oddelek": "Oddelek H", "Vloga": "Manager", 
        "Ure": 40.0, "Max_Nocnih": 0, "Dnevi_dela": "Samo Pon-Pet", "Posebno": "Brez"
    })
    
    # Oddelek F (Nočni bazen) - npr. 3 DGKP, ki delajo samo 3-4 nočne na mesec
    for i in range(1, 4):
        initial_staff.append({
            "ID": len(initial_staff), "Ime": f"DGKP F-{i} (Bazen)", "Oddelek": "Oddelek F", "Vloga": "DGKP", 
            "Ure": 37.0, "Max_Nocnih": 4, "Dnevi_dela": "Vsi dnevi", "Posebno": "Samo nočne (brez dnevnih)"
        })
        
    # Oddelek B (DGKP) - 4 osobe
    for i in range(1, 5):
        initial_staff.append({
            "ID": len(initial_staff), "Ime": f"DGKP B-{i}", "Oddelek": "Oddelek B", "Vloga": "DGKP", 
            "Ure": 37.0, "Max_Nocnih": 0, "Dnevi_dela": "Vsi dnevi", "Posebno": "Brez"
        })
        
    # Oddelek H (DGKP) - 4 osobe (ena SM izmena)
    initial_staff.append({
        "ID": len(initial_staff), "Ime": "DGKP H-1 (SM izmena)", "Oddelek": "Oddelek H", "Vloga": "DGKP", 
        "Ure": 37.0, "Max_Nocnih": 0, "Dnevi_dela": "Vsi dnevi", "Posebno": "SM (7:45-18:15)"
    })
    for i in range(2, 5):
        initial_staff.append({
            "ID": len(initial_staff), "Ime": f"DGKP H-{i}", "Oddelek": "Oddelek H", "Vloga": "DGKP", 
            "Ure": 37.0, "Max_Nocnih": 0, "Dnevi_dela": "Vsi dnevi", "Posebno": "Brez"
        })

    # Oddelek B (3 Bolničarji za Jedilnico 6:30-18:00)
    for i in range(1, 4):
        initial_staff.append({
            "ID": len(initial_staff), "Ime": f"Bolničar B-{i} (Jedilnica)", "Oddelek": "Oddelek B", "Vloga": "Bolničar", 
            "Ure": 37.0, "Max_Nocnih": 0, "Dnevi_dela": "Vsi dnevi", "Posebno": "Jedilnica JED (6:30-18:00)"
        })
        
    # Oddelek B (Tehniki) - 11 oseb (ena noseča)
    initial_staff.append({
        "ID": len(initial_staff), "Ime": "Tehnik B-1 (Noseča)", "Oddelek": "Oddelek B", "Vloga": "Tehnik", 
        "Ure": 37.0, "Max_Nocnih": 0, "Dnevi_dela": "Samo Pon-Pet", "Posebno": "Mutterschutz (7:30-15:00)"
    })
    for i in range(2, 12):
        initial_staff.append({
            "ID": len(initial_staff), "Ime": f"Tehnik B-{i}", "Oddelek": "Oddelek B", "Vloga": "Tehnik", 
            "Ure": 37.0, "Max_Nocnih": 5, "Dnevi_dela": "Vsi dnevi", "Posebno": "Brez"
        })

    # Oddelek H (Tehniki) - 14 oseb
    for i in range(1, 15):
        initial_staff.append({
            "ID": len(initial_staff), "Ime": f"Tehnik H-{i}", "Oddelek": "Oddelek H", "Vloga": "Tehnik", 
            "Ure": 37.0, "Max_Nocnih": 5, "Dnevi_dela": "Vsi dnevi", "Posebno": "Brez"
        })
    
    st.session_state.staff_df = pd.DataFrame(initial_staff)

edited_df = st.data_editor(
    st.session_state.staff_df, 
    num_rows="dynamic",
    key="tabela_zaposlenih_v6",
    column_config={
        "Oddelek": st.column_config.SelectboxColumn("Oddelek", options=["Oddelek B", "Oddelek H", "Oddelek F"], required=True),
        "Vloga": st.column_config.SelectboxColumn("Vloga", options=["Manager", "DGKP", "Tehnik", "Bolničar"], required=True),
        "Ure": st.column_config.NumberColumn("Tedenske ure", min_value=10.0, max_value=40.0, required=True),
        "Max_Nocnih": st.column_config.NumberColumn("Max nočnih/mesec", min_value=0, max_value=15, default=0),
        "Dnevi_dela": st.column_config.SelectboxColumn("Dnevi dela", options=["Vsi dnevi", "Samo Pon-Pet", "Samo Vikendi", "Tor-Sre-Čet"], required=True),
        "Posebno": st.column_config.SelectboxColumn("Posebni urnik", options=["Brez", "Jedilnica JED (6:30-18:00)", "Mutterschutz (7:30-15:00)", "SM (7:45-18:15)", "Samo nočne (brez dnevnih)"], required=True)
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
if st.button("🚀 Izračunaj urnik s prilagojenimi pravili", type="primary", use_container_width=True):
    staff_list = edited_df.to_dict('records')
    
    try:
        with st.spinner("Računam urnik z upoštevanjem posebnih želja, jedilnice in omejitev nočnih..."):
            model = cp_model.CpModel()
            
            # ŠIFRE IN VREDNOSTI (ure * 100)
            shifts = {
                'X4': 825,    # do 15:30
                'X6': 1100,   # do 18:15
                'X7': 1200,   # do 19:15
                'N1': 1350,   # Nočna DGKP (11.5 + 2h bonus)
                'N2': 1350,   # Nočna Tehnik
                'JED': 1050,  # Jedilnica 06:30 - 18:00 (10.5 h net)
                'MS': 700,    # Mutterschutz 7:30-15:00
                'SM': 1000,   # SM 7:45-18:15
                'OFF': 0
            }
            
            work = {}
            for s in staff_list:
                for d in range(num_days):
                    for sh in shifts.keys():
                        work[(s["ID"], d, sh)] = model.NewBoolVar(f'work_{s["ID"]}_{d}_{sh}')
            
            # Točno 1 izmena na dan
            for s in staff_list:
                for d in range(num_days):
                    model.Add(sum(work[(s["ID"], d, sh)] for sh in shifts.keys()) == 1)
            
            # DOLOČITEV DOVOLJENIH IZMEN ZA POSAMEZNIKA
            for s in staff_list:
                allowed_shifts = ['OFF']
                
                # Posebni urniki
                if s["Posebno"] == "Jedilnica JED (6:30-18:00)":
                    allowed_shifts.append('JED')
                elif s["Posebno"] == "Mutterschutz (7:30-15:00)":
                    allowed_shifts.append('MS')
                elif s["Posebno"] == "SM (7:45-18:15)":
                    allowed_shifts.append('SM')
                elif s["Posebno"] == "Samo nočne (brez dnevnih)":
                    if s["Vloga"] == "DGKP":
                        allowed_shifts.append('N1')
                    else:
                        allowed_shifts.append('N2')
                elif s["Vloga"] == "Manager":
                    allowed_shifts.append('X4') 
                else:
                    # Standardne dnevne izmene
                    allowed_shifts.extend(['X4', 'X6', 'X7']) 
                    if s["Max_Nocnih"] > 0:
                        if s["Vloga"] == "DGKP":
                            allowed_shifts.append('N1')
                        elif s["Vloga"] in ["Tehnik", "Bolničar"]:
                            allowed_shifts.append('N2')
                
                # Prepoved nedovoljenih izmen
                unallowed = [sh for sh in shifts.keys() if sh not in allowed_shifts]
                for d in range(num_days):
                    for sh in unallowed:
                        model.Add(work[(s["ID"], d, sh)] == 0)

                # OMEJITEV MAKSIMALNEGA ŠTEVILA NOČNIH
                if s["Max_Nocnih"] >= 0:
                    nocna_koda = 'N1' if s["Vloga"] == "DGKP" else 'N2'
                    model.Add(sum(work[(s["ID"], d, nocna_koda)] for d in range(num_days)) <= int(s["Max_Nocnih"]))

                # DNEVI DELA (Omejitve prisotnosti po dnevih v tednu)
                for d in range(num_days):
                    day_of_week = (d + first_day_of_month_weekday) % 7 # 0=Pon, 5=Sob, 6=Ned
                    
                    if s["Dnevi_dela"] == "Samo Pon-Pet" and day_of_week >= 5:
                        model.Add(work[(s["ID"], d, 'OFF')] == 1)
                    elif s["Dnevi_dela"] == "Samo Vikendi" and day_of_week < 5:
                        model.Add(work[(s["ID"], d, 'OFF')] == 1)
                    elif s["Dnevi_dela"] == "Tor-Sre-Čet" and day_of_week not in [1, 2, 3]:
                        model.Add(work[(s["ID"], d, 'OFF')] == 1)

            # Dopusti
            for a in st.session_state.absences:
                if a["day"] < num_days:
                    model.Add(work[(a["emp_id"], a["day"], 'OFF')] == 1)

            # DNEVNA POKRITOST PO ODDELKIH
            oB_tehniki = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek B" and s["Vloga"] in ["Tehnik", "Bolničar"]]
            oH_tehniki = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek H" and s["Vloga"] in ["Tehnik", "Bolničar"]]
            all_dgkp = [s["ID"] for s in staff_list if s["Vloga"] in ["DGKP", "Manager"]]
            jedilnica_kadri = [s["ID"] for s in staff_list if s["Posebno"] == "Jedilnica JED (6:30-18:00)"]

            day_shifts = ['X4', 'X6', 'X7', 'MS', 'SM', 'JED']

            for d in range(num_days):
                # 1. Pokritost Jedilnice (Obvezno 1 bolničar na JED vsak dan)
                if len(jedilnica_kadri) > 0:
                    model.Add(sum(work[(e, d, 'JED')] for e in jedilnica_kadri) == 1)

                # 2. Dnevna pokritost tehnikov
                if len(oB_tehniki) >= 3: model.Add(sum(work[(e, d, sh)] for e in oB_tehniki for sh in day_shifts) >= 4)
                if len(oH_tehniki) >= 3: model.Add(sum(work[(e, d, sh)] for e in oH_tehniki for sh in day_shifts) >= 4)
                
                # 3. Nočne izmene (1 DGKP na N1 celotna enota, 1 Tehnik N2 na Odd B, 1 Tehnik N2 na Odd H)
                dgkp_nocni = [s["ID"] for s in staff_list if s["Vloga"] == "DGKP" and (s["Max_Nocnih"] > 0 or s["Posebno"] == "Samo nočne (brez dnevnih)")]
                if len(dgkp_nocni) > 0: model.Add(sum(work[(e, d, 'N1')] for e in dgkp_nocni) == 1)
                
                tech_nocni_B = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek B" and s["Vloga"] in ["Tehnik", "Bolničar"] and s["Max_Nocnih"] > 0]
                if len(tech_nocni_B) > 0: model.Add(sum(work[(e, d, 'N2')] for e in tech_nocni_B) == 1)
                
                tech_nocni_H = [s["ID"] for s in staff_list if s["Oddelek"] == "Oddelek H" and s["Vloga"] in ["Tehnik", "Bolničar"] and s["Max_Nocnih"] > 0]
                if len(tech_nocni_H) > 0: model.Add(sum(work[(e, d, 'N2')] for e in tech_nocni_H) == 1)
                
                # 4. Predaja 19:15 (X7 izmena)
                if len(all_dgkp) > 0: model.Add(sum(work[(e, d, 'X7')] for e in all_dgkp) >= 1)

            # POČITEK PO NOČNI
            for s in staff_list:
                for d in range(num_days - 1):
                    model.AddImplication(work[(s["ID"], d, 'N1')], work[(s["ID"], d + 1, 'OFF')])
                    model.AddImplication(work[(s["ID"], d, 'N2')], work[(s["ID"], d + 1, 'OFF')])

            # OPTIMIZACIJA UR (Prilagoditev ciljnih ur)
            for s in staff_list:
                # Če dela samo nočne, se cilj ur prilagodi zgolj nočnim izmenam
                if s["Posebno"] == "Samo nočne (brez dnevnih)":
                    continue # Ne silimo ga v dnevne ure
                
                target = int((s["Ure"] / 7.0) * num_days * 100)
                total_hours = model.NewIntVar(0, 35000, f'tot_{s["ID"]}')
                model.Add(total_hours == sum(work[(s["ID"], d, sh)] * shifts[sh] for d in range(num_days) for sh in shifts.keys()))
                
                min_h = max(0, target - 3500)
                model.Add(total_hours >= min_h)
                model.Add(total_hours <= target + 3500)

            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = 15.0
            status = solver.Solve(model)

            if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                st.success("🎉 Urnik uspešno zgeneriran!")
                
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
                
                st.subheader("🔵 Oddelek B")
                df_b = df_rezultat[df_rezultat["Oddelek"] == "Oddelek B"].drop(columns=["Oddelek"])
                st.dataframe(df_b.style.map(highlight_hours, subset=['RAZLIKA']), use_container_width=True)
                
                st.subheader("🟢 Oddelek H")
                df_h = df_rezultat[df_rezultat["Oddelek"] == "Oddelek H"].drop(columns=["Oddelek"])
                st.dataframe(df_h.style.map(highlight_hours, subset=['RAZLIKA']), use_container_width=True)
                
                st.subheader("🟣 Oddelek F (Nočni bazen)")
                df_f = df_rezultat[df_rezultat["Oddelek"] == "Oddelek F"].drop(columns=["Oddelek"])
                st.dataframe(df_f.style.map(highlight_hours, subset=['RAZLIKA']), use_container_width=True)
                
            else:
                st.error("🚨 Sistem ni našel rešitve. Preveri, ali imajo nočni delavci dovolj visoko številko 'Max nočnih' ali pa je izbranih preveč dopustov.")
    
    except Exception as e:
        st.error(f"⚠️ Sistemska napaka: {e}")
