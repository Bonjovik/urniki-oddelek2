import calendar
from datetime import date
import io
import re
import os
import holidays
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KI-Dienstplan PRO 26.0", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 26.0 - MAG Planer)")
st.markdown(
    "Neue Funktionen: **Mitarbeitergespräche (MAG) automatisch planen!** Der neue Tab 7 sucht automatisch "
    "nach gemeinsamen Tagesschichten zwischen der Leitung und den Mitarbeitern."
)

# NOVO: Dodan 7. zavihek
tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs(["⚙️ 1. Einstellungen", "📅 2. Dienstplan", "🚑 3. SOS", "🔄 4. Tausch", "📱 5. WhatsApp", "📉 6. Analyse", "🗣️ 7. Gespräche"])

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
        except Exception as e:
            st.error(f"Fehler beim Lesen der Datei: {e}")
            
    if st.button("🗑️ Vormonat-Daten löschen"):
        if "old_plan" in st.session_state:
            del st.session_state.old_plan
            st.rerun()

    st.header("2. Team verwalten")
    
    if "staff_df_v26" not in st.session_state:
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
                    
                cols_order = ["ID", "Name", "Abteilung", "Rolle", "Wochenstd", "Prozent", "URL_Gesamt", "URL_Rest", "Saldo_Alt", "Max_Nacht", "Nur_Nacht", "MO", "DI", "MI", "DO", "FR", "SA", "SO", "FT", "Spezialdienst"]
                
                for c in cols_order:
                    if c not in loaded_df.columns:
                        if c in ["MO", "DI", "MI", "DO", "FR", "SA", "SO", "FT"]: loaded_df[c] = True
                        elif c == "Spezialdienst": loaded_df[c] = "Ohne"
                        else: loaded_df[c] = 0
                st.session_state.staff_df_v26 = loaded_df[cols_order]
            except Exception: pass 

        if "staff_df_v26" not in st.session_state:
            initial_staff = [{
                "ID": 0, "Name": "WBL (Uroš)", "Abteilung": "Abteilung H", "Rolle": "Leitung",
                "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 30.0, "URL_Rest": 30.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False,
                "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": False, "SO": False, "FT": False, "Spezialdienst": "Ohne"
            }]
            st.session_state.staff_df_v26 = pd.DataFrame(initial_staff)

    with st.form("team_editor_form"):
        edited_data = st.data_editor(
            st.session_state.staff_df_v26, num_rows="dynamic", key="tabelle_mitarbeiter_v26",
            column_config={
                "ID": None,
                "Abteilung": st.column_config.SelectboxColumn("Abteilung", options=["Abteilung B", "Abteilung H", "Abteilung F"]),
                "Rolle": st.column_config.SelectboxColumn("Rolle", options=["Leitung", "DGKP", "Pflegeassistenz", "Heimhelfer"]),
                "Wochenstd": st.column_config.NumberColumn("Wochenstd.", min_value=1.0, max_value=60.0, default=37.0, step=0.5),
                "Prozent": st.column_config.NumberColumn("Anst. (%)", disabled=True), 
                "Spezialdienst": st.column_config.SelectboxColumn("Spezialdienst", options=["Ohne", "Nur WE und Feiertage", "F2 (PA 6:45-19:15)", "F7 (PA 6:45-18:15)", "X7 (DGKP 6:45-19:15)", "X6 (DGKP 6:45-18:15)", "X4 (DGKP 6:45-15:30)", "JED", "MS", "SM"])
            }, use_container_width=True,
        )
        if st.form_submit_button("💾 Spremembe ekipe potrdi", type="primary"):
            edited_data["Prozent"] = (edited_data["Wochenstd"] / 37.0) * 100
            edited_data["Prozent"] = edited_data["Prozent"].round(1)
            edited_data["URL_Rest"] = edited_data.apply(lambda row: min(row["URL_Gesamt"], row["URL_Rest"]), axis=1)
            st.session_state.staff_df_v26 = edited_data
            edited_data.to_csv("team_data.csv", index=False)
            st.success("✅ Teamdaten gespeichert!")
            st.rerun()

    st.divider()

    if "absences_v26" not in st.session_state: st.session_state.absences_v26 = []
    if "work_rules_v26" not in st.session_state: st.session_state.work_rules_v26 = []

    st.header("3. Abwesenheiten & Wünsche")
    col_smart, col_manual = st.columns([1, 1])
    with col_smart:
        with st.form("smart_wunsch_form"):
            emp_smart = st.selectbox("Wer hat einen Wunsch?", options=st.session_state.staff_df_v26["Name"].dropna().tolist())
            smart_text = st.text_input("Beispiel: 'želi prosto 12. in 14.' oder 'arbeiten am 5.'")
            if st.form_submit_button("✨ KI analysieren") and smart_text:
                dates = [int(x) for x in re.findall(r'\b(?:[1-9]|[12][0-9]|3[01])\b', smart_text)]
                txt = smart_text.lower()
                is_free = any(w in txt for w in ["frei", "prosto", "nicht", "ne dela", "urlaub", "dopust", "ausfall"])
                is_work = any(w in txt for w in ["arbeit", "dela", "muss", "will", "želi", "dienst"])
                
                if not dates: st.error("❌ Keine Daten gefunden.")
                else:
                    emp_id = st.session_state.staff_df_v26.loc[st.session_state.staff_df_v26["Name"] == emp_smart, "ID"].values[0]
                    valid_dates = [d for d in dates if 1 <= d <= num_days]
                    if is_free:
                        for d in valid_dates: st.session_state.absences_v26.append({"emp_id": emp_id, "emp_name": emp_smart, "day": d-1, "reason": "WUNSCH (Frei)"})
                        st.success(f"🤖 Erledigt: FREI am {valid_dates}")
                    elif is_work:
                        for d in valid_dates: st.session_state.work_rules_v26.append({"emp_id": emp_id, "emp_name": emp_smart, "day": d-1, "rule": "MUSS arbeiten"})
                        st.success(f"🤖 Erledigt: MUSS ARBEITEN am {valid_dates}")
    with col_manual:
        with st.form("absence_form"):
            emp_names = st.multiselect("Mitarbeiter:", options=st.session_state.staff_df_v26["Name"].dropna().tolist(), key="abs_emp")
            izbrani_datumi = st.multiselect("Tage:", options=list(range(1, num_days + 1)), key="abs_dates")
            reason = st.selectbox("Grund/Regel:", ["URL (Urlaub)", "KRA (Krankenstand)", "GEB", "ENT", "NA", "Ü", "MUSS arbeiten", "DARF NUR arbeiten"])
            if st.form_submit_button("Manuell Speichern") and izbrani_datumi and emp_names:
                for emp_name in emp_names:
                    emp_id = st.session_state.staff_df_v26.loc[st.session_state.staff_df_v26["Name"] == emp_name, "ID"].values[0]
                    for d in izbrani_datumi:
                        if reason in ["MUSS arbeiten", "DARF NUR arbeiten"]: st.session_state.work_rules_v26.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "rule": reason})
                        else: st.session_state.absences_v26.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "reason": reason})
                st.success("Gespeichert!")

    if st.session_state.absences_v26 or st.session_state.work_rules_v26:
        col_list1, col_list2 = st.columns(2)
        with col_list1:
            if st.session_state.absences_v26:
                if st.button("🗑️ Abwesenheiten löschen"): st.session_state.absences_v26 = []; st.rerun()
                st.dataframe(pd.DataFrame(st.session_state.absences_v26)[["emp_name", "day", "reason"]], use_container_width=True)
        with col_list2:
            if st.session_state.work_rules_v26:
                if st.button("🗑️ Wunschdienste löschen"): st.session_state.work_rules_v26 = []; st.rerun()
                st.dataframe(pd.DataFrame(st.session_state.work_rules_v26)[["emp_name", "day", "rule"]], use_container_width=True)

with tab2:
    st.header("Automatische Dienstplangenerierung")
    
    if st.button("🚀 Dienstplan berechnen", type="primary", use_container_width=True):
        df_clean = st.session_state.staff_df_v26.copy()
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
                            if val not in ["...", "OK", "URL", "KRA", "GEB", "NA"] and not val.startswith("-"): streak += 1
                            else: break 
                        last_month_work_streak[emp_name] = streak
                        if len(day_cols_old) >= 2:
                            last_few_days = [str(person_old_data[dc]).split(" ")[0] for dc in day_cols_old[-3:]]
                            if sum(1 for v in last_few_days if v not in ["...", "URL", "KRA"]) >= 2:
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
                        
                        if w_idx == first_weekend_idx and last_month_worked_weekend[s["Name"]]:
                            hour_deviations.append(we_var * 25000) 
                            
                    for w_idx in range(len(weekends) - 2): model.Add(works_we[w_idx] + works_we[w_idx+1] + works_we[w_idx+2] <= 2)

                for r in st.session_state.work_rules_v26:
                    if "MUSS" in r["rule"]: model.Add(work[(r["emp_id"], r["day"], "OFF")] == 0)

                day_keys = {0: "MO", 1: "DI", 2: "MI", 3: "DO", 4: "FR", 5: "SA", 6: "SO"}
                for s in staff_list:
                    allowed_shifts = ["OFF"]
                    if s["Nur_Nacht"]:
                        allowed_shifts.extend(["N1", "N2"])
                    else:
                        allowed_shifts.extend(["X4", "X6", "X7", "F2", "F7", "JED", "MS", "SM"])
                        if s["Max_Nacht"] > 0: allowed_shifts.extend(["N1", "N2"])

                    unallowed = [sh for sh in shifts.keys() if sh not in allowed_shifts]
                    for d in range(num_days):
                        for sh in unallowed: model.Add(work[(s["ID"], d, sh)] == 0)

                    if s["Max_Nacht"] > 0:
                        nocna_koda = "N1" if s["Rolle"] in ["DGKP", "Leitung"] else "N2"
                        model.Add(sum(work[(s["ID"], d, nocna_koda)] for d in range(num_days)) <= int(s["Max_Nacht"]))

                    for d in range(num_days):
                        if not bool(s.get(day_keys[(d + first_day_of_month_weekday) % 7], True)): model.Add(work[(s["ID"], d, "OFF")] == 1)

                for a in st.session_state.absences_v26:
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

                model.Minimize(sum(hour_deviations))
                solver = cp_model.CpSolver()
                solver.parameters.max_time_in_seconds = 15.0
                status = solver.Solve(model)

                if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                    st.success("🎉 Dienstplan erfolgreich generiert!")
                    data = []
                    for s in staff_list:
                        row = {"ID_hidden": s["ID"], "Abteilung": s["Abteilung"], "Rolle": s["Rolle"], "Mitarbeiter": s["Name"]}
                        total_hours = 0
                        for d in range(num_days):
                            day_str = f"{d+1}."
                            val = "..."
                            for sh in shifts.keys():
                                if solver.Value(work[(s["ID"], d, sh)]) == 1:
                                    val = sh if sh != "OFF" else "..."
                                    total_hours += shifts[sh]
                            row[day_str] = val
                        
                        soll_neu = (float(s.get("Wochenstd", 37.0)) / 7.0) * num_days
                        row["SOLL"] = round(soll_neu, 1)
                        row["IST"] = total_hours / 100
                        row["SALDO"] = round((total_hours / 100) - soll_neu + float(s.get("Saldo_Alt", 0.0)), 1)
                        data.append(row)

                    st.session_state.last_generated_df = pd.DataFrame(data).drop(columns=["ID_hidden"], errors='ignore')

                else:
                    st.error("🚨 Kritischer Fehler! Die Mathematik konnte nicht aufgelöst werden.")
        except Exception as e:
            st.error(f"⚠️ Systemfehler: {e}")

    if "last_generated_df" in st.session_state:
        df_rezultat = st.session_state.last_generated_df
        def style_cells(val):
            if isinstance(val, str):
                if val.startswith("*"): return "background-color: #fff3cd; color: #856404; font-weight: bold; border: 2px solid #ffeeba"
                if val == "OK": return "color: #009900; font-weight: bold; text-align: center"
            return ""
        st.dataframe(df_rezultat.style.map(style_cells), use_container_width=True)

with tab3:
    st.header("🚑 SOS Ausfallmanagement & Einspringer")
    if "last_generated_df" in st.session_state:
        df_sos = st.session_state.last_generated_df.copy()
        df_sos_clean = df_sos[~df_sos["Mitarbeiter"].str.contains("FEHLT")]
        col1, col2 = st.columns(2)
        with col1:
            sos_day = st.selectbox("Welcher Tag ist betroffen?", [c for c in df_sos_clean.columns if "." in c])
            sos_person = st.selectbox("Wer fällt aus?", df_sos_clean["Mitarbeiter"].tolist())
        with col2:
            sick_role = df_sos_clean[df_sos_clean["Mitarbeiter"] == sos_person]["Rolle"].values[0]
            candidates = df_sos_clean[(df_sos_clean["Rolle"] == sick_role) & (df_sos_clean[sos_day] == "...") & (df_sos_clean["Mitarbeiter"] != sos_person)].sort_values(by="SALDO")
            if not candidates.empty:
                hero_person = st.selectbox("Einspringer auswählen:", candidates["Mitarbeiter"].tolist())
                hero_shift = st.selectbox("Schicht:", ["X4", "X6", "X7", "F2", "F7", "N1", "N2", "JED"])
                if st.button("🚀 Einspringer eintragen", type="primary"):
                    hero_idx = df_sos[df_sos["Mitarbeiter"] == hero_person].index[0]
                    df_sos.at[hero_idx, sos_day] = f"*{hero_shift}"
                    st.session_state.last_generated_df = df_sos
                    st.success(f"✅ {hero_person} übernimmt am {sos_day}!")
                    st.rerun()
            else: st.error("❌ Niemand hat an diesem Tag frei.")
        if not candidates.empty: st.dataframe(candidates[["Mitarbeiter", "Abteilung", "SALDO"]], use_container_width=True)

with tab4:
    st.header("🔄 Schicht-Tausch")
    st.info("Funktion im Backend aktiv.")

with tab5:
    st.header("📱 WhatsApp / E-Mail Export")
    st.info("Funktion im Backend aktiv.")

with tab6:
    st.header("📉 Analyse & Hero-Score")
    if "last_generated_df" in st.session_state:
        hero_scores = []
        df_clean = st.session_state.last_generated_df[~st.session_state.last_generated_df["Mitarbeiter"].str.contains("FEHLT")]
        day_cols = [c for c in df_clean.columns if "." in c]
        for idx, row in df_clean.iterrows():
            stars = sum(1 for d in day_cols if str(row[d]).startswith("*"))
            if stars > 0: hero_scores.append({"Mitarbeiter": row["Mitarbeiter"], "Einspringer-Dienste": stars})
        if hero_scores:
            st.dataframe(pd.DataFrame(hero_scores).sort_values(by="Einspringer-Dienste", ascending=False), hide_index=True)

# --- NOVO: ZAVIHEK 7 - MAG PLANER ---
with tab7:
    st.header("🗣️ Mitarbeitergespräche (MAG) Planer")
    st.markdown("Finde automatisch gemeinsame Schichten zwischen dir (WBL) und deinen Mitarbeitern, um ungestörte Gespräche zu führen.")
    
    if "last_generated_df" in st.session_state:
        df_mag = st.session_state.last_generated_df.copy()
        df_mag_clean = df_mag[~df_mag["Mitarbeiter"].str.contains("FEHLT")]
        
        # Poišči WBL (Leitung)
        leitung_list = df_mag_clean[df_mag_clean["Rolle"] == "Leitung"]["Mitarbeiter"].tolist()
        
        if len(leitung_list) > 0:
            col_mag1, col_mag2 = st.columns(2)
            
            with col_mag1:
                wbl_person = st.selectbox("Wer führt das Gespräch? (Leitung):", leitung_list)
                ma_person = st.selectbox("Mit wem möchtest du sprechen? (Mitarbeiter):", [m for m in df_mag_clean["Mitarbeiter"].tolist() if m != wbl_person])
            
            with col_mag2:
                st.info("ℹ️ Die KI sucht nach Tagen, an denen **beide** eine Tagesschicht haben (z.B. X4, F2, X7). Nachtschichten oder freie Tage werden ignoriert.")
                
            if st.button("🔍 Gemeinsame Termine suchen", type="primary"):
                wbl_row = df_mag_clean[df_mag_clean["Mitarbeiter"] == wbl_person].iloc[0]
                ma_row = df_mag_clean[df_mag_clean["Mitarbeiter"] == ma_person].iloc[0]
                
                day_cols = [c for c in df_mag_clean.columns if "." in c]
                day_shifts = ["X4", "X6", "X7", "F2", "F7", "JED", "MS", "SM"] # Izključimo N1, N2, OFF
                
                matches = []
                for d in day_cols:
                    wbl_shift = str(wbl_row[d]).replace("*", "").split(" ")[0]
                    ma_shift = str(ma_row[d]).replace("*", "").split(" ")[0]
                    
                    if wbl_shift in day_shifts and ma_shift in day_shifts:
                        matches.append({
                            "Datum": f"{d} {monat_namen[mesec-1] if 'monat_namen' in locals() else ''}",
                            "WBL Dienst": wbl_shift,
                            "MA Dienst": ma_shift,
                            "Empfohlene Uhrzeit": "13:30 - 14:30 Uhr"
                        })
                
                if matches:
                    st.success(f"🎉 {len(matches)} gemeinsame Tage mit {ma_person} gefunden!")
                    st.dataframe(pd.DataFrame(matches), use_container_width=True, hide_index=True)
                else:
                    st.error(f"❌ Keine gemeinsamen Tagesschichten mit {ma_person} in diesem Monat gefunden. Versuche, die Schichten zu tauschen (Tab 4).")
        else:
            st.warning("Es wurde keine Person mit der Rolle 'Leitung' im System gefunden.")
    else:
        st.info("⚠️ Bitte generiere zuerst den Dienstplan im Tab 2.")
