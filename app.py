import calendar
from datetime import date
import io
import re
import os
import holidays
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KI-Dienstplan PRO 16.1", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 16.1 - Rollen-Logik & Migration)")
st.markdown(
    "Automatische Zuweisung von **X4/X6/X7/N1 für DGKP**, **F2/F7/N2 für PA** und **JED/F7 für Heimhelfer**. "
    "Neue Checkbox **'Nur Nacht'** ist nun für alte Speicherstände sichtbar!"
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
    st.info("💡 **Tipp:** Nutze das Häkchen 'Nur Nacht' für F-Station Mitarbeiter, die keine Tagdienste machen dürfen.")

    # NALAGANJE IN MIGRACIJA STARIH PODATKOV
    if "staff_df_v16_1" not in st.session_state:
        if os.path.exists("team_data.csv"):
            try:
                loaded_df = pd.read_csv("team_data.csv")
                
                # --- MIGRACIJA: Če stolpca "Nur_Nacht" še ni v stari datoteki, ga dodaj! ---
                if "Nur_Nacht" not in loaded_df.columns:
                    loaded_df["Nur_Nacht"] = False
                    # Če si imel prej ročno izbrano 'Nur Nachtdienste', ti to pretvori v kljukico
                    loaded_df.loc[loaded_df["Spezialdienst"] == "Nur Nachtdienste", "Nur_Nacht"] = True
                    loaded_df.loc[loaded_df["Spezialdienst"] == "Nur Nachtdienste", "Spezialdienst"] = "Ohne"
                
                st.session_state.staff_df_v16_1 = loaded_df
            except Exception:
                pass 

        if "staff_df_v16_1" not in st.session_state:
            initial_staff = []
            initial_staff.append({
                "ID": 0, "Name": "WBL (Uroš)", "Abteilung": "Abteilung H", "Rolle": "Leitung",
                "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False,
                "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": False, "SO": False, "FT": False,
                "Spezialdienst": "Ohne", "Geb_Monat": "März"
            })
            for i in range(1, 4):
                initial_staff.append({
                    "ID": len(initial_staff), "Name": f"DGKP F-{i} (Pool)", "Abteilung": "Abteilung F", "Rolle": "DGKP",
                    "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 7, "Nur_Nacht": True,
                    "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True,
                    "Spezialdienst": "Ohne", "Geb_Monat": "Ohne"
                })
            for i in range(1, 5):
                initial_staff.append({
                    "ID": len(initial_staff), "Name": f"DGKP B-{i}", "Abteilung": "Abteilung B", "Rolle": "DGKP",
                    "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False,
                    "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True,
                    "Spezialdienst": "Ohne", "Geb_Monat": "Ohne"
                })
            st.session_state.staff_df_v16_1 = pd.DataFrame(initial_staff)

    with st.form("team_editor_form"):
        # PRISILNI VRSTNI RED STOLPCEV, da se Nur_Nacht pokaže tam, kjer mora
        cols_order = ["Abteilung", "Rolle", "Name", "Prozent", "Saldo_Alt", "Max_Nacht", "Nur_Nacht", "MO", "DI", "MI", "DO", "FR", "SA", "SO", "FT", "Spezialdienst"]
        
        # Preveri, če so vsi stolpci prisotni, preden jih filtriraš
        display_cols = [c for c in cols_order if c in st.session_state.staff_df_v16_1.columns]
        
        edited_data = st.data_editor(
            st.session_state.staff_df_v16_1[display_cols],
            num_rows="dynamic",
            key="tabelle_mitarbeiter_v16_1",
            column_config={
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
            st.session_state.staff_df_v16_1 = edited_data
            edited_data.to_csv("team_data.csv", index=False)
            st.success("✅ Teamdaten erfolgreich gespeichert!")

    st.divider()

    if "absences_v16_1" not in st.session_state: st.session_state.absences_v16_1 = []
    if "work_rules_v16_1" not in st.session_state: st.session_state.work_rules_v16_1 = []

    st.header("3. Abwesenheiten & Wünsche")
    
    col_smart, col_manual = st.columns([1, 1])
    
    with col_smart:
        st.subheader("🤖 Smart-Wunsch KI (Freitext)")
        with st.form("smart_wunsch_form"):
            emp_smart = st.selectbox("Wer hat einen Wunsch?", options=st.session_state.staff_df_v16_1["Name"].dropna().tolist())
            smart_text = st.text_input("Beispiel: 'želi prosto 12. in 14.' oder 'arbeiten am 5.'")
            
            if st.form_submit_button("✨ KI analysieren") and smart_text:
                dates = [int(x) for x in re.findall(r'\b(?:[1-9]|[12][0-9]|3[01])\b', smart_text)]
                txt = smart_text.lower()
                
                is_free = any(w in txt for w in ["frei", "prosto", "nicht", "ne dela", "urlaub", "dopust", "ausfall"])
                is_work = any(w in txt for w in ["arbeit", "dela", "muss", "will", "želi", "dienst"])
                
                if not dates:
                    st.error("❌ Die KI konnte keine Datum-Zahlen finden.")
                else:
                    emp_id = st.session_state.staff_df_v16_1.loc[st.session_state.staff_df_v16_1["Name"] == emp_smart, "ID"].values[0]
                    valid_dates = [d for d in dates if 1 <= d <= num_days]
                    
                    if is_free:
                        for d in valid_dates:
                            st.session_state.absences_v16_1.append({"emp_id": emp_id, "emp_name": emp_smart, "day": d-1, "reason": "WUNSCH (Frei)"})
                        st.success(f"🤖 KI hat verstanden: {emp_smart} ist FREI am: {valid_dates}")
                    elif is_work:
                        for d in valid_dates:
                            st.session_state.work_rules_v16_1.append({"emp_id": emp_id, "emp_name": emp_smart, "day": d-1, "rule": "MUSS arbeiten"})
                        st.success(f"🤖 KI hat verstanden: {emp_smart} MUSS ARBEITEN am: {valid_dates}")
                    else:
                        st.warning("KI ist sich unsicher. Bitte 'frei' oder 'dela' verwenden.")

    with col_manual:
        st.subheader("Oder Manuell eintragen:")
        with st.form("absence_form"):
            emp_names = st.multiselect("Mitarbeiter:", options=st.session_state.staff_df_v16_1["Name"].dropna().tolist(), key="abs_emp")
            izbrani_datumi = st.multiselect("Tage:", options=list(range(1, num_days + 1)), key="abs_dates")
            reason = st.selectbox("Grund/Regel:", ["URL (Urlaub)", "KRA (Krankenstand)", "GEB", "ENT", "NA", "Ü", "MUSS arbeiten", "DARF NUR arbeiten"])

            if st.form_submit_button("Manuell Speichern") and izbrani_datumi and emp_names:
                for emp_name in emp_names:
                    emp_id = st.session_state.staff_df_v16_1.loc[st.session_state.staff_df_v16_1["Name"] == emp_name, "ID"].values[0]
                    for d in izbrani_datumi:
                        if reason in ["MUSS arbeiten", "DARF NUR arbeiten"]:
                            st.session_state.work_rules_v16_1.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "rule": reason})
                        else:
                            st.session_state.absences_v16_1.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "reason": reason})
                st.success("Gespeichert!")

    if st.session_state.absences_v16_1 or st.session_state.work_rules_v16_1:
        st.write("---")
        col_list1, col_list2 = st.columns(2)
        with col_list1:
            if st.session_state.absences_v16_1:
                if st.button("🗑️ Abwesenheiten/Frei löschen", key="del_abs"):
                    st.session_state.absences_v16_1 = []
                    st.rerun()
                abs_df = pd.DataFrame(st.session_state.absences_v16_1)
                abs_df["Datum"] = abs_df["day"].apply(lambda x: f"{x+1}.")
                st.dataframe(abs_df[["emp_name", "Datum", "reason"]], use_container_width=True)
        with col_list2:
            if st.session_state.work_rules_v16_1:
                if st.button("🗑️ Wunschdienste (Arbeiten) löschen", key="del_work"):
                    st.session_state.work_rules_v16_1 = []
                    st.rerun()
                work_df = pd.DataFrame(st.session_state.work_rules_v16_1)
                work_df["Datum"] = work_df["day"].apply(lambda x: f"{x+1}.")
                st.dataframe(work_df[["emp_name", "Datum", "rule"]], use_container_width=True)

with tab2:
    st.header("Automatische Dienstplangenerierung")
    if st.button("🚀 Dienstplan berechnen", type="primary", use_container_width=True):
        
        df_clean = st.session_state.staff_df_v16_1.copy()
        
        # MIGRACIJA ZA VSAK SLUČAJ TUDI TUKAJ
        if "Nur_Nacht" not in df_clean.columns: df_clean["Nur_Nacht"] = False
        df_clean["Nur_Nacht"] = df_clean["Nur_Nacht"].fillna(False).astype(bool)
        
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
            with st.spinner("KI berechnet Rollen-Beschränkungen, Blöcke und Feiertage..."):
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

                    for w_idx in range(len(weekends) - 1):
                        cons_we = model.NewBoolVar(f'cons_we_{s["ID"]}_{w_idx}')
                        model.AddMinEquality(cons_we, [works_we[w_idx], works_we[w_idx+1]])
                        hour_deviations.append(cons_we * 2500)

                only_work_days = {s["ID"]: set() for s in staff_list}
                must_work_days = {s["ID"]: set() for s in staff_list}
                has_only_rule = {s["ID"]: False for s in staff_list}
                
                for r in st.session_state.work_rules_v16_1:
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
