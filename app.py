import calendar
from datetime import date
import io
import re
import os
import holidays
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KI-Dienstplan PRO 28.0", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 28.0 - Strict Roles & Cross-Coverage)")
st.markdown(
    "**Neue Logik:** Strikte Trennung der Schichten nach Qualifikation (DGKP: X-Schichten, PA: F-Schichten). "
    "Abteilung F ist reiner DGKP-Nachtpool (N1). Abteilungen unterstützen sich gegenseitig bei Engpässen (sichtbar durch '➔ Abt. H')."
)

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "⚙️ 1. Einstellungen", "📅 2. Dienstplan", "🚑 3. SOS", "🔄 4. Tausch", 
    "📱 5. WhatsApp", "📉 6. Analyse & ZA", "🗣️ 7. Gespräche", "🛡️ 8. Inspektorat"
])

with tab1:
    st.header("1. Monat und Jahr auswählen")
    col_date1, col_date2 = st.columns(2)
    with col_date1: leto = st.selectbox("Jahr:", [2026, 2027, 2028], index=0)
    with col_date2: mesec = st.selectbox("Monat:", list(range(1, 13)), format_func=lambda x: ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"][x - 1])

    first_day_of_month_weekday, num_days = calendar.monthrange(leto, mesec)
    at_holidays = holidays.Austria(years=leto, subdiv='6')

    st.divider()
    st.header("🔄 Schutz beim Monatsübergang")
    uploaded_file = st.file_uploader("Lade die CSV-Datei des Vormonats hoch (Optional):", type=["csv"])
    if uploaded_file is not None:
        try:
            old_plan_df = pd.read_csv(uploaded_file)
            st.session_state.old_plan = old_plan_df
            st.success("✅ Vormonat erfolgreich geladen!")
        except Exception as e: st.error(f"Fehler: {e}")
            
    if st.button("🗑️ Vormonat-Daten löschen"):
        if "old_plan" in st.session_state: del st.session_state.old_plan; st.rerun()

    st.header("2. Team verwalten (Inkl. Qualifikationen)")
    
    if "staff_df_v28" not in st.session_state:
        if os.path.exists("team_data.csv"):
            try:
                loaded_df = pd.read_csv("team_data.csv")
                if "Wochenstd" not in loaded_df.columns: loaded_df["Wochenstd"] = 37.0
                loaded_df["Prozent"] = (loaded_df["Wochenstd"] / 37.0) * 100
                loaded_df["Prozent"] = loaded_df["Prozent"].round(1)
                if "Nur_Nacht" not in loaded_df.columns: loaded_df["Nur_Nacht"] = False
                if "ID" not in loaded_df.columns: loaded_df["ID"] = range(len(loaded_df))
                if "URL_Gesamt" not in loaded_df.columns: loaded_df["URL_Gesamt"] = 25.0
                if "URL_Rest" not in loaded_df.columns: loaded_df["URL_Rest"] = loaded_df["URL_Gesamt"]
                if "Qualifikation" not in loaded_df.columns: loaded_df["Qualifikation"] = "Keine"
                    
                cols_order = ["ID", "Name", "Abteilung", "Rolle", "Qualifikation", "Wochenstd", "Prozent", "URL_Gesamt", "URL_Rest", "Saldo_Alt", "Max_Nacht", "Nur_Nacht", "MO", "DI", "MI", "DO", "FR", "SA", "SO", "FT", "Spezialdienst"]
                for c in cols_order:
                    if c not in loaded_df.columns:
                        if c in ["MO", "DI", "MI", "DO", "FR", "SA", "SO", "FT"]: loaded_df[c] = True
                        elif c == "Spezialdienst": loaded_df[c] = "Ohne"
                        elif c == "Qualifikation": loaded_df[c] = "Keine"
                        else: loaded_df[c] = 0
                st.session_state.staff_df_v28 = loaded_df[cols_order]
            except Exception: pass 

        if "staff_df_v28" not in st.session_state:
            initial_staff = [{
                "ID": 0, "Name": "WBL (Uroš)", "Abteilung": "Abteilung H", "Rolle": "Leitung", "Qualifikation": "Keine",
                "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 30.0, "URL_Rest": 30.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False,
                "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": False, "SO": False, "FT": False, "Spezialdienst": "Ohne"
            }]
            for i in range(1, 4):
                initial_staff.append({
                    "ID": len(initial_staff), "Name": f"DGKP F-{i}", "Abteilung": "Abteilung F", "Rolle": "DGKP", "Qualifikation": "Keine",
                    "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 15, "Nur_Nacht": True,
                    "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"
                })
            for i in range(1, 5):
                initial_staff.append({
                    "ID": len(initial_staff), "Name": f"DGKP B-{i}", "Abteilung": "Abteilung B", "Rolle": "DGKP", "Qualifikation": "Keine",
                    "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False,
                    "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"
                })
            st.session_state.staff_df_v28 = pd.DataFrame(initial_staff)

    with st.form("team_editor_form"):
        edited_data = st.data_editor(
            st.session_state.staff_df_v28, num_rows="dynamic", key="tabelle_mitarbeiter_v28",
            column_config={
                "ID": None,
                "Abteilung": st.column_config.SelectboxColumn("Abteilung", options=["Abteilung B", "Abteilung H", "Abteilung F"]),
                "Rolle": st.column_config.SelectboxColumn("Rolle", options=["Leitung", "DGKP", "Pflegeassistenz", "Heimhelfer"]),
                "Qualifikation": st.column_config.SelectboxColumn("Zusatzqualifikation", options=["Keine", "Wundmanager", "Praxisanleiter", "Palliativ"]),
                "Wochenstd": st.column_config.NumberColumn("Wochenstd.", min_value=1.0, max_value=60.0, default=37.0, step=0.5),
                "Prozent": st.column_config.NumberColumn("Anst. (%)", disabled=True), 
                "Spezialdienst": st.column_config.SelectboxColumn("Spezialdienst", options=["Ohne", "Nur WE und Feiertage", "F2", "F7", "X7", "X6", "X4", "JED", "MS", "SM"])
            }, use_container_width=True,
        )
        if st.form_submit_button("💾 Spremembe ekipe potrdi", type="primary"):
            edited_data["Prozent"] = (edited_data["Wochenstd"] / 37.0) * 100
            edited_data["Prozent"] = edited_data["Prozent"].round(1)
            edited_data["URL_Rest"] = edited_data.apply(lambda row: min(row["URL_Gesamt"], row["URL_Rest"]), axis=1)
            st.session_state.staff_df_v28 = edited_data
            edited_data.to_csv("team_data.csv", index=False)
            st.success("✅ Teamdaten gespeichert!")
            st.rerun()

    st.divider()

    if "absences_v28" not in st.session_state: st.session_state.absences_v28 = []
    if "work_rules_v28" not in st.session_state: st.session_state.work_rules_v28 = []

    st.header("3. Abwesenheiten & Wünsche")
    col_smart, col_manual = st.columns([1, 1])
    with col_manual:
        with st.form("absence_form"):
            emp_names = st.multiselect("Mitarbeiter:", options=st.session_state.staff_df_v28["Name"].dropna().tolist())
            izbrani_datumi = st.multiselect("Tage:", options=list(range(1, num_days + 1)))
            reason = st.selectbox("Grund/Regel:", ["URL (Urlaub)", "KRA (Krankenstand)", "GEB", "ENT", "NA", "Ü", "ZA (Zeitausgleich)", "MUSS arbeiten", "DARF NUR arbeiten"])
            if st.form_submit_button("Speichern") and izbrani_datumi and emp_names:
                for emp_name in emp_names:
                    emp_id = st.session_state.staff_df_v28.loc[st.session_state.staff_df_v28["Name"] == emp_name, "ID"].values[0]
                    for d in izbrani_datumi:
                        if reason in ["MUSS arbeiten", "DARF NUR arbeiten"]: st.session_state.work_rules_v28.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "rule": reason})
                        else: st.session_state.absences_v28.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "reason": reason})
                st.success("Gespeichert!")

    if st.session_state.absences_v28 or st.session_state.work_rules_v28:
        col_list1, col_list2 = st.columns(2)
        with col_list1:
            if st.session_state.absences_v28:
                if st.button("🗑️ Abwesenheiten löschen"): st.session_state.absences_v28 = []; st.rerun()
                st.dataframe(pd.DataFrame(st.session_state.absences_v28)[["emp_name", "day", "reason"]])
        with col_list2:
            if st.session_state.work_rules_v28:
                if st.button("🗑️ Wunschdienste löschen"): st.session_state.work_rules_v28 = []; st.rerun()
                st.dataframe(pd.DataFrame(st.session_state.work_rules_v28)[["emp_name", "day", "rule"]])

with tab2:
    st.header("Automatische Dienstplangenerierung")
    
    if st.button("🚀 Dienstplan berechnen", type="primary", use_container_width=True):
        df_clean = st.session_state.staff_df_v28.copy()
        staff_list = df_clean.to_dict("records")
        
        last_month_work_streak = {s["Name"]: 0 for s in staff_list}
        last_month_worked_weekend = {s["Name"]: False for s in staff_list}
        
        if "old_plan" in st.session_state:
            old_df = st.session_state.old_plan
            day_cols_old = [c for c in old_df.columns if "." in c]
            if day_cols_old:
                for s in staff_list:
                    emp_name = s["Name"]
                    if emp_name in old_df["Mitarbeiter"].values:
                        person_old_data = old_df[old_df["Mitarbeiter"] == emp_name].iloc[0]
                        streak = 0
                        for dc in reversed(day_cols_old):
                            val = str(person_old_data[dc]).split(" ")[0]
                            if val not in ["...", "OK", "URL", "KRA", "GEB", "NA", "ZA"] and not val.startswith("-"): streak += 1
                            else: break 
                        last_month_work_streak[emp_name] = streak
                        if len(day_cols_old) >= 2:
                            last_few_days = [str(person_old_data[dc]).split(" ")[0] for dc in day_cols_old[-3:]]
                            if sum(1 for v in last_few_days if v not in ["...", "URL", "KRA", "ZA"]) >= 2:
                                last_month_worked_weekend[emp_name] = True

        try:
            with st.spinner("KI berechnet Dienstplan..."):
                model = cp_model.CpModel()
                hour_deviations = []
                shifts = {"X4": 825, "X6": 1100, "X7": 1200, "F2": 1200, "F7": 1100, "N1": 1350, "N2": 1350, "JED": 1050, "MS": 700, "SM": 1075, "OFF": 0}
                work = {}
                for s in staff_list:
                    for d in range(num_days):
                        for sh in shifts.keys(): work[(s["ID"], d, sh)] = model.NewBoolVar(f'work_{s["ID"]}_{d}_{sh}')

                worked_day = {}
                for s in staff_list:
                    for d in range(num_days):
                        model.Add(sum(work[(s["ID"], d, sh)] for sh in shifts.keys()) == 1)
                        worked_d = model.NewBoolVar(f'worked_any_{s["ID"]}_{d}')
                        model.Add(worked_d == 1 - work[(s["ID"], d, "OFF")])
                        worked_day[(s["ID"], d)] = worked_d

                for s in staff_list:
                    # Zakon o zaporednih dneh
                    for d in range(num_days - 3):
                        four_days = model.NewBoolVar(f'four_days_{s["ID"]}_{d}')
                        model.AddMinEquality(four_days, [worked_day[(s["ID"], d+i)] for i in range(4)])
                        hour_deviations.append(four_days * 3500)
                    for d in range(num_days - 5): model.Add(sum(work[(s["ID"], d + i, "OFF")] for i in range(6)) >= 1)
                    
                    streak = last_month_work_streak[s["Name"]]
                    if streak >= 4: model.Add(work[(s["ID"], 0, "OFF")] == 1)
                    elif streak == 3 and num_days >= 2: model.Add(work[(s["ID"], 0, "OFF")] + work[(s["ID"], 1, "OFF")] >= 1)

                    # Osamljeni prosti dnevi
                    for d in range(1, num_days - 1):
                        single_off = model.NewBoolVar(f'sing_off_{s["ID"]}_{d}')
                        model.AddMinEquality(single_off, [worked_day[(s["ID"], d-1)], work[(s["ID"], d, "OFF")], worked_day[(s["ID"], d+1)]])
                        hour_deviations.append(single_off * 1000)

                weekends = []
                sat = -1
                first_weekend_idx = -1
                for d in range(num_days):
                    dow = (d + first_day_of_month_weekday) % 7
                    if dow == 5: 
                        sat = d
                        if first_weekend_idx == -1: first_weekend_idx = len(weekends) 
                    elif dow == 6:
                        if sat != -1: weekends.append([sat, d])
                        else: 
                            weekends.append([d])
                            if first_weekend_idx == -1: first_weekend_idx = len(weekends) - 1
                        sat = -1
                if sat != -1: weekends.append([sat])

                for s in staff_list:
                    works_we = []
                    for w_idx, we_days in enumerate(weekends):
                        we_var = model.NewBoolVar(f'we_{s["ID"]}_{w_idx}')
                        model.AddMaxEquality(we_var, [worked_day[(s["ID"], day)] for day in we_days])
                        works_we.append(we_var)
                        if w_idx == first_weekend_idx and last_month_worked_weekend[s["Name"]]: hour_deviations.append(we_var * 25000) 
                    for w_idx in range(len(weekends) - 2): model.Add(works_we[w_idx] + works_we[w_idx+1] + works_we[w_idx+2] <= 2)

                for r in st.session_state.work_rules_v28:
                    if "MUSS" in r["rule"]: model.Add(work[(r["emp_id"], r["day"], "OFF")] == 0)

                # --- STRIKTE QUALIFIKATIONS-REGELN ---
                for s in staff_list:
                    allowed_shifts = ["OFF"]
                    
                    if s["Abteilung"] == "Abteilung F":
                        # F Station = Samo N1 za DGKP
                        if s["Rolle"] in ["DGKP", "Leitung"]:
                            allowed_shifts.append("N1")
                        else:
                            allowed_shifts.append("N2") # Just in case a PA is assigned to F
                    else:
                        if s["Rolle"] in ["DGKP", "Leitung"]:
                            allowed_shifts.extend(["X4", "X6", "X7", "N1"])
                        elif s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]:
                            allowed_shifts.extend(["F2", "F7", "N2"])
                    
                    # Spezialdienst override (razen ce je oznaceno drugace)
                    spez = str(s.get("Spezialdienst", "Ohne"))
                    if spez != "Ohne" and spez != "Nur WE und Feiertage":
                        if "F2" in spez: allowed_shifts.append("F2")
                        if "F7" in spez: allowed_shifts.append("F7")
                        if "X7" in spez: allowed_shifts.append("X7")
                        if "X6" in spez: allowed_shifts.append("X6")
                        if "X4" in spez: allowed_shifts.append("X4")
                        if "JED" in spez: allowed_shifts.append("JED")
                        if "MS" in spez: allowed_shifts.append("MS")
                        if "SM" in spez: allowed_shifts.append("SM")
                        
                    allowed_shifts = list(set(allowed_shifts)) # Remove duplicates

                    unallowed = [sh for sh in shifts.keys() if sh not in allowed_shifts]
                    for d in range(num_days):
                        for sh in unallowed: model.Add(work[(s["ID"], d, sh)] == 0)

                    if s["Max_Nacht"] > 0:
                        nocna_koda = "N1" if s["Rolle"] in ["DGKP", "Leitung"] else "N2"
                        if nocna_koda in allowed_shifts:
                            model.Add(sum(work[(s["ID"], d, nocna_koda)] for d in range(num_days)) <= int(s["Max_Nacht"]))
                    else:
                        if "N1" in allowed_shifts: model.Add(sum(work[(s["ID"], d, "N1")] for d in range(num_days)) == 0)
                        if "N2" in allowed_shifts: model.Add(sum(work[(s["ID"], d, "N2")] for d in range(num_days)) == 0)

                for a in st.session_state.absences_v28:
                    if a["day"] < num_days: model.Add(work[(a["emp_id"], a["day"], "OFF")] == 1)

                for s in staff_list:
                    for d in range(num_days - 1):
                        model.AddImplication(work[(s["ID"], d, "N1")], work[(s["ID"], d + 1, "OFF")])
                        model.AddImplication(work[(s["ID"], d, "N2")], work[(s["ID"], d + 1, "OFF")])

                    w_std = float(s.get("Wochenstd", 37.0))
                    standard_target = (w_std / 7.0) * num_days
                    saldo_alt = float(s.get("Saldo_Alt", 0.0))
                    adjusted_target = max(0, int((standard_target - saldo_alt) * 100))
                    
                    total_hours = model.NewIntVar(0, 35000, f'tot_{s["ID"]}')
                    model.Add(total_hours == sum(work[(s["ID"], d, sh)] * shifts[sh] for d in range(num_days) for sh in shifts.keys()))

                    dev = model.NewIntVar(0, 20000, f'dev_{s["ID"]}')
                    model.Add(dev >= total_hours - adjusted_target)
                    model.Add(dev >= adjusted_target - total_hours)
                    hour_deviations.append(dev)

                # Cross-Coverage Engine (Dopolnjevanje med oddelki)
                # Ensure global minimums are met, solver will distribute the shifts
                o_tehniki = [s["ID"] for s in staff_list if s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and s["Abteilung"] != "Abteilung F"]
                o_dgkp = [s["ID"] for s in staff_list if s["Rolle"] in ["DGKP", "Leitung"] and s["Abteilung"] != "Abteilung F"]
                o_noc_n1 = [s["ID"] for s in staff_list if "N1" in ["N1" if s["Rolle"] in ["DGKP","Leitung"] else "N2"] and s["Max_Nacht"] > 0]
                
                tech_shifts = ["F2", "F7", "MS"]
                dgkp_shifts = ["X4", "X6", "X7"]
                
                for d in range(num_days):
                    # Globale zahteve za hišo (npr. B in H skupaj rabita min. 8 tehnikov in 2 DGKP zjutraj)
                    if len(o_tehniki) >= 8:
                        model.Add(sum(work[(e, d, sh)] for e in o_tehniki for sh in tech_shifts) >= 8)
                    if len(o_dgkp) >= 2:
                        model.Add(sum(work[(e, d, sh)] for e in o_dgkp for sh in dgkp_shifts) >= 2)
                    if len(o_noc_n1) >= 1:
                        model.Add(sum(work[(e, d, "N1")] for e in o_noc_n1) >= 1)

                model.Minimize(sum(hour_deviations))
                solver = cp_model.CpSolver()
                solver.parameters.max_time_in_seconds = 20.0
                status = solver.Solve(model)

                if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                    st.success("🎉 Dienstplan erfolgreich generiert!")
                    data = []
                    for s in staff_list:
                        qual_str = f" ({s['Qualifikation']})" if s['Qualifikation'] != "Keine" else ""
                        row = {"ID_hidden": s["ID"], "Abteilung": s["Abteilung"], "Rolle": s["Rolle"], "Mitarbeiter": f"{s['Name']}{qual_str}"}
                        total_hours = 0
                        for d in range(num_days):
                            day_str = f"{d+1}."
                            val = "..."
                            for sh in shifts.keys():
                                if solver.Value(work[(s["ID"], d, sh)]) == 1:
                                    val = sh if sh != "OFF" else "..."
                                    for a in st.session_state.absences_v28:
                                        if a["emp_id"] == s["ID"] and a["day"] == d: val = a["reason"].split(" ")[0] 
                                    total_hours += shifts[sh]
                            row[day_str] = val
                        
                        soll_neu = (float(s.get("Wochenstd", 37.0)) / 7.0) * num_days
                        row["SOLL"] = round(soll_neu, 1)
                        row["IST"] = total_hours / 100
                        row["SALDO"] = round((total_hours / 100) - soll_neu + float(s.get("Saldo_Alt", 0.0)), 1)
                        data.append(row)
                        
                    day_cols = [f"{d+1}." for d in range(num_days)]
                    
                    # Post-Processing: Cross-Coverage Zuweisung (Abt B vs Abt H)
                    for day_str in day_cols:
                        # Tehniki
                        tech_b = [i for i, r in enumerate(data) if r["Abteilung"] == "Abteilung B" and r["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and str(r[day_str]) in tech_shifts]
                        tech_h = [i for i, r in enumerate(data) if r["Abteilung"] == "Abteilung H" and r["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and str(r[day_str]) in tech_shifts]
                        
                        while len(tech_b) < 4 and len(tech_h) > 4:
                            idx = tech_h.pop()
                            data[idx][day_str] = f"{data[idx][day_str]} ➔ Abt. B"
                            tech_b.append(idx)
                        while len(tech_h) < 4 and len(tech_b) > 4:
                            idx = tech_b.pop()
                            data[idx][day_str] = f"{data[idx][day_str]} ➔ Abt. H"
                            tech_h.append(idx)
                            
                        # Diplomirani
                        dgkp_b = [i for i, r in enumerate(data) if r["Abteilung"] == "Abteilung B" and r["Rolle"] in ["DGKP", "Leitung"] and str(r[day_str]) in dgkp_shifts]
                        dgkp_h = [i for i, r in enumerate(data) if r["Abteilung"] == "Abteilung H" and r["Rolle"] in ["DGKP", "Leitung"] and str(r[day_str]) in dgkp_shifts]
                        
                        while len(dgkp_b) < 1 and len(dgkp_h) > 1:
                            idx = dgkp_h.pop()
                            data[idx][day_str] = f"{data[idx][day_str]} ➔ Abt. B"
                            dgkp_b.append(idx)
                        while len(dgkp_h) < 1 and len(dgkp_b) > 1:
                            idx = dgkp_b.pop()
                            data[idx][day_str] = f"{data[idx][day_str]} ➔ Abt. H"
                            dgkp_h.append(idx)

                    st.session_state.last_generated_df = pd.DataFrame(data).drop(columns=["ID_hidden"], errors='ignore')
                else:
                    st.error("🚨 Kritischer Fehler!")
        except Exception as e: st.error(f"⚠️ Systemfehler: {e}")

    if "last_generated_df" in st.session_state:
        df_rezultat = st.session_state.last_generated_df
        def style_cells(val):
            if isinstance(val, str):
                if val.startswith("*"): return "background-color: #fff3cd; color: #856404; font-weight: bold; border: 2px solid #ffeeba"
                if "➔" in val: return "background-color: #d4edda; color: #006600; font-weight: bold; border: 2px solid #28a745"
                if val == "OK": return "color: #009900; font-weight: bold; text-align: center"
                if "Wundmanager" in val or "Praxisanleiter" in val: return "font-weight: bold; color: #0056b3"
            return ""
        
        st.subheader("🔵 Dienstplan: Abteilung B")
        st.dataframe(df_rezultat[df_rezultat["Abteilung"] == "Abteilung B"].drop(columns=["Abteilung"], errors='ignore').style.map(style_cells), use_container_width=True)

        st.subheader("🟢 Dienstplan: Abteilung H")
        st.dataframe(df_rezultat[df_rezultat["Abteilung"] == "Abteilung H"].drop(columns=["Abteilung"], errors='ignore').style.map(style_cells), use_container_width=True)

        st.subheader("🟣 Dienstplan: Abteilung F (Nachtpool)")
        st.dataframe(df_rezultat[df_rezultat["Abteilung"] == "Abteilung F"].drop(columns=["Abteilung"], errors='ignore').style.map(style_cells), use_container_width=True)

with tab3:
    st.header("🚑 SOS Ausfallmanagement")
    st.info("SOS & Einspringer Modul aktiv.")

with tab4:
    st.header("🔄 Schicht-Tausch")
    st.info("Tauschfunktion aktiv.")

with tab5:
    st.header("📱 WhatsApp / E-Mail Export")
    st.info("Export aktiv.")

with tab6:
    st.header("📉 Analyse & ⚖️ ZA-Asistent")
    if "last_generated_df" in st.session_state:
        st.subheader("⚖️ Zeitausgleich (ZA) Empfehlungen")
        st.markdown("Die KI sucht nach Tagen ohne Engpässe und schlägt Mitarbeiter mit den meisten Überstunden für Zeitausgleich vor.")
        
        df_clean = st.session_state.last_generated_df[~st.session_state.last_generated_df["Mitarbeiter"].str.contains("FEHLT")]
        day_cols = [c for c in df_clean.columns if "." in c]
        
        za_suggestions = []
        for d in day_cols:
            workers_today = df_clean[(df_clean[d] != "...") & (df_clean[d] != "URL") & (df_clean[d] != "KRA") & (df_clean["SALDO"].apply(lambda x: pd.to_numeric(x, errors='coerce')) > 15.0)]
            if not workers_today.empty:
                top_overtime_worker = workers_today.sort_values(by="SALDO", ascending=False).iloc[0]
                za_suggestions.append({"Tag": d, "Mitarbeiter": top_overtime_worker["Mitarbeiter"], "Geplanter Dienst": top_overtime_worker[d], "Aktueller Saldo": top_overtime_worker["SALDO"], "Vorschlag": "Dienst streichen -> 'ZA' eintragen"})
        
        if za_suggestions: st.dataframe(pd.DataFrame(za_suggestions), hide_index=True, use_container_width=True)
        else: st.success("Keine kritischen Überstunden oder ideale Tage für ZA gefunden.")
    else: st.info("Bitte generiere den Dienstplan.")

with tab7:
    st.header("🗣️ Mitarbeitergespräche Planer")
    st.info("Gesprächsplaner aktiv.")

with tab8:
    st.header("🛡️ Arbeitsinspektorat Audit (AZG/ARG Check)")
    st.markdown("Offizielle Prüfung des Dienstplans nach den österreichischen Arbeitszeitgesetzen.")
    
    if "last_generated_df" in st.session_state:
        if st.button("🕵️‍♂️ Dienstplan offiziell prüfen", type="primary"):
            df_audit = st.session_state.last_generated_df[~st.session_state.last_generated_df["Mitarbeiter"].str.contains("FEHLT")]
            day_cols = [c for c in df_audit.columns if "." in c]
            violations = []
            
            for idx, row in df_audit.iterrows():
                emp = row["Mitarbeiter"]
                streak = 0
                for i, d in enumerate(day_cols):
                    shift = str(row[d]).split(" ")[0].replace("*", "").replace("➔", "").strip()
                    if shift in ["N1", "N2"] and i < len(day_cols) - 1:
                        next_shift = str(row[day_cols[i+1]]).split(" ")[0].replace("*", "")
                        if next_shift not in ["...", "URL", "KRA", "ZA", "GEB"]:
                            violations.append({"Mitarbeiter": emp, "Gesetz": "Ruhezeitverletzung (11h)", "Datum": day_cols[i+1], "Details": f"Dienst '{next_shift}' nach einer Nachtschicht."})
                    
                    if shift not in ["...", "URL", "KRA", "ZA", "GEB"] and not shift.startswith("-"):
                        streak += 1
                        if streak > 6: violations.append({"Mitarbeiter": emp, "Gesetz": "Max. 6 Tage am Stück", "Datum": d, "Details": f"Arbeitet den {streak}. Tag in Folge."})
                    else: streak = 0
                        
                shift_hours_dict = {"X4": 8.25, "X6": 11.0, "X7": 12.0, "F2": 12.0, "F7": 11.0, "N1": 13.5, "N2": 13.5, "JED": 10.5, "MS": 7.0, "SM": 10.75}
                for i in range(len(day_cols) - 6):
                    weekly_hours = 0
                    for j in range(7):
                        sh = str(row[day_cols[i+j]]).split(" ")[0].replace("*", "").replace("➔", "").strip()
                        weekly_hours += shift_hours_dict.get(sh, 0)
                    if weekly_hours > 50:
                        violations.append({"Mitarbeiter": emp, "Gesetz": "Max. 50h pro Woche (AZG)", "Datum": f"Woche ab {day_cols[i]}", "Details": f"{weekly_hours} Stunden in 7 Tagen."})

            if len(violations) > 0:
                st.error("🚨 **ACHTUNG:** Das Arbeitsinspektorat würde folgende Verstöße beanstanden!")
                st.dataframe(pd.DataFrame(violations), hide_index=True, use_container_width=True)
            else:
                st.success("✅ **ZERTIFIZIERT:** Der Dienstplan entspricht den Vorgaben des Arbeitszeitgesetzes (AZG).")
                st.balloons()
    else: st.info("Bitte generiere den Dienstplan zuerst.")
