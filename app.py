import calendar
from datetime import date
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KI-Dienstplan PRO 9.0", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 9.0 - Sanocon Level)")
st.markdown(
    "Inklusive **50h-Wochenlimit**, **Wochenend-Rhythmus (max 2, dann 2 frei)**, "
    "**Blockfreizeit (2 Tage frei)** sowie Codes **NA** und **Ü**."
)

# --- 1. KOLEDAR IN NASTAVITVE MESECA ---
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

# --- 2. UPRAVLJANJE ZAPOSLENIH IN ODDELKOV ---
st.header("2. Team (Anstellung in % und Dienste)")

if "staff_df_v9" not in st.session_state:
  initial_staff = []

  # Leitung
  initial_staff.append({
      "ID": 0, "Name": "WBL (Uroš)", "Abteilung": "Abteilung H", "Rolle": "Leitung",
      "Prozent": 100, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
      "FR": True, "SA": False, "SO": False, "Spezialdienst": "Ohne",
      "Ue42_ENT": False, "Geb_Monat": "März"
  })

  for i in range(1, 4):
    initial_staff.append({
        "ID": len(initial_staff), "Name": f"DGKP F-{i} (Pool)", "Abteilung": "Abteilung F", "Rolle": "DGKP",
        "Prozent": 100, "Max_Nacht": 4, "MO": True, "DI": True, "MI": True, "DO": True, 
        "FR": True, "SA": True, "SO": True, "Spezialdienst": "Nur Nachtdienste",
        "Ue42_ENT": False, "Geb_Monat": "Ohne"
    })

  initial_staff.append({
        "ID": len(initial_staff), "Name": "DGKP B-1 (Teilzeit 50%)", "Abteilung": "Abteilung B", "Rolle": "DGKP",
        "Prozent": 50, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
        "FR": True, "SA": True, "SO": True, "Spezialdienst": "Ohne",
        "Ue42_ENT": False, "Geb_Monat": "Ohne"
  })
  for i in range(2, 5):
    initial_staff.append({
        "ID": len(initial_staff), "Name": f"DGKP B-{i}", "Abteilung": "Abteilung B", "Rolle": "DGKP",
        "Prozent": 100, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
        "FR": True, "SA": True, "SO": True, "Spezialdienst": "Ohne",
        "Ue42_ENT": False, "Geb_Monat": "Ohne"
    })

  for i in range(1, 5):
    initial_staff.append({
        "ID": len(initial_staff), "Name": f"DGKP H-{i}", "Abteilung": "Abteilung H", "Rolle": "DGKP",
        "Prozent": 100, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
        "FR": True, "SA": True, "SO": True, "Spezialdienst": "Ohne",
        "Ue42_ENT": False, "Geb_Monat": "Ohne"
    })

  for i in range(1, 4):
    initial_staff.append({
        "ID": len(initial_staff), "Name": f"Heimhelfer B-{i} (JED)", "Abteilung": "Abteilung B", "Rolle": "Heimhelfer",
        "Prozent": 75 if i==3 else 100, "Max_Nacht": 0, "MO": True, "DI": True, "MI": True, "DO": True, 
        "FR": True, "SA": True, "SO": True, "Spezialdienst": "JED (Speisesaal 6:30-18:00)",
        "Ue42_ENT": True, "Geb_Monat": "Januar"
    })

  for i in range(1, 10):
    initial_staff.append({
        "ID": len(initial_staff), "Name": f"PA B-{i}", "Abteilung": "Abteilung B", "Rolle": "Pflegeassistenz",
        "Prozent": 100, "Max_Nacht": 5, "MO": True, "DI": True, "MI": True, "DO": True, 
        "FR": True, "SA": True, "SO": True, "Spezialdienst": "Ohne",
        "Ue42_ENT": False, "Geb_Monat": "Ohne"
    })
  for i in range(1, 10):
    initial_staff.append({
        "ID": len(initial_staff), "Name": f"PA H-{i}", "Abteilung": "Abteilung H", "Rolle": "Pflegeassistenz",
        "Prozent": 100, "Max_Nacht": 5, "MO": True, "DI": True, "MI": True, "DO": True, 
        "FR": True, "SA": True, "SO": True, "Spezialdienst": "Ohne",
        "Ue42_ENT": False, "Geb_Monat": "Ohne"
    })

  st.session_state.staff_df_v9 = pd.DataFrame(initial_staff)

edited_df = st.data_editor(
    st.session_state.staff_df_v9,
    num_rows="dynamic",
    key="tabelle_mitarbeiter_v9",
    column_config={
        "Abteilung": st.column_config.SelectboxColumn("Abteilung", options=["Abteilung B", "Abteilung H", "Abteilung F"], required=True),
        "Rolle": st.column_config.SelectboxColumn("Rolle", options=["Leitung", "DGKP", "Pflegeassistenz", "Heimhelfer"], required=True),
        "Prozent": st.column_config.NumberColumn("Anstellung (%)", min_value=10, max_value=120, default=100, required=True),
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
                     "Mutterschutz (7:30-15:00)", "SM (7:45-18:15)", "Nur Nachtdienste"], required=True,
        ),
        "Ue42_ENT": st.column_config.CheckboxColumn("Ü42 (ENT)", default=False),
        "Geb_Monat": st.column_config.SelectboxColumn("Geburtsmonat", options=["Ohne", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"])
    },
    use_container_width=True,
)

if "absences_v9" not in st.session_state:
  st.session_state.absences_v9 = []
if "work_rules_v9" not in st.session_state:
  st.session_state.work_rules_v9 = []

st.divider()

# --- 3. TOČEN VNOS ODSOTNOSTI IN ŽELJA ---
col_abs, col_work = st.columns(2)

with col_abs:
  st.header("3. Abwesenheiten (Inkl. NA & Ü)")
  with st.form("absence_form"):
    emp_names = st.multiselect("Mitarbeiter auswählen:", options=edited_df["Name"].tolist(), key="abs_emp")
    izbrani_datumi = st.multiselect("Tage auswählen:", options=list(range(1, num_days + 1)), key="abs_dates")
    
    # NOVE KODE DODANE TUKAJ (NA in Ü)
    reason = st.selectbox(
        "Grund:", 
        ["URL (Urlaub)", "KRA (Krankenstand)", "GEB (Geburtstagsurlaub)", "ENT (Entlastungstag)", "NA (Nachtausgleich)", "Ü (Überstundenabbau)"], 
        key="abs_reason"
    )

    if st.form_submit_button("Abwesenheiten speichern") and izbrani_datumi and emp_names:
      for emp_name in emp_names:
          emp_id = edited_df.loc[edited_df["Name"] == emp_name, "ID"].values[0]
          for d in izbrani_datumi:
            st.session_state.absences_v9.append({"emp_id": emp_id, "emp_name": emp_name, "day": d - 1, "reason": reason})
      st.success("Erfolgreich gespeichert!")

  if st.session_state.absences_v9:
    if st.button("🗑️ Alle Abwesenheiten löschen"):
      st.session_state.absences_v9 = []
      st.rerun()
    abs_df = pd.DataFrame(st.session_state.absences_v9)
    abs_df["Datum"] = abs_df["day"].apply(lambda x: f"{x+1}.")
    st.dataframe(abs_df[["emp_name", "Datum", "reason"]].rename(columns={"emp_name": "Mitarbeiter", "reason": "Grund"}), use_container_width=True)

with col_work:
  st.header("4. Wunschdienstplan")
  with st.form("work_form"):
    emp_names_w = st.multiselect("Mitarbeiter auswählen:", options=edited_df["Name"].tolist(), key="work_emp")
    izbrani_datumi_w = st.multiselect("Tage auswählen:", options=list(range(1, num_days + 1)), key="work_dates")
    rule_w = st.selectbox("Regel:", ["MUSS an diesen Tagen arbeiten", "DARF NUR an diesen Tagen arbeiten"], key="work_rule")

    if st.form_submit_button("Wunschdienst speichern") and izbrani_datumi_w and emp_names_w:
      for emp_name_w in emp_names_w:
          emp_id_w = edited_df.loc[edited_df["Name"] == emp_name_w, "ID"].values[0]
          for d in izbrani_datumi_w:
            st.session_state.work_rules_v9.append({"emp_id": emp_id_w, "emp_name": emp_name_w, "day": d - 1, "rule": rule_w})
      st.success("Wunschdienst gespeichert!")

  if st.session_state.work_rules_v9:
    if st.button("🗑️ Alle Wunschdienste löschen"):
      st.session_state.work_rules_v9 = []
      st.rerun()
    work_df = pd.DataFrame(st.session_state.work_rules_v9)
    work_df["Datum"] = work_df["day"].apply(lambda x: f"{x+1}.")
    st.dataframe(work_df[["emp_name", "Datum", "rule"]].rename(columns={"emp_name": "Mitarbeiter", "rule": "Regel"}), use_container_width=True)

st.divider()

# --- 5. GENERIRANJE URNIKA ---
st.header("5. Automatische Dienstplangenerierung (Sanocon-Level)")
if st.button("🚀 Dienstplan berechnen", type="primary", use_container_width=True):
  staff_list = edited_df.to_dict("records")

  try:
    with st.spinner("Berechne komplexe Sanocon-Regeln (Max 20 Sekunden)..."):
      model = cp_model.CpModel()
      hour_deviations = [] # Za optimizacijo in mehke kazni

      shifts = {
          "X4": 825, "X6": 1100, "X7": 1200, "F1": 1200, "F2": 1100,
          "N1": 1350, "N2": 1350, "JED": 1050, "MS": 700, "SM": 1000, "OFF": 0,
      }

      work = {}
      for s in staff_list:
        for d in range(num_days):
          for sh in shifts.keys():
            work[(s["ID"], d, sh)] = model.NewBoolVar(f'work_{s["ID"]}_{d}_{sh}')

      # Pomožne spremenljivke: ali oseba ta dan sploh dela?
      worked_day = {}
      for s in staff_list:
        for d in range(num_days):
          model.Add(sum(work[(s["ID"], d, sh)] for sh in shifts.keys()) == 1)
          worked_d = model.NewBoolVar(f'worked_any_{s["ID"]}_{d}')
          model.Add(worked_d == 1 - work[(s["ID"], d, "OFF")])
          worked_day[(s["ID"], d)] = worked_d

      # ZAKON 1: MAX 6 DNI ZAPOREDOMA
      for s in staff_list:
          for d in range(num_days - 6):
              model.Add(sum(work[(s["ID"], d + i, "OFF")] for i in range(7)) >= 1)

      # ZAKON 2: MAX 50 UR NA TEDEN (Koledarski tedni PON-NED)
      weeks = []
      curr = []
      for d in range(num_days):
          curr.append(d)
          if (d + first_day_of_month_weekday) % 7 == 6 or d == num_days - 1:
              weeks.append(curr)
              curr = []

      for s in staff_list:
          for w_days in weeks:
              total_w_h = sum(work[(s["ID"], d, sh)] * shifts[sh] for d in w_days for sh in shifts.keys())
              model.Add(total_w_h <= 5000) # Max 50.00 ur

      # ZAKON 3: DVA DNI PROSTA SKUPAJ (Penalizacija enojnih prostih dni)
      for s in staff_list:
          for d in range(1, num_days - 1):
              single_off = model.NewBoolVar(f'sing_off_{s["ID"]}_{d}')
              # Če je delal včeraj IN dela jutri IN ima danes prosto -> single_off postane 1
              model.AddMinEquality(single_off, [worked_day[(s["ID"], d-1)], work[(s["ID"], d, "OFF")], worked_day[(s["ID"], d+1)]])
              hour_deviations.append(single_off * 1000) # Kazen (AI se bo temu izogibala)

      # ZAKON 4: VIKENDI (Max 2 zapored, nato 2 prosta)
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

          # Pravila in kazni za vikende
          for w_idx in range(len(weekends) - 1):
              cons_we = model.NewBoolVar(f'cons_we_{s["ID"]}_{w_idx}')
              model.AddMinEquality(cons_we, [works_we[w_idx], works_we[w_idx+1]])
              hour_deviations.append(cons_we * 1500) # Močna kazen za 2 vikenda zapored (AI preferira 1 deloven, 1 prost)

              # Če vendarle dodeli 2 zapored, morata biti naslednja dva 100% PROSTA!
              if w_idx + 2 < len(weekends):
                  model.Add(works_we[w_idx+2] == 0).OnlyEnforceIf(cons_we)
              if w_idx + 3 < len(weekends):
                  model.Add(works_we[w_idx+3] == 0).OnlyEnforceIf(cons_we)

      # --- SPECIFIČNI DATUMI ---
      only_work_days = {s["ID"]: set() for s in staff_list}
      must_work_days = {s["ID"]: set() for s in staff_list}
      has_only_rule = {s["ID"]: False for s in staff_list}

      for r in st.session_state.work_rules_v9:
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

      # DOVOLJENE IZMENE
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

      # Dopusti (URL, KRA, GEB, ENT, NA, Ü)
      for a in st.session_state.absences_v9:
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
        if len(oB_tehniki) >= 3: model.Add(sum(work[(e, d, sh)] for e in oB_tehniki for sh in day_shifts_tech) >= 4)
        if len(oH_tehniki) >= 3: model.Add(sum(work[(e, d, sh)] for e in oH_tehniki for sh in day_shifts_tech) >= 4)

        dgkp_nocni = [s["ID"] for s in staff_list if s["Rolle"] == "DGKP" and (s["Max_Nacht"] > 0 or "Nur Nachtdienste" in s["Spezialdienst"])]
        if len(dgkp_nocni) > 0: model.Add(sum(work[(e, d, "N1")] for e in dgkp_nocni) == 1)

        tech_nocni_B = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and s["Max_Nacht"] > 0]
        if len(tech_nocni_B) > 0: model.Add(sum(work[(e, d, "N2")] for e in tech_nocni_B) == 1)

        tech_nocni_H = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"] and s["Max_Nacht"] > 0]
        if len(tech_nocni_H) > 0: model.Add(sum(work[(e, d, "N2")] for e in tech_nocni_H) == 1)

        if len(all_dgkp) > 0: model.Add(sum(work[(e, d, "X7")] for e in all_dgkp) >= 1)

      # ZAKON: POČITEK PO NOČNI
      for s in staff_list:
        for d in range(num_days - 1):
          model.AddImplication(work[(s["ID"], d, "N1")], work[(s["ID"], d + 1, "OFF")])
          model.AddImplication(work[(s["ID"], d, "N2")], work[(s["ID"], d + 1, "OFF")])

      # IZRAČUN UR NA PODLAGI ODSTOTKOV (37h = 100%)
      for s in staff_list:
        if "Nur Nachtdienste" in s["Spezialdienst"]: continue
        
        target_hours_per_day = (37.0 * (s["Prozent"] / 100.0)) / 7.0
        target = int(target_hours_per_day * num_days * 100)
        
        total_hours = model.NewIntVar(0, 35000, f'tot_{s["ID"]}')
        model.Add(total_hours == sum(work[(s["ID"], d, sh)] * shifts[sh] for d in range(num_days) for sh in shifts.keys()))

        dev = model.NewIntVar(0, 20000, f'dev_{s["ID"]}')
        model.Add(dev >= total_hours - target)
        model.Add(dev >= target - total_hours)
        hour_deviations.append(dev)
        
        min_h = max(0, target - 3500)
        model.Add(total_hours >= min_h)
        model.Add(total_hours <= target + 3500)

      # Optimiziramo rešitev (Minimiziramo kazni za posamične proste dni in zaporedne vikende)
      model.Minimize(sum(hour_deviations))

      solver = cp_model.CpSolver()
      solver.parameters.max_time_in_seconds = 20.0
      status = solver.Solve(model)

      if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        st.success("🎉 Dienstplan nach Gesetz erfolgreich generiert!")

        data = []
        for s in staff_list:
          row = {"Abteilung": s["Abteilung"], "Rolle": s["Rolle"], "Anst.%": s["Prozent"], "Mitarbeiter": s["Name"]}
          total_hours = 0
          for d in range(num_days):
            for sh in shifts.keys():
              if solver.Value(work[(s["ID"], d, sh)]) == 1:
                val = sh if sh != "OFF" else "..."
                # Vstavljanje kode odsotnosti (URL, KRA, GEB, ENT, NA, Ü)
                for a in st.session_state.absences_v9:
                  if a["emp_id"] == s["ID"] and a["day"] == d:
                    val = a["reason"].split(" ")[0] 
                row[f"{d+1}."] = val
                total_hours += shifts[sh]

          target_hrs = (37.0 * (s["Prozent"] / 100.0) / 7.0) * num_days
          row["SOLL"] = round(target_hrs, 1)
          row["IST"] = total_hours / 100
          row["SALDO"] = round((total_hours / 100) - target_hrs, 1)
          data.append(row)

        df_rezultat = pd.DataFrame(data)

        def highlight_hours(val):
          if isinstance(val, (int, float)):
            if val > 12: return "background-color: #ffcccc; color: #990000; font-weight: bold"
            elif val < -12: return "background-color: #ccccff; color: #000099; font-weight: bold"
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
        st.error("🚨 Keine Lösung! Jemand hat zu viele Wünsche oder die Regeln kollidieren (z.B. zu wenig Personal am Wochenende).")

  except Exception as e:
    st.error(f"⚠️ Systemfehler: {e}")
