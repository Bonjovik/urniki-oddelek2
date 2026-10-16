import calendar
from datetime import date
import holidays
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KI-Dienstplan PRO 11.1", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 11.1 - Ultimate)")
st.markdown(
    "Das System findet **immer** eine Lösung! Wenn Personal fehlt, wird der Tag in der "
    "untersten Zeile (**🚨 FEHLT**) rot markiert, anstatt abzubrechen."
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

    if "staff_df_v11" not in st.session_state:
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

        st.session_state.staff_df_v11 = pd.DataFrame(initial_staff)

    edited_df = st.data_editor(
        st.session_state.staff_df_v11,
        num_rows="dynamic",
        key="tabelle_mitarbeiter_v11",
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

    if "absences_v11" not in st.session_state:
        st.session_state.absences_v11 = []
    if "work_rules_v11" not in st.session_state:
        st.session_state.work_rules_v11 = []

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
                        st.session_state.absences_v11.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "reason": reason})
                st.success("Gespeichert!")
                
        if st.session_state.absences_v11:
            if st.button("🗑️ Alle löschen", key="del_abs"):
                st.session_state.absences_v11 = []
                st.rerun()
            abs_df = pd.DataFrame(st.session_state.absences_v11)
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
                        st.session_state.work_rules_v11.append({"emp_id": emp_id_w, "emp_name": emp_name_w, "day": d - 1, "rule": rule_w})
                st.success("Gespeichert!")

        if st.session_state.work_rules_v11:
            if st.button("🗑️ Alle löschen", key="del_work"):
                st.session_state.work_rules_v11 = []
                st.rerun()
            work_df = pd.DataFrame(st.session_state.work_rules_v11)
            work_df["Datum"] = work_df["day"].apply(lambda x: f"{x+1}.")
            st.dataframe(work_df[["emp_name", "Datum", "rule"]], use_container_width=True)

with tab2:
    st.header("Automatische Dienstplangenerierung (Soft-Constraints)")
    st.info("💡 Wenn Personal fehlt, bricht das System nicht ab, sondern markiert fehlende Dienste ROT in der Zeile '🚨 FEHLT'.")
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
                        hour_deviations.append(cons_we * 1500)
                        if w_idx + 2 < len(weekends):
                            model.Add(works_we[w_idx+2] == 0).OnlyEnforceIf(cons_we)

                only_work_days = {s["ID"]: set() for s in staff_list}
                must_work_days = {s["ID"]: set() for s in staff_list}
                has_only_rule = {s["ID"]: False for s in staff_list}
                
                for r in st.session_state.work_rules_v11:
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

                day_keys =
