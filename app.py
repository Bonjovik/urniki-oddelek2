import calendar
from datetime import date
import io
import re
import os
import holidays
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KI-Dienstplan PRO 17.0", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 17.0 - Fair-Weekend & Max 2-Rule)")
st.markdown(
    "Absolute Sperre (Hard-Constraint) für **3 Wochenenden in Folge** eingebaut! "
    "Die KI verteilt Wochenenden nun fair auf das gesamte Team (Vermeidet selbst 2 Wochenenden in Folge, wenn möglich)."
)

tab1, tab2, tab3 = st.tabs(["⚙️ 1. Einstellungen & Team", "📅 2. Dienstplan & KI", "🚑 3. SOS Ausfallmanagement"])

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
    st.info("💡 **Tipp:** Niemand wird mehr als 2 Wochenenden in Folge arbeiten. Das ist nun absolut verboten (Hard-Constraint).")

    if "staff_df_v17" not in st.session_state:
        if os.path.exists("team_data.csv"):
            try:
                loaded_df = pd.read_csv("team_data.csv")
                if "Nur_Nacht" not in loaded_df.columns:
                    loaded_df["Nur_Nacht"] = False
                    if "Spezialdienst" in loaded_df.columns:
                        loaded_df.loc[loaded_df["Spezialdienst"] == "Nur Nachtdienste", "Nur_Nacht"] = True
                        loaded_df.loc[loaded_df["Spezialdienst"] == "Nur Nachtdienste", "Spezialdienst"] = "Ohne"
                if "ID" not in loaded_df.columns:
                    loaded_df["ID"] = range(len(loaded_df))
                if "Ue42_ENT" not in loaded_df.columns:
                    loaded_df["Ue42_ENT"] = False
                if "Geb_Monat" not in loaded_df.columns:
                    loaded_df["Geb_Monat"] = "Ohne"
                if "FT" not in loaded_df.columns:
                    loaded_df["FT"] = True
                    
                cols_order = ["ID", "Name", "Abteilung", "Rolle", "Prozent", "Saldo_Alt", "Max_Nacht", "Nur_Nacht", 
                              "MO", "DI", "MI", "DO", "FR", "SA", "SO", "FT", "Spezialdienst", "Ue42_ENT", "Geb_Monat"]
                
                for c in cols_order:
                    if c not in loaded_df.columns:
                        if c in ["MO", "DI", "MI", "DO", "FR", "SA", "SO", "FT"]:
                            loaded_df[c] = True
                        elif c in ["Spezialdienst", "Geb_Monat"]:
                            loaded_df[c] = "Ohne"
                        else:
                            loaded_df[c] = 0
                            
                st.session_state.staff_df_v17 = loaded_df[cols_order]
            except Exception:
                pass 

        if "staff_df_v17" not in st.session_state:
            initial_staff = []
            initial_staff.append({
                "ID": 0, "Name": "WBL (Uroš)", "Abteilung": "Abteilung H", "Rolle": "Leitung",
                "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False,
                "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": False, "SO": False, "FT": False,
                "Spezialdienst": "Ohne", "Ue42_ENT": False, "Geb_Monat": "März"
            })
            for i in range(1, 4):
                initial_staff.append({
                    "ID": len(initial_staff), "Name": f"DGKP F-{i} (Pool)", "Abteilung": "Abteilung F", "Rolle": "DGKP",
                    "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 7, "Nur_Nacht": True,
                    "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True,
                    "Spezialdienst": "Ohne", "Ue42_ENT": False, "Geb_Monat": "Ohne"
                })
            for i in range(1, 5):
                initial_staff.append({
                    "ID": len(initial_staff), "Name": f"DGKP B-{i}", "Abteilung": "Abteilung B", "Rolle": "DGKP",
                    "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False,
                    "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True,
                    "Spezialdienst": "Ohne", "Ue42_ENT": False, "Geb_Monat": "Ohne"
                })
            st.session_state.staff_df_v17 = pd.DataFrame(initial_staff)

    with st.form("team_editor_form"):
        edited_data = st.data_editor(
            st.session_state.staff_df_v17,
            num_rows="dynamic",
            key="tabelle_mitarbeiter_v17",
            column_config={
                "ID": None, "Ue42_ENT": None, "Geb_Monat": None,
                "Abteilung": st.column_config.SelectboxColumn("Abteilung", options=["Abteilung B", "Abteilung H", "Abteilung F"]),
                "Rolle": st.column_config.SelectboxColumn("Rolle", options=["Leitung", "DGKP", "Pflegeassistenz", "Heimhelfer"]),
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
            st.session_state.staff_df_v17 = edited_data
            edited_data.to_csv("team_data.csv", index=False)
            st.success("✅ Teamdaten erfolgreich gespeichert!")

    st.divider()

    if "absences_v17" not in st.session_state: st.session_state.absences_v17 = []
    if "work_rules_v17" not in st.session_state: st.session_state.work_rules_v17 = []

    st.header("3. Abwesenheiten & Wünsche")
    col_smart, col_manual = st.columns([1, 1])
    with col_smart:
        st.subheader("🤖 Smart-Wunsch KI (Freitext)")
        with st.form("smart_wunsch_form"):
            emp_smart = st.selectbox("Wer hat einen Wunsch?", options=st.session_state.staff_df_v17["Name"].dropna().tolist())
            smart_text = st.text_input("Beispiel: 'želi prosto 12. in 14.' oder 'arbeiten am 5.'")
            if st.form_submit_button("✨ KI analysieren") and smart_text:
                dates = [int(x) for x in re.findall(r'\b(?:[1-9]|[12][0-9]|3[01])\b', smart_text)]
                txt = smart_text.lower()
                is_free = any(w in txt for w in ["frei", "prosto", "nicht", "ne dela", "urlaub", "dopust", "ausfall"])
                is_work = any(w in txt for w in ["arbeit", "dela", "muss", "will", "želi", "dienst"])
                
                if not dates:
                    st.error("❌ Die KI konnte keine Datum-Zahlen finden.")
                else:
                    emp_id = st.session_state.staff_df_v17.loc[st.session_state.staff_df_v17["Name"] == emp_smart, "ID"].values[0]
                    valid_dates = [d for d in dates if 1 <= d <= num_days]
                    if is_free:
                        for d in valid_dates:
                            st.session_state.absences_v17.append({"emp_id": emp_id, "emp_name": emp_smart, "day": d-1, "reason": "WUNSCH (Frei)"})
                        st.success(f"🤖 KI hat verstanden: {emp_smart} ist FREI am: {valid_dates}")
                    elif is_work:
                        for d in valid_dates:
                            st.session_state.work_rules_v17.append({"emp_id": emp_id, "emp_name": emp_smart, "day": d-1, "rule": "MUSS arbeiten"})
                        st.success(f"🤖 KI hat verstanden: {emp_smart} MUSS ARBEITEN am: {valid_dates}")
                    else:
                        st.warning("KI ist sich unsicher. Bitte 'frei' oder 'dela' verwenden.")
    with col_manual:
        st.subheader("Oder Manuell eintragen:")
        with st.form("absence_form"):
            emp_names = st.multiselect("Mitarbeiter:", options=st.session_state.staff_df_v17["Name"].dropna().tolist(), key="abs_emp")
            izbrani_datumi = st.multiselect("Tage:", options=list(range(1, num_days + 1)), key="abs_dates")
            reason = st.selectbox("Grund/Regel:", ["URL (Urlaub)", "KRA (Krankenstand)", "GEB", "ENT", "NA", "Ü", "MUSS arbeiten", "DARF NUR arbeiten"])
            if st.form_submit_button("Manuell Speichern") and izbrani_datumi and emp_names:
                for emp_name in emp_names:
                    emp_id = st.session_state.staff_df_v17.loc[st.session_state.staff_df_v17["Name"] == emp_name, "ID"].values[0]
                    for d in izbrani_datumi:
                        if reason in ["MUSS arbeiten", "DARF NUR arbeiten"]:
                            st.session_state.work_rules_v17.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "rule": reason})
                        else:
                            st.session_state.absences_v17.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "reason": reason})
                st.success("Gespeichert!")

    if st.session_state.absences_v17 or st.session_state.work_rules_v17:
        st.write("---")
        col_list1, col_list2 = st.columns(2)
        with col_list1:
            if st.session_state.absences_v17:
                if st.button("🗑️ Abwesenheiten/Frei löschen", key="del_abs"):
                    st.session_state.absences_v17 = []
                    st.rerun()
                abs_df = pd.DataFrame(st.session_state.absences_v17)
                abs_df["Datum"] = abs_df["day"].apply(lambda x: f"{x+1}.")
                st.dataframe(abs_df[["emp_name", "Datum", "reason"]], use_container_width=True)
        with col_list2:
            if st.session_state.work_rules_v17:
                if st.button("🗑️ Wunschdienste (Arbeiten) löschen", key="del_work"):
                    st.session_state.work_rules_v17 = []
                    st.rerun()
                work_df = pd.DataFrame(st.session_state.work_rules_v17)
                work_df["Datum"] = work_df["day"].apply(lambda x: f"{x+1}.")
                st.dataframe(work_df[["emp_name", "Datum", "rule"]], use_container_width=True)

with tab2:
    st.header("Automatische Dienstplangenerierung")
    if st.button("🚀 Dienstplan berechnen", type="primary", use_container_width=True):
        
        df_clean = st.session_state.staff_df_v17.copy()
        if "Nur_Nacht" not in df_clean.columns: df_clean["Nur_Nacht"] = False
        df_clean["Nur_Nacht"] = df_clean["Nur_Nacht"].fillna(False).astype(bool)
        if "ID" not in df_clean.columns: df_clean["ID"] = range(len(df_clean))
        
        df_clean["Spezialdienst"] = df_clean["Spezialdienst"].fillna("Ohne")
        df_clean["Name"] = df_clean["Name"].fillna("Unbekannt")
        df_clean["Rolle"] = df_clean["Rolle"].fillna("Pflegeassistenz")
        df_clean["Abteilung"] = df_clean["Abteilung"].fillna("Abteilung B")
        df_clean["Max_Nacht"] = df_clean["Max_Nacht"].fillna(0).astype(int)
        df_clean["Prozent"] = df_clean["Prozent"].fillna(100).astype(float)
        df_clean["Saldo_Alt"] = df_clean["Saldo_Alt"].fillna(0.0).astype(float)
        
        for day in ["MO", "DI", "MI", "DO", "FR", "SA", "SO", "FT"]:
            if day in df_clean.columns:
                df_clean[day] = df_clean[day].fillna(True).astype(bool)
            
        staff_list = df_clean.to_dict("records")

        try:
            with st.spinner("KI berechnet Fairness, 3-Wochenenden-Verbot und Rollen..."):
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

                    # --- ZAKON O VIKENDIH (HARD CONSTRAINT & FAIRNESS) ---
                    # 1. Absolutna prepoved 3 vikendov zapored (Hard constraint)
                    for w_idx in range(len(weekends) - 2):
                        model.Add(works_we[w_idx] + works_we[w_idx+1] + works_we[w_idx+2] <= 2)

                    # 2. Močna kazen za 2 vikenda zapored (Soft constraint za fair-play)
                    for w_idx in range(len(weekends) - 1):
                        cons_we = model.NewBoolVar(f'cons_we_{s["ID"]}_{w_idx}')
                        model.AddMinEquality(cons_we, [works_we[w_idx], works_we[w_idx+1]])
                        hour_deviations.append(cons_we * 5000) # Ogromna kazen za 2 vikenda zapored!

                only_work_days = {s["ID"]: set() for s in staff_list}
                must_work_days = {s["ID"]: set() for s in staff_list}
                has_only_rule = {s["ID"]: False for s in staff_list}
                
                for r in st.session_state.work_rules_v17:
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

                for a in st.session_state.absences_v17:
                    if a["day"] < num_days:
                        model.Add(work[(a["emp_id"], a["day"], "OFF")] == 1)

                oB_tehniki = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]]
                oH_tehniki = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]]
                all_dgkp = [s["ID"] for s in staff_list if s["Rolle"] in ["DGKP", "Leitung"]]
                jedilnica_kadri = [s["ID"] for s in staff_list if "JED" in s["Spezialdienst"] or s["Rolle"] == "Heimhelfer"]
                
                dgkp_nocni = [s["ID"] for s in staff_list if s["Rolle"] == "DGKP" and (s["Max_Nacht"] > 0 or s["Nur_Nacht"])]
                tech_nocni_B = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and s["Max_Nacht"] > 0]
                tech_nocni_H = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and s["Max_Nacht"] > 0]
                
                day_shifts_tech = ["F2", "F7", "MS", "JED"]
                deficit_vars = {"JED": {}, "TB": {}, "TH": {}, "N1": {}, "N2B": {}, "N2H": {}, "X7": {}}

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
                    
                    x7_diff = model.NewIntVar(0, 1, f'x7_diff_{d}')
                    deficit_vars["X7"][d] = x7_diff
                    if len(all_dgkp) > 0:
                        model.Add(sum(work[(e, d, "X7")] for e in all_dgkp) + x7_diff >= 1)
                        hour_deviations.append(x7_diff * 50000)

                for s in staff_list:
                    for d in range(num_days - 1):
                        model.AddImplication(work[(s["ID"], d, "N1")], work[(s["ID"], d + 1, "OFF")])
                        model.AddImplication(work[(s["ID"], d, "N2")], work[(s["ID"], d + 1, "OFF")])

                for s in staff_list:
                    if s["Nur_Nacht"]: continue
                    
                    standard_target = (37.0 * (s["Prozent"] / 100.0) / 7.0) * num_days
                    feiertags_stunden = 0
                    for d in range(num_days):
                        if date(leto, mesec, d+1) in at_holidays:
                            dow = (d + first_day_of_month_weekday) % 7
                            if dow < 5: 
                                feiertags_stunden += (37.0 * (s["Prozent"] / 100.0) / 5.0)

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
                    st.success("🎉 Dienstplan erfolgreich generiert! Maximale Fairness bei Wochenenden angewendet.")

                    data = []
                    for s in staff_list:
                        row = {"Abteilung": s["Abteilung"], "Rolle": s["Rolle"], "Anst.%": s["Prozent"], "Mitarbeiter": s["Name"]}
                        total_hours = 0
                        for d in range(num_days):
                            day_str = f"{d+1}."
                            if date(leto, mesec, d+1) in at_holidays: day_str = f"{d+1}. (FT)"
                            
                            val = "..."
                            for sh in shifts.keys():
                                if solver.Value(work[(s["ID"], d, sh)]) == 1:
                                    val = sh if sh != "OFF" else "..."
                                    for a in st.session_state.absences_v17:
                                        if a["emp_id"] == s["ID"] and a["day"] == d:
                                            val = a["reason"].split(" ")[0] 
                                    total_hours += shifts[sh]
                            row[day_str] = val

                        standard_target = (37.0 * (s["Prozent"] / 100.0) / 7.0) * num_days
                        
                        feiertags_stunden = 0
                        for d in range(num_days):
                            if date(leto, mesec, d+1) in at_holidays and (d + first_day_of_month_weekday) % 7 < 5:
                                feiertags_stunden += (37.0 * (s["Prozent"] / 100.0) / 5.0)
                        
                        soll_neu = standard_target - feiertags_stunden
                        saldo_alt = float(s.get("Saldo_Alt", 0.0))
                        
                        row["SOLL"] = round(soll_neu, 1)
                        row["IST"] = total_hours / 100
                        row["SALDO"] = round((total_hours / 100) - soll_neu + saldo_alt, 1)
                        data.append(row)

                    fehlt_row_b = {"Abteilung": "Abteilung B", "Rolle": "", "Anst.%": "", "Mitarbeiter": "🚨 FEHLT (Pflege/JED)", "SOLL": "", "IST": "", "SALDO": ""}
                    fehlt_row_h = {"Abteilung": "Abteilung H", "Rolle": "", "Anst.%": "", "Mitarbeiter": "🚨 FEHLT (Pflege)", "SOLL": "", "IST": "", "SALDO": ""}
                    fehlt_row_f = {"Abteilung": "Abteilung F", "Rolle": "", "Anst.%": "", "Mitarbeiter": "🚨 FEHLT (DGKP N1/X7)", "SOLL": "", "IST": "", "SALDO": ""}

                    for d in range(num_days):
                        day_str = f"{d+1}."
                        if date(leto, mesec, d+1) in at_holidays: day_str = f"{d+1}. (FT)"
                        
                        def_b = solver.Value(deficit_vars["JED"][d]) + solver.Value(deficit_vars["TB"][d]) + solver.Value(deficit_vars["N2B"][d])
                        def_h = solver.Value(deficit_vars["TH"][d]) + solver.Value(deficit_vars["N2H"][d])
                        def_dgkp = solver.Value(deficit_vars["N1"][d]) + solver.Value(deficit_vars["X7"][d])
                        
                        fehlt_row_b[day_str] = f"-{def_b}" if def_b > 0 else "OK"
                        fehlt_row_h[day_str] = f"-{def_h}" if def_h > 0 else "OK"
                        fehlt_row_f[day_str] = f"-{def_dgkp}" if def_dgkp > 0 else "OK"

                    data.extend([fehlt_row_b, fehlt_row_h, fehlt_row_f])
                    df_rezultat = pd.DataFrame(data)

                    day_cols = [c for c in df_rezultat.columns if "." in c]
                    for d_col in day_cols:
                        dgkp_rows = df_rezultat[(df_rezultat["Rolle"].isin(["DGKP", "Leitung"])) & (df_rezultat[d_col] == "X7")]
                        if not dgkp_rows.empty:
                            df_rezultat.at[dgkp_rows.index[0], d_col] = "*X7"
                        else:
                            dgkp_rows_x6 = df_rezultat[(df_rezultat["Rolle"].isin(["DGKP", "Leitung"])) & (df_rezultat[d_col] == "X6")]
                            if not dgkp_rows_x6.empty:
                                df_rezultat.at[dgkp_rows_x6.index[0], d_col] = "*X6"

                    st.session_state.last_generated_df = df_rezultat

                    def style_cells(val):
                        if isinstance(val, (int, float)):
                            if val > 12: return "background-color: #ffcccc; color: #990000; font-weight: bold"
                            elif val < -12: return "background-color: #ccccff; color: #000099; font-weight: bold"
                        elif isinstance(val, str):
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
