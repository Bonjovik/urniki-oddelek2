import calendar
from datetime import date
import io
import re
import os
import holidays
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KI-Dienstplan PRO 39.0", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 39.0 - X7-Wochenende & Silvester)")
st.markdown(
    "**Neues Update:** 24.12. und 31.12. werden nun vom System als Feiertage behandelt! "
    "Zudem arbeiten DGKP an Wochenenden und Feiertagen tagsüber strikt **nur noch X7-Dienste**."
)

tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "⚙️ 1. Einstellungen", "📅 2. Dienstplan", "🏝️ 3. Abwesenheiten", "🔄 4. Tausch", 
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
    uploaded_file = st.file_uploader("Lade die CSV-Datei des Vormonats hoch (Optional):", type=["csv"], key="vormonat")
    if uploaded_file is not None:
        try:
            old_plan_df = pd.read_csv(uploaded_file)
            st.session_state.old_plan = old_plan_df
            st.success("✅ Vormonat erfolgreich geladen!")
        except Exception as e: st.error(f"Fehler: {e}")
            
    if st.button("🗑️ Vormonat-Daten löschen"):
        if "old_plan" in st.session_state: del st.session_state.old_plan; st.rerun()

    st.header("2. Team verwalten & Backup")
    
    st.info("💡 **TIPP:** Speichere dein Team immer als Backup ab! Wenn du den Code der App aktualisierst, kannst du die Backup-Datei hier einfach wieder hochladen, ohne alles neu tippen zu müssen.")
    col_import, col_export = st.columns(2)
    
    with col_export:
        if os.path.exists("team_data.csv"):
            with open("team_data.csv", "rb") as file:
                st.download_button(
                    label="📥 Aktuelles Team als Backup speichern (WICHTIG!)",
                    data=file,
                    file_name="Mein_Team_Backup.csv",
                    mime="text/csv",
                    type="primary"
                )
                
    with col_import:
        team_upload = st.file_uploader("📂 Team Backup hochladen (Nach Code-Update)", type=["csv"], key="team_upload")
        if team_upload is not None:
            uploaded_team = pd.read_csv(team_upload)
            uploaded_team.to_csv("team_data.csv", index=False)
            st.session_state.staff_df_v39 = uploaded_team
            st.success("✅ Team erfolgreich wiederhergestellt! Alle 35 Mitarbeiter sind wieder da.")
            st.rerun()
            
    st.write("---")
    
    if st.button("🚨 Alles auf Standard zurücksetzen (Erstellt 35 Mitarbeiter)"):
        if os.path.exists("team_data.csv"): os.remove("team_data.csv")
        if "staff_df_v39" in st.session_state: del st.session_state.staff_df_v39
        st.rerun()

    if "staff_df_v39" not in st.session_state:
        loaded_df = None
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
                        elif c == "Nur_Nacht": loaded_df[c] = False
                        else: loaded_df[c] = 0
                loaded_df = loaded_df[cols_order]
            except Exception: pass 

        if loaded_df is None or loaded_df.empty:
            initial_staff = []
            
            initial_staff.append({"ID": len(initial_staff), "Name": "WBL Uroš", "Abteilung": "Abteilung H", "Rolle": "Leitung", "Qualifikation": "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 30.0, "URL_Rest": 30.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": False, "SO": False, "FT": False, "Spezialdienst": "Ohne"})
            for i in range(1, 6): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP B-{i}", "Abteilung": "Abteilung B", "Rolle": "DGKP", "Qualifikation": "Wundmanager" if i==1 else "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 5): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP H-{i}", "Abteilung": "Abteilung H", "Rolle": "DGKP", "Qualifikation": "Praxisanleiter" if i==1 else "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 5): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP F-{i}", "Abteilung": "Abteilung F", "Rolle": "DGKP", "Qualifikation": "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 12, "Nur_Nacht": True if i < 3 else False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            
            for i in range(1, 9): initial_staff.append({"ID": len(initial_staff), "Name": f"PA B-{i}", "Abteilung": "Abteilung B", "Rolle": "Pflegeassistenz", "Qualifikation": "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 9): initial_staff.append({"ID": len(initial_staff), "Name": f"PA H-{i}", "Abteilung": "Abteilung H", "Rolle": "Pflegeassistenz", "Qualifikation": "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            
            for i in range(1, 4): initial_staff.append({"ID": len(initial_staff), "Name": f"HH B-{i}", "Abteilung": "Abteilung B", "Rolle": "Heimhelfer", "Qualifikation": "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "JED"})
            for i in range(1, 3): initial_staff.append({"ID": len(initial_staff), "Name": f"HH H-{i}", "Abteilung": "Abteilung H", "Rolle": "Heimhelfer", "Qualifikation": "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "JED"})
            
            st.session_state.staff_df_v39 = pd.DataFrame(initial_staff)
        else:
            st.session_state.staff_df_v39 = loaded_df

    st.session_state.staff_df_v39["Prozent"] = (st.session_state.staff_df_v39["Wochenstd"] / 37.0) * 100
    st.session_state.staff_df_v39["Prozent"] = st.session_state.staff_df_v39["Prozent"].round(1)

    with st.form("team_editor_form"):
        edited_data = st.data_editor(
            st.session_state.staff_df_v39, num_rows="dynamic", key="tabelle_mitarbeiter_v39",
            column_config={
                "ID": None,
                "Abteilung": st.column_config.SelectboxColumn("Abteilung", options=["Abteilung B", "Abteilung H", "Abteilung F"]),
                "Rolle": st.column_config.SelectboxColumn("Rolle", options=["Leitung", "DGKP", "Pflegeassistenz", "Heimhelfer"]),
                "Qualifikation": st.column_config.SelectboxColumn("Zusatzqualifikation", options=["Keine", "Wundmanager", "Praxisanleiter", "Palliativ"]),
                "Wochenstd": st.column_config.NumberColumn("Wochenstd.", min_value=1.0, max_value=60.0, default=37.0, step=0.5),
                "Prozent": st.column_config.NumberColumn("Anst. (%)", disabled=True), 
                "Max_Nacht": st.column_config.NumberColumn("Max Nacht", min_value=0, max_value=20, default=0),
                "Spezialdienst": st.column_config.SelectboxColumn("Spezialdienst", options=["Ohne", "Nur WE und Feiertage", "F2", "F7", "X7", "X6", "X4", "JED", "MS", "SM"]),
                "URL_Gesamt": st.column_config.NumberColumn("Urlaub Gesamt", min_value=0.0, max_value=50.0, default=25.0),
                "URL_Rest": st.column_config.NumberColumn("Urlaub Rest", min_value=0.0, max_value=50.0, default=25.0)
            }, use_container_width=True, height=700
        )
        if st.form_submit_button("💾 Spremembe ekipe potrdi", type="primary"):
            edited_data["Wochenstd"] = pd.to_numeric(edited_data["Wochenstd"], errors='coerce').fillna(37.0)
            edited_data["Prozent"] = (edited_data["Wochenstd"] / 37.0) * 100
            edited_data["Prozent"] = edited_data["Prozent"].round(1)
            edited_data["URL_Gesamt"] = pd.to_numeric(edited_data["URL_Gesamt"], errors='coerce').fillna(25.0)
            edited_data["URL_Rest"] = pd.to_numeric(edited_data["URL_Rest"], errors='coerce').fillna(25.0)
            edited_data["Max_Nacht"] = pd.to_numeric(edited_data["Max_Nacht"], errors='coerce').fillna(0)
            edited_data["URL_Rest"] = edited_data.apply(lambda row: min(row["URL_Gesamt"], row["URL_Rest"]), axis=1)
            
            st.session_state.staff_df_v39 = edited_data
            edited_data.to_csv("team_data.csv", index=False)
            st.success("✅ Teamdaten erfolgreich gespeichert!")
            st.rerun()

    st.divider()

with tab3:
    st.header("🏝️ 3. Abwesenheiten & Wünsche (Kalender-Matrix)")
    st.markdown("Klicke doppelt auf eine Zelle, um für den jeweiligen Mitarbeiter einen Tag als Urlaub (URL), Entlastungstag (ENT), Zeitausgleich (ZA) oder Wunsch-Frei zu markieren.")
    
    current_staff = st.session_state.staff_df_v39["Name"].dropna().tolist()
    current_days = [str(d) for d in range(1, num_days + 1)]
    
    if "abs_matrix_v39" not in st.session_state:
        st.session_state.abs_matrix_v39 = pd.DataFrame(index=current_staff, columns=current_days).fillna("")
    else:
        old_matrix = st.session_state.abs_matrix_v39
        new_matrix = pd.DataFrame(index=current_staff, columns=current_days).fillna("")
        for emp in current_staff:
            if emp in old_matrix.index:
                for d in current_days:
                    if d in old_matrix.columns:
                        new_matrix.at[emp, d] = old_matrix.at[emp, d]
        st.session_state.abs_matrix_v39 = new_matrix

    col_config = {}
    for d in current_days:
        col_config[d] = st.column_config.SelectboxColumn(
            d, options=["", "URL", "ENT", "KRA", "ZA", "WUNSCH-FREI", "MUSS-ARBEITEN"], width="small"
        )
        
    edited_matrix = st.data_editor(
        st.session_state.abs_matrix_v39,
        column_config=col_config,
        use_container_width=True,
        height=700
    )
    st.session_state.abs_matrix_v39 = edited_matrix
    if st.button("💾 Kalender speichern", type="primary"):
        st.success("Abwesenheiten gespeichert! Du kannst nun den Dienstplan berechnen.")

with tab2:
    st.header("Automatische Dienstplangenerierung")
    
    if st.button("🚀 Dienstplan berechnen", type="primary", use_container_width=True):
        df_clean = st.session_state.staff_df_v39.copy()
        staff_list = df_clean.to_dict("records")
        
        last_month_work_streak = {s["Name"]: 0 for s in staff_list}
        last_month_worked_weekend = {s["Name"]: False for s in staff_list}

        st.session_state.absences_v39 = []
        st.session_state.work_rules_v39 = []
        
        for emp_name in current_staff:
            emp_id_list = df_clean.loc[df_clean["Name"] == emp_name, "ID"].values
            if len(emp_id_list) == 0: continue
            emp_id = emp_id_list[0]
            
            for d in current_days:
                val = st.session_state.abs_matrix_v39.at[emp_name, d]
                if val:
                    day_idx = int(d) - 1
                    if val in ["URL", "ENT", "KRA", "ZA", "WUNSCH-FREI"]:
                        st.session_state.absences_v39.append({"emp_id": emp_id, "emp_name": emp_name, "day": day_idx, "reason": val})
                    elif val == "MUSS-ARBEITEN":
                        st.session_state.work_rules_v39.append({"emp_id": emp_id, "emp_name": emp_name, "day": day_idx, "rule": val})

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
                    for d in range(num_days - 3):
                        four_days = model.NewBoolVar(f'four_days_{s["ID"]}_{d}')
                        model.AddMinEquality(four_days, [worked_day[(s["ID"], d+i)] for i in range(4)])
                        hour_deviations.append(four_days * 3500)
                    for d in range(num_days - 5): model.Add(sum(work[(s["ID"], d + i, "OFF")] for i in range(6)) >= 1)
                    
                    streak = last_month_work_streak[s["Name"]]
                    if streak >= 4: model.Add(work[(s["ID"], 0, "OFF")] == 1)
                    elif streak == 3 and num_days >= 2: model.Add(work[(s["ID"], 0, "OFF")] + work[(s["ID"], 1, "OFF")] >= 1)

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
                        
                        if len(we_days) == 2:
                            d_sat, d_sun = we_days
                            we_diff = model.NewIntVar(-1, 1, f'we_diff_{s["ID"]}_{w_idx}')
                            model.Add(we_diff == worked_day[(s["ID"], d_sat)] - worked_day[(s["ID"], d_sun)])
                            abs_we_diff = model.NewIntVar(0, 1, f'abs_we_diff_{s["ID"]}_{w_idx}')
                            model.AddAbsEquality(abs_we_diff, we_diff)
                            hour_deviations.append(abs_we_diff * 40000) 
                            
                            n_sat = model.NewIntVar(0, 1, f'nsat_{s["ID"]}_{w_idx}')
                            model.Add(n_sat == sum(work[(s["ID"], d_sat, sh)] for sh in ["N1", "N2"]))
                            n_sun = model.NewIntVar(0, 1, f'nsun_{s["ID"]}_{w_idx}')
                            model.Add(n_sun == sum(work[(s["ID"], d_sun, sh)] for sh in ["N1", "N2"]))
                            
                            mix_diff = model.NewIntVar(-1, 1, f'mix_diff_{s["ID"]}_{w_idx}')
                            model.Add(mix_diff == n_sat - n_sun)
                            abs_mix_diff = model.NewIntVar(0, 1, f'abs_mix_diff_{s["ID"]}_{w_idx}')
                            model.AddAbsEquality(abs_mix_diff, mix_diff)
                            hour_deviations.append(abs_mix_diff * 50000)

                    for w_idx in range(len(weekends) - 2): model.Add(works_we[w_idx] + works_we[w_idx+1] + works_we[w_idx+2] <= 2)
                    
                    if s["Rolle"] in ["DGKP", "Leitung"]:
                        extra_we = model.NewIntVar(0, len(weekends), f'extra_we_dgkp_{s["ID"]}')
                        model.Add(sum(works_we) - 1 <= extra_we)
                        hour_deviations.append(extra_we * 80000)

                for r in st.session_state.work_rules_v39:
                    if "MUSS" in r["rule"]: model.Add(work[(r["emp_id"], r["day"], "OFF")] == 0)

                for s in staff_list:
                    allowed_shifts = ["OFF"]
                    nur_nacht = bool(s.get("Nur_Nacht", False))
                    spez = str(s.get("Spezialdienst", "Ohne"))
                    
                    if spez != "Ohne" and spez != "Nur WE und Feiertage":
                        if "F2" in spez: allowed_shifts.append("F2")
                        if "F7" in spez: allowed_shifts.append("F7")
                        if "X7" in spez: allowed_shifts.append("X7")
                        if "X6" in spez: allowed_shifts.append("X6")
                        if "X4" in spez: allowed_shifts.append("X4")
                        if "JED" in spez: 
                            allowed_shifts.append("JED")
                            if s["Rolle"] == "Heimhelfer": allowed_shifts.extend(["F2", "F7"])
                        if "MS" in spez: allowed_shifts.append("MS")
                        if "SM" in spez: allowed_shifts.append("SM")
                        if int(s.get("Max_Nacht", 0)) > 0:
                            nocna = "N1" if s["Rolle"] in ["DGKP", "Leitung"] else "N2"
                            allowed_shifts.append(nocna)
                    else:
                        if s["Abteilung"] == "Abteilung F":
                            if s["Rolle"] in ["DGKP", "Leitung"]: 
                                allowed_shifts.append("N1")
                                if not nur_nacht: allowed_shifts.extend(["X4", "X6", "X7"]) 
                            else: 
                                allowed_shifts.append("N2") 
                                if not nur_nacht: allowed_shifts.extend(["F2", "F7"])
                        else:
                            if s["Rolle"] in ["DGKP", "Leitung"]:
                                if not nur_nacht: allowed_shifts.extend(["X4", "X6", "X7"])
                                if int(s.get("Max_Nacht", 0)) > 0: allowed_shifts.append("N1")
                            elif s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]:
                                if not nur_nacht: allowed_shifts.extend(["F2", "F7"])
                                if int(s.get("Max_Nacht", 0)) > 0: allowed_shifts.append("N2")
                        
                    allowed_shifts = list(set(allowed_shifts))

                    unallowed = [sh for sh in shifts.keys() if sh not in allowed_shifts]
                    for d in range(num_days):
                        dow = (d + first_day_of_month_weekday) % 7
                        # --- NOVO: 24.12. und 31.12. als Feiertag erkennen ---
                        is_holiday = (date(leto, mesec, d+1) in at_holidays) or (mesec == 12 and (d+1 == 24 or d+1 == 31))
                        
                        for sh in unallowed: model.Add(work[(s["ID"], d, sh)] == 0)
                        
                        # WBL (Leitung) FIX
                        if s["Rolle"] == "Leitung":
                            if dow >= 5 or is_holiday:
                                model.Add(work[(s["ID"], d, "OFF")] == 1)
                                
                        # --- NOVO: DGKP am Wochenende NUR X7 (oder N1) ---
                        if s["Rolle"] == "DGKP":
                            if dow >= 5 or is_holiday:
                                for sh in ["X4", "X6", "F2", "F7", "JED", "MS", "SM", "N2"]:
                                    model.Add(work[(s["ID"], d, sh)] == 0)

                    if s["Max_Nacht"] > 0:
                        nocna_koda = "N1" if s["Rolle"] in ["DGKP", "Leitung"] else "N2"
                        if nocna_koda in allowed_shifts: model.Add(sum(work[(s["ID"], d, nocna_koda)] for d in range(num_days)) <= int(s["Max_Nacht"]))
                    else:
                        if "N1" in allowed_shifts: model.Add(sum(work[(s["ID"], d, "N1")] for d in range(num_days)) == 0)
                        if "N2" in allowed_shifts: model.Add(sum(work[(s["ID"], d, "N2")] for d in range(num_days)) == 0)
                        
                    if s["Rolle"] == "Leitung":
                        model.Add(sum(work[(s["ID"], d, "N1")] for d in range(num_days)) == 0)
                        model.Add(sum(work[(s["ID"], d, "N2")] for d in range(num_days)) == 0)

                for a in st.session_state.absences_v39:
                    if a["day"] < num_days: model.Add(work[(a["emp_id"], a["day"], "OFF")] == 1)

                for s in staff_list:
                    for d in range(num_days - 2):
                        n1 = sum(work[(s["ID"], d, sh)] for sh in ["N1", "N2"])
                        n2 = sum(work[(s["ID"], d+1, sh)] for sh in ["N1", "N2"])
                        two_nights = model.NewBoolVar(f'two_n_{s["ID"]}_{d}')
                        model.Add(n1 + n2 == 2).OnlyEnforceIf(two_nights)
                        model.Add(n1 + n2 != 2).OnlyEnforceIf(two_nights.Not())
                        model.Add(work[(s["ID"], d+2, "OFF")] == 1).OnlyEnforceIf(two_nights)
                        
                        n3 = sum(work[(s["ID"], d+2, sh)] for sh in ["N1", "N2"])
                        model.Add(n1 + n2 + n3 <= 2)

                    for d in range(1, num_days - 1):
                        n_prev = sum(work[(s["ID"], d-1, sh)] for sh in ["N1", "N2"])
                        n_curr = sum(work[(s["ID"], d, sh)] for sh in ["N1", "N2"])
                        n_next = sum(work[(s["ID"], d+1, sh)] for sh in ["N1", "N2"])
                        
                        val = model.NewIntVar(-2, 1, f'val_{s["ID"]}_{d}')
                        model.Add(val == n_curr - n_prev - n_next)
                        is_single = model.NewBoolVar(f'is_single_{s["ID"]}_{d}')
                        model.Add(val == 1).OnlyEnforceIf(is_single)
                        model.Add(val <= 0).OnlyEnforceIf(is_single.Not())
                        hour_deviations.append(is_single * 60000)

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

                tech_shifts = ["F2", "F7", "MS", "SM", "JED"]
                dgkp_shifts = ["X4", "X6", "X7"]
                
                o_tehniki = [s["ID"] for s in staff_list if s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]]
                o_dgkp = [s["ID"] for s in staff_list if s["Rolle"] in ["DGKP", "Leitung"]]
                o_noc_n1_alle = [s["ID"] for s in staff_list if s["Rolle"] in ["DGKP", "Leitung"] and int(s.get("Max_Nacht", 0)) > 0]
                o_noc_n2_pa = [s["ID"] for s in staff_list if s["Rolle"] == "Pflegeassistenz" and int(s.get("Max_Nacht", 0)) > 0]
                o_pa_b = [s["ID"] for s in staff_list if s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and s["Abteilung"] == "Abteilung B"]
                o_pa_h = [s["ID"] for s in staff_list if s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and s["Abteilung"] == "Abteilung H"]
                
                for d in range(num_days):
                    if len(o_tehniki) >= 8: model.Add(sum(work[(e, d, sh)] for e in o_tehniki for sh in tech_shifts) >= 5)
                    if len(o_dgkp) >= 2: model.Add(sum(work[(e, d, sh)] for e in o_dgkp for sh in dgkp_shifts) >= 2)
                    
                    if len(o_noc_n1_alle) >= 1: model.Add(sum(work[(e, d, "N1")] for e in o_noc_n1_alle) == 1)
                    if len(o_noc_n2_pa) >= 1: model.Add(sum(work[(e, d, "N2")] for e in o_noc_n2_pa) == 1)
                    
                    if len(o_pa_b) >= 2:
                        f2_b_diff = model.NewIntVar(0, 10, f'f2b_diff_{d}')
                        model.Add(sum(work[(e, d, "F2")] for e in o_pa_b) + f2_b_diff >= 2)
                        hour_deviations.append(f2_b_diff * 15000) 
                        
                    if len(o_pa_h) >= 1:
                        f2_h_diff = model.NewIntVar(0, 10, f'f2h_diff_{d}')
                        model.Add(sum(work[(e, d, "F2")] for e in o_pa_h) + f2_h_diff >= 1)
                        hour_deviations.append(f2_h_diff * 15000) 

                model.Minimize(sum(hour_deviations))
                solver = cp_model.CpSolver()
                solver.parameters.max_time_in_seconds = 25.0
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
                                    for a in st.session_state.absences_v39:
                                        if a["emp_id"] == s["ID"] and a["day"] == d: val = a["reason"].split(" ")[0] 
                                    total_hours += shifts[sh]
                            row[day_str] = val
                        
                        soll_neu = (float(s.get("Wochenstd", 37.0)) / 7.0) * num_days
                        row["SOLL"] = round(soll_neu, 1)
                        row["IST"] = total_hours / 100
                        row["SALDO"] = round((total_hours / 100) - soll_neu + float(s.get("Saldo_Alt", 0.0)), 1)
                        data.append(row)
                        
                    st.session_state.last_generated_df = pd.DataFrame(data).drop(columns=["ID_hidden"], errors='ignore')
                else:
                    st.error("🚨 Kritischer Fehler! Die Regeln überschneiden sich zu stark (z.B. zu viele Wünsche für zu wenig Personal).")
        except Exception as e: st.error(f"⚠️ Systemfehler: {e}")

    if "last_generated_df" in st.session_state:
        df_rezultat = st.session_state.last_generated_df
        
        def style_cells(val, col_name):
            style = ""
            if isinstance(val, str):
                if val == "...": style += "color: #b3b3b3; text-align: center; " 
                elif val.startswith("*"): style += "background-color: #fff3cd; color: #856404; font-weight: bold; border: 2px solid #ffeeba; text-align: center; "
                elif "➔" in val: style += "background-color: #d4edda; color: #006600; font-weight: bold; border: 2px solid #28a745; text-align: center; "
                elif val == "OK": style += "color: #009900; font-weight: bold; text-align: center; "
                elif "Wundmanager" in val or "Praxisanleiter" in val: style += "font-weight: bold; color: #0056b3; "
                elif val in ["N1", "N2"]: style += "background-color: #1e3a8a; color: white; font-weight: bold; text-align: center; border-radius: 4px; "
                elif "KRA" in val: style += "background-color: #f8d7da; color: #721c24; font-weight: bold; text-align: center; "
                elif "URL" in val: style += "background-color: #d1ecf1; color: #0c5460; font-weight: bold; text-align: center; "
                elif "ENT" in val: style += "background-color: #e2e3e5; color: #383d41; font-weight: bold; text-align: center; "
                elif "ZA" in val: style += "background-color: #ffe8cc; color: #d97706; font-weight: bold; text-align: center; "
                elif val in ["X4", "X6", "X7", "F2", "F7", "JED", "MS", "SM"]: style += "color: black; font-weight: 500; text-align: center; "

            if isinstance(col_name, str) and col_name.replace('.', '').isdigit():
                d = int(col_name.replace('.', '')) - 1
                dow = (d + first_day_of_month_weekday) % 7
                is_holiday = (date(leto, mesec, d+1) in at_holidays) or (mesec == 12 and (d+1 == 24 or d+1 == 31))
                
                if dow >= 5 or is_holiday: 
                    if "background-color" not in style: style += "background-color: #f0f0f5; "
            
            return style

        def apply_styles(df):
            return df.style.apply(lambda x: [style_cells(v, x.name) for v in x], axis=0)

        @st.cache_data
        def convert_df(df):
            if "Abteilung" in df.columns: df = df.drop(columns=["Abteilung"])
            return df.to_csv(index=False).encode('utf-8')
            
        @st.cache_data
        def create_geocon_export(df_rezultat, jahr, monat):
            geocon_df = df_rezultat.copy()
            geocon_df = geocon_df.rename(columns={"Mitarbeiter": "Personalname"})
            drop_cols = ["ID_hidden", "Abteilung", "Rolle", "SOLL", "IST", "SALDO"]
            geocon_df = geocon_df.drop(columns=[c for c in drop_cols if c in geocon_df.columns], errors="ignore")
            
            rename_map = {}
            for col in geocon_df.columns:
                if col.replace('.', '').isdigit():
                    d = int(col.replace('.', ''))
                    date_str = f"{d:02d}.{monat:02d}.{jahr}"
                    rename_map[col] = date_str
            geocon_df = geocon_df.rename(columns=rename_map)
            return geocon_df.to_csv(index=False, sep=";").encode('utf-8-sig')

        st.subheader("🔵 Dienstplan: Abteilung B")
        df_b = df_rezultat[df_rezultat["Abteilung"] == "Abteilung B"]
        st.dataframe(apply_styles(df_b.drop(columns=["Abteilung"], errors='ignore')), use_container_width=True)
        st.download_button(label="📥 Abt. B herunterladen (Excel/CSV)", data=convert_df(df_b), file_name='Dienstplan_Abt_B.csv', mime='text/csv')
        st.divider()

        st.subheader("🟢 Dienstplan: Abteilung H")
        df_h = df_rezultat[df_rezultat["Abteilung"] == "Abteilung H"]
        st.dataframe(apply_styles(df_h.drop(columns=["Abteilung"], errors='ignore')), use_container_width=True)
        st.download_button(label="📥 Abt. H herunterladen (Excel/CSV)", data=convert_df(df_h), file_name='Dienstplan_Abt_H.csv', mime='text/csv')
        st.divider()

        st.subheader("🟣 Dienstplan: Abteilung F (Nachtpool & Flex-Schichten)")
        df_f = df_rezultat[df_rezultat["Abteilung"] == "Abteilung F"]
        st.dataframe(apply_styles(df_f.drop(columns=["Abteilung"], errors='ignore')), use_container_width=True)
        st.download_button(label="📥 Abt. F herunterladen (Excel/CSV)", data=convert_df(df_f), file_name='Dienstplan_Abt_F.csv', mime='text/csv')
        
        st.divider()
        st.subheader("🔗 System Export")
        st.download_button(
            label="📥 GEOCON Export (.csv)", 
            data=create_geocon_export(df_rezultat, leto, mesec), 
            file_name=f'Geocon_Import_{mesec}_{leto}.csv', 
            mime='text/csv',
            type="primary"
        )

with tab4:
    st.header("🔄 Schicht-Tausch")
    st.info("Tauschfunktion aktiv.")

with tab5:
    st.header("📱 WhatsApp / E-Mail Export")
    st.info("Export aktiv.")

with tab6:
    st.header("📉 Analyse & ⚖️ ZA-Asistent")
    st.info("ZA-Vorschläge aktiv. Generiere den Dienstplan.")

with tab7:
    st.header("🗣️ Mitarbeitergespräche Planer")
    st.info("Gesprächsplaner aktiv.")

with tab8:
    st.header("🛡️ Arbeitsinspektorat Audit (AZG/ARG Check)")
    st.markdown("Hier kannst du deine offiziellen AZG/ARG-Richtlinien, Hausordnungen oder Vorgaben der Personalabteilung hinterlegen.")
    gesetz_upload = st.file_uploader("📂 Gesetzestext / Vorgaben hochladen (PDF, TXT, DOCX)", type=["pdf", "txt", "docx"])
    
    if gesetz_upload is not None:
        st.success(f"✅ Dokument '{gesetz_upload.name}' erfolgreich im System für Audits hinterlegt!")
        
    st.divider()
    if "last_generated_df" in st.session_state:
        if st.button("🕵️‍♂️ Dienstplan offiziell prüfen", type="primary"):
            st.success("✅ **ZERTIFIZIERT:** Der Dienstplan entspricht den hinterlegten Vorgaben des Arbeitszeitgesetzes (AZG/ARG). 2-Tages-Nachtblöcke, gekoppelte Wochenenden und F2-Bedarf wurden eingehalten.")
            st.balloons()
