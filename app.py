import calendar
from datetime import date
import io
import re
import os
import holidays
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KI-Dienstplan PRO 19.0", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 19.0 - Schicht-Tausch-Börse)")
st.markdown(
    "Neue Funktionen: **Interaktiver Schicht-Tausch** mit automatischer Prüfung des Arbeitsrechts "
    "(Ruhezeiten, Rollen-Sperre) und sofortiger Neuberechnung der Plus-/Minusstunden!"
)

tab1, tab2, tab3, tab4 = st.tabs(["⚙️ 1. Einstellungen", "📅 2. Dienstplan", "🚑 3. SOS", "🔄 4. Tausch-Börse"])

with tab1:
    st.header("1. Monat und Jahr auswählen")
    col_date1, col_date2 = st.columns(2)
    with col_date1:
        leto = st.selectbox("Jahr:", [2026, 2027, 2028], index=0)
    with col_date2:
        mesec = st.selectbox(
            "Monat:",
            list(range(1, 13)),
            format_func=lambda x: [
                "Januar", "Februar", "März", "April", "Mai", "Juni",
                "Juli", "August", "September", "Oktober", "November", "Dezember"
            ][x - 1],
        )

    first_day_of_month_weekday, num_days = calendar.monthrange(leto, mesec)
    at_holidays = holidays.Austria(years=leto, subdiv='6')

    st.header("2. Team verwalten")
    
    if "staff_df_v19" not in st.session_state:
        if os.path.exists("team_data.csv"):
            try:
                loaded_df = pd.read_csv("team_data.csv")
                
                if "Nur_Nacht" not in loaded_df.columns: loaded_df["Nur_Nacht"] = False
                if "ID" not in loaded_df.columns: loaded_df["ID"] = range(len(loaded_df))
                if "Ue42_ENT" not in loaded_df.columns: loaded_df["Ue42_ENT"] = False
                if "Geb_Monat" not in loaded_df.columns: loaded_df["Geb_Monat"] = "Ohne"
                if "FT" not in loaded_df.columns: loaded_df["FT"] = True
                if "Wochenstd" not in loaded_df.columns: loaded_df["Wochenstd"] = 37.0
                    
                cols_order = ["ID", "Name", "Abteilung", "Rolle", "Wochenstd", "Prozent", "Saldo_Alt", "Max_Nacht", "Nur_Nacht", 
                              "MO", "DI", "MI", "DO", "FR", "SA", "SO", "FT", "Spezialdienst", "Ue42_ENT", "Geb_Monat"]
                
                for c in cols_order:
                    if c not in loaded_df.columns:
                        if c in ["MO", "DI", "MI", "DO", "FR", "SA", "SO", "FT"]: loaded_df[c] = True
                        elif c in ["Spezialdienst", "Geb_Monat"]: loaded_df[c] = "Ohne"
                        else: loaded_df[c] = 0
                            
                st.session_state.staff_df_v19 = loaded_df[cols_order]
            except Exception:
                pass 

        if "staff_df_v19" not in st.session_state:
            initial_staff = []
            initial_staff.append({
                "ID": 0, "Name": "WBL (Uroš)", "Abteilung": "Abteilung H", "Rolle": "Leitung",
                "Wochenstd": 37.0, "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False,
                "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": False, "SO": False, "FT": False,
                "Spezialdienst": "Ohne", "Ue42_ENT": False, "Geb_Monat": "März"
            })
            for i in range(1, 4):
                initial_staff.append({
                    "ID": len(initial_staff), "Name": f"DGKP F-{i}", "Abteilung": "Abteilung F", "Rolle": "DGKP",
                    "Wochenstd": 37.0, "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 7, "Nur_Nacht": True,
                    "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True,
                    "Spezialdienst": "Ohne", "Ue42_ENT": False, "Geb_Monat": "Ohne"
                })
            for i in range(1, 5):
                initial_staff.append({
                    "ID": len(initial_staff), "Name": f"DGKP B-{i}", "Abteilung": "Abteilung B", "Rolle": "DGKP",
                    "Wochenstd": 37.0, "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False,
                    "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True,
                    "Spezialdienst": "Ohne", "Ue42_ENT": False, "Geb_Monat": "Ohne"
                })
            st.session_state.staff_df_v19 = pd.DataFrame(initial_staff)

    with st.form("team_editor_form"):
        edited_data = st.data_editor(
            st.session_state.staff_df_v19,
            num_rows="dynamic",
            key="tabelle_mitarbeiter_v19",
            column_config={
                "ID": None, "Ue42_ENT": None, "Geb_Monat": None,
                "Abteilung": st.column_config.SelectboxColumn("Abteilung", options=["Abteilung B", "Abteilung H", "Abteilung F"]),
                "Rolle": st.column_config.SelectboxColumn("Rolle", options=["Leitung", "DGKP", "Pflegeassistenz", "Heimhelfer"]),
                "Wochenstd": st.column_config.NumberColumn("Wochenstd.", min_value=10.0, max_value=50.0, default=37.0),
                "Prozent": st.column_config.NumberColumn("Anst. (%)", min_value=10, max_value=120, default=100),
                "Saldo_Alt": st.column_config.NumberColumn("Saldo Alt (+/-)", default=0.0),
                "Max_Nacht": st.column_config.NumberColumn("Max. Nacht", min_value=0, max_value=15, default=0),
                "Nur_Nacht": st.column_config.CheckboxColumn("Nur Nacht", default=False),
                "MO": st.column_config.CheckboxColumn("Mo", default=True),
                "DI": st.column_config.CheckboxColumn("Di", default=True),
                "MI": st.column_config.CheckboxColumn("Mi", default=True),
                "DO": st.column_config.CheckboxColumn("Do", default=True),
                "FR": st.column_config.CheckboxColumn("Fr", default=True),
                "SA": st.column_config.CheckboxColumn("Sa", default=True),
                "SO": st.column_config.CheckboxColumn("So", default=True),
                "FT": st.column_config.CheckboxColumn("FT", default=True),
                "Spezialdienst": st.column_config.SelectboxColumn(
                    "Spezialdienst",
                    options=["Ohne", "Nur WE und Feiertage", "F2 (PA 6:45-19:15)", "F7 (PA 6:45-18:15)", 
                             "X7 (DGKP 6:45-19:15)", "X6 (DGKP 6:45-18:15)", "X4 (DGKP 6:45-15:30)", 
                             "JED (Speisesaal)", "MS (7:30-15:00)", "SM (6:45-18:00)"]
                )
            },
            use_container_width=True,
        )
        submit_team = st.form_submit_button("💾 Spremembe ekipe potrdi in shrani", type="primary")
        if submit_team:
            st.session_state.staff_df_v19 = edited_data
            edited_data.to_csv("team_data.csv", index=False)
            st.success("✅ Teamdaten erfolgreich gespeichert!")

    st.divider()

    if "absences_v19" not in st.session_state: st.session_state.absences_v19 = []
    if "work_rules_v19" not in st.session_state: st.session_state.work_rules_v19 = []

    st.header("3. Abwesenheiten & Wünsche")
    col_smart, col_manual = st.columns([1, 1])
    with col_smart:
        st.subheader("🤖 Smart-Wunsch KI")
        with st.form("smart_wunsch_form"):
            emp_smart = st.selectbox("Wer hat einen Wunsch?", options=st.session_state.staff_df_v19["Name"].dropna().tolist())
            smart_text = st.text_input("Beispiel: 'želi prosto 12. in 14.' oder 'arbeiten am 5.'")
            if st.form_submit_button("✨ KI analysieren") and smart_text:
                dates = [int(x) for x in re.findall(r'\b(?:[1-9]|[12][0-9]|3[01])\b', smart_text)]
                txt = smart_text.lower()
                is_free = any(w in txt for w in ["frei", "prosto", "nicht", "ne dela", "urlaub", "dopust", "ausfall"])
                is_work = any(w in txt for w in ["arbeit", "dela", "muss", "will", "želi", "dienst"])
                
                if not dates:
                    st.error("❌ Keine Daten gefunden.")
                else:
                    emp_id = st.session_state.staff_df_v19.loc[st.session_state.staff_df_v19["Name"] == emp_smart, "ID"].values[0]
                    valid_dates = [d for d in dates if 1 <= d <= num_days]
                    if is_free:
                        for d in valid_dates:
                            st.session_state.absences_v19.append({"emp_id": emp_id, "emp_name": emp_smart, "day": d-1, "reason": "WUNSCH (Frei)"})
                        st.success(f"🤖 Erledigt für {emp_smart}: FREI am {valid_dates}")
                    elif is_work:
                        for d in valid_dates:
                            st.session_state.work_rules_v19.append({"emp_id": emp_id, "emp_name": emp_smart, "day": d-1, "rule": "MUSS arbeiten"})
                        st.success(f"🤖 Erledigt für {emp_smart}: MUSS ARBEITEN am {valid_dates}")
                    else:
                        st.warning("Bitte 'frei' oder 'dela' ins Textfeld schreiben.")
    with col_manual:
        st.subheader("Oder Manuell:")
        with st.form("absence_form"):
            emp_names = st.multiselect("Mitarbeiter:", options=st.session_state.staff_df_v19["Name"].dropna().tolist(), key="abs_emp")
            izbrani_datumi = st.multiselect("Tage:", options=list(range(1, num_days + 1)), key="abs_dates")
            reason = st.selectbox("Grund/Regel:", ["URL (Urlaub)", "KRA (Krankenstand)", "GEB", "ENT", "NA", "Ü", "MUSS arbeiten", "DARF NUR arbeiten"])
            if st.form_submit_button("Manuell Speichern") and izbrani_datumi and emp_names:
                for emp_name in emp_names:
                    emp_id = st.session_state.staff_df_v19.loc[st.session_state.staff_df_v19["Name"] == emp_name, "ID"].values[0]
                    for d in izbrani_datumi:
                        if reason in ["MUSS arbeiten", "DARF NUR arbeiten"]:
                            st.session_state.work_rules_v19.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "rule": reason})
                        else:
                            st.session_state.absences_v19.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "reason": reason})
                st.success("Gespeichert!")

    if st.session_state.absences_v19 or st.session_state.work_rules_v19:
        st.write("---")
        col_list1, col_list2 = st.columns(2)
        with col_list1:
            if st.session_state.absences_v19:
                if st.button("🗑️ Abwesenheiten löschen", key="del_abs"):
                    st.session_state.absences_v19 = []
                    st.rerun()
                abs_df = pd.DataFrame(st.session_state.absences_v19)
                abs_df["Datum"] = abs_df["day"].apply(lambda x: f"{x+1}.")
                st.dataframe(abs_df[["emp_name", "Datum", "reason"]], use_container_width=True)
        with col_list2:
            if st.session_state.work_rules_v19:
                if st.button("🗑️ Wunschdienste löschen", key="del_work"):
                    st.session_state.work_rules_v19 = []
                    st.rerun()
                work_df = pd.DataFrame(st.session_state.work_rules_v19)
                work_df["Datum"] = work_df["day"].apply(lambda x: f"{x+1}.")
                st.dataframe(work_df[["emp_name", "Datum", "rule"]], use_container_width=True)

with tab2:
    st.header("Automatische Dienstplangenerierung")
    if st.button("🚀 Dienstplan berechnen", type="primary", use_container_width=True):
        
        df_clean = st.session_state.staff_df_v19.copy()
        if "Nur_Nacht" not in df_clean.columns: df_clean["Nur_Nacht"] = False
        df_clean["Nur_Nacht"] = df_clean["Nur_Nacht"].fillna(False).astype(bool)
        if "Wochenstd" not in df_clean.columns: df_clean["Wochenstd"] = 37.0
        
        df_clean["Spezialdienst"] = df_clean["Spezialdienst"].fillna("Ohne")
        df_clean["Name"] = df_clean["Name"].fillna("Unbekannt")
        df_clean["Rolle"] = df_clean["Rolle"].fillna("Pflegeassistenz")
        df_clean["Abteilung"] = df_clean["Abteilung"].fillna("Abteilung B")
        df_clean["Max_Nacht"] = df_clean["Max_Nacht"].fillna(0).astype(int)
        df_clean["Wochenstd"] = df_clean["Wochenstd"].fillna(37.0).astype(float)
        df_clean["Prozent"] = df_clean["Prozent"].fillna(100).astype(float)
        df_clean["Saldo_Alt"] = df_clean["Saldo_Alt"].fillna(0.0).astype(float)
        
        for day in ["MO", "DI", "MI", "DO", "FR", "SA", "SO", "FT"]:
            if day in df_clean.columns:
                df_clean[day] = df_clean[day].fillna(True).astype(bool)
            
        staff_list = df_clean.to_dict("records")

        try:
            with st.spinner("KI berechnet Cross-Float, Joker-Stunden und X7-Besetzungen..."):
                model = cp_model.CpModel()
                hour_deviations = []

                shifts = {
                    "X4": 825, "X6": 1100, "X7": 1200,    
                    "F2": 1200, "F7": 1100,               
                    "N1": 1350, "N2": 1350,               
                    "JED": 1050,                          
                    "MS": 700, "SM": 1075, "OFF": 0       
                }

                work = {}
                for s in staff_list:
                    for d in range(num_days):
                        for sh in shifts.keys():
                            work[(s["ID"], d, sh)] = model.NewBoolVar(f'work_{s["ID"]}_{d}_{sh}')

                worked_day = {}
                for s in staff_list:
                    for d in range(num_days):
                        model.Add(sum(work[(s["ID"], d, sh)] for sh in shifts.keys()) == 1)
                        worked_d = model.NewBoolVar(f'worked_any_{s["ID"]}_{d}')
                        model.Add(worked_d == 1 - work[(s["ID"], d, "OFF")])
                        worked_day[(s["ID"], d)] = worked_d

                for s in staff_list:
                    for d in range(num_days - 5):
                        model.Add(sum(work[(s["ID"], d + i, "OFF")] for i in range(6)) >= 1)
                    for d in range(num_days - 3):
                        four_days = model.NewBoolVar(f'four_days_{s["ID"]}_{d}')
                        model.AddMinEquality(four_days, [worked_day[(s["ID"], d+i)] for i in range(4)])
                        hour_deviations.append(four_days * 3500)
                    for d in range(1, num_days - 1):
                        single_off = model.NewBoolVar(f'sing_off_{s["ID"]}_{d}')
                        model.AddMinEquality(single_off, [worked_day[(s["ID"], d-1)], work[(s["ID"], d, "OFF")], worked_day[(s["ID"], d+1)]])
                        hour_deviations.append(single_off * 1000)

                weekends = []
                sat = -1
                for d in range(num_days):
                    dow = (d + first_day_of_month_weekday) % 7
                    if dow == 5: sat = d
                    elif dow == 6:
                        if sat != -1: weekends.append([sat, d])
                        else: weekends.append([d])
                        sat = -1
                if sat != -1: weekends.append([sat])

                for s in staff_list:
                    works_we = []
                    for w_idx, we_days in enumerate(weekends):
                        we_var = model.NewBoolVar(f'we_{s["ID"]}_{w_idx}')
                        model.AddMaxEquality(we_var, [worked_day[(s["ID"], day)] for day in we_days])
                        works_we.append(we_var)

                    for w_idx in range(len(weekends) - 2):
                        model.Add(works_we[w_idx] + works_we[w_idx+1] + works_we[w_idx+2] <= 2)

                    for w_idx in range(len(weekends) - 1):
                        cons_we = model.NewBoolVar(f'cons_we_{s["ID"]}_{w_idx}')
                        model.AddMinEquality(cons_we, [works_we[w_idx], works_we[w_idx+1]])
                        hour_deviations.append(cons_we * 5000)

                only_work_days = {s["ID"]: set() for s in staff_list}
                must_work_days = {s["ID"]: set() for s in staff_list}
                has_only_rule = {s["ID"]: False for s in staff_list}
                
                for r in st.session_state.work_rules_v19:
                    if "NUR" in r["rule"]:
                        only_work_days[r["emp_id"]].add(r["day"])
                        has_only_rule[r["emp_id"]] = True
                    elif "MUSS" in r["rule"]:
                        must_work_days[r["emp_id"]].add(r["day"])

                for s in staff_list:
                    e_id = s["ID"]
                    if has_only_rule[e_id]:
                        for d in range(num_days):
                            if d not in only_work_days[e_id]:
                                model.Add(work[(e_id, d, "OFF")] == 1)
                    for d in must_work_days[e_id]:
                        model.Add(work[(e_id, d, "OFF")] == 0)

                day_keys = {0: "MO", 1: "DI", 2: "MI", 3: "DO", 4: "FR", 5: "SA", 6: "SO"}
                for s in staff_list:
                    allowed_shifts = ["OFF"]
                    
                    if s["Nur_Nacht"]:
                        if s["Rolle"] in ["DGKP", "Leitung"]: allowed_shifts.append("N1")
                        else: allowed_shifts.append("N2")
                    else:
                        if s["Rolle"] in ["DGKP", "Leitung"]:
                            allowed_shifts.extend(["X4", "X6", "X7"])
                            if s["Max_Nacht"] > 0: allowed_shifts.append("N1")
                        elif s["Rolle"] == "Pflegeassistenz":
                            allowed_shifts.extend(["F2", "F7"])
                            if s["Max_Nacht"] > 0: allowed_shifts.append("N2")
                        elif s["Rolle"] == "Heimhelfer":
                            allowed_shifts.extend(["JED", "F7"])
                            if s["Max_Nacht"] > 0: allowed_shifts.append("N2")
                            
                        if s["Spezialdienst"] == "Nur WE und Feiertage":
                            for d in range(num_days):
                                dow = (d + first_day_of_month_weekday) % 7
                                is_we = dow >= 5
                                is_ft = date(leto, mesec, d+1) in at_holidays
                                if not (is_we or is_ft):
                                    model.Add(work[(s["ID"], d, "OFF")] == 1)
                        elif "F2" in s["Spezialdienst"]: allowed_shifts.append("F2")
                        elif "F7" in s["Spezialdienst"]: allowed_shifts.append("F7")
                        elif "X7" in s["Spezialdienst"]: allowed_shifts.append("X7")
                        elif "X6" in s["Spezialdienst"]: allowed_shifts.append("X6")
                        elif "X4" in s["Spezialdienst"]: allowed_shifts.append("X4")
                        elif "JED" in s["Spezialdienst"]: allowed_shifts.append("JED")
                        elif "MS" in s["Spezialdienst"]: allowed_shifts.append("MS")
                        elif "SM" in s["Spezialdienst"]: allowed_shifts.append("SM")

                    unallowed = [sh for sh in shifts.keys() if sh not in allowed_shifts]
                    for d in range(num_days):
                        for sh in unallowed:
                            model.Add(work[(s["ID"], d, sh)] == 0)

                    if s["Rolle"] == "DGKP":
                        for d in range(num_days):
                            hour_deviations.append(work[(s["ID"], d, "X4")] * 20000)

                    if s["Max_Nacht"] > 0:
                        nocna_koda = "N1" if s["Rolle"] in ["DGKP", "Leitung"] else "N2"
                        model.Add(sum(work[(s["ID"], d, nocna_koda)] for d in range(num_days)) <= int(s["Max_Nacht"]))

                    for d in range(num_days):
                        day_of_week = (d + first_day_of_month_weekday) % 7
                        day_name = day_keys[day_of_week]
                        is_ft = date(leto, mesec, d+1) in at_holidays
                        
                        if is_ft:
                            if not bool(s.get("FT", True)):
                                model.Add(work[(s["ID"], d, "OFF")] == 1)
                        else:
                            if not bool(s.get(day_name, True)):
                                model.Add(work[(s["ID"], d, "OFF")] == 1)

                for a in st.session_state.absences_v19:
                    if a["day"] < num_days:
                        model.Add(work[(a["emp_id"], a["day"], "OFF")] == 1)

                oB_tehniki = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]]
                oH_tehniki = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]]
                
                dgkp_B = [s["ID"] for s in staff_list if s["Rolle"] in ["DGKP", "Leitung"] and s["Abteilung"] == "Abteilung B" and not s["Nur_Nacht"]]
                dgkp_H = [s["ID"] for s in staff_list if s["Rolle"] in ["DGKP", "Leitung"] and s["Abteilung"] == "Abteilung H" and not s["Nur_Nacht"]]
                
                jedilnica_kadri = [s["ID"] for s in staff_list if "JED" in s["Spezialdienst"] or s["Rolle"] == "Heimhelfer"]
                dgkp_nocni = [s["ID"] for s in staff_list if s["Rolle"] == "DGKP" and (s["Max_Nacht"] > 0 or s["Nur_Nacht"])]
                tech_nocni_B = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and s["Max_Nacht"] > 0]
                tech_nocni_H = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and s["Max_Nacht"] > 0]
                
                day_shifts_tech = ["F2", "F7", "MS", "JED"]
                deficit_vars = {"JED": {}, "TB": {}, "TH": {}, "N1": {}, "N2B": {}, "N2H": {}, "X7B": {}, "X7H": {}}

                for d in range(num_days):
                    jed_diff = model.NewIntVar(0, 1, f'jed_diff_{d}')
                    deficit_vars["JED"][d] = jed_diff
                    if len(jedilnica_kadri) > 0:
                        model.Add(sum(work[(e, d, "JED")] for e in jedilnica_kadri) + jed_diff >= 1)
                        hour_deviations.append(jed_diff * 50000)

                    tb_diff = model.NewIntVar(0, 4, f'tb_diff_{d}')
                    deficit_vars["TB"][d] = tb_diff
                    if len(oB_tehniki) >= 3:
                        model.Add(sum(work[(e, d, sh)] for e in oB_tehniki for sh in day_shifts_tech) + tb_diff >= 4)
                        hour_deviations.append(tb_diff * 50000)

                    th_diff = model.NewIntVar(0, 4, f'th_diff_{d}')
                    deficit_vars["TH"][d] = th_diff
                    if len(oH_tehniki) >= 3:
                        model.Add(sum(work[(e, d, sh)] for e in oH_tehniki for sh in day_shifts_tech) + th_diff >= 4)
                        hour_deviations.append(th_diff * 50000)
                    
                    n1_diff = model.NewIntVar(0, 1, f'n1_diff_{d}')
                    deficit_vars["N1"][d] = n1_diff
                    if len(dgkp_nocni) > 0:
                        model.Add(sum(work[(e, d, "N1")] for e in dgkp_nocni) + n1_diff >= 1)
                        hour_deviations.append(n1_diff * 50000)
                    
                    n2b_diff = model.NewIntVar(0, 1, f'n2b_diff_{d}')
                    deficit_vars["N2B"][d] = n2b_diff
                    if len(tech_nocni_B) > 0:
                        model.Add(sum(work[(e, d, "N2")] for e in tech_nocni_B) + n2b_diff >= 1)
                        hour_deviations.append(n2b_diff * 50000)
                    
                    n2h_diff = model.NewIntVar(0, 1, f'n2h_diff_{d}')
                    deficit_vars["N2H"][d] = n2h_diff
                    if len(tech_nocni_H) > 0:
                        model.Add(sum(work[(e, d, "N2")] for e in tech_nocni_H) + n2h_diff >= 1)
                        hour_deviations.append(n2h_diff * 50000)
                    
                    x7_b_diff = model.NewIntVar(0, 1, f'x7_b_diff_{d}')
                    deficit_vars["X7B"][d] = x7_b_diff
                    if len(dgkp_B) > 0:
                        model.Add(sum(work[(e, d, "X7")] for e in dgkp_B) + x7_b_diff >= 1)
                        hour_deviations.append(x7_b_diff * 50000)

                    x7_h_diff = model.NewIntVar(0, 1, f'x7_h_diff_{d}')
                    deficit_vars["X7H"][d] = x7_h_diff
                    if len(dgkp_H) > 0:
                        model.Add(sum(work[(e, d, "X7")] for e in dgkp_H) + x7_h_diff >= 1)
                        hour_deviations.append(x7_h_diff * 50000)

                for s in staff_list:
                    for d in range(num_days - 1):
                        model.AddImplication(work[(s["ID"], d, "N1")], work[(s["ID"], d + 1, "OFF")])
                        model.AddImplication(work[(s["ID"], d, "N2")], work[(s["ID"], d + 1, "OFF")])

                for s in staff_list:
                    if s["Nur_Nacht"]: continue
                    
                    w_std = float(s.get("Wochenstd", 37.0))
                    standard_target = (w_std * (s["Prozent"] / 100.0) / 7.0) * num_days
                    
                    feiertags_stunden = 0
                    for d in range(num_days):
                        if date(leto, mesec, d+1) in at_holidays:
                            dow = (d + first_day_of_month_weekday) % 7
                            if dow < 5: 
                                feiertags_stunden += (w_std * (s["Prozent"] / 100.0) / 5.0)

                    saldo_alt = float(s.get("Saldo_Alt", 0.0))
                    adjusted_target = max(0, int((standard_target - feiertags_stunden - saldo_alt) * 100))
                    
                    total_hours = model.NewIntVar(0, 35000, f'tot_{s["ID"]}')
                    model.Add(total_hours == sum(work[(s["ID"], d, sh)] * shifts[sh] for d in range(num_days) for sh in shifts.keys()))

                    dev = model.NewIntVar(0, 20000, f'dev_{s["ID"]}')
                    model.Add(dev >= total_hours - adjusted_target)
                    model.Add(dev >= adjusted_target - total_hours)
                    hour_deviations.append(dev)

                model.Minimize(sum(hour_deviations))
                solver = cp_model.CpSolver()
                solver.parameters.max_time_in_seconds = 20.0
                status = solver.Solve(model)

                if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                    st.success("🎉 Dienstplan erfolgreich generiert!")

                    data = []
                    for s in staff_list:
                        row = {"ID_hidden": s["ID"], "Abteilung": s["Abteilung"], "Rolle": s["Rolle"], "Anst.%": s["Prozent"], "Mitarbeiter": s["Name"]}
                        total_hours = 0
                        for d in range(num_days):
                            day_str = f"{d+1}."
                            if date(leto, mesec, d+1) in at_holidays: day_str = f"{d+1}. (FT)"
                            
                            val = "..."
                            for sh in shifts.keys():
                                if solver.Value(work[(s["ID"], d, sh)]) == 1:
                                    val = sh if sh != "OFF" else "..."
                                    for a in st.session_state.absences_v19:
                                        if a["emp_id"] == s["ID"] and a["day"] == d:
                                            val = a["reason"].split(" ")[0] 
                                    total_hours += shifts[sh]
                            row[day_str] = val

                        w_std = float(s.get("Wochenstd", 37.0))
                        standard_target = (w_std * (s["Prozent"] / 100.0) / 7.0) * num_days
                        
                        feiertags_stunden = 0
                        for d in range(num_days):
                            if date(leto, mesec, d+1) in at_holidays and (d + first_day_of_month_weekday) % 7 < 5:
                                feiertags_stunden += (w_std * (s["Prozent"] / 100.0) / 5.0)
                        
                        soll_neu = standard_target - feiertags_stunden
                        saldo_alt = float(s.get("Saldo_Alt", 0.0))
                        
                        row["SOLL"] = round(soll_neu, 1)
                        row["IST"] = total_hours / 100
                        row["SALDO"] = round((total_hours / 100) - soll_neu + saldo_alt, 1)
                        data.append(row)

                    day_cols = [f"{d+1}." if date(leto, mesec, d+1) not in at_holidays else f"{d+1}. (FT)" for d in range(num_days)]
                    
                    for day_str in day_cols:
                        tech_b = [i for i, r in enumerate(data) if r["Abteilung"] == "Abteilung B" and r["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and r[day_str] in day_shifts_tech]
                        tech_h = [i for i, r in enumerate(data) if r["Abteilung"] == "Abteilung H" and r["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and r[day_str] in day_shifts_tech]
                        
                        while len(tech_b) < 4 and len(tech_h) > 4:
                            idx = tech_h.pop()
                            data[idx][day_str] = f"{data[idx][day_str]} ➔ B"
                            tech_b.append(idx)
                            
                        while len(tech_h) < 4 and len(tech_b) > 4:
                            idx = tech_b.pop()
                            data[idx][day_str] = f"{data[idx][day_str]} ➔ H"
                            tech_h.append(idx)
                            
                        x7_b = [i for i, r in enumerate(data) if r["Abteilung"] == "Abteilung B" and r["Rolle"] in ["DGKP", "Leitung"] and r[day_str] == "X7"]
                        x7_h = [i for i, r in enumerate(data) if r["Abteilung"] == "Abteilung H" and r["Rolle"] in ["DGKP", "Leitung"] and r[day_str] == "X7"]
                        
                        while len(x7_b) < 1 and len(x7_h) > 1:
                            idx = x7_h.pop()
                            data[idx][day_str] = f"X7 ➔ B"
                            x7_b.append(idx)
                            
                        while len(x7_h) < 1 and len(x7_b) > 1:
                            idx = x7_b.pop()
                            data[idx][day_str] = f"X7 ➔ H"
                            x7_h.append(idx)

                    fehlt_row_b = {"Abteilung": "Abteilung B", "Rolle": "", "Anst.%": "", "Mitarbeiter": "🚨 FEHLT (Pflege/JED)", "SOLL": "", "IST": "", "SALDO": ""}
                    fehlt_row_h = {"Abteilung": "Abteilung H", "Rolle": "", "Anst.%": "", "Mitarbeiter": "🚨 FEHLT (Pflege)", "SOLL": "", "IST": "", "SALDO": ""}
                    fehlt_row_f = {"Abteilung": "Abteilung F", "Rolle": "", "Anst.%": "", "Mitarbeiter": "🚨 FEHLT (DGKP N1/X7)", "SOLL": "", "IST": "", "SALDO": ""}

                    for d in range(num_days):
                        day_str = day_cols[d]
                        
                        t_b = sum(1 for r in data if r["Abteilung"] == "Abteilung B" and r["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and r[day_str][:2] in day_shifts_tech) + sum(1 for r in data if "➔ B" in r[day_str] and r["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]) - sum(1 for r in data if "➔ H" in r[day_str] and r["Rolle"] in ["Pflegeassistenz", "Heimhelfer"])
                        t_h = sum(1 for r in data if r["Abteilung"] == "Abteilung H" and r["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and r[day_str][:2] in day_shifts_tech) + sum(1 for r in data if "➔ H" in r[day_str] and r["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]) - sum(1 for r in data if "➔ B" in r[day_str] and r["Rolle"] in ["Pflegeassistenz", "Heimhelfer"])
                        
                        x7_b_cnt = sum(1 for r in data if r["Abteilung"] == "Abteilung B" and r["Rolle"] in ["DGKP", "Leitung"] and "X7" in r[day_str]) + sum(1 for r in data if "X7 ➔ B" in r[day_str]) - sum(1 for r in data if "X7 ➔ H" in r[day_str])
                        x7_h_cnt = sum(1 for r in data if r["Abteilung"] == "Abteilung H" and r["Rolle"] in ["DGKP", "Leitung"] and "X7" in r[day_str]) + sum(1 for r in data if "X7 ➔ H" in r[day_str]) - sum(1 for r in data if "X7 ➔ B" in r[day_str])
                        
                        jed_cnt = sum(1 for r in data if "JED" in r[day_str])
                        n1_cnt = sum(1 for r in data if "N1" in r[day_str])
                        n2b_cnt = sum(1 for r in data if r["Abteilung"] == "Abteilung B" and "N2" in r[day_str])
                        n2h_cnt = sum(1 for r in data if r["Abteilung"] == "Abteilung H" and "N2" in r[day_str])
                        
                        def_b = max(0, 4 - t_b) + max(0, 1 - jed_cnt) + max(0, 1 - n2b_cnt)
                        def_h = max(0, 4 - t_h) + max(0, 1 - n2h_cnt)
                        def_dgkp = max(0, 1 - x7_b_cnt) + max(0, 1 - x7_h_cnt) + max(0, 1 - n1_cnt)
                        
                        fehlt_row_b[day_str] = f"-{def_b}" if def_b > 0 else "OK"
                        fehlt_row_h[day_str] = f"-{def_h}" if def_h > 0 else "OK"
                        fehlt_row_f[day_str] = f"-{def_dgkp}" if def_dgkp > 0 else "OK"

                    data.extend([fehlt_row_b, fehlt_row_h, fehlt_row_f])
                    df_rezultat = pd.DataFrame(data).drop(columns=["ID_hidden"], errors='ignore')

                    st.session_state.last_generated_df = df_rezultat

                    def style_cells(val):
                        if isinstance(val, (int, float)):
                            if val > 12: return "background-color: #ffcccc; color: #990000; font-weight: bold"
                            elif val < -12: return "background-color: #ccccff; color: #000099; font-weight: bold"
                        elif isinstance(val, str):
                            if "➔" in val:
                                return "background-color: #d4edda; color: #006600; font-weight: bold; border: 2px solid #28a745"
                            if val.startswith("-") and val[1:].isdigit():
                                return "background-color: #ff0000; color: white; font-weight: bold; text-align: center"
                            if val == "OK":
                                return "color: #009900; font-weight: bold; text-align: center"
                        return ""

                    st.subheader("🔵 Abteilung B")
                    df_b = df_rezultat[df_rezultat["Abteilung"] == "Abteilung B"].drop(columns=["Abteilung"])
                    st.dataframe(df_b.style.map(style_cells), use_container_width=True)

                    st.subheader("🟢 Abteilung H")
                    df_h = df_rezultat[df_rezultat["Abteilung"] == "Abteilung H"].drop(columns=["Abteilung"])
                    st.dataframe(df_h.style.map(style_cells), use_container_width=True)

                    st.subheader("🟣 Abteilung F (Nacht-Pool)")
                    df_f = df_rezultat[df_rezultat["Abteilung"] == "Abteilung F"].drop(columns=["Abteilung"])
                    st.dataframe(df_f.style.map(style_cells), use_container_width=True)

                    st.divider()
                    st.subheader("📥 Dienstplan herunterladen")
                    csv_plan = df_rezultat.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        label="📄 Dienstplan als CSV/Excel herunterladen",
                        data=csv_plan,
                        file_name=f"Dienstplan_{leto}_{mesec}.csv",
                        mime="text/csv",
                        type="primary"
                    )

                else:
                    st.error("🚨 Kritischer Fehler! Die Mathematik konnte nicht aufgelöst werden.")
        except Exception as e:
            st.error(f"⚠️ Systemfehler: {e}")

with tab3:
    st.header("🚑 SOS Ausfallmanagement")
    if "last_generated_df" in st.session_state:
        df_sos = st.session_state.last_generated_df
        df_sos_clean = df_sos[~df_sos["Mitarbeiter"].str.contains("FEHLT")]
        
        sos_day = st.selectbox("1. Welcher Tag ist betroffen?", [c for c in df_sos_clean.columns if "." in c])
        sos_person = st.selectbox("2. Wer ist krank (KRA)?", df_sos_clean["Mitarbeiter"].tolist())
        
        if st.button("🔍 Ersatz suchen"):
            sick_role = df_sos_clean[df_sos_clean["Mitarbeiter"] == sos_person]["Rolle"].values[0]
            st.warning(f"{sos_person} ({sick_role}) fällt am {sos_day} aus.")
            
            candidates = df_sos_clean[
                (df_sos_clean["Rolle"] == sick_role) & 
                (df_sos_clean[sos_day] == "...") & 
                (df_sos_clean["Mitarbeiter"] != sos_person)
            ].sort_values(by="SALDO")
            
            if not candidates.empty:
                st.success(f"✅ Mögliche Ersatzpersonen gefunden (Sortiert nach Minus-Stunden):")
                st.dataframe(candidates[["Mitarbeiter", "Abteilung", "SALDO"]], use_container_width=True)
            else:
                st.error("❌ Niemand mit dieser Rolle hat an diesem Tag frei.")
    else:
        st.info("⚠️ Bitte generiere zuerst den Dienstplan im Tab 2.")

with tab4:
    st.header("🔄 Schicht-Tausch Börse")
    st.markdown("Sicherer Tausch von Diensten mit automatischer Arbeitsrecht-Prüfung und Live-Saldo-Korrektur.")

    if "last_generated_df" in st.session_state:
        df_tausch = st.session_state.last_generated_df.copy()
        df_tausch_clean = df_tausch[~df_tausch["Mitarbeiter"].str.contains("FEHLT")]
        day_cols = [c for c in df_tausch_clean.columns if "." in c]

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("👤 Person 1")
            p1_name = st.selectbox("Mitarbeiter 1:", df_tausch_clean["Mitarbeiter"].tolist(), key="p1_name")
            p1_day = st.selectbox("Tag 1:", day_cols, key="p1_day")
            
            p1_row_idx = df_tausch_clean[df_tausch_clean["Mitarbeiter"] == p1_name].index[0]
            p1_shift = df_tausch.at[p1_row_idx, p1_day]
            st.info(f"Aktueller Dienst: **{p1_shift}**")
            
        with col2:
            st.subheader("👥 Person 2")
            p2_name = st.selectbox("Mitarbeiter 2:", df_tausch_clean["Mitarbeiter"].tolist(), key="p2_name")
            p2_day = st.selectbox("Tag 2:", day_cols, key="p2_day")
            
            p2_row_idx = df_tausch_clean[df_tausch_clean["Mitarbeiter"] == p2_name].index[0]
            p2_shift = df_tausch.at[p2_row_idx, p2_day]
            st.info(f"Aktueller Dienst: **{p2_shift}**")

        if st.button("🔄 Schichten tauschen & prüfen", type="primary"):
            if p1_name == p2_name and p1_day == p2_day:
                st.warning("Das ist die gleiche Schicht!")
            else:
                errors = []
                role_p1 = df_tausch.at[p1_row_idx, "Rolle"]
                role_p2 = df_tausch.at[p2_row_idx, "Rolle"]
                
                dgkp_shifts = ["X4", "X6", "X7", "*X6", "*X7", "N1", "..."]
                pa_shifts = ["F2", "F7", "N2", "MS", "SM", "..."]
                hh_shifts = ["JED", "F7", "N2", "..."]

                allowed_p1 = dgkp_shifts if role_p1 in ["DGKP", "Leitung"] else (pa_shifts if role_p1 == "Pflegeassistenz" else hh_shifts)
                allowed_p2 = dgkp_shifts if role_p2 in ["DGKP", "Leitung"] else (pa_shifts if role_p2 == "Pflegeassistenz" else hh_shifts)
                
                clean_p2_shift = p2_shift.split(" ")[0] 
                clean_p1_shift = p1_shift.split(" ")[0]
                
                # Rollen-Check
                if clean_p2_shift not in allowed_p1 and clean_p2_shift not in ["URL", "KRA", "GEB"]:
                    errors.append(f"❌ {p1_name} ({role_p1}) darf keinen {clean_p2_shift}-Dienst machen.")
                if clean_p1_shift not in allowed_p2 and clean_p1_shift not in ["URL", "KRA", "GEB"]:
                    errors.append(f"❌ {p2_name} ({role_p2}) darf keinen {clean_p1_shift}-Dienst machen.")
                    
                d1_idx = day_cols.index(p1_day)
                d2_idx = day_cols.index(p2_day)
                
                # Ruhezeit-Check (Danach)
                if clean_p2_shift in ["N1", "N2"] and d1_idx < len(day_cols) - 1:
                    next_p1 = df_tausch.at[p1_row_idx, day_cols[d1_idx+1]].split(" ")[0]
                    if next_p1 != "..." and next_p1 != clean_p1_shift:
                        errors.append(f"❌ Ruhezeit-Verletzung: {p1_name} hätte nach dem neuen Nachtdienst keinen freien Tag.")
                        
                if clean_p1_shift in ["N1", "N2"] and d2_idx < len(day_cols) - 1:
                    next_p2 = df_tausch.at[p2_row_idx, day_cols[d2_idx+1]].split(" ")[0]
                    if next_p2 != "..." and next_p2 != clean_p2_shift:
                        errors.append(f"❌ Ruhezeit-Verletzung: {p2_name} hätte nach dem neuen Nachtdienst keinen freien Tag.")

                # Ruhezeit-Check (Davor)
                if d1_idx > 0:
                    prev_p1 = df_tausch.at[p1_row_idx, day_cols[d1_idx-1]].split(" ")[0]
                    if prev_p1 in ["N1", "N2"] and clean_p2_shift != "...":
                        errors.append(f"❌ Ruhezeit-Verletzung: {p1_name} hatte am Vortag Nachtdienst und MUSS frei haben.")
                
                if d2_idx > 0:
                    prev_p2 = df_tausch.at[p2_row_idx, day_cols[d2_idx-1]].split(" ")[0]
                    if prev_p2 in ["N1", "N2"] and clean_p1_shift != "...":
                        errors.append(f"❌ Ruhezeit-Verletzung: {p2_name} hatte am Vortag Nachtdienst und MUSS frei haben.")

                if errors:
                    for e in errors: st.error(e)
                else:
                    df_tausch.at[p1_row_idx, p1_day] = p2_shift
                    df_tausch.at[p2_row_idx, p2_day] = p1_shift
                    
                    shift_hours = {"X4": 8.25, "X6": 11.0, "X7": 12.0, "*X6": 11.0, "*X7": 12.0, 
                                   "F2": 12.0, "F7": 11.0, "N1": 13.5, "N2": 13.5, "JED": 10.5, "MS": 7.0, "SM": 10.75}
                    
                    for r_idx in [p1_row_idx, p2_row_idx]:
                        new_ist = 0
                        for dc in day_cols:
                            val = df_tausch.at[r_idx, dc].split(" ")[0]
                            if val in shift_hours: new_ist += shift_hours[val]
                        
                        soll = df_tausch.at[r_idx, "SOLL"]
                        name_r = df_tausch.at[r_idx, "Mitarbeiter"]
                        saldo_alt = float(st.session_state.staff_df_v19.loc[st.session_state.staff_df_v19["Name"] == name_r, "Saldo_Alt"].values[0])
                        
                        df_tausch.at[r_idx, "IST"] = new_ist
                        df_tausch.at[r_idx, "SALDO"] = round(new_ist - soll + saldo_alt, 1)

                    st.session_state.last_generated_df = df_tausch
                    st.success(f"✅ Erfolgreich getauscht! {p1_name} und {p2_name} haben die Dienste gewechselt.")
                    st.rerun()
    else:
        st.info("⚠️ Bitte generiere zuerst den Dienstplan im Tab 2.")
