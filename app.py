import calendar
from datetime import date
import holidays
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KI-Dienstplan PRO 11.2", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 11.2 - Crash-Free)")
st.markdown(
    "Das System findet **immer** eine Lösung! Wenn Personal fehlt, wird der Tag in der "
    "untersten Zeile (**🚨 FEHLT**) rot markiert. Keine Abstürze mehr bei Urlauben!"
)

tab1, tab2, tab3 = st.tabs(["⚙️ 1. Einstellungen & Team", "📅 2. Dienstplan & KI", "🚑 3. SOS Ausfallmanagement"])

with tab1:
    st.header("Monat und Jahr auswählen")
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

    st.header("Team (Stundenübertrag und %-Anstellung)")
    st.info("💡 Trage bei 'Saldo Alt' die Plus/Minus-Stunden aus dem Vormonat ein.")

    if "staff_df_v11_2" not in st.session_state:
        initial_staff = []

        initial_staff.append({
            "ID": 0, "Name": "WBL (Uroš)", "Abteilung": "Abteilung H", "Rolle": "Leitung",
            "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, 
            "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": False, "SO": False, 
            "Spezialdienst": "Ohne", "Ue42_ENT": False, "Geb_Monat": "März"
        })

        for i in range(1, 4):
            initial_staff.append({
                "ID": len(initial_staff), "Name": f"DGKP F-{i} (Pool)", "Abteilung": "Abteilung F", "Rolle": "DGKP",
                "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 4, 
                "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, 
                "Spezialdienst": "Nur Nachtdienste", "Ue42_ENT": False, "Geb_Monat": "Ohne"
            })

        for i in range(1, 5):
            initial_staff.append({
                "ID": len(initial_staff), "Name": f"DGKP B-{i}", "Abteilung": "Abteilung B", "Rolle": "DGKP",
                "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, 
                "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, 
                "Spezialdienst": "Ohne", "Ue42_ENT": False, "Geb_Monat": "Ohne"
            })

        initial_staff.append({
            "ID": len(initial_staff), "Name": "DGKP H-1 (SM Dienst)", "Abteilung": "Abteilung H", "Rolle": "DGKP",
            "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, 
            "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, 
            "Spezialdienst": "SM (7:45-18:15)", "Ue42_ENT": False, "Geb_Monat": "Ohne"
        })
        
        for i in range(2, 5):
            initial_staff.append({
                "ID": len(initial_staff), "Name": f"DGKP H-{i}", "Abteilung": "Abteilung H", "Rolle": "DGKP",
                "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, 
                "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, 
                "Spezialdienst": "Ohne", "Ue42_ENT": False, "Geb_Monat": "Ohne"
            })

        for i in range(1, 4):
            initial_staff.append({
                "ID": len(initial_staff), "Name": f"Heimhelfer B-{i} (JED)", "Abteilung": "Abteilung B", "Rolle": "Heimhelfer",
                "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 0, 
                "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, 
                "Spezialdienst": "JED (Speisesaal 6:30-18:00)", "Ue42_ENT": True, "Geb_Monat": "Januar"
            })

        for i in range(1, 10):
            initial_staff.append({
                "ID": len(initial_staff), "Name": f"PA B-{i}", "Abteilung": "Abteilung B", "Rolle": "Pflegeassistenz",
                "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 5, 
                "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, 
                "Spezialdienst": "Ohne", "Ue42_ENT": False, "Geb_Monat": "Ohne"
            })
            
        for i in range(1, 10):
            initial_staff.append({
                "ID": len(initial_staff), "Name": f"PA H-{i}", "Abteilung": "Abteilung H", "Rolle": "Pflegeassistenz",
                "Prozent": 100, "Saldo_Alt": 0.0, "Max_Nacht": 5, 
                "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, 
                "Spezialdienst": "Ohne", "Ue42_ENT": False, "Geb_Monat": "Ohne"
            })

        st.session_state.staff_df_v11_2 = pd.DataFrame(initial_staff)

    edited_df = st.data_editor(
        st.session_state.staff_df_v11_2,
        num_rows="dynamic",
        key="tabelle_mitarbeiter_v11_2",
        column_config={
            "Abteilung": st.column_config.SelectboxColumn("Abteilung", options=["Abteilung B", "Abteilung H", "Abteilung F"]),
            "Rolle": st.column_config.SelectboxColumn("Rolle", options=["Leitung", "DGKP", "Pflegeassistenz", "Heimhelfer"]),
            "Prozent": st.column_config.NumberColumn("Anst. (%)", min_value=10, max_value=120, default=100),
            "Saldo_Alt": st.column_config.NumberColumn("Saldo Alt (+/- Std)", default=0.0),
            "Max_Nacht": st.column_config.NumberColumn("Max. Nacht", min_value=0, max_value=15, default=0),
            "MO": st.column_config.CheckboxColumn("Mo", default=True),
            "DI": st.column_config.CheckboxColumn("Di", default=True),
            "MI": st.column_config.CheckboxColumn("Mi", default=True),
            "DO": st.column_config.CheckboxColumn("Do", default=True),
            "FR": st.column_config.CheckboxColumn("Fr", default=True),
            "SA": st.column_config.CheckboxColumn("Sa", default=True),
            "SO": st.column_config.CheckboxColumn("So", default=True),
            "Spezialdienst": st.column_config.SelectboxColumn(
                "Spezialdienst",
                options=["Ohne", "F1 (PA 6:45-19:15)", "F2 (PA 6:45-18:15)", "X7 (DGKP 6:45-19:15)", 
                         "X6 (DGKP 6:45-18:15)", "X4 (6:45-15:30)", "JED (Speisesaal 6:30-18:00)", 
                         "Mutterschutz (7:30-15:00)", "SM (7:45-18:15)", "Nur Nachtdienste"]
            ),
            "Ue42_ENT": st.column_config.CheckboxColumn("Ü42 (ENT)", default=False),
            "Geb_Monat": st.column_config.SelectboxColumn("Geburtsmonat", options=["Ohne", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"])
        },
        use_container_width=True,
    )

    if "absences_v11_2" not in st.session_state:
        st.session_state.absences_v11_2 = []
    if "work_rules_v11_2" not in st.session_state:
        st.session_state.work_rules_v11_2 = []

    col_abs, col_work = st.columns(2)
    with col_abs:
        st.subheader("Abwesenheiten")
        with st.form("absence_form"):
            emp_names = st.multiselect("Mitarbeiter:", options=edited_df["Name"].tolist(), key="abs_emp")
            izbrani_datumi = st.multiselect("Tage:", options=list(range(1, num_days + 1)), key="abs_dates")
            reason = st.selectbox("Grund:", ["URL (Urlaub)", "KRA (Krankenstand)", "GEB (Geburtstagsurlaub)", "ENT (Entlastungstag)", "NA (Nachtausgleich)", "Ü (Überstundenabbau)"], key="abs_reason")

            if st.form_submit_button("Speichern") and izbrani_datumi and emp_names:
                for emp_name in emp_names:
                    emp_id = edited_df.loc[edited_df["Name"] == emp_name, "ID"].values[0]
                    for d in izbrani_datumi:
                        st.session_state.absences_v11_2.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "reason": reason})
                st.success("Gespeichert!")
                
        if st.session_state.absences_v11_2:
            if st.button("🗑️ Alle löschen", key="del_abs"):
                st.session_state.absences_v11_2 = []
                st.rerun()
            abs_df = pd.DataFrame(st.session_state.absences_v11_2)
            abs_df["Datum"] = abs_df["day"].apply(lambda x: f"{x+1}.")
            st.dataframe(abs_df[["emp_name", "Datum", "reason"]], use_container_width=True)

    with col_work:
        st.subheader("Wunschdienstplan")
        with st.form("work_form"):
            emp_names_w = st.multiselect("Mitarbeiter:", options=edited_df["Name"].tolist(), key="work_emp")
            izbrani_datumi_w = st.multiselect("Tage:", options=list(range(1, num_days + 1)), key="work_dates")
            rule_w = st.selectbox("Regel:", ["MUSS arbeiten", "DARF NUR arbeiten"], key="work_rule")

            if st.form_submit_button("Speichern") and izbrani_datumi_w and emp_names_w:
                for emp_name_w in emp_names_w:
                    emp_id_w = edited_df.loc[edited_df["Name"] == emp_name_w, "ID"].values[0]
                    for d in izbrani_datumi_w:
                        st.session_state.work_rules_v11_2.append({"emp_id": emp_id_w, "emp_name": emp_name_w, "day": d - 1, "rule": rule_w})
                st.success("Gespeichert!")

        if st.session_state.work_rules_v11_2:
            if st.button("🗑️ Alle löschen", key="del_work"):
                st.session_state.work_rules_v11_2 = []
                st.rerun()
            work_df = pd.DataFrame(st.session_state.work_rules_v11_2)
            work_df["Datum"] = work_df["day"].apply(lambda x: f"{x+1}.")
            st.dataframe(work_df[["emp_name", "Datum", "rule"]], use_container_width=True)

with tab2:
    st.header("Automatische Dienstplangenerierung (Soft-Constraints)")
    st.info("💡 Wenn Personal fehlt, bricht das System nicht ab, sondern markiert fehlende Dienste ROT.")
    if st.button("🚀 Dienstplan berechnen", type="primary", use_container_width=True):
        staff_list = edited_df.to_dict("records")

        try:
            with st.spinner("KI berechnet besten Plan und deckt Fehlzeiten auf (Max 20 Sekunden)..."):
                model = cp_model.CpModel()
                hour_deviations = []

                shifts = {
                    "X4": 825, "X6": 1100, "X7": 1200, "F1": 1200, "F2": 1100,
                    "N1": 1350, "N2": 1350, "JED": 1050, "MS": 700, "SM": 1000, "OFF": 0,
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
                    for d in range(num_days - 6):
                        model.Add(sum(work[(s["ID"], d + i, "OFF")] for i in range(7)) >= 1)

                for s in staff_list:
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
                        hour_deviations.append(cons_we * 2500) # Kazen za zaporedne vikende

                only_work_days = {s["ID"]: set() for s in staff_list}
                must_work_days = {s["ID"]: set() for s in staff_list}
                has_only_rule = {s["ID"]: False for s in staff_list}
                
                for r in st.session_state.work_rules_v11_2:
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
                    if "F1" in s["Spezialdienst"]: allowed_shifts.append("F1")
                    elif "F2" in s["Spezialdienst"]: allowed_shifts.append("F2")
                    elif "X7" in s["Spezialdienst"]: allowed_shifts.append("X7")
                    elif "X6" in s["Spezialdienst"]: allowed_shifts.append("X6")
                    elif "X4" in s["Spezialdienst"]: allowed_shifts.append("X4")
                    elif "JED" in s["Spezialdienst"]: allowed_shifts.append("JED")
                    elif "Mutterschutz" in s["Spezialdienst"]: allowed_shifts.append("MS")
                    elif "SM" in s["Spezialdienst"]: allowed_shifts.append("SM")
                    elif "Nur Nachtdienste" in s["Spezialdienst"]:
                        if s["Rolle"] == "DGKP": allowed_shifts.append("N1")
                        else: allowed_shifts.append("N2")
                    elif s["Rolle"] == "Leitung": allowed_shifts.append("X4")
                    elif s["Rolle"] == "DGKP":
                        allowed_shifts.extend(["X4", "X6", "X7"])
                        if s["Max_Nacht"] > 0: allowed_shifts.append("N1")
                    elif s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]:
                        allowed_shifts.extend(["F1", "F2", "X4"])
                        if s["Max_Nacht"] > 0: allowed_shifts.append("N2")

                    unallowed = [sh for sh in shifts.keys() if sh not in allowed_shifts]
                    for d in range(num_days):
                        for sh in unallowed:
                            model.Add(work[(s["ID"], d, sh)] == 0)

                    if s["Max_Nacht"] >= 0:
                        nocna_koda = "N1" if s["Rolle"] == "DGKP" else "N2"
                        model.Add(sum(work[(s["ID"], d, nocna_koda)] for d in range(num_days)) <= int(s["Max_Nacht"]))

                    for d in range(num_days):
                        day_of_week = (d + first_day_of_month_weekday) % 7
                        day_name = day_keys[day_of_week]
                        if not s[day_name]:
                            model.Add(work[(s["ID"], d, "OFF")] == 1)

                for a in st.session_state.absences_v11_2:
                    if a["day"] < num_days:
                        model.Add(work[(a["emp_id"], a["day"], "OFF")] == 1)

                oB_tehniki = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]]
                oH_tehniki = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]]
                all_dgkp = [s["ID"] for s in staff_list if s["Rolle"] in ["DGKP", "Leitung"]]
                jedilnica_kadri = [s["ID"] for s in staff_list if "JED" in s["Spezialdienst"]]
                
                dgkp_nocni = [s["ID"] for s in staff_list if s["Rolle"] == "DGKP" and (s["Max_Nacht"] > 0 or "Nur Nachtdienste" in s["Spezialdienst"])]
                tech_nocni_B = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and s["Max_Nacht"] > 0]
                tech_nocni_H = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and s["Max_Nacht"] > 0]
                
                day_shifts_tech = ["F1", "F2", "X4", "MS", "JED"]
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

                # ODSTRANJENA STROGA PRAVILA ZA URE - Sistem več ne pade!
                for s in staff_list:
                    if "Nur Nachtdienste" in s["Spezialdienst"]: continue
                    
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
                    hour_deviations.append(dev) # AI se bo samo trudila biti blizu fonda, a ne bo crashala

                model.Minimize(sum(hour_deviations))
                solver = cp_model.CpSolver()
                solver.parameters.max_time_in_seconds = 20.0
                status = solver.Solve(model)

                if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                    st.success("🎉 Dienstplan generiert! Prüfe die roten Felder ('🚨 FEHLT') am Ende jeder Tabelle.")

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
                                    for a in st.session_state.absences_v11_2:
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
                        
                        row["SOLL (FT abg.)"] = round(soll_neu, 1)
                        row["IST"] = total_hours / 100
                        row["SALDO NEU"] = round((total_hours / 100) - soll_neu + saldo_alt, 1)
                        data.append(row)

                    fehlt_row_b = {"Abteilung": "Abteilung B", "Rolle": "", "Anst.%": "", "Mitarbeiter": "🚨 FEHLT (Pflege/JED)", "SOLL (FT abg.)": "", "IST": "", "SALDO NEU": ""}
                    fehlt_row_h = {"Abteilung": "Abteilung H", "Rolle": "", "Anst.%": "", "Mitarbeiter": "🚨 FEHLT (Pflege)", "SOLL (FT abg.)": "", "IST": "", "SALDO NEU": ""}
                    fehlt_row_f = {"Abteilung": "Abteilung F", "Rolle": "", "Anst.%": "", "Mitarbeiter": "🚨 FEHLT (DGKP N1/X7)", "SOLL (FT abg.)": "", "IST": "", "SALDO NEU": ""}

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

                else:
                    st.error("🚨 Kritischer Fehler! Die Mathematik konnte nicht aufgelöst werden. Überprüfe die Feiertage.")
        except Exception as e:
            st.error(f"⚠️ Systemfehler: {e}")

with tab3:
    st.header("🚑 SOS Ausfallmanagement")
    st.markdown("Fällt jemand kurzfristig aus? Finde sofort den perfekten Ersatz!")
    
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
            ].sort_values(by="SALDO NEU")
            
            if not candidates.empty:
                st.success(f"✅ {len(candidates)} mögliche Ersatzpersonen gefunden (Sortiert nach Minus-Stunden):")
                st.dataframe(candidates[["Mitarbeiter", "Abteilung", "SALDO NEU"]], use_container_width=True)
            else:
                st.error("❌ Niemand mit dieser Rolle hat an diesem Tag frei.")
    else:
        st.info("⚠️ Bitte generiere zuerst den Dienstplan im Tab 2.")
