import calendar
from datetime import date
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="AI Urniki PRO 6.3", layout="wide")

st.title("🏥 Centralni AI Sistem (Verzija 6.3)")
st.markdown(
    "Natančne šifre izmen: X7, X6, X4, N1 za DGKP in F1, F2, X4, N2 za Tehnike"
    " ter posebne izmene."
)

# --- 1. KOLEDAR IN NASTAVITVE MESECA ---
st.header("1. Izbira meseca in leta")
col_date1, col_date2 = st.columns(2)
with col_date1:
  leto = st.selectbox("Leto:", [2026, 2027, 2028], index=0)
with col_date2:
  mesec = st.selectbox(
      "Mesec:",
      list(range(1, 13)),
      format_func=lambda x: [
          "Januar",
          "Februar",
          "Marec",
          "April",
          "Maj",
          "Junij",
          "Julij",
          "Avgust",
          "September",
          "Oktober",
          "November",
          "December",
      ][x - 1],
  )

first_day_of_month_weekday, num_days = calendar.monthrange(leto, mesec)

# --- 2. UPRAVLJANJE ZAPOSLENIH IN ODDELKOV ---
st.header("2. Ekipa (Izbira vlog, dni in posebnih dinstov)")
st.info(
    "💡 V stolpcu 'Posebno' lahko posamezniku dodeliš fiksen posebni urnik"
    " (npr. F1, F2, X7, JED ili Mutterschutz)."
)

if "staff_df" not in st.session_state:
  initial_staff = []

  # Vodja (Manager - dela X4, vikendi prosto)
  initial_staff.append({
      "ID": 0,
      "Ime": "Vodja (Uroš)",
      "Oddelek": "Oddelek H",
      "Vloga": "Manager",
      "Ure": 40.0,
      "Max_Nocnih": 0,
      "PO": True,
      "TO": True,
      "SR": True,
      "ČE": True,
      "PE": True,
      "SO": False,
      "NE": False,
      "Posebno": "Brez",
  })

  # Oddelek F (Nočni bazen - Samo N1/N2 nočne)
  for i in range(1, 4):
    initial_staff.append({
        "ID": len(initial_staff),
        "Ime": f"DGKP F-{i} (Bazen)",
        "Oddelek": "Oddelek F",
        "Vloga": "DGKP",
        "Ure": 37.0,
        "Max_Nocnih": 4,
        "PO": True,
        "TO": True,
        "SR": True,
        "ČE": True,
        "PE": True,
        "SO": True,
        "NE": True,
        "Posebno": "Samo nočne (brez dnevnih)",
    })

  # Oddelek B (DGKP)
  for i in range(1, 5):
    initial_staff.append({
        "ID": len(initial_staff),
        "Ime": f"DGKP B-{i}",
        "Oddelek": "Oddelek B",
        "Vloga": "DGKP",
        "Ure": 37.0,
        "Max_Nocnih": 0,
        "PO": True,
        "TO": True,
        "SR": True,
        "ČE": True,
        "PE": True,
        "SO": True,
        "NE": True,
        "Posebno": "Brez",
    })

  # Oddelek H (DGKP - ena SM izmena)
  initial_staff.append({
      "ID": len(initial_staff),
      "Ime": "DGKP H-1 (SM izmena)",
      "Oddelek": "Oddelek H",
      "Vloga": "DGKP",
      "Ure": 37.0,
      "Max_Nocnih": 0,
      "PO": True,
      "TO": True,
      "SR": True,
      "ČE": True,
      "PE": True,
      "SO": True,
      "NE": True,
      "Posebno": "SM (7:45-18:15)",
  })
  for i in range(2, 5):
    initial_staff.append({
        "ID": len(initial_staff),
        "Ime": f"DGKP H-{i}",
        "Oddelek": "Oddelek H",
        "Vloga": "DGKP",
        "Ure": 37.0,
        "Max_Nocnih": 0,
        "PO": True,
        "TO": True,
        "SR": True,
        "ČE": True,
        "PE": True,
        "SO": True,
        "NE": True,
        "Posebno": "Brez",
    })

  # Oddelek B (3 Bolničarji za Jedilnico 6:30-18:00)
  for i in range(1, 4):
    initial_staff.append({
        "ID": len(initial_staff),
        "Ime": f"Bolničar B-{i} (JED)",
        "Oddelek": "Oddelek B",
        "Vloga": "Bolničar",
        "Ure": 37.0,
        "Max_Nocnih": 0,
        "PO": True,
        "TO": True,
        "SR": True,
        "ČE": True,
        "PE": True,
        "SO": True,
        "NE": True,
        "Posebno": "Jedilnica JED (6:30-18:00)",
    })

  # Oddelek B (Tehniki)
  initial_staff.append({
      "ID": len(initial_staff),
      "Ime": "Tehnik B-1 (Noseča)",
      "Oddelek": "Oddelek B",
      "Vloga": "Tehnik",
      "Ure": 37.0,
      "Max_Nocnih": 0,
      "PO": True,
      "TO": True,
      "SR": True,
      "ČE": True,
      "PE": True,
      "SO": False,
      "NE": False,
      "Posebno": "Mutterschutz (7:30-15:00)",
  })
  for i in range(2, 12):
    initial_staff.append({
        "ID": len(initial_staff),
        "Ime": f"Tehnik B-{i}",
        "Oddelek": "Oddelek B",
        "Vloga": "Tehnik",
        "Ure": 37.0,
        "Max_Nocnih": 5,
        "PO": True,
        "TO": True,
        "SR": True,
        "ČE": True,
        "PE": True,
        "SO": True,
        "NE": True,
        "Posebno": "Brez",
    })

  # Oddelek H (Tehniki)
  for i in range(1, 15):
    initial_staff.append({
        "ID": len(initial_staff),
        "Ime": f"Tehnik H-{i}",
        "Oddelek": "Oddelek H",
        "Vloga": "Tehnik",
        "Ure": 37.0,
        "Max_Nocnih": 5,
        "PO": True,
        "TO": True,
        "SR": True,
        "ČE": True,
        "PE": True,
        "SO": True,
        "NE": True,
        "Posebno": "Brez",
    })

  st.session_state.staff_df = pd.DataFrame(initial_staff)

edited_df = st.data_editor(
    st.session_state.staff_df,
    num_rows="dynamic",
    key="tabela_zaposlenih_v63",
    column_config={
        "Oddelek": st.column_config.SelectboxColumn(
            "Oddelek",
            options=["Oddelek B", "Oddelek H", "Oddelek F"],
            required=True,
        ),
        "Vloga": st.column_config.SelectboxColumn(
            "Vloga",
            options=["Manager", "DGKP", "Tehnik", "Bolničar"],
            required=True,
        ),
        "Ure": st.column_config.NumberColumn(
            "Ted. ure", min_value=10.0, max_value=40.0, required=True
        ),
        "Max_Nocnih": st.column_config.NumberColumn(
            "Max noč.", min_value=0, max_value=15, default=0
        ),
        "PO": st.column_config.CheckboxColumn("Pon", default=True),
        "TO": st.column_config.CheckboxColumn("Tor", default=True),
        "SR": st.column_config.CheckboxColumn("Sre", default=True),
        "ČE": st.column_config.CheckboxColumn("Čet", default=True),
        "PE": st.column_config.CheckboxColumn("Pet", default=True),
        "SO": st.column_config.CheckboxColumn("Sob", default=True),
        "NE": st.column_config.CheckboxColumn("Ned", default=True),
        "Posebno": st.column_config.SelectboxColumn(
            "Posebni urnik",
            options=[
                "Brez",
                "F1 (Tehnik 6:45-19:15)",
                "F2 (Tehnik 6:45-18:15)",
                "X7 (DGKP 6:45-19:15)",
                "X6 (DGKP 6:45-18:15)",
                "X4 (6:45-15:30)",
                "Jedilnica JED (6:30-18:00)",
                "Mutterschutz (7:30-15:00)",
                "SM (7:45-18:15)",
                "Samo nočne (brez dnevnih)",
            ],
            required=True,
        ),
    },
    use_container_width=True,
)

if "absences" not in st.session_state:
  st.session_state.absences = []
if "work_rules" not in st.session_state:
  st.session_state.work_rules = []

st.divider()

# --- 3. TOČEN VNOS ODSOTNOSTI IN ŽELJA ---
col_abs, col_work = st.columns(2)

with col_abs:
  st.header("3. Vnos odsotnosti (Dopusti)")
  with st.form("absence_form"):
    emp_name = st.selectbox(
        "Zaposleni:", options=edited_df["Ime"].tolist(), key="abs_emp"
    )
    izbrani_datumi = st.multiselect(
        "Izberi datume odsotnosti:",
        options=list(range(1, num_days + 1)),
        key="abs_dates",
    )
    reason = st.selectbox(
        "Razlog:", ["DOP (Dopust)", "BOL (Bolniška)", "ROJ", "ENT"], key="abs_reason"
    )

    if st.form_submit_button("Shrani odsotnosti") and izbrani_datumi:
      emp_id = edited_df.loc[edited_df["Ime"] == emp_name, "ID"].values[0]
      for d in izbrani_datumi:
        st.session_state.absences.append({
            "emp_id": emp_id,
            "emp_name": emp_name,
            "day": d - 1,
            "reason": reason,
        })
      st.success("Odsotnosti shranjene!")

  if st.session_state.absences:
    if st.button("🗑️ Izbriši vse odsotnosti"):
      st.session_state.absences = []
      st.rerun()
    abs_df = pd.DataFrame(st.session_state.absences)
    abs_df["Datum"] = abs_df["day"].apply(lambda x: f"{x+1}.")
    st.dataframe(
        abs_df[["emp_name", "Datum", "reason"]], use_container_width=True
    )

with col_work:
  st.header("4. Vnos delovnih dni (Specifični datumi)")
  with st.form("work_form"):
    emp_name_w = st.selectbox(
        "Zaposleni:", options=edited_df["Ime"].tolist(), key="work_emp"
    )
    izbrani_datumi_w = st.multiselect(
        "Izberi točne datume:",
        options=list(range(1, num_days + 1)),
        key="work_dates",
    )
    rule_w = st.selectbox(
        "Pravilo:",
        [
            "MORA delati na te izbrane dni",
            "Sme delati SAMO na te izbrane dni",
        ],
        key="work_rule",
    )

    if st.form_submit_button("Shrani delovne dni") and izbrani_datumi_w:
      emp_id_w = edited_df.loc[edited_df["Ime"] == emp_name_w, "ID"].values[0]
      for d in izbrani_datumi_w:
        st.session_state.work_rules.append({
            "emp_id": emp_id_w,
            "emp_name": emp_name_w,
            "day": d - 1,
            "rule": rule_w,
        })
      st.success("Pravila za delo shranjena!")

  if st.session_state.work_rules:
    if st.button("🗑️ Izbriši vse delovne želje"):
      st.session_state.work_rules = []
      st.rerun()
    work_df = pd.DataFrame(st.session_state.work_rules)
    work_df["Datum"] = work_df["day"].apply(lambda x: f"{x+1}.")
    st.dataframe(
        work_df[["emp_name", "Datum", "rule"]], use_container_width=True
    )

st.divider()

# --- 5. GENERIRANJE URNIKA ---
st.header("5. Avtomatska generacija")
if st.button("🚀 Izračunaj urnik", type="primary", use_container_width=True):
  staff_list = edited_df.to_dict("records")

  try:
    with st.spinner("Računam urnik z novimi šiframi (X7, X6, X4, F1, F2)..."):
      model = cp_model.CpModel()

      # ŠIFRE IN URE (ure * 100)
      shifts = {
          "X4": 825,  # 06:45 - 15:30 (8.25 h)
          "X6": 1100,  # 06:45 - 18:15 (11.0 h)
          "X7": 1200,  # 06:45 - 19:15 (12.0 h)
          "F1": 1200,  # Tehnik 06:45 - 19:15 (12.0 h)
          "F2": 1100,  # Tehnik 06:45 - 18:15 (11.0 h)
          "N1": 1350,  # DGKP Nočna 19:00 - 07:00 (11.5h + 2h bonus = 13.5h)
          "N2": 1350,  # Tehnik Nočna 19:00 - 07:00
          "JED": 1050,  # Jedilnica 06:30 - 18:00 (10.5 h)
          "MS": 700,  # Mutterschutz 07:30 - 15:00
          "SM": 1000,  # SM 07:45 - 18:15
          "OFF": 0,
      }

      work = {}
      for s in staff_list:
        for d in range(num_days):
          for sh in shifts.keys():
            work[(s["ID"], d, sh)] = model.NewBoolVar(
                f'work_{s["ID"]}_{d}_{sh}'
            )

      for s in staff_list:
        for d in range(num_days):
          model.Add(sum(work[(s["ID"], d, sh)] for sh in shifts.keys()) == 1)

      # --- SPECIFIČNI DATUMI ---
      only_work_days = {s["ID"]: set() for s in staff_list}
      must_work_days = {s["ID"]: set() for s in staff_list}
      has_only_rule = {s["ID"]: False for s in staff_list}

      for r in st.session_state.work_rules:
        if "SAMO" in r["rule"]:
          only_work_days[r["emp_id"]].add(r["day"])
          has_only_rule[r["emp_id"]] = True
        elif "MORA" in r["rule"]:
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
      day_keys = {0: "PO", 1: "TO", 2: "SR", 3: "ČE", 4: "PE", 5: "SO", 6: "NE"}

      for s in staff_list:
        allowed_shifts = ["OFF"]

        # Posebnosti iz spustnega seznama
        if "F1" in s["Posebno"]:
          allowed_shifts.append("F1")
        elif "F2" in s["Posebno"]:
          allowed_shifts.append("F2")
        elif "X7" in s["Posebno"]:
          allowed_shifts.append("X7")
        elif "X6" in s["Posebno"]:
          allowed_shifts.append("X6")
        elif "X4" in s["Posebno"]:
          allowed_shifts.append("X4")
        elif "Jedilnica JED" in s["Posebno"]:
          allowed_shifts.append("JED")
        elif "Mutterschutz" in s["Posebno"]:
          allowed_shifts.append("MS")
        elif "SM" in s["Posebno"]:
          allowed_shifts.append("SM")
        elif "Samo nočne" in s["Posebno"]:
          if s["Vloga"] == "DGKP":
            allowed_shifts.append("N1")
          else:
            allowed_shifts.append("N2")
        elif s["Vloga"] == "Manager":
          allowed_shifts.append("X4")
        elif s["Vloga"] == "DGKP":
          # DGKP lahko dela X4, X6, X7 ter N1 (če ima nočne)
          allowed_shifts.extend(["X4", "X6", "X7"])
          if s["Max_Nocnih"] > 0:
            allowed_shifts.append("N1")
        elif s["Vloga"] in ["Tehnik", "Bolničar"]:
          # Tehnik lahko dela F1, F2, X4 ter N2 (če ima nočne)
          allowed_shifts.extend(["F1", "F2", "X4"])
          if s["Max_Nocnih"] > 0:
            allowed_shifts.append("N2")

        unallowed = [sh for sh in shifts.keys() if sh not in allowed_shifts]
        for d in range(num_days):
          for sh in unallowed:
            model.Add(work[(s["ID"], d, sh)] == 0)

        # MAX NOČNIH
        if s["Max_Nocnih"] >= 0:
          nocna_koda = "N1" if s["Vloga"] == "DGKP" else "N2"
          model.Add(
              sum(work[(s["ID"], d, nocna_koda)] for d in range(num_days))
              <= int(s["Max_Nocnih"])
          )

        # KLJUKICE PO-NE
        for d in range(num_days):
          day_of_week = (d + first_day_of_month_weekday) % 7
          day_name = day_keys[day_of_week]
          if not s[day_name]:
            model.Add(work[(s["ID"], d, "OFF")] == 1)

      # Dopusti
      for a in st.session_state.absences:
        if a["day"] < num_days:
          model.Add(work[(a["emp_id"], a["day"], "OFF")] == 1)

      # POKRITOST ODDELKOV
      oB_tehniki = [
          s["ID"]
          for s in staff_list
          if s["Oddelek"] == "Oddelek B" and s["Vloga"] in ["Tehnik", "Bolničar"]
      ]
      oH_tehniki = [
          s["ID"]
          for s in staff_list
          if s["Oddelek"] == "Oddelek H" and s["Vloga"] in ["Tehnik", "Bolničar"]
      ]
      all_dgkp = [
          s["ID"]
          for s in staff_list
          if s["Vloga"] in ["DGKP", "Manager"]
      ]
      jedilnica_kadri = [
          s["ID"]
          for s in staff_list
          if "Jedilnica JED" in s["Posebno"]
      ]

      day_shifts_tech = ["F1", "F2", "X4", "MS", "JED"]
      day_shifts_dgkp = ["X4", "X6", "X7", "SM"]

      for d in range(num_days):
        # Jedilnica pokrita
        if len(jedilnica_kadri) > 0:
          model.Add(
              sum(work[(e, d, "JED")] for e in jedilnica_kadri) == 1
          )

        # Dnevno pokritje tehnikov na B in H
        if len(oB_tehniki) >= 3:
          model.Add(
              sum(work[(e, d, sh)] for e in oB_tehniki for sh in day_shifts_tech)
              >= 4
          )
        if len(oH_tehniki) >= 3:
          model.Add(
              sum(work[(e, d, sh)] for e in oH_tehniki for sh in day_shifts_tech)
              >= 4
          )

        # Nočne izmene (N1 in N2)
        dgkp_nocni = [
            s["ID"]
            for s in staff_list
            if s["Vloga"] == "DGKP"
            and (
                s["Max_Nocnih"] > 0
                or "Samo nočne" in s["Posebno"]
            )
        ]
        if len(dgkp_nocni) > 0:
          model.Add(sum(work[(e, d, "N1")] for e in dgkp_nocni) == 1)

        tech_nocni_B = [
            s["ID"]
            for s in staff_list
            if s["Oddelek"] == "Oddelek B"
            and s["Vloga"] in ["Tehnik", "Bolničar"]
            and s["Max_Nocnih"] > 0
        ]
        if len(tech_nocni_B) > 0:
          model.Add(sum(work[(e, d, "N2")] for e in tech_nocni_B) == 1)

        tech_nocni_H = [
            s["ID"]
            for s in staff_list
            if s["Oddelek"] == "Oddelek H"
            and s["Vloga"] in ["Tehnik", "Bolničar"]
            and s["Max_Nocnih"] > 0
        ]
        if len(tech_nocni_H) > 0:
          model.Add(sum(work[(e, d, "N2")] for e in tech_nocni_H) == 1)

        # Predaja ob 19:15 (DGKP na X7 ali Tehnik na F1)
        if len(all_dgkp) > 0:
          model.Add(sum(work[(e, d, "X7")] for e in all_dgkp) >= 1)

      # POČITEK PO NOČNI
      for s in staff_list:
        for d in range(num_days - 1):
          model.AddImplication(
              work[(s["ID"], d, "N1")], work[(s["ID"], d + 1, "OFF")]
          )
          model.AddImplication(
              work[(s["ID"], d, "N2")], work[(s["ID"], d + 1, "OFF")]
          )

      # IZRAČUN UR
      for s in staff_list:
        if "Samo nočne" in s["Posebno"]:
          continue
        target = int((s["Ure"] / 7.0) * num_days * 100)
        total_hours = model.NewIntVar(0, 35000, f'tot_{s["ID"]}')
        model.Add(
            total_hours
            == sum(
                work[(s["ID"], d, sh)] * shifts[sh]
                for d in range(num_days)
                for sh in shifts.keys()
            )
        )

        min_h = max(0, target - 3500)
        model.Add(total_hours >= min_h)
        model.Add(total_hours <= target + 3500)

      solver = cp_model.CpSolver()
      solver.parameters.max_time_in_seconds = 15.0
      status = solver.Solve(model)

      if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
        st.success("🎉 Urnik uspešno zgeneriran!")

        data = []
        for s in staff_list:
          row = {
              "Oddelek": s["Oddelek"],
              "Vloga": s["Vloga"],
              "Zaposleni": s["Ime"],
          }
          total_hours = 0
          for d in range(num_days):
            for sh in shifts.keys():
              if solver.Value(work[(s["ID"], d, sh)]) == 1:
                val = sh if sh != "OFF" else "..."
                for a in st.session_state.absences:
                  if a["emp_id"] == s["ID"] and a["day"] == d:
                    val = a["reason"].split(" ")[0]
                row[f"{d+1}."] = val
                total_hours += shifts[sh]

          target_hrs = (s["Ure"] / 7.0) * num_days
          row["FOND"] = round(target_hrs, 1)
          row["PLANIRANO"] = total_hours / 100
          row["RAZLIKA"] = round((total_hours / 100) - target_hrs, 1)
          data.append(row)

        df_rezultat = pd.DataFrame(data)

        def highlight_hours(val):
          if isinstance(val, (int, float)):
            if val > 12:
              return "background-color: #ffcccc; color: #990000; font-weight:"
              " bold"
            elif val < -12:
              return "background-color: #ccccff; color: #000099; font-weight:"
              " bold"
          return ""

        st.subheader("🔵 Oddelek B")
        df_b = df_rezultat[df_rezultat["Oddelek"] == "Oddelek B"].drop(
            columns=["Oddelek"]
        )
        st.dataframe(
            df_b.style.map(highlight_hours, subset=["RAZLIKA"]),
            use_container_width=True,
        )

        st.subheader("🟢 Oddelek H")
        df_h = df_rezultat[df_rezultat["Oddelek"] == "Oddelek H"].drop(
            columns=["Oddelek"]
        )
        st.dataframe(
            df_h.style.map(highlight_hours, subset=["RAZLIKA"]),
            use_container_width=True,
        )

        st.subheader("🟣 Oddelek F (Nočni bazen)")
        df_f = df_rezultat[df_rezultat["Oddelek"] == "Oddelek F"].drop(
            columns=["Oddelek"]
        )
        st.dataframe(
            df_f.style.map(highlight_hours, subset=["RAZLIKA"]),
            use_container_width=True,
        )

      else:
        st.error(
            "🚨 Sistem ni našel rešitve. Preveri nastavitve ali število nočnih!"
        )

  except Exception as e:
    st.error(f"⚠️ Sistemska napaka: {e}")
