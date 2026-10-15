import calendar
from datetime import date
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KI-Dienstplan PRO 7.0", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 7.0)")
st.markdown(
    "Vollständig auf Deutsch. Inklusive Verwaltung von Entlastungstagen (ENT) "
    "ab 42 Jahren und Geburtstagsurlaub (GEB) im Quartal."
)

# --- 1. KOLEDAR IN NASTAVITVE MESECA (Monat & Jahr) ---
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

# --- 2. UPRAVLJANJE ZAPOSLENIH IN ODDELKOV (Team-Einstellungen) ---
st.header("2. Team (Dienste, Tage & Urlaubsanspruch)")
st.info(
    "💡 Setze das Häkchen bei 'Ü42', wenn der Mitarbeiter Anspruch auf 5 Entlastungstage hat. "
    "Wähle den Geburtsmonat, um den 3-monatigen GEB-Zeitraum zu planen."
)

if "staff_df_v7" not in st.session_state:
  initial_staff = []

  # Leitung
  initial_staff.append({
      "ID": 0, "Name": "WBL (Uroš)", "Abteilung": "Abteilung H", "Rolle": "Leitung",
      "Stunden": 40.0, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
      "FR": True, "SA": False, "SO": False, "Spezialdienst": "Ohne",
      "Ue42_ENT": False, "Geb_Monat": "März"
  })

  # Abteilung F (Nacht-Pool)
  for i in range(1, 4):
    initial_staff.append({
        "ID": len(initial_staff), "Name": f"DGKP F-{i} (Pool)", "Abteilung": "Abteilung F", "Rolle": "DGKP",
        "Stunden": 37.0, "Max_Nacht": 4, "MO": True, "DI": True, "MI": True, "DO": True, 
        "FR": True, "SA": True, "SO": True, "Spezialdienst": "Nur Nachtdienste",
        "Ue42_ENT": False, "Geb_Monat": "Ohne"
    })

  # Abteilung B (DGKP)
  for i in range(1, 5):
    initial_staff.append({
        "ID": len(initial_staff), "Name": f"DGKP B-{i}", "Abteilung": "Abteilung B", "Rolle": "DGKP",
        "Stunden": 37.0, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
        "FR": True, "SA": True, "SO": True, "Spezialdienst": "Ohne",
        "Ue42_ENT": False, "Geb_Monat": "Ohne"
    })

  # Abteilung H (DGKP)
  initial_staff.append({
      "ID": len(initial_staff), "Name": "DGKP H-1 (SM Dienst)", "Abteilung": "Abteilung H", "Rolle": "DGKP",
      "Stunden": 37.0, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
      "FR": True, "SA": True, "SO": True, "Spezialdienst": "SM (7:45-18:15)",
      "Ue42_ENT": False, "Geb_Monat": "Ohne"
  })
  for i in range(2, 5):
    initial_staff.append({
        "ID": len(initial_staff), "Name": f"DGKP H-{i}", "Abteilung": "Abteilung H", "Rolle": "DGKP",
        "Stunden": 37.0, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
        "FR": True, "SA": True, "SO": True, "Spezialdienst": "Ohne",
        "Ue42_ENT": False, "Geb_Monat": "Ohne"
    })

  # Abteilung B (Heimhelfer - Speisesaal)
  for i in range(1, 4):
    initial_staff.append({
        "ID": len(initial_staff), "Name": f"Heimhelfer B-{i} (JED)", "Abteilung": "Abteilung B", "Rolle": "Heimhelfer",
        "Stunden": 37.0, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
        "FR": True, "SA": True, "SO": True, "Spezialdienst": "JED (Speisesaal 6:30-18:00)",
        "Ue42_ENT": True, "Geb_Monat": "Januar" # Пример
    })

  # Abteilung B (Pflegeassistenz)
  initial_staff.append({
      "ID": len(initial_staff), "Name": "PA B-1 (Schwanger)", "Abteilung": "Abteilung B", "Rolle": "Pflegeassistenz",
      "Stunden": 37.0, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
      "FR": True, "SA": False, "SO": False, "Spezialdienst": "Mutterschutz (7:30-15:00)",
      "Ue42_ENT": False, "Geb_Monat": "Ohne"
  })
  for i in range(2, 12):
    initial_staff.append({
        "ID": len(initial_staff), "Name": f"PA B-{i}", "Abteilung": "Abteilung B", "Rolle": "Pflegeassistenz",
        "Stunden": 37.0, "Max_Nacht": 5, "MO": True, "DI": True, "MI": True, "DO": True, 
        "FR": True, "SA": True, "SO": True, "Spezialdienst": "Ohne",
        "Ue42_ENT": False, "Geb_Monat": "Ohne"
    })

  # Abteilung H (Pflegeassistenz)
  for i in range(1, 15):
    initial_staff.append({
        "ID": len(initial_staff), "Name": f"PA H-{i}", "Abteilung": "Abteilung H", "Rolle": "Pflegeassistenz",
        "Stunden": 37.0, "Max_Nacht": 5, "MO": True, "DI": True, "MI": True, "DO": True, 
        "FR": True, "SA": True, "SO": True, "Spezialdienst": "Ohne",
        "Ue42_ENT": False, "Geb_Monat": "Ohne"
    })

  st.session_state.staff_df_v7 = pd.DataFrame(initial_staff)

edited_df = st.data_editor(
    st.session_state.staff_df_v7,
    num_rows="dynamic",
    key="tabelle_mitarbeiter_v7",
    column_config={
        "Abteilung": st.column_config.SelectboxColumn("Abteilung", options=["Abteilung B", "Abteilung H", "Abteilung F"], required=True),
        "Rolle": st.column_config.SelectboxColumn("Rolle", options=["Leitung", "DGKP", "Pflegeassistenz", "Heimhelfer"], required=True),
        "Stunden": st.column_config.NumberColumn("Wo. Std.", min_value=10.0, max_value=40.0, required=True),
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
            options=[
                "Ohne", "F1 (PA 6:45-19:15)", "F2 (PA 6:45-18:15)", "X7 (DGKP 6:45-19:15)", 
                "X6 (DGKP 6:45-18:15)", "X4 (6:45-15:30)", "JED (Speisesaal 6:30-18:00)", 
                "Mutterschutz (7:30-15:00)", "SM (7:45-18:15)", "Nur Nachtdienste"
            ], required=True,
        ),
        "Ue42_ENT": st.column_config.CheckboxColumn("Ü42 (5 ENT-Tage)", default=False),
        "Geb_Monat": st.column_config.SelectboxColumn(
            "Geburtsmonat", options=["Ohne", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]
        )
    },
    use_container_width=True,
)

if "absences_v7" not in st.session_state:
  st.session_state.absences_v7 = []
if "work_rules_v7" not in st.session_state:
  st.session_state.work_rules_v7 = []

st.divider()

# --- 3. TOČEN VNOS ODSOTNOSTI IN ŽELJA (Abwesenheiten & Wunschdienst) ---
col_abs, col_work = st.columns(2)

with col_abs:
  st.header("3. Abwesenheiten (Urlaub, Krankenstand, GEB, ENT)")
  with st.form("absence_form"):
    emp_names = st.multiselect("Mitarbeiter auswählen (Mehrfachauswahl möglich):", options=edited_df["Name"].tolist(), key="abs_emp")
    izbrani_datumi = st.multiselect("Tage auswählen:", options=list(range(1, num_days + 1)), key="abs_dates")
    
    # NOV ŠIFRANT ODSOTNOSTI V NEMŠČINI
    reason = st.selectbox(
        "Grund:", ["URL (Urlaub)", "KRA (Krankenstand)", "GEB (Geburtstagsurlaub)", "ENT (Entlastungstag)"], key="abs_reason"
    )

    if st.form_submit_button("Abwesenheiten für Ausgewählte speichern") and izbrani_datumi and emp_names:
      for emp_name in emp_names:
          emp_id = edited_df.loc[edited_df["Name"] == emp_name, "ID"].values[0]
          for d in izbrani_datumi:
            st.session_state.absences_v7.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "reason": reason})
      st.success("Abwesenheiten erfolgreich gespeichert!")

  if st.session_state.absences_v7:
    if st.button("🗑️ Alle Abwesenheiten löschen"):
      st.session_state.absences_v7 = []
      st.rerun()
    abs_df = pd.DataFrame(st.session_state.absences_v7)
    abs_df["Datum"] = abs_df["day"].apply(lambda x: f"{x+1}.")
    st.dataframe(abs_df[["emp_name", "Datum", "reason"]].rename(columns={"emp_name": "Mitarbeiter", "reason": "Grund"}), use_container_width=True)

with col_work:
  st.header("4. Wunschdienstplan (Spezifische Tage)")
  with st.form("work_form"):
    emp_names_w = st.multiselect("Mitarbeiter auswählen:", options=edited_df["Name"].tolist(), key="work_emp")
    izbrani_datumi_w = st.multiselect("Tage auswählen:", options=list(range(1, num_days + 1)), key="work_dates")
    rule_w = st.selectbox(
        "Regel:", ["MUSS an diesen Tagen arbeiten", "DARF NUR an diesen Tagen arbeiten"], key="work_rule"
    )

    if st.form_submit_button("Arbeitsregeln speichern") and izbrani_datumi_w and emp_names_w:
      for emp_name_w in emp_names_w:
          emp_id_w = edited_df.loc[edited_df["Name"] == emp_name_w, "ID"].values[0]
          for d in izbrani_datumi_w:
            st.session_state.work_rules_v7.append({"emp_id": emp_id_w, "emp_name": emp_name_w, "day": d - 1, "rule": rule_w})
      st.success("Arbeitsregeln gespeichert!")

  if st.session_state.work_rules_v7:
    if st.button("🗑️ Alle Wunschdienste löschen"):
      st.session_state.work_rules_v7 = []
      st.rerun()
    work_df = pd.DataFrame(st.session_state.work_rules_v7)
    work_df["Datum"] = work_df["day"].apply(lambda x: f"{x+1}.")
    st.dataframe(work_df[["emp_name", "Datum", "rule"]].rename(columns={"emp_name": "Mitarbeiter", "rule": "Regel"}), use_container_width=True)

st.divider()

# --- 5. GENERIRANJE URNIKA (Dienstplan Erstellung) ---
st.header("5. Automatische Dienstplangenerierung")
if st.button("🚀 Dienstplan berechnen", type="primary", use_container_width=True):
  staff_list = edited_df.to_dict("records")

  try:
    with st.spinner("Berechne optimalen Dienstplan (Dauer ca. 10-15 Sekunden)..."):
      model = cp_model.CpModel()

      # ŠIFRE IN URE (ure * 100)
      shifts = {
          "X4": 825, "X6": 1100, "X7": 1200, "F1": 1200, "F2": 1100,
          "N1": 1350, "N2": 1350, "JED": 1050, "MS": 700, "SM": 1000, "OFF": 0,
      }

      work = {}
      for s in staff_list:
        for d in range(num_days):
          for sh in shifts.keys():
            work[(s["ID"], d, sh)] = model.NewBoolVar(f'work_{s["ID"]}_{d}_{sh}')

      for s in staff_list:
        for d in range(num_days):
          model.Add(sum(work[(s["ID"], d, sh)] for sh in shifts.keys()) == 1)

      # --- SPECIFIČNI DATUMI ---
      only_work_days = {s["ID"]: set() for s in staff_list}
      must_work_days = {s["ID"]: set() for s in staff_list}
      has_only_rule = {s["ID"]: False for s in staff_list}

      for r in st.session_state.work_rules_v7:
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

      # DOVOLJENE IZMENE GLEDE NA VLOGO IN POSEBNOST
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
        elif s["Rolle"] == "Leitung":
          allowed_shifts.append("X4")
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

        # MAX NOČNIH
        if s["Max_Nacht"] >= 0:
          nocna_koda = "N1" if s["Rolle"] == "DGKP" else "N2"
          model.Add(
              sum(work[(s["ID"], d, nocna_koda)] for d in range(num_days))
              <= int(s["Max_Nacht"])
          )

        # KLJUKICE MO-SO
        for d in range(num_days):
          day_of_week = (d + first_day_of_month_weekday) % 7
          day_name = day_keys[day_of_week]
          if not s[day_name]:
            model.Add(work[(s["ID"], d, "OFF")] == 1)

      # Dopusti (Urlaub, Krank, GEB, ENT)
      for a in st.session_state.absences_v7:
        if a["day"] < num_days:
          model.Add(work[(a["emp_id"], a["day"], "OFF")] == 1)

      # POKRITOST ODDELKOV
      oB_tehniki = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]]
      oH_tehniki = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]]
      all_dgkp = [s["ID"] for s in staff_list if s["Rolle"] in ["DGKP", "Leitung"]]
      jedilnica_kadri = [s["ID"] for s in staff_list if "JED" in s["Spezialdienst"]]

      day_shifts_tech = ["F1", "F2", "X4", "MS", "JED"]

      for d in range(num_days):
        if len(jedilnica_kadri) > 0:
          model.Add(sum(work[(e, d, "JED")] for e in jedilnica_kadri) == 1)

        if len(oB_tehniki) >= 3:
          model.Add(sum(work[(e, d, sh)] for e in oB_tehniki for sh in day_shifts_tech) >= 4)
        if len(oH_tehniki) >= 3:
          model.Add(sum(work[(e, d, sh)] for e in oH_tehniki for sh in day_shifts_tech) >= 4)

        dgkp_nocni = [s["ID"] for s in staff_list if s["Rolle"] == "DGKP" and (s["Max_Nacht"] > 0 or "Nur Nachtdienste" in s["Spezialdienst"])]
        if len(dgkp_nocni) > 0:
          model.Add(sum(work[(e, d, "N1")] for e in dgkp_nocni) == 1)

        tech_nocni_B = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and s["Max_Nacht"] > 0]
        if len(tech_nocni_B) > 0:
          model.Add(sum(work[(e, d, "N2")] for e in tech_nocni_B) == 1)

        tech_nocni_H = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and s["Max_Nacht"] > 0]
        if len(tech_nocni_H) > 0:
          model.Add(sum(work[(e, d, "N2")] for e in tech_nocni_H) == 1)

        if len(all_dgkp) > 0:
          model.Add(sum(work[(e, d, "X7")] for e in all_dgkp) >= 1)

      # POČITEK PO NOČNI
      for s in staff_list:
        for d in range(num_days - 1):
          model.AddImplication(work[(s["ID"], d, "N1")], work[(s["ID"], d + 1, "OFF")])
          model.AddImplication(work[(s["ID"], d, "N2")], work[(s["ID"], d + 1, "OFF")])

      # IZRAČUN UR
      for s in staff_list:
        if "Nur Nachtdienste" in s["Spezialdienst"]: continue
        target = int((s["Stunden"] / 7.0) * num_days * 100)
        total_hours = model.NewIntVar(0, 35000, f'tot_{s["ID"]}')
        model.Add(
            total_hours == sum(work[(s["ID"], d, sh)] * shifts[sh] for d in range(num_days) for sh in shifts.keys())
        )

        min_h = max(0, target - 3500)
        model.Add(total_hours >= min_h)
        model.Add(total_hours <= target + 3500)

      solver = cp_model.CpSolver()
      solver.parameters.max_time_in_seconds = 15.0
      status = solver.Solve(model)

      if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        st.success("🎉 Dienstplan erfolgreich generiert!")

        data = []
        for s in staff_list:
          row = {"Abteilung": s["Abteilung"], "Rolle": s["Rolle"], "Mitarbeiter": s["Name"]}
          total_hours = 0
          for d in range(num_days):
            for sh in shifts.keys():
              if solver.Value(work[(s["ID"], d, sh)]) == 1:
                val = sh if sh != "OFF" else "..."
                # Vstavljanje kode odsotnosti (URL, KRA, GEB, ENT)
                for a in st.session_state.absences_v7:
                  if a["emp_id"] == s["ID"] and a["day"] == d:
                    val = a["reason"].split(" ")[0] 
                row[f"{d+1}."] = val
                total_hours += shifts[sh]

          target_hrs = (s["Stunden"] / 7.0) * num_days
          row["SOLL"] = round(target_hrs, 1)
          row["IST"] = total_hours / 100
          row["SALDO"] = round((total_hours / 100) - target_hrs, 1)
          data.append(row)

        df_rezultat = pd.DataFrame(data)

        def highlight_hours(val):
          if isinstance(val, (int, float)):
            if val > 12:
              return "background-color: #ffcccc; color: #990000; font-weight: bold"
            elif val < -12:
              return "background-color: #ccccff; color: #000099; font-weight: bold"
          return ""

        st.subheader("🔵 Abteilung B")
        df_b = df_rezultat[df_rezultat["Abteilung"] == "Abteilung B"].drop(columns=["Abteilung"])
        st.dataframe(df_b.style.map(highlight_hours, subset=["SALDO"]), use_container_width=True)

        st.subheader("🟢 Abteilung H")
        df_h = df_rezultat[df_rezultat["Abteilung"] == "Abteilung H"].drop(columns=["Abteilung"])
        st.dataframe(df_h.style.map(highlight_hours, subset=["SALDO"]), use_container_width=True)

        st.subheader("🟣 Abteilung F (Nacht-Pool)")
        df_f = df_rezultat[df_rezultat["Abteilung"] == "Abteilung F"].drop(columns=["Abteilung"])
        st.dataframe(df_f.style.map(highlight_hours, subset=["SALDO"]), use_container_width=True)

      else:
        st.error("🚨 Keine Lösung gefunden. Überprüfe die Einstellungen!")

  except Exception as e:
    st.error(f"⚠️ Systemfehler: {e}")
