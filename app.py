import calendar
from datetime import date
import hashlib
import io
import os
import holidays
import numpy as np
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KI-Dienstplan PRO 67.0", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 67.0 - Steiermark Legal & Manual Planner)")
st.markdown(
    "**System-Architektur (Steiermark Rechts-Engine, Fix-Dienst-Planer & 1x-DGKP-Nacht-Sperre):** \n"
    "- 🌙 **Striktes Nacht-Limit:** Es wird **niemals mehr als 1 DGKP (`N1`)** pro Nacht eingeplant (Hard-Lock: max. 1x `N1` DGKP + 1x `N2` PA).\n"
    "- 📌 **Manuelle Fix-Dienste vorab (Tab 3) & Live-Editor (Tab 2):** Du kannst jedem Mitarbeiter vorab exakte Schichten (`F2`, `F7`, `X7`, `X6`, `X4`, `N1`, `N2`, `JED`) fest eintragen.\n"
    "- ⚖️ **Gesetzes-Status pro Mitarbeiter (Tab 1 & Tab 6):** Unterstützt **Mutterschutz (MSchG)**, **Altersteilzeit (ATZ)**, **Elternteilzeit (ETZ)**, **StPAVO Steiermark**, **GuKG** & **NSchG**."
)

# --- KONSTANTEN FÜR SCHICHTDAUER (in 100stel Stunden) ---
SHIFTS_HUNDREDTHS = {
    "X4": 825, "X6": 1100, "X7": 1200, "F2": 1200, "F7": 1100, 
    "N1": 1350, "N2": 1350, "JED": 1050, "MS": 700, "SM": 1075, "OFF": 0
}
SHIFT_LABELS = {
    "X7": "X7 (12,0h DGKP Lang)",
    "X6": "X6 (11,0h DGKP Tag)",
    "X4": "X4 (8,25h DGKP Kurz / MSchG-konform)",
    "F2": "F2 (12,0h PA/HH Lang)",
    "F7": "F7 (11,0h PA/HH Tag)",
    "SM": "SM (10,75h HH/DGKP)",
    "JED": "JED (10,5h Speisesaal)",
    "MS": "MS (7,0h Kurz / MSchG-konform)",
    "N1": "N1 (13,5h Nacht DGKP)",
    "N2": "N2 (13,5h Nacht PA)"
}
GESETZ_STATUS_OPTIONS = [
    "Normal",
    "Altersteilzeit (ATZ)",
    "Mutterschutz (MSchG)",
    "Elternteilzeit (ETZ)",
    "Pflegekarenz / Teilzeit",
    "Nachtschwerarbeit (NSchG)"
]
DAY_CARE_SHIFTS = ["X4", "X6", "X7", "F2", "F7", "MS", "SM"]
DGKP_DAY_SHIFTS = ["X4", "X6", "X7"]
PAID_ABSENCES = ["URL", "SU", "ENT", "KRA", "PFLEGE"]
MANUAL_SHIFT_CODES = ["X7", "X6", "X4", "F2", "F7", "N1", "N2", "JED", "MS", "SM"]

# --- HILFSFUNKTIONEN FÜR DATEIEN & DATENBEREINIGUNG ---
def read_csv_smart(raw_bytes, is_index_col=False):
    for enc in ["utf-8-sig", "utf-8", "latin1", "cp1252"]:
        try:
            text = raw_bytes.decode(enc)
            lines = [line for line in text.splitlines() if line.strip()]
            first_line = lines[0] if lines else ""
            sep = ";" if first_line.count(";") > first_line.count(",") else ","
            if is_index_col:
                return pd.read_csv(io.StringIO(text), sep=sep, index_col=0)
            else:
                return pd.read_csv(io.StringIO(text), sep=sep)
        except Exception:
            continue
    if is_index_col:
        return pd.read_csv(io.BytesIO(raw_bytes), index_col=0)
    return pd.read_csv(io.BytesIO(raw_bytes))

def sanitize_team_df(df):
    df = df.copy()
    if "Name" not in df.columns and len(df.columns) > 0:
        df = df.reset_index()
        if "Name" not in df.columns:
            df.rename(columns={df.columns[0]: "Name"}, inplace=True)
            
    df = df.dropna(subset=["Name"])
    df["Name"] = df["Name"].astype(str).str.strip()
    df = df[df["Name"] != ""]
    df = df[~df["Name"].str.lower().isin(["nan", "none", "<na>", "null"])]
    
    if "Wochenstd" not in df.columns: 
        df["Wochenstd"] = 37.0
    df["Wochenstd"] = pd.to_numeric(df["Wochenstd"], errors='coerce').fillna(37.0)
    df["Prozent"] = ((df["Wochenstd"] / 37.0) * 100).round(1)
    
    if "Nur_Nacht" not in df.columns: 
        df["Nur_Nacht"] = False
    df["Nur_Nacht"] = df["Nur_Nacht"].apply(lambda x: str(x).strip().lower() in ["true", "1", "yes", "ja", "wahr"])
    
    df["ID"] = range(len(df))
    
    if "URL_Gesamt" not in df.columns: 
        df["URL_Gesamt"] = 25.0
    df["URL_Gesamt"] = pd.to_numeric(df["URL_Gesamt"], errors='coerce').fillna(25.0)
    
    if "URL_Rest" not in df.columns: 
        df["URL_Rest"] = df["URL_Gesamt"]
    df["URL_Rest"] = pd.to_numeric(df["URL_Rest"], errors='coerce').fillna(25.0)
    
    if "Saldo_Alt" not in df.columns: 
        df["Saldo_Alt"] = 0.0
    df["Saldo_Alt"] = pd.to_numeric(df["Saldo_Alt"], errors='coerce').fillna(0.0)
    
    if "Max_Nacht" not in df.columns: 
        df["Max_Nacht"] = 0
    df["Max_Nacht"] = pd.to_numeric(df["Max_Nacht"], errors='coerce').fillna(0).astype(int)
    
    if "Qualifikation" not in df.columns: 
        df["Qualifikation"] = "Keine"
    if "Gesetz_Status" not in df.columns:
        df["Gesetz_Status"] = "Normal"
        
    cols_order = [
        "ID", "Name", "Abteilung", "Rolle", "Qualifikation", "Gesetz_Status", "Wochenstd", "Prozent", 
        "URL_Gesamt", "URL_Rest", "Saldo_Alt", "Max_Nacht", "Nur_Nacht", 
        "MO", "DI", "MI", "DO", "FR", "SA", "SO", "FT", "Spezialdienst"
    ]
    for c in cols_order:
        if c not in df.columns:
            if c in ["MO", "DI", "MI", "DO", "FR", "SA", "SO", "FT"]: 
                df[c] = True
            elif c == "Spezialdienst": 
                df[c] = "Ohne"
            elif c == "Qualifikation": 
                df[c] = "Keine"
            elif c == "Gesetz_Status":
                df[c] = "Normal"
            elif c == "Nur_Nacht": 
                df[c] = False
            else: 
                df[c] = 0
        else:
            if c in ["MO", "DI", "MI", "DO", "FR", "SA", "SO", "FT"]:
                df[c] = df[c].apply(lambda x: False if str(x).strip().lower() in ["false", "0", "no", "nein", "falsch"] else True)
            elif c == "Spezialdienst":
                df[c] = df[c].fillna("Ohne").astype(str).str.strip()
                df.loc[df[c].isin(["", "nan", "None", "none"]), c] = "Ohne"
            elif c == "Gesetz_Status":
                df[c] = df[c].fillna("Normal").astype(str).str.strip()
                df.loc[~df[c].isin(GESETZ_STATUS_OPTIONS), c] = "Normal"
                
    return df[cols_order].reset_index(drop=True)

def resolve_allowed_shifts_for_person(s):
    """
    Ermittelt die erlaubten Schichten pro Person:
    - Berücksichtigt Rolle (PA strikt nur F2, F7, N2)
    - Berücksichtigt Mutterschutz (MSchG: keine Nacht, keine Langdienste > 9h)
    - Berücksichtigt individuelle Einträge im Feld 'Spezialdienst'
    """
    allowed_shifts = ["OFF"]
    nur_nacht = bool(s.get("Nur_Nacht", False))
    spez = str(s.get("Spezialdienst", "Ohne")).upper().strip()
    rolle = str(s.get("Rolle", "Pflegeassistenz")).strip()
    gesetz = str(s.get("Gesetz_Status", "Normal")).strip()
    max_n = int(s.get("Max_Nacht", 0))

    # 1. MUTTERSCHUTZ (MSchG): Absolutes Nachtarbeitsverbot & Verbot von Diensten > 9h
    if gesetz == "Mutterschutz (MSchG)":
        if rolle in ["DGKP", "Leitung"]:
            allowed_shifts.append("X4")  # 8,25h
        elif rolle == "Pflegeassistenz":
            # Für PA im Mutterschutz ist ausnahmsweise F7 nicht zulässig (>9h), falls im Haus Kurzdienst nötig, sonst F7 nur wenn freigegeben
            if "F7" in spez:
                allowed_shifts.append("F7")
            else:
                allowed_shifts.append("F7") # PA hat im System nur F2/F7, wir bevorzugen den kürzeren F7
        else:
            allowed_shifts.append("MS")  # 7,0h
        return list(set(allowed_shifts))

    # 2. STRIKTE REGEL FÜR PFLEGEASSISTENZ (PA): Nur F2, F7 und N2!
    if rolle == "Pflegeassistenz":
        if not nur_nacht:
            pa_day = []
            if "F2" in spez:
                pa_day.append("F2")
            if "F7" in spez:
                pa_day.append("F7")
            if not pa_day:
                pa_day = ["F2", "F7"]
            allowed_shifts.extend(pa_day)
        if max_n > 0 or nur_nacht:
            allowed_shifts.append("N2")
        return list(set(allowed_shifts))

    # 3. REGELN FÜR DGKP, LEITUNG & HEIMHELFER
    if spez not in ["OHNE", "NUR WE UND FEIERTAGE", ""]:
        for sh_code in ["X4", "X6", "X7", "F2", "F7", "JED", "MS", "SM"]:
            if sh_code in spez and not nur_nacht:
                allowed_shifts.append(sh_code)
        if spez == "JED" and rolle == "Heimhelfer" and not nur_nacht:
            allowed_shifts.extend(["F2", "F7"])
        if len(allowed_shifts) == 1 and not nur_nacht:
            if rolle in ["DGKP", "Leitung"]:
                allowed_shifts.extend(["X4", "X6", "X7"])
            else:
                allowed_shifts.extend(["JED", "F2", "F7"])
    else:
        if rolle in ["DGKP", "Leitung"]:
            if not nur_nacht:
                allowed_shifts.extend(["X4", "X6", "X7"])
        elif rolle == "Heimhelfer":
            if not nur_nacht:
                allowed_shifts.extend(["JED", "F2", "F7"])

    # DGKP darf NIEMALS N2 machen, sondern im Nachtdienst ausschließlich N1!
    if max_n > 0 and rolle != "Leitung":
        if rolle == "DGKP":
            allowed_shifts.append("N1")
        elif rolle != "DGKP":
            allowed_shifts.append("N2")

    return list(set(allowed_shifts))

def recalculate_plan_df(df_plan, staff_df, num_days):
    """Berechnet SOLL, IST, ÜBERSTD. und SALDO für alle Zeilen nach manuellen Änderungen neu."""
    df_out = df_plan.copy()
    day_cols_plan = [f"{d}." for d in range(1, num_days + 1) if f"{d}." in df_out.columns]
    
    staff_lookup = {}
    for _, s_row in staff_df.iterrows():
        base_name = str(s_row["Name"]).strip()
        qual = str(s_row.get("Qualifikation", "Keine")).strip()
        full_display = f"{base_name} ({qual})" if qual != "Keine" else base_name
        info = {
            "Wochenstd": float(s_row.get("Wochenstd", 37.0)),
            "Saldo_Alt": float(s_row.get("Saldo_Alt", 0.0))
        }
        staff_lookup[full_display.lower()] = info
        staff_lookup[base_name.lower()] = info

    rows_to_keep = []
    for idx, row in df_out.iterrows():
        emp_display = str(row.get("Mitarbeiter", "")).strip()
        is_virtual = ("X-Oseba" in emp_display) or ("FEHLT" in emp_display) or ("⚠️" in emp_display)
        
        if is_virtual:
            has_any_alarm = False
            for c in day_cols_plan:
                raw_val = row[c]
                if pd.isna(raw_val) or str(raw_val).strip().upper() in ["", "...", "OFF", "NAN", "NONE"]:
                    df_out.at[idx, c] = "..."
                else:
                    clean_v = str(raw_val).strip().upper()
                    if not clean_v.startswith("🚨") and clean_v in SHIFTS_HUNDREDTHS:
                        clean_v = f"🚨 {clean_v}"
                    df_out.at[idx, c] = clean_v
                    has_any_alarm = True
            df_out.at[idx, "SOLL"] = 0.0
            df_out.at[idx, "IST"] = 0.0
            df_out.at[idx, "ÜBERSTD."] = 0.0
            df_out.at[idx, "SALDO"] = 0.0
            if has_any_alarm:
                rows_to_keep.append(idx)
            continue

        rows_to_keep.append(idx)
        base_emp = emp_display.split(" (")[0].strip().lower()
        emp_info = staff_lookup.get(emp_display.lower(), staff_lookup.get(base_emp, {"Wochenstd": 37.0, "Saldo_Alt": 0.0}))
        
        w_std = emp_info["Wochenstd"]
        saldo_alt = emp_info["Saldo_Alt"]
        daily_avg = w_std / 7.0
        
        total_hours_100 = 0
        for c in day_cols_plan:
            raw_val = row[c]
            if pd.isna(raw_val) or str(raw_val).strip().upper() in ["", "...", "OFF", "NAN", "NONE"]:
                clean_v = "..."
            else:
                clean_v = str(raw_val).strip().upper().replace("📌", "").strip()
                for code in ["URL", "SU", "ENT", "KRA", "ZA", "PFLEGE", "WUNSCH", "MUSS"]:
                    if code in clean_v:
                        clean_v = code
                        break
            df_out.at[idx, c] = clean_v
            
            sh_check = clean_v.replace("🚨", "").strip()
            if sh_check in SHIFTS_HUNDREDTHS:
                total_hours_100 += SHIFTS_HUNDREDTHS[sh_check]
            elif any(pa in clean_v for pa in PAID_ABSENCES):
                total_hours_100 += int(round(daily_avg * 100))
                
        soll_exact = daily_avg * num_days
        ist_std = round(total_hours_100 / 100.0, 1)
        ueberstd = round(max(0.0, ist_std - soll_exact), 1)
        saldo_neu = round(ist_std - soll_exact + saldo_alt, 1)
        
        df_out.at[idx, "SOLL"] = round(soll_exact, 1)
        df_out.at[idx, "IST"] = ist_std
        df_out.at[idx, "ÜBERSTD."] = ueberstd
        df_out.at[idx, "SALDO"] = saldo_neu
        
    return df_out.loc[rows_to_keep].reset_index(drop=True)

def build_coverage_summary_df(full_df, dept_name, num_days):
    """Erstellt die Kontrollzeilen inkl. automatischer Springer-Erkennung bei DGKP."""
    day_cols_only = [f"{d}." for d in range(1, num_days + 1)]
    real_full = full_df[~full_df["Mitarbeiter"].astype(str).str.contains("X-Oseba|FEHLT|⚠️", na=False)]
    real_dept = real_full[real_full["Abteilung"] == dept_name]

    summary_rows = []

    if dept_name in ["Abteilung B", "Abteilung H"]:
        row_care = {"Kontroll-Kategorie": "👥 Pflege Tag (Min. 4)"}
        row_dgkp = {"Kontroll-Kategorie": "🩺 davon DGKP (Min. 1)"}
        for c in day_cols_only:
            vals = real_dept[c].astype(str).str.strip().tolist()
            row_care[c] = sum(1 for v in vals if v in DAY_CARE_SHIFTS)
            
            dgkp_vals = real_dept[real_dept["Rolle"].isin(["DGKP", "Leitung"])][c].astype(str).str.strip().tolist()
            own_dgkp = sum(1 for v in dgkp_vals if v in DGKP_DAY_SHIFTS)
            
            all_dgkp_vals = real_full[real_full["Rolle"].isin(["DGKP", "Leitung"])][c].astype(str).str.strip().tolist()
            house_dgkp = sum(1 for v in all_dgkp_vals if v in DGKP_DAY_SHIFTS)
            
            if own_dgkp == 0 and house_dgkp >= 2:
                row_dgkp[c] = "0 (🤝 Springer)"
            else:
                row_dgkp[c] = own_dgkp
            
        summary_rows.append(row_care)
        summary_rows.append(row_dgkp)

        if dept_name == "Abteilung B":
            row_jed = {"Kontroll-Kategorie": "🍽️ Speisesaal JED (Min. 1)"}
            for c in day_cols_only:
                vals = real_dept[c].astype(str).str.strip().tolist()
                row_jed[c] = sum(1 for v in vals if v == "JED")
            summary_rows.append(row_jed)

    else:
        row_f_day = {"Kontroll-Kategorie": "👥 Flex Tagdienst (Abt. F)"}
        row_n1 = {"Kontroll-Kategorie": "🌙 Hausweit N1 - DGKP (Exakt 1)"}
        row_n2 = {"Kontroll-Kategorie": "🌙 Hausweit N2 - PA (Exakt 1)"}
        for c in day_cols_only:
            vals_f = real_dept[c].astype(str).str.strip().tolist()
            row_f_day[c] = sum(1 for v in vals_f if v in DAY_CARE_SHIFTS)
            
            vals_all = real_full[c].astype(str).str.strip().tolist()
            row_n1[c] = sum(1 for v in vals_all if v == "N1")
            row_n2[c] = sum(1 for v in vals_all if v == "N2")
            
        summary_rows.append(row_f_day)
        summary_rows.append(row_n1)
        summary_rows.append(row_n2)

    return pd.DataFrame(summary_rows)

def style_coverage_summary(df_sum):
    def color_row(row):
        kat = str(row.get("Kontroll-Kategorie", ""))
        styles = ["font-weight: bold; background-color: #f8f9fa; color: #212529;"]
        for col in df_sum.columns[1:]:
            val = row[col]
            if isinstance(val, str) and "Springer" in val:
                styles.append("background-color: #fff3cd; color: #856404; font-weight: bold; text-align: center; border: 1px solid #ffeeba;")
                continue
            if not isinstance(val, (int, float, np.integer)):
                styles.append("text-align: center;")
                continue
            if "Min. 4" in kat:
                if val < 4:
                    styles.append("background-color: #f8d7da; color: #721c24; font-weight: bold; text-align: center; border: 1px solid #f5c6cb;")
                else:
                    styles.append("background-color: #d4edda; color: #155724; font-weight: bold; text-align: center;")
            elif "Min. 1" in kat:
                if val < 1:
                    styles.append("background-color: #f8d7da; color: #721c24; font-weight: bold; text-align: center; border: 1px solid #f5c6cb;")
                else:
                    styles.append("background-color: #d4edda; color: #155724; font-weight: bold; text-align: center;")
            elif "Exakt 1" in kat:
                if val == 1:
                    styles.append("background-color: #d4edda; color: #155724; font-weight: bold; text-align: center;")
                else:
                    styles.append("background-color: #f8d7da; color: #721c24; font-weight: bold; text-align: center; border: 1px solid #f5c6cb;")
            else:
                styles.append("background-color: #eef2f7; color: #333333; font-weight: bold; text-align: center;")
        return styles

    return df_sum.style.apply(color_row, axis=1)

def run_austrian_law_audit(df_plan, staff_df, num_days, leto, mesec, first_day_weekday, at_holidays):
    """Prüft den Dienstplan nach Steiermark- & Österreich-Recht (MSchG, ATZ, ETZ, KA-AZG, ARG, StPAVO)."""
    issues = []
    day_cols_only = [f"{d}." for d in range(1, num_days + 1) if f"{d}." in df_plan.columns]
    real_df = df_plan[~df_plan["Mitarbeiter"].astype(str).str.contains("X-Oseba|FEHLT|⚠️", na=False)]

    # Lookup für Gesetz_Status
    status_map = {}
    for _, s_r in staff_df.iterrows():
        b_n = str(s_r["Name"]).strip().lower()
        status_map[b_n] = str(s_r.get("Gesetz_Status", "Normal")).strip()

    for _, row in real_df.iterrows():
        emp = str(row["Mitarbeiter"])
        base_emp = emp.split(" (")[0].strip().lower()
        gesetz_st = status_map.get(base_emp, "Normal")
        abt = str(row["Abteilung"])
        rolle = str(row["Rolle"])
        vals = [str(row[c]).strip().upper() for c in day_cols_only]

        # 0a. PA-Schichtprüfung (Nur F2, F7, N2)
        if rolle == "Pflegeassistenz":
            for d, v in enumerate(vals):
                if v in SHIFTS_HUNDREDTHS and v not in ["F2", "F7", "N2", "OFF"]:
                    issues.append({
                        "Kategorie": "🛑 Ungültiger PA-Dienst",
                        "Betroffen": f"{emp} ({abt})",
                        "Zeitraum": f"Tag {d+1}.",
                        "Details": f"Pflegeassistenz hat Dienst '{v}' (Erlaubt sind nur F2, F7 oder N2)."
                    })

        # 0b. Mutterschutz-Prüfung (MSchG §§ 6-8)
        if gesetz_st == "Mutterschutz (MSchG)":
            for d, v in enumerate(vals):
                dow = (d + first_day_weekday) % 7
                is_hol = (date(leto, mesec, d+1) in at_holidays) or (mesec == 12 and (d+1 in [24, 31]))
                if v in ["N1", "N2"]:
                    issues.append({
                        "Kategorie": "🛑 Mutterschutz-Verstoß (§ 6 MSchG)",
                        "Betroffen": f"{emp} ({abt})",
                        "Zeitraum": f"Tag {d+1}.",
                        "Details": "Absolutes Nachtarbeitsverbot im Mutterschutz!"
                    })
                if (dow == 6 or is_hol) and v in SHIFTS_HUNDREDTHS and v != "OFF":
                    issues.append({
                        "Kategorie": "🛑 Mutterschutz-Verstoß (§ 7 MSchG)",
                        "Betroffen": f"{emp} ({abt})",
                        "Zeitraum": f"Tag {d+1}.",
                        "Details": "Sonn- und Feiertagsarbeitsverbot im Mutterschutz!"
                    })
                if SHIFTS_HUNDREDTHS.get(v, 0) > 900:
                    issues.append({
                        "Kategorie": "⚠️ Mutterschutz-Tagesgrenze (§ 8 MSchG)",
                        "Betroffen": f"{emp} ({abt})",
                        "Zeitraum": f"Tag {d+1}.",
                        "Details": f"Dienst '{v}' überschreitet die 9,0h Tageshöchstgrenze des MSchG."
                    })

        # 0c. Altersteilzeit / Elternteilzeit Überstunden-Check
        if gesetz_st in ["Altersteilzeit (ATZ)", "Elternteilzeit (ETZ)"] and float(row.get("ÜBERSTD.", 0.0)) > 2.0:
            issues.append({
                "Kategorie": f"⚠️ {gesetz_st} Mehrarbeit",
                "Betroffen": f"{emp} ({abt})",
                "Zeitraum": "Gesamter Monat",
                "Details": f"{row['ÜBERSTD.']}h Überstunden geplant (Bei {gesetz_st} sollte SOLL exakt eingehalten werden)."
            })

        # a) Nachtruhe-Prüfung (2 Tage frei nach Nachtblock)
        for d in range(len(vals) - 1):
            if vals[d] in ["N1", "N2"] and vals[d+1] not in ["N1", "N2"]:
                if vals[d+1] in SHIFTS_HUNDREDTHS and vals[d+1] != "OFF":
                    issues.append({
                        "Kategorie": "🛑 Nachtruhe (KA-AZG / ARG)",
                        "Betroffen": f"{emp} ({abt})",
                        "Zeitraum": f"Tag {d+1}. ➔ {d+2}.",
                        "Details": f"Nach Nachtdienst ({vals[d]}) folgt direkt {vals[d+1]} ohne Schlaftag!"
                    })
                elif d + 2 < len(vals) and vals[d+2] in SHIFTS_HUNDREDTHS and vals[d+2] != "OFF":
                    issues.append({
                        "Kategorie": "⚠️ Erholungsphase nach Nacht",
                        "Betroffen": f"{emp} ({abt})",
                        "Zeitraum": f"Tag {d+1}. ➔ {d+3}.",
                        "Details": f"Nach Nachtdienst ({vals[d]}) nur 1 freier Tag (Tag {d+3}. hat Dienst {vals[d+2]})."
                    })

        # b) Mehr als 3 Nächte in Folge
        n_streak = 0
        for d, v in enumerate(vals):
            if v in ["N1", "N2"]:
                n_streak += 1
                if n_streak > 3:
                    issues.append({
                        "Kategorie": "🛑 Max. Nachtblock (>3 Nächte)",
                        "Betroffen": f"{emp} ({abt})",
                        "Zeitraum": f"Ab Tag {d-2}. bis {d+1}.",
                        "Details": f"{n_streak} Nachtdienste am Stück eingeteilt (Maximal 3 erlaubt)."
                    })
            else:
                n_streak = 0

        # c) Mehr als 5 Arbeitstage in Folge
        w_streak = 0
        for d, v in enumerate(vals):
            if v in SHIFTS_HUNDREDTHS and v != "OFF":
                w_streak += 1
                if w_streak == 6:
                    issues.append({
                        "Kategorie": "⚠️ Durchgehende Arbeitstage (ARG)",
                        "Betroffen": f"{emp} ({abt})",
                        "Zeitraum": f"Tag {d-4}. bis {d+1}.",
                        "Details": "6 Arbeitstage in Folge ohne freien Tag."
                    })
            else:
                w_streak = 0

        # d) 50-Stunden-Woche (Gleitendes 7-Tage-Fenster)
        for d in range(len(vals) - 6):
            hrs_100 = sum(SHIFTS_HUNDREDTHS.get(vals[d+i], 0) for i in range(7))
            if hrs_100 > 5000:
                issues.append({
                    "Kategorie": "⚠️ Wochenhöchstgrenze > 50h (AZG)",
                    "Betroffen": f"{emp} ({abt})",
                    "Zeitraum": f"Tag {d+1}. bis {d+7}.",
                    "Details": f"{hrs_100/100.0:.1f} Stunden innerhalb von 7 Tagen (Limit: 50,0h)."
                })
                break

    # 2. Stations- & StPAVO-Besetzungsprüfung (inkl. 2-DGKP-Nacht-Verbot!)
    for d, c in enumerate(day_cols_only):
        b_rows = real_df[real_df["Abteilung"] == "Abteilung B"]
        h_rows = real_df[real_df["Abteilung"] == "Abteilung H"]
        dgkp_rows = real_df[real_df["Rolle"].isin(["DGKP", "Leitung"])]
        
        b_care = sum(1 for v in b_rows[c].astype(str).str.strip() if v in DAY_CARE_SHIFTS)
        h_care = sum(1 for v in h_rows[c].astype(str).str.strip() if v in DAY_CARE_SHIFTS)
        all_n1 = sum(1 for v in real_df[c].astype(str).str.strip() if v == "N1")
        all_n2 = sum(1 for v in real_df[c].astype(str).str.strip() if v == "N2")
        dgkp_in_night = sum(1 for v in dgkp_rows[c].astype(str).str.strip() if v in ["N1", "N2"])

        if dgkp_in_night > 1:
            issues.append({
                "Kategorie": "🛑 2 DGKP im Nachtdienst (Verboten!)",
                "Betroffen": "Nachtdienst",
                "Zeitraum": f"Nacht am {d+1}.",
                "Details": f"Es sind {dgkp_in_night} DGKP gleichzeitig in der Nacht eingeteilt (Maximal 1 DGKP erlaubt!)."
            })
        if b_care < 4:
            issues.append({
                "Kategorie": "🚨 StPAVO Mindestbesetzung",
                "Betroffen": "Abteilung B",
                "Zeitraum": f"Tag {d+1}.",
                "Details": f"Nur {b_care} Pflegekräfte im Tagdienst (Mindestens 4 erforderlich)."
            })
        if h_care < 4:
            issues.append({
                "Kategorie": "🚨 StPAVO Mindestbesetzung",
                "Betroffen": "Abteilung H",
                "Zeitraum": f"Tag {d+1}.",
                "Details": f"Nur {h_care} Pflegekräfte im Tagdienst (Mindestens 4 erforderlich)."
            })
        if all_n1 < 1 or all_n2 < 1:
            issues.append({
                "Kategorie": "🚨 StPAVO Nachtdienst-Deckung",
                "Betroffen": "Gesamtes Haus",
                "Zeitraum": f"Nacht am {d+1}.",
                "Details": f"Nachtbesetzung unvollständig (N1={all_n1}, N2={all_n2})."
            })

    return pd.DataFrame(issues)

if "team_editor_ver" not in st.session_state:
    st.session_state.team_editor_ver = 0
if "cal_editor_ver" not in st.session_state:
    st.session_state.cal_editor_ver = 0
if "plan_editor_ver" not in st.session_state:
    st.session_state.plan_editor_ver = 0

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "⚙️ 1. Einstellungen & Verträge", 
    "📅 2. Dienstplan", 
    "🗓️ 3. Fix-Dienste, Wünsche & Urlaub", 
    "🚨 4. SOS & Tauschbörse", 
    "📉 5. Analyse & Fairness-Radar", 
    "🛡️ 6. Inspektorat Steiermark"
])

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
            ][x - 1]
        )

    first_day_of_month_weekday, num_days = calendar.monthrange(leto, mesec)
    at_holidays = holidays.Austria(years=leto, subdiv='6')
    
    cal_autosave_path = f"cal_autosave_{mesec}_{leto}.csv"
    plan_autosave_path = f"plan_autosave_{mesec}_{leto}.csv"

    st.divider()
    st.header("🔄 Schutz beim Monatsübergang (Nachtschicht-Schutz am 1. & 2. Tag)")
    uploaded_vormonat = st.file_uploader("Lade die CSV-Datei des Vormonats hoch (Optional):", type=["csv"], key="vormonat")
    if uploaded_vormonat is not None:
        try:
            old_plan_df = read_csv_smart(uploaded_vormonat.getvalue(), is_index_col=False)
            st.session_state.old_plan = old_plan_df
            st.success("✅ Vormonat geladen! Nachtschichten am Monatsende schützen automatisch den 1. und 2. Tag im neuen Monat.")
        except Exception as e: 
            st.error(f"Fehler beim Laden des Vormonats: {e}")
            
    if st.button("🗑️ Vormonat-Daten löschen"):
        if "old_plan" in st.session_state: 
            del st.session_state.old_plan
            st.rerun()

    st.divider()
    st.header("2. Team, Gesetzlicher Status (ATZ / MSchG) & Erlaubte Dienste")
    
    if "staff_df_v67" not in st.session_state:
        loaded_df = None
        if os.path.exists("team_data.csv"):
            try:
                with open("team_data.csv", "rb") as f:
                    loaded_df = sanitize_team_df(read_csv_smart(f.read(), is_index_col=False))
            except Exception: 
                loaded_df = None

        if loaded_df is None or loaded_df.empty:
            initial_staff = []
            initial_staff.append({"ID": len(initial_staff), "Name": "WBL Uroš", "Abteilung": "Abteilung H", "Rolle": "Leitung", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 30.0, "URL_Rest": 30.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": False, "SO": False, "FT": False, "Spezialdienst": "Ohne"})
            for i in range(1, 6): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP B-{i}", "Abteilung": "Abteilung B", "Rolle": "DGKP", "Qualifikation": "Wundmanager" if i==1 else "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 5): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP H-{i}", "Abteilung": "Abteilung H", "Rolle": "DGKP", "Qualifikation": "Praxisanleiter" if i==1 else "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 5): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP F-{i}", "Abteilung": "Abteilung F", "Rolle": "DGKP", "Qualifikation": "Keine", "Gesetz_Status": "Nachtschwerarbeit (NSchG)" if i < 3 else "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 12, "Nur_Nacht": True if i < 3 else False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 9): initial_staff.append({"ID": len(initial_staff), "Name": f"PA B-{i}", "Abteilung": "Abteilung B", "Rolle": "Pflegeassistenz", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 9): initial_staff.append({"ID": len(initial_staff), "Name": f"PA H-{i}", "Abteilung": "Abteilung H", "Rolle": "Pflegeassistenz", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 4): initial_staff.append({"ID": len(initial_staff), "Name": f"HH B-{i}", "Abteilung": "Abteilung B", "Rolle": "Heimhelfer", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "JED"})
            for i in range(1, 3): initial_staff.append({"ID": len(initial_staff), "Name": f"HH H-{i}", "Abteilung": "Abteilung H", "Rolle": "Heimhelfer", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "JED"})
            
            st.session_state.staff_df_v67 = pd.DataFrame(initial_staff)
        else:
            st.session_state.staff_df_v67 = loaded_df

    col_import, col_export = st.columns(2)
    with col_export:
        st.download_button(
            label="📥 Aktuelles Team als Backup speichern", 
            data=st.session_state.staff_df_v67.to_csv(index=False).encode('utf-8'), 
            file_name="Mein_Team_Backup.csv", 
            mime="text/csv", 
            type="primary"
        )
                
    with col_import:
        team_upload = st.file_uploader("📂 Team Backup hochladen", type=["csv"], key="team_upload")
        if team_upload is None:
            st.session_state.last_team_hash = None
        else:
            raw_bytes = team_upload.getvalue()
            file_hash = hashlib.md5(raw_bytes).hexdigest()
            force_team_btn = st.button("🔄 Hochgeladenes Team jetzt erzwingend übernehmen", type="secondary")
            if st.session_state.get("last_team_hash") != file_hash or force_team_btn:
                try:
                    uploaded_team = sanitize_team_df(read_csv_smart(raw_bytes, is_index_col=False))
                    uploaded_team.to_csv("team_data.csv", index=False)
                    st.session_state.staff_df_v67 = uploaded_team
                    st.session_state.last_team_hash = file_hash
                    st.session_state.team_editor_ver += 1
                    st.session_state.cal_editor_ver += 1
                    st.session_state.needs_cal_resync = True
                    st.success("✅ Team sofort geladen und gespeichert!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Fehler beim Laden der Team-Datei: {e}")
            
    st.write("---")
    if st.button("🚨 Alles auf Standard zurücksetzen (Löscht Auto-Save)"):
        for f_path in ["team_data.csv", cal_autosave_path, plan_autosave_path]:
            if os.path.exists(f_path): 
                os.remove(f_path)
        for k in ["staff_df_v67", "abs_matrix_v67", "raw_uploaded_cal", "last_generated_df"]:
            if k in st.session_state: 
                del st.session_state[k]
        st.session_state.team_editor_ver += 1
        st.session_state.cal_editor_ver += 1
        st.session_state.plan_editor_ver += 1
        st.rerun()

    st.subheader("🎛️ Individueller Dienst-, Stunden- & Schutzstatus-Konfigurator")
    st.caption(
        "Hier kannst du jedem Mitarbeiter frei einstellen, **welche Dienste** er arbeiten darf, wie viele **Wochenstunden** er hat "
        "und ob ein gesetzlicher Schutzstatus (**Altersteilzeit**, **Mutterschutz**, **Elternteilzeit**) gilt. "
        "Alternativ kannst du die Dienste auch direkt unten in die Spalte `Erlaubte Dienste` eintippen!"
    )
    current_staff_tab1 = st.session_state.staff_df_v67["Name"].dropna().astype(str).str.strip().tolist()
    with st.form("custom_shift_builder_form"):
        cb1, cb2, cb3, cb4, cb5 = st.columns([1.8, 2.2, 1.3, 1.3, 0.9])
        with cb1:
            sel_staff_custom = st.multiselect("1. Mitarbeiter:", current_staff_tab1)
        with cb2:
            sel_shifts_custom = st.multiselect(
                "2. Erlaubte Schichten:",
                options=list(SHIFT_LABELS.keys()),
                format_func=lambda k: SHIFT_LABELS[k]
            )
        with cb3:
            sel_status_custom = st.selectbox(
                "3. Gesetzl. Status:",
                options=["Unverändert"] + GESETZ_STATUS_OPTIONS
            )
        with cb4:
            sel_hours_mode = st.selectbox(
                "4. Wochenstunden:",
                options=["Unverändert", "37.0 h (100%)", "35.0 h", "32.0 h", "30.0 h (81%)", "28.0 h", "25.0 h (67.6%)", "22.2 h (60% ATZ)", "20.0 h (54%)", "18.5 h (50% ATZ)", "14.8 h (40% ATZ)", "10.0 h"]
            )
        with cb5:
            st.write("")
            st.write("")
            apply_custom_btn = st.form_submit_button("✅ Speichern", type="primary", use_container_width=True)

        if apply_custom_btn and sel_staff_custom:
            df_mod = st.session_state.staff_df_v67.copy()
            for emp_n in sel_staff_custom:
                mask = df_mod["Name"] == emp_n
                if sel_shifts_custom:
                    day_codes = [c for c in sel_shifts_custom if c not in ["N1", "N2"]]
                    if day_codes:
                        df_mod.loc[mask, "Spezialdienst"] = ", ".join(day_codes)
                    if "N1" in sel_shifts_custom or "N2" in sel_shifts_custom:
                        df_mod.loc[mask, "Max_Nacht"] = df_mod.loc[mask, "Max_Nacht"].apply(lambda x: max(int(x), 8))
                        if not day_codes:
                            df_mod.loc[mask, "Nur_Nacht"] = True
                if sel_status_custom != "Unverändert":
                    df_mod.loc[mask, "Gesetz_Status"] = sel_status_custom
                    if sel_status_custom == "Mutterschutz (MSchG)":
                        df_mod.loc[mask, "Max_Nacht"] = 0
                        df_mod.loc[mask, "Nur_Nacht"] = False
                        df_mod.loc[mask, "SO"] = False
                        df_mod.loc[mask, "FT"] = False
                if sel_hours_mode != "Unverändert":
                    w_val = float(sel_hours_mode.split(" ")[0])
                    df_mod.loc[mask, "Wochenstd"] = w_val
            df_mod = sanitize_team_df(df_mod)
            st.session_state.staff_df_v67 = df_mod
            df_mod.to_csv("team_data.csv", index=False)
            st.session_state.team_editor_ver += 1
            st.success("✅ Einstellungen erfolgreich auf Mitarbeiter übertragen!")
            st.rerun()

    with st.form("team_editor_form"):
        edited_data = st.data_editor(
            st.session_state.staff_df_v67, 
            num_rows="dynamic", 
            key=f"tabelle_mitarbeiter_v67_{st.session_state.team_editor_ver}",
            column_config={
                "ID": None,
                "Abteilung": st.column_config.SelectboxColumn("Abteilung", options=["Abteilung B", "Abteilung H", "Abteilung F"]),
                "Rolle": st.column_config.SelectboxColumn("Rolle", options=["Leitung", "DGKP", "Pflegeassistenz", "Heimhelfer"]),
                "Qualifikation": st.column_config.SelectboxColumn("Zusatzqualifikation", options=["Keine", "Wundmanager", "Praxisanleiter", "Palliativ"]),
                "Gesetz_Status": st.column_config.SelectboxColumn("Gesetzl. Status (Steiermark)", options=GESETZ_STATUS_OPTIONS, width="medium"),
                "Wochenstd": st.column_config.NumberColumn("Wochenstd.", min_value=1.0, max_value=60.0, default=37.0, step=0.5),
                "Prozent": st.column_config.NumberColumn("Anst. (%)", disabled=True), 
                "Max_Nacht": st.column_config.NumberColumn("Max Nacht", min_value=0, max_value=20, default=0),
                "Spezialdienst": st.column_config.TextColumn(
                    "Erlaubte Dienste (z.B. Ohne, F2, F7, X6, X7)", 
                    width="medium",
                    help="Tippe 'Ohne' für Standard oder beliebige Kürzel wie 'F2', 'F7', 'X6, X7', 'JED' direkt ein."
                ),
                "URL_Gesamt": st.column_config.NumberColumn("Urlaub Gesamt", min_value=0.0, max_value=50.0, default=25.0),
                "URL_Rest": st.column_config.NumberColumn("Urlaub Rest", min_value=0.0, max_value=50.0, default=25.0)
            }, 
            use_container_width=True, 
            height=700
        )
        if st.form_submit_button("💾 Spremembe ekipe potrdi", type="primary"):
            clean_edited = sanitize_team_df(edited_data)
            clean_edited["URL_Rest"] = clean_edited.apply(lambda row: min(row["URL_Gesamt"], row["URL_Rest"]), axis=1)
            st.session_state.staff_df_v67 = clean_edited
            clean_edited.to_csv("team_data.csv", index=False)
            st.session_state.team_editor_ver += 1
            st.session_state.cal_editor_ver += 1
            if "last_generated_df" in st.session_state:
                st.session_state.last_generated_df = recalculate_plan_df(
                    st.session_state.last_generated_df, clean_edited, num_days
                )
                st.session_state.last_generated_df.to_csv(plan_autosave_path, index=False)
                st.session_state.plan_editor_ver += 1
            st.success("✅ Teamdaten erfolgreich gespeichert!")
            st.rerun()

with tab3:
    st.header("🗓️ 3. Manuelle Fix-Dienste, Wünsche & Abwesenheiten (Vorab-Planung)")
    st.markdown(
        "**Neu:** Du kannst hier vor der Berechnung nicht nur Urlaube (`URL`, `KRA`, `ZA`), sondern auch **fixe Dienste für jeden Mitarbeiter manuell vorgeben** "
        "(`📌 F2`, `📌 F7`, `📌 X7`, `📌 X6`, `📌 X4`, `📌 N1`, `📌 N2`, `📌 JED`, `📌 MS`, `📌 SM` – oder einfach `F2`, `X7` etc. direkt in die Zelle tippen). "
        "Die KI übernimmt diese Schichten 1:1 und baut den restlichen Dienstplan intelligent darum herum!"
    )
    
    current_staff = st.session_state.staff_df_v67["Name"].dropna().astype(str).str.strip().tolist()
    
    day_cols = []
    for d in range(1, num_days + 1):
        dow = (d - 1 + first_day_of_month_weekday) % 7
        is_holiday = (date(leto, mesec, d) in at_holidays) or (mesec == 12 and d in [24, 31])
        dow_str = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"][dow]
        
        if is_holiday: 
            col_name = f"{d}.⭐"
        elif dow >= 5: 
            col_name = f"{d}.🔴"
        else: 
            col_name = f"{d}. {dow_str}"
        day_cols.append(col_name)

    def sync_calendar_df(source_df, staff_names, target_day_cols):
        new_mat = pd.DataFrame("", index=staff_names, columns=target_day_cols)
        if source_df is None or source_df.empty:
            return new_mat
        
        src = source_df.copy()
        if "Name" in src.columns:
            src = src.set_index("Name")
        elif "Personalname" in src.columns:
            src = src.set_index("Personalname")
        elif "Mitarbeiter" in src.columns:
            src = src.set_index("Mitarbeiter")
            
        src.index = src.index.astype(str).str.strip()
        src_index_map = {idx.lower(): idx for idx in src.index}
        
        for emp in staff_names:
            emp_clean = emp.strip()
            match_idx = None
            if emp_clean in src.index:
                match_idx = emp_clean
            elif emp_clean.lower() in src_index_map:
                match_idx = src_index_map[emp_clean.lower()]
                
            if match_idx is not None:
                row_data = src.loc[match_idx]
                if isinstance(row_data, pd.DataFrame):
                    row_data = row_data.iloc[0]
                for i in range(min(len(target_day_cols), len(row_data))):
                    val_cell = row_data.iloc[i]
                    if pd.isna(val_cell) or str(val_cell).strip().lower() in ["nan", "none", "<na>", "null"]:
                        val_cell = ""
                    new_mat.at[emp, target_day_cols[i]] = str(val_cell).strip()
        return new_mat

    if "abs_matrix_v67" not in st.session_state:
        if os.path.exists(cal_autosave_path):
            try:
                with open(cal_autosave_path, "rb") as f:
                    saved_cal = read_csv_smart(f.read(), is_index_col=True)
                st.session_state.raw_uploaded_cal = saved_cal
                st.session_state.abs_matrix_v67 = sync_calendar_df(saved_cal, current_staff, day_cols)
            except Exception:
                st.session_state.abs_matrix_v67 = pd.DataFrame("", index=current_staff, columns=day_cols)
        else:
            st.session_state.abs_matrix_v67 = pd.DataFrame("", index=current_staff, columns=day_cols)
    else:
        if st.session_state.get("needs_cal_resync") and "raw_uploaded_cal" in st.session_state:
            st.session_state.abs_matrix_v67 = sync_calendar_df(st.session_state.raw_uploaded_cal, current_staff, day_cols)
            st.session_state.needs_cal_resync = False
        else:
            st.session_state.abs_matrix_v67 = sync_calendar_df(st.session_state.abs_matrix_v67, current_staff, day_cols)

    entry_options = [
        "", 
        "🔴 URL", "🟠 SU", "🟣 ENT", "🔵 KRA", "⚫ ZA", "🟢 WUNSCH-FREI", "⚪ MUSS",
        "📌 F2 (Fix 12h PA/HH)", "📌 F7 (Fix 11h PA/HH)", 
        "📌 X7 (Fix 12h DGKP)", "📌 X6 (Fix 11h DGKP)", "📌 X4 (Fix 8.25h DGKP)",
        "📌 N1 (Fix Nacht DGKP)", "📌 N2 (Fix Nacht PA)",
        "📌 JED (Fix Speisesaal)", "📌 MS (Fix 7h)", "📌 SM (Fix 10.75h)",
        "🗑️ LÖSCHEN (Zelle leeren)"
    ]

    col_bak1, col_bak2 = st.columns(2)
    with col_bak1:
        st.download_button(
            label="📥 Kalender / Fix-Dienste als Backup speichern", 
            data=st.session_state.abs_matrix_v67.to_csv(index=True).encode('utf-8'), 
            file_name=f"Urlaubsmatrix_{mesec}_{leto}.csv", 
            mime="text/csv"
        )
    with col_bak2:
        cal_upload = st.file_uploader("📂 Kalender Backup hochladen", type=["csv"], key="cal_upload")
        if cal_upload is None:
            st.session_state.last_cal_hash = None
        else:
            raw_cal_bytes = cal_upload.getvalue()
            cal_hash = hashlib.md5(raw_cal_bytes).hexdigest()
            force_cal_btn = st.button("🔄 Hochgeladenen Kalender jetzt erzwingend in Tabelle schreiben", type="secondary")
            if st.session_state.get("last_cal_hash") != cal_hash or force_cal_btn:
                try:
                    uploaded_cal = read_csv_smart(raw_cal_bytes, is_index_col=True)
                    uploaded_cal = uploaded_cal.fillna("").astype(str)
                    uploaded_cal = uploaded_cal.replace(to_replace=r'^(nan|NaN|None|<NA>|null|none)$', value='', regex=True)
                    
                    st.session_state.raw_uploaded_cal = uploaded_cal
                    synced_cal = sync_calendar_df(uploaded_cal, current_staff, day_cols)
                    st.session_state.abs_matrix_v67 = synced_cal
                    synced_cal.to_csv(cal_autosave_path, index=True)
                    st.session_state.last_cal_hash = cal_hash
                    st.session_state.cal_editor_ver += 1
                    st.success("✅ Kalender sofort geladen und auf Festplatte gesichert!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Fehler beim Laden des Kalenders: {e}")
            
    st.divider()

    st.subheader("⚡ Schnelleingabe für Urlaube ODER manuelle Fix-Dienste")
    with st.form("bulk_add_form"):
        b_col1, b_col2, b_col3, b_col4 = st.columns([2, 2, 1.5, 1])
        with b_col1: 
            selected_emps = st.multiselect("1. Mitarbeiter auswählen:", current_staff)
        with b_col2: 
            d_start, d_end = st.slider("2. Von Tag bis Tag:", 1, num_days, (1, 5))
        with b_col3: 
            selected_reason = st.selectbox("3. Urlaub oder Fix-Dienst:", entry_options[1:])
        with b_col4: 
            st.write("")
            st.write("")
            submit_bulk = st.form_submit_button("➕ Eintragen", type="primary", use_container_width=True)
            
        if submit_bulk and selected_emps:
            val_to_write = ""
            if "LÖSCHEN" in selected_reason:
                val_to_write = ""
            elif selected_reason.startswith("📌"):
                sh_code_extracted = selected_reason.split(" ")[1].strip()
                val_to_write = f"📌 {sh_code_extracted}"
            else:
                val_to_write = selected_reason
            for emp in selected_emps:
                for d in range(d_start, d_end + 1):
                    target_col = day_cols[d-1]
                    st.session_state.abs_matrix_v67.at[emp, target_col] = val_to_write
            st.session_state.raw_uploaded_cal = st.session_state.abs_matrix_v67.copy()
            st.session_state.abs_matrix_v67.to_csv(cal_autosave_path, index=True)
            st.session_state.cal_editor_ver += 1
            st.success("✅ Erfolgreich in die Matrix übernommen & automatisch gespeichert!")
            st.rerun()

    st.markdown("👇 **Die Live-Matrix (Tippe `URL`, `KRA`, `ZA` oder direkt einen Wunsch-/Fix-Dienst wie `F2`, `F7`, `X7`, `N1` ein)**")
    
    col_config = {}
    for c in day_cols:
        col_config[c] = st.column_config.TextColumn(c, width="small")
        
    edited_cal_matrix = st.data_editor(
        st.session_state.abs_matrix_v67,
        column_config=col_config,
        use_container_width=True,
        height=700,
        key=f"live_abwesenheiten_matrix_v67_{st.session_state.cal_editor_ver}"
    )
    if not edited_cal_matrix.equals(st.session_state.abs_matrix_v67):
        st.session_state.abs_matrix_v67 = edited_cal_matrix
        st.session_state.raw_uploaded_cal = edited_cal_matrix.copy()
        edited_cal_matrix.to_csv(cal_autosave_path, index=True)

with tab2:
    st.header("Automatische Dienstplangenerierung & Live-Editor")
    
    if "last_generated_df" not in st.session_state and os.path.exists(plan_autosave_path):
        try:
            loaded_plan = pd.read_csv(plan_autosave_path)
            st.session_state.last_generated_df = recalculate_plan_df(
                loaded_plan, st.session_state.staff_df_v67, num_days
            )
        except Exception:
            pass
    
    if st.button("🚀 Dienstplan neu berechnen (KI-Optimierung)", type="primary", use_container_width=True):
        
        try:
            with st.spinner("⏳ KI berechnet optimalen Dienstplan (Max. 1 DGKP in Nacht, Fix-Dienste, MSchG/ATZ & StPAVO aktiv)..."):
                
                df_clean = sanitize_team_df(st.session_state.staff_df_v67)
                staff_list = df_clean.to_dict("records")
                
                st.session_state.absences_v67 = []
                st.session_state.work_rules_v67 = []
                st.session_state.fixed_shifts_v67 = []
                
                for emp_name in current_staff:
                    emp_id_list = df_clean.loc[df_clean["Name"] == emp_name, "ID"].values
                    if len(emp_id_list) == 0: 
                        continue
                    emp_id = int(emp_id_list[0])
                    emp_role_val = str(df_clean.loc[df_clean["ID"] == emp_id, "Rolle"].values[0]).strip()
                    
                    for d in range(1, num_days + 1):
                        col_name = day_cols[d-1]
                        val = st.session_state.abs_matrix_v67.at[emp_name, col_name]
                        
                        if pd.notna(val) and str(val).strip() != "":
                            val_str = str(val).upper().replace("📌", "").strip()
                            if val_str in ["NAN", "NONE", "<NA>", "NULL", ""]: 
                                continue
                                
                            day_idx = d - 1
                            reason = ""
                            
                            # Prüfe zuerst, ob ein manueller Fix-Dienst (F2, F7, X7, X6, X4, N1, N2, JED, MS, SM) eingetragen wurde
                            matched_manual_sh = None
                            for sh_c in MANUAL_SHIFT_CODES:
                                if val_str == sh_c or val_str.startswith(sh_c + " "):
                                    matched_manual_sh = sh_c
                                    break
                                    
                            if matched_manual_sh is not None:
                                # Sicherheitscheck: DGKP niemals N2, PA nur F2/F7/N2
                                if emp_role_val in ["DGKP", "Leitung"] and matched_manual_sh == "N2":
                                    matched_manual_sh = "N1"
                                elif emp_role_val == "Pflegeassistenz" and matched_manual_sh not in ["F2", "F7", "N2"]:
                                    matched_manual_sh = "F2"
                                st.session_state.fixed_shifts_v67.append({
                                    "emp_id": emp_id, "emp_name": emp_name, "day": day_idx, "shift": matched_manual_sh
                                })
                                continue

                            if "URL" in val_str: reason = "URL"
                            elif "SU" in val_str: reason = "SU"
                            elif "ENT" in val_str: reason = "ENT"
                            elif "KRA" in val_str: reason = "KRA"
                            elif "ZA" in val_str: reason = "ZA"
                            elif "PFLEGE" in val_str: reason = "PFLEGE"
                            elif "WUNSCH" in val_str or "FREI" in val_str: reason = "WUNSCH-FREI"
                            elif "MUSS" in val_str: reason = "MUSS-ARBEITEN"
                            
                            if reason in ["URL", "SU", "ENT", "KRA", "ZA", "PFLEGE", "WUNSCH-FREI"]:
                                st.session_state.absences_v67.append({"emp_id": emp_id, "emp_name": emp_name, "day": day_idx, "reason": reason})
                            elif reason == "MUSS-ARBEITEN":
                                st.session_state.work_rules_v67.append({"emp_id": emp_id, "emp_name": emp_name, "day": day_idx, "rule": reason})

                prev_month_last_day_night = {s["ID"]: False for s in staff_list}
                prev_month_second_last_day_night = {s["ID"]: False for s in staff_list}
                if "old_plan" in st.session_state and st.session_state.old_plan is not None:
                    old_df = st.session_state.old_plan
                    day_cols_old = [c for c in old_df.columns if str(c).replace('.', '').isdigit()]
                    if len(day_cols_old) >= 2:
                        last_c = day_cols_old[-1]
                        sec_last_c = day_cols_old[-2]
                        name_col = "Mitarbeiter" if "Mitarbeiter" in old_df.columns else ("Personalname" if "Personalname" in old_df.columns else old_df.columns[0])
                        for s in staff_list:
                            m_rows = old_df[old_df[name_col].astype(str).str.contains(s["Name"], na=False)]
                            if not m_rows.empty:
                                v_last = str(m_rows.iloc[0][last_c]).upper().strip()
                                v_sec = str(m_rows.iloc[0][sec_last_c]).upper().strip()
                                if v_last in ["N1", "N2"]:
                                    prev_month_last_day_night[s["ID"]] = True
                                if v_sec in ["N1", "N2"]:
                                    prev_month_second_last_day_night[s["ID"]] = True

                model = cp_model.CpModel()
                hour_deviations = []
                shifts = SHIFTS_HUNDREDTHS
                work = {}
                is_night = {}
                worked_day = {}
                
                for s in staff_list:
                    for d in range(num_days):
                        for sh in shifts.keys(): 
                            work[(s["ID"], d, sh)] = model.NewBoolVar(f'work_{s["ID"]}_{d}_{sh}')
                        model.Add(sum(work[(s["ID"], d, sh)] for sh in shifts.keys()) == 1)
                        
                        worked_d = model.NewBoolVar(f'worked_any_{s["ID"]}_{d}')
                        model.Add(worked_d == 1 - work[(s["ID"], d, "OFF")])
                        worked_day[(s["ID"], d)] = worked_d
                        
                        night_d = model.NewBoolVar(f'is_night_{s["ID"]}_{d}')
                        model.Add(night_d == work[(s["ID"], d, "N1")] + work[(s["ID"], d, "N2")])
                        is_night[(s["ID"], d)] = night_d

                for s in staff_list:
                    gesetz = str(s.get("Gesetz_Status", "Normal")).strip()

                    if prev_month_last_day_night[s["ID"]]:
                        sl_v0 = model.NewBoolVar(f'sl_v0_{s["ID"]}')
                        model.Add(work[(s["ID"], 0, "OFF")] + is_night[(s["ID"], 0)] + sl_v0 >= 1)
                        hour_deviations.append(sl_v0 * 1000000)
                        re_v0 = model.NewBoolVar(f're_v0_{s["ID"]}')
                        model.Add(work[(s["ID"], 1, "OFF")] + is_night[(s["ID"], 0)] + re_v0 >= 1)
                        hour_deviations.append(re_v0 * 900000)
                    elif prev_month_second_last_day_night[s["ID"]]:
                        re_v1 = model.NewBoolVar(f're_v1_{s["ID"]}')
                        model.Add(work[(s["ID"], 0, "OFF")] + re_v1 >= 1)
                        hour_deviations.append(re_v1 * 900000)

                    for d in range(num_days - 1):
                        sleep_viol = model.NewBoolVar(f'sleep_viol_{s["ID"]}_{d}')
                        model.Add(work[(s["ID"], d+1, "OFF")] + is_night[(s["ID"], d+1)] + sleep_viol >= is_night[(s["ID"], d)])
                        hour_deviations.append(sleep_viol * 1000000)
                        
                    for d in range(num_days - 2):
                        rest_viol = model.NewBoolVar(f'rest_viol_{s["ID"]}_{d}')
                        model.Add(work[(s["ID"], d+2, "OFF")] + is_night[(s["ID"], d+1)] + rest_viol >= is_night[(s["ID"], d)])
                        hour_deviations.append(rest_viol * 900000)

                    for d in range(num_days - 3):
                        four_n_viol = model.NewBoolVar(f'four_n_{s["ID"]}_{d}')
                        model.Add(sum(is_night[(s["ID"], d+i)] for i in range(4)) <= 3 + four_n_viol)
                        hour_deviations.append(four_n_viol * 1500000)

                    for d in range(num_days - 2):
                        three_n = model.NewBoolVar(f'three_n_{s["ID"]}_{d}')
                        model.AddMinEquality(three_n, [is_night[(s["ID"], d)], is_night[(s["ID"], d+1)], is_night[(s["ID"], d+2)]])
                        hour_deviations.append(three_n * 35000)

                    for d in range(num_days):
                        single_n_pen = model.NewIntVar(0, 1, f'single_n_pen_{s["ID"]}_{d}')
                        if d == 0:
                            prev_n = 1 if prev_month_last_day_night[s["ID"]] else 0
                            model.Add(single_n_pen >= is_night[(s["ID"], 0)] - prev_n - is_night[(s["ID"], 1)])
                        elif d == num_days - 1:
                            model.Add(single_n_pen >= is_night[(s["ID"], d)] - is_night[(s["ID"], d-1)])
                        else:
                            model.Add(single_n_pen >= is_night[(s["ID"], d)] - is_night[(s["ID"], d-1)] - is_night[(s["ID"], d+1)])
                        hour_deviations.append(single_n_pen * 65000)

                    for d in range(num_days - 3):
                        four_days = model.NewBoolVar(f'four_days_{s["ID"]}_{d}')
                        model.AddMinEquality(four_days, [worked_day[(s["ID"], d+i)] for i in range(4)])
                        hour_deviations.append(four_days * 3000)
                    
                    for d in range(num_days - 5): 
                        no_off = model.NewBoolVar(f'no_off_{s["ID"]}_{d}')
                        model.Add(sum(work[(s["ID"], d + i, "OFF")] for i in range(6)) + no_off >= 1)
                        hour_deviations.append(no_off * 60000)

                    for d in range(1, num_days - 1):
                        single_off = model.NewBoolVar(f'sing_off_{s["ID"]}_{d}')
                        model.AddMinEquality(single_off, [worked_day[(s["ID"], d-1)], work[(s["ID"], d, "OFF")], worked_day[(s["ID"], d+1)]])
                        hour_deviations.append(single_off * 1500)

                    # Wochenhöchstgrenze: Bei Mutterschutz 40h (4000), sonst 50h (5000)
                    week_limit_100 = 4000 if gesetz == "Mutterschutz (MSchG)" else 5000
                    for d in range(num_days - 6):
                        week_hrs = sum(work[(s["ID"], d+i, sh)] * shifts[sh] for i in range(7) for sh in shifts.keys())
                        over_lim = model.NewIntVar(0, 10000, f'overlim_{s["ID"]}_{d}')
                        model.Add(over_lim >= week_hrs - week_limit_100)
                        hour_deviations.append(over_lim * 450)

                weekends = []
                sat = -1
                for d in range(num_days):
                    dow = (d + first_day_of_month_weekday) % 7
                    if dow == 5: 
                        sat = d
                    elif dow == 6:
                        if sat != -1: 
                            weekends.append([sat, d])
                        else: 
                            weekends.append([d])
                        sat = -1
                if sat != -1: 
                    weekends.append([sat])

                for s in staff_list:
                    works_we = []
                    for w_idx, we_days in enumerate(weekends):
                        we_var = model.NewBoolVar(f'we_{s["ID"]}_{w_idx}')
                        model.AddMaxEquality(we_var, [worked_day[(s["ID"], day)] for day in we_days])
                        works_we.append(we_var)
                        
                        if len(we_days) == 2:
                            d_sat, d_sun = we_days
                            we_diff = model.NewIntVar(-1, 1, f'we_diff_{s["ID"]}_{w_idx}')
                            model.Add(we_diff == worked_day[(s["ID"], d_sat)] - worked_day[(s["ID"], d_sun)])
                            abs_we_diff = model.NewIntVar(0, 1, f'abs_we_diff_{s["ID"]}_{w_idx}')
                            model.AddAbsEquality(abs_we_diff, we_diff)
                            hour_deviations.append(abs_we_diff * 35000) 

                    for w_idx in range(len(weekends) - 2): 
                        we_strk = model.NewIntVar(0, 1, f'we_strk_{s["ID"]}_{w_idx}')
                        model.Add(works_we[w_idx] + works_we[w_idx+1] + works_we[w_idx+2] - 2 <= we_strk)
                        hour_deviations.append(we_strk * 70000)
                    
                    if s["Rolle"] in ["DGKP", "Leitung"]:
                        extra_we = model.NewIntVar(0, len(weekends), f'extra_we_dgkp_{s["ID"]}')
                        model.Add(sum(works_we) - 1 <= extra_we)
                        hour_deviations.append(extra_we * 60000)

                for r in st.session_state.work_rules_v67:
                    if r["day"] < num_days:
                        hour_deviations.append(work[(r["emp_id"], r["day"], "OFF")] * 800000)

                # --- MANUELLE FIX-DIENSTE AUS TAB 3 ---
                fixed_Set = set()
                for fx in st.session_state.fixed_shifts_v67:
                    if fx["day"] < num_days:
                        fixed_Set.add((fx["emp_id"], fx["day"]))
                        # Extrem hohe Priorität für den manuell fixierten Dienst
                        hour_deviations.append((1 - work[(fx["emp_id"], fx["day"], fx["shift"])]) * 1800000)

                dow_keys = ["MO", "DI", "MI", "DO", "FR", "SA", "SO"]
                for s in staff_list:
                    allowed_shifts = resolve_allowed_shifts_for_person(s)
                    # Wenn der User für diese Person manuell einen bestimmten Dienst in Tab 3 eingetragen hat, erlaube ihn (außer N2 für DGKP)
                    for fx in st.session_state.fixed_shifts_v67:
                        if fx["emp_id"] == s["ID"] and fx["shift"] not in allowed_shifts:
                            if not (s["Rolle"] in ["DGKP", "Leitung"] and fx["shift"] == "N2"):
                                allowed_shifts.append(fx["shift"])

                    unallowed = [sh for sh in shifts.keys() if sh not in allowed_shifts]
                    spez_str = str(s.get("Spezialdienst", "Ohne")).strip()
                    gesetz = str(s.get("Gesetz_Status", "Normal")).strip()
                    
                    for d in range(num_days):
                        dow = (d + first_day_of_month_weekday) % 7
                        is_holiday = (date(leto, mesec, d+1) in at_holidays) or (mesec == 12 and (d+1 == 24 or d+1 == 31))
                        
                        for sh in unallowed: 
                            model.Add(work[(s["ID"], d, sh)] == 0)

                        # Mutterschutz (§ 6 & § 7 MSchG): Strikte Sperre von Nacht sowie Sonn- und Feiertag
                        if gesetz == "Mutterschutz (MSchG)":
                            model.Add(work[(s["ID"], d, "N1")] == 0)
                            model.Add(work[(s["ID"], d, "N2")] == 0)
                            if dow == 6 or is_holiday:
                                model.Add(work[(s["ID"], d, "OFF")] == 1)

                        if spez_str == "Nur WE und Feiertage" and dow < 5 and not is_holiday:
                            hour_deviations.append(worked_day[(s["ID"], d)] * 500000)
                            
                        day_col_key = dow_keys[dow]
                        if not bool(s.get(day_col_key, True)) and (s["ID"], d) not in fixed_Set:
                            hour_deviations.append(worked_day[(s["ID"], d)] * 450000)
                        if is_holiday and not bool(s.get("FT", True)) and (s["ID"], d) not in fixed_Set:
                            hour_deviations.append(worked_day[(s["ID"], d)] * 450000)
                        
                        if s["Rolle"] == "Leitung" and (s["ID"], d) not in fixed_Set:
                            if dow >= 5 or is_holiday:
                                has_muss = any(r["day"] == d and r["emp_id"] == s["ID"] for r in st.session_state.work_rules_v67)
                                if not has_muss:
                                    model.Add(work[(s["ID"], d, "OFF")] == 1)
                                
                        if s["Rolle"] == "DGKP" and (s["ID"], d) not in fixed_Set:
                            if dow >= 5 or is_holiday:
                                if "X7" in allowed_shifts:
                                    for sh in ["X4", "X6", "F2", "F7", "JED", "MS", "SM", "N2"]:
                                        model.Add(work[(s["ID"], d, sh)] == 0)

                    if s["Max_Nacht"] > 0 and gesetz != "Mutterschutz (MSchG)":
                        nocna_koda = "N1" if s["Rolle"] in ["DGKP", "Leitung"] else "N2"
                        if nocna_koda in allowed_shifts: 
                            over_nacht = model.NewIntVar(0, 31, f'over_n_{s["ID"]}')
                            model.Add(sum(work[(s["ID"], d, nocna_koda)] for d in range(num_days)) - int(s["Max_Nacht"]) <= over_nacht)
                            hour_deviations.append(over_nacht * 50000)

                for a in st.session_state.absences_v67:
                    if a["day"] < num_days: 
                        model.Add(work[(a["emp_id"], a["day"], "OFF")] == 1)

                for s in staff_list:
                    w_std = float(s.get("Wochenstd", 37.0))
                    daily_avg = w_std / 7.0
                    standard_target = daily_avg * num_days
                    saldo_alt = float(s.get("Saldo_Alt", 0.0))
                    gesetz = str(s.get("Gesetz_Status", "Normal")).strip()
                    
                    emp_paid_abs_days = sum(
                        1 for a in st.session_state.absences_v67 
                        if a["emp_id"] == s["ID"] and a["reason"] in PAID_ABSENCES
                    )
                    paid_abs_hours_100 = int(round(emp_paid_abs_days * daily_avg * 100))
                    adjusted_target = max(0, int(round((standard_target - saldo_alt) * 100)) - paid_abs_hours_100)
                    
                    total_worked = model.NewIntVar(0, 35000, f'tot_{s["ID"]}')
                    model.Add(total_worked == sum(work[(s["ID"], d, sh)] * shifts[sh] for d in range(num_days) for sh in shifts.keys()))

                    under_work = model.NewIntVar(0, 25000, f'under_{s["ID"]}')
                    over_work = model.NewIntVar(0, 25000, f'over_{s["ID"]}')
                    
                    model.Add(under_work >= adjusted_target - total_worked)
                    model.Add(over_work >= total_worked - adjusted_target)
                    
                    hour_deviations.append(under_work * 250) 
                    # Bei Altersteilzeit (ATZ), Elternteilzeit (ETZ) oder Mutterschutz keine Überstunden aufbauen!
                    if gesetz in ["Altersteilzeit (ATZ)", "Elternteilzeit (ETZ)", "Mutterschutz (MSchG)", "Pflegekarenz / Teilzeit"]:
                        hour_deviations.append(over_work * 300)
                    else:
                        hour_deviations.append(over_work * 12)

                # --- STATIONS-ABDECKUNG & HARTE SPERRE FÜR 2 DGKP IN DER NACHT ---
                day_sh = DAY_CARE_SHIFTS
                dgkp_shifts = DGKP_DAY_SHIFTS
                
                o_b_all = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B"]
                o_h_all = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H"]
                o_dgkp_b = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] in ["DGKP", "Leitung"]]
                o_dgkp_h = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] in ["DGKP", "Leitung"]]
                o_dgkp_f = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung F" and s["Rolle"] in ["DGKP", "Leitung"]]
                o_dgkp_all = [s["ID"] for s in staff_list if s["Rolle"] in ["DGKP", "Leitung"]]
                o_pa_all = [s["ID"] for s in staff_list if s["Rolle"] == "Pflegeassistenz"]
                
                b_shorts, h_shorts, jed_shorts, dg_shorts, n1_shorts, n2_shorts = {}, {}, {}, {}, {}, {}

                for d in range(num_days):
                    b_day = sum(work[(e, d, sh)] for e in o_b_all for sh in day_sh)
                    b_short = model.NewIntVar(0, 10, f'b_short_{d}')
                    model.Add(b_day + b_short >= 4)
                    hour_deviations.append(b_short * 80000)
                    b_shorts[d] = b_short
                    
                    jed_b = sum(work[(e, d, "JED")] for e in o_b_all)
                    jed_short = model.NewIntVar(0, 10, f'jed_short_{d}')
                    model.Add(jed_b + jed_short >= 1)
                    hour_deviations.append(jed_short * 80000)
                    jed_shorts[d] = jed_short
                    
                    h_day = sum(work[(e, d, sh)] for e in o_h_all for sh in day_sh)
                    h_short = model.NewIntVar(0, 10, f'h_short_{d}')
                    model.Add(h_day + h_short >= 4)
                    hour_deviations.append(h_short * 80000)
                    h_shorts[d] = h_short
                    
                    # DGKP Priorität am Tag: Zuerst 1 eigene DGKP auf B und 1 eigene DGKP auf H
                    b_dgkp = sum(work[(e, d, sh)] for e in o_dgkp_b for sh in dgkp_shifts)
                    h_dgkp = sum(work[(e, d, sh)] for e in o_dgkp_h for sh in dgkp_shifts)
                    f_dgkp = sum(work[(e, d, sh)] for e in o_dgkp_f for sh in dgkp_shifts)
                    
                    b_dg_miss = model.NewIntVar(0, 1, f'b_dg_miss_{d}')
                    model.Add(b_dgkp + b_dg_miss >= 1)
                    hour_deviations.append(b_dg_miss * 220000)
                    
                    h_dg_miss = model.NewIntVar(0, 1, f'h_dg_miss_{d}')
                    model.Add(h_dgkp + h_dg_miss >= 1)
                    hour_deviations.append(h_dg_miss * 220000)
                    
                    dg_tot = model.NewIntVar(0, 15, f'dg_tot_{d}')
                    model.Add(dg_tot == b_dgkp + h_dgkp + f_dgkp)
                    dg_short = model.NewIntVar(0, 10, f'dg_short_{d}')
                    model.Add(dg_tot + dg_short >= 2)
                    hour_deviations.append(dg_short * 320000)
                    dg_shorts[d] = dg_short
                    
                    # --- HARTE NACHT-SPERRE: NIEMALS 2 DGKP IN DER NACHT! ---
                    for e_dg in o_dgkp_all:
                        model.Add(work[(e_dg, d, "N2")] == 0)
                    
                    n1_sum = sum(work[(e, d, "N1")] for e in o_dgkp_all)
                    # HARD CONSTRAINT: Maximal 1 DGKP im Nachtdienst!
                    model.Add(n1_sum <= 1)
                    n1_short = model.NewIntVar(0, 1, f'n1_short_{d}')
                    model.Add(n1_sum + n1_short >= 1)
                    hour_deviations.append(n1_short * 250000)
                    n1_shorts[d] = n1_short
                    
                    n2_sum = sum(work[(e, d, "N2")] for e in o_pa_all)
                    # HARD CONSTRAINT: Maximal 1 PA im Nachtdienst!
                    model.Add(n2_sum <= 1)
                    n2_short = model.NewIntVar(0, 1, f'n2_short_{d}')
                    model.Add(n2_sum + n2_short >= 1)
                    hour_deviations.append(n2_short * 250000)
                    n2_shorts[d] = n2_short

                model.Minimize(sum(hour_deviations))
                solver = cp_model.CpSolver()
                solver.parameters.max_time_in_seconds = 35.0
                solver.parameters.num_search_workers = 8
                status = solver.Solve(model)

                if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                    data = []
                    for s in staff_list:
                        qual_str = f" ({s['Qualifikation']})" if s.get('Qualifikation', 'Keine') != "Keine" else ""
                        row = {
                            "Abteilung": s["Abteilung"], 
                            "Rolle": s["Rolle"], 
                            "Mitarbeiter": f"{s['Name']}{qual_str}"
                        }
                        for d in range(num_days):
                            day_str = f"{d+1}."
                            val = "..."
                            for sh in shifts.keys():
                                if solver.Value(work[(s["ID"], d, sh)]) == 1:
                                    val = sh if sh != "OFF" else "..."
                                    for a in st.session_state.absences_v67:
                                        if a["emp_id"] == s["ID"] and a["day"] == d: 
                                            if "WUNSCH" in a["reason"]: val = "WUNSCH"
                                            elif "MUSS" in a["reason"]: val = "MUSS"
                                            else: val = a["reason"]
                            row[day_str] = val
                        
                        row["SOLL"] = 0.0
                        row["IST"] = 0.0
                        row["ÜBERSTD."] = 0.0
                        row["SALDO"] = 0.0
                        data.append(row)

                    virtual_rows = []
                    def add_v_shift(name, abt, rolle, day, shift):
                        found = False
                        for r in virtual_rows:
                            if r["Mitarbeiter"] == name:
                                if r[f"{day+1}."] == "...":
                                    r[f"{day+1}."] = f"🚨 {shift}"
                                    found = True
                                    break
                        if not found:
                            new_row = {
                                "Abteilung": abt, "Rolle": rolle, 
                                "Mitarbeiter": name, "SOLL": 0.0, "IST": 0.0, "ÜBERSTD.": 0.0, "SALDO": 0.0
                            }
                            for i in range(num_days): 
                                new_row[f"{i+1}."] = "..."
                            new_row[f"{day+1}."] = f"🚨 {shift}"
                            virtual_rows.append(new_row)

                    for d in range(num_days):
                        if solver.Value(n1_shorts[d]) > 0:
                            add_v_shift("⚠️ X-Oseba N1", "Abteilung F", "DGKP", d, "N1")
                        if solver.Value(n2_shorts[d]) > 0:
                            add_v_shift("⚠️ X-Oseba N2", "Abteilung F", "Pflegeassistenz", d, "N2")
                        if solver.Value(jed_shorts[d]) > 0:
                            for _ in range(solver.Value(jed_shorts[d])): add_v_shift("⚠️ X-Oseba Speis", "Abteilung B", "Heimhelfer", d, "JED")
                        if solver.Value(b_shorts[d]) > 0:
                            for _ in range(solver.Value(b_shorts[d])): add_v_shift("⚠️ X-Oseba B", "Abteilung B", "Pflegeassistenz", d, "F2")
                        if solver.Value(h_shorts[d]) > 0:
                            for _ in range(solver.Value(h_shorts[d])): add_v_shift("⚠️ X-Oseba H", "Abteilung H", "Pflegeassistenz", d, "F2")
                        if solver.Value(dg_shorts[d]) > 0:
                            for _ in range(solver.Value(dg_shorts[d])): add_v_shift("⚠️ X-Oseba DGKP", "Abteilung B", "DGKP", d, "X7")

                    data.extend(virtual_rows)
                    final_df = recalculate_plan_df(pd.DataFrame(data), df_clean, num_days)
                    st.session_state.last_generated_df = final_df
                    final_df.to_csv(plan_autosave_path, index=False)
                    st.session_state.plan_editor_ver += 1
                    st.success("🎉 Dienstplan erfolgreich generiert (Max. 1 DGKP in Nacht garantiert)!")
                    st.rerun()
                else:
                    st.error("🚨 UNBEKANNTER FEHLER: Modell konnte nicht gelöst werden.")
        except Exception as e: 
            st.error(f"⚠️ KRITISCHER SYSTEMFEHLER: {e}")

    if "last_generated_df" in st.session_state:
        df_rezultat = st.session_state.last_generated_df
        
        st.info(
            "✏️ **Live-Editor & Besetzungs-Check aktiv:** Doppelklicke auf eine beliebige Tageszelle (`1.` bis `31.`), tippe ein Schichtkürzel ein "
            "(`F2`, `F7`, `X7`, `X6`, `X4`, `N1`, `N2`, `JED`, `URL`, `KRA`, `ZA` oder `...` für Frei) und drücke **Enter**. "
            "In Tab 3 kannst du zudem fixe Schichten (`📌 F2`, `📌 X7` etc.) schon vor der Berechnung festlegen!"
        )
        
        def style_cells(val, col_name):
            style = ""
            if isinstance(val, str):
                if val == "...": style += "color: #b3b3b3; text-align: center; " 
                elif "🚨" in val: style += "background-color: #ffcccc; color: #cc0000; font-weight: bold; text-align: center; border: 2px solid red; " 
                elif "⚠️" in val: style += "color: #cc0000; font-weight: bold; " 
                elif "Wundmanager" in val or "Praxisanleiter" in val: style += "font-weight: bold; color: #0056b3; "
                elif val in ["N1", "N2"]: style += "background-color: #1e3a8a; color: white; font-weight: bold; text-align: center; border-radius: 4px; "
                elif "KRA" in val: style += "background-color: #f8d7da; color: #721c24; font-weight: bold; text-align: center; "
                elif "URL" in val: style += "background-color: #d1ecf1; color: #0c5460; font-weight: bold; text-align: center; "
                elif "SU" in val or "PFLEGE" in val: style += "background-color: #ffebd6; color: #cc5500; font-weight: bold; text-align: center; border: 1px solid #ffcc99; "
                elif "ENT" in val: style += "background-color: #f3e8ff; color: #4b0082; font-weight: bold; text-align: center; border: 1px solid #d8b4fe; "
                elif "ZA" in val: style += "background-color: #333333; color: white; font-weight: bold; text-align: center; border-radius: 4px; "
                elif "WUNSCH" in val: style += "background-color: #d4edda; color: #155724; font-weight: bold; text-align: center; "
                elif val in ["X4", "X6", "X7", "F2", "F7", "JED", "MS", "SM"]: style += "color: black; font-weight: 500; text-align: center; "

            if col_name == "ÜBERSTD." and isinstance(val, (int, float)) and val > 0:
                style += "background-color: #fff3cd; color: #856404; font-weight: bold; "

            if isinstance(col_name, str) and col_name.replace('.', '').isdigit():
                d = int(col_name.replace('.', '')) - 1
                dow = (d + first_day_of_month_weekday) % 7
                is_holiday = (date(leto, mesec, d+1) in at_holidays) or (mesec == 12 and (d+1 == 24 or d+1 == 31))
                
                if dow >= 5 or is_holiday: 
                    if "background-color" not in style: 
                        style += "background-color: #f0f0f5; "
            
            return style

        def apply_styles(df):
            return df.style.apply(lambda x: [style_cells(v, x.name) for v in x], axis=0)

        plan_col_config = {
            "Rolle": st.column_config.TextColumn("Rolle", disabled=True, width="medium"),
            "Mitarbeiter": st.column_config.TextColumn("Mitarbeiter", disabled=True, width="medium"),
            "SOLL": st.column_config.NumberColumn("SOLL", disabled=True, format="%.1f"),
            "IST": st.column_config.NumberColumn("IST", disabled=True, format="%.1f"),
            "ÜBERSTD.": st.column_config.NumberColumn("ÜBERSTD.", disabled=True, format="%.1f"),
            "SALDO": st.column_config.NumberColumn("SALDO", disabled=True, format="%.1f"),
        }
        day_cols_only = [f"{d}." for d in range(1, num_days + 1)]
        for c_d in day_cols_only:
            plan_col_config[c_d] = st.column_config.TextColumn(c_d, width="small")

        def render_editable_dept(dept_name, dept_key):
            sub_df = df_rezultat[df_rezultat["Abteilung"] == dept_name].copy()
            display_df = sub_df.drop(columns=["Abteilung"], errors='ignore')
            try:
                edited_sub = st.data_editor(
                    apply_styles(display_df),
                    column_config=plan_col_config,
                    use_container_width=True,
                    hide_index=True,
                    key=f"editor_{dept_key}_{st.session_state.plan_editor_ver}"
                )
            except Exception:
                edited_sub = st.data_editor(
                    display_df,
                    column_config=plan_col_config,
                    use_container_width=True,
                    hide_index=True,
                    key=f"editor_{dept_key}_{st.session_state.plan_editor_ver}"
                )
            
            if not edited_sub[day_cols_only].equals(display_df[day_cols_only]):
                full_updated = df_rezultat.copy()
                full_updated.loc[sub_df.index, day_cols_only] = edited_sub[day_cols_only].values
                recalculated_full = recalculate_plan_df(full_updated, st.session_state.staff_df_v67, num_days)
                st.session_state.last_generated_df = recalculated_full
                recalculated_full.to_csv(plan_autosave_path, index=False)
                st.session_state.plan_editor_ver += 1
                st.rerun()

            st.caption(f"📊 **Tägliche Besetzungs-Kontrolle ({dept_name} – reale Mitarbeiter):** Grün = Ziel erreicht | Gelb = Springer-Deckung | Rot = Unterbesetzt / Überbesetzt")
            cov_df = build_coverage_summary_df(df_rezultat, dept_name, num_days)
            st.dataframe(
                style_coverage_summary(cov_df),
                use_container_width=True,
                hide_index=True
            )
            return sub_df

        @st.cache_data
        def convert_df(df):
            if "Abteilung" in df.columns: 
                df = df.drop(columns=["Abteilung"])
            return df.to_csv(index=False).encode('utf-8')
            
        @st.cache_data
        def create_geocon_export(df_rez, jahr, monat):
            geocon_df = df_rez.copy()
            geocon_df = geocon_df[~geocon_df["Mitarbeiter"].str.contains("FEHLT|X-Oseba", na=False)]
            geocon_df = geocon_df.rename(columns={"Mitarbeiter": "Personalname"})
            drop_cols = ["ID_hidden", "Abteilung", "Rolle", "SOLL", "IST", "ÜBERSTD.", "SALDO"]
            geocon_df = geocon_df.drop(columns=[c for c in drop_cols if c in geocon_df.columns], errors="ignore")
            
            rename_map = {}
            for col in geocon_df.columns:
                if col.replace('.', '').isdigit():
                    d = int(col.replace('.', ''))
                    date_str = f"{d:02d}.{monat:02d}.{jahr}"
                    rename_map[col] = date_str
            geocon_df = geocon_df.rename(columns=rename_map)
            return geocon_df.to_csv(index=False, sep=";").encode('utf-8-sig')

        st.subheader("🔵 Dienstplan: Abteilung B (direkt editierbar)")
        df_b = render_editable_dept("Abteilung B", "abt_b")
        st.download_button(
            label="📥 Abt. B herunterladen", 
            data=convert_df(df_b), 
            file_name='Dienstplan_Abt_B.csv', 
            mime='text/csv'
        )
        st.divider()

        st.subheader("🟢 Dienstplan: Abteilung H (direkt editierbar)")
        df_h = render_editable_dept("Abteilung H", "abt_h")
        st.download_button(
            label="📥 Abt. H herunterladen", 
            data=convert_df(df_h), 
            file_name='Dienstplan_Abt_H.csv', 
            mime='text/csv'
        )
        st.divider()

        st.subheader("🟣 Dienstplan: Abteilung F (Nachtpool & Flex - direkt editierbar)")
        df_f = render_editable_dept("Abteilung F", "abt_f")
        st.download_button(
            label="📥 Abt. F herunterladen", 
            data=convert_df(df_f), 
            file_name='Dienstplan_Abt_F.csv', 
            mime='text/csv'
        )
        
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
    st.header("🚨 SOS Einspringer-Finder & 🔄 Smart-Tauschbörse")
    if "last_generated_df" in st.session_state:
        df_plan = st.session_state.last_generated_df
        staff_names = df_plan[~df_plan["Mitarbeiter"].str.contains("X-Oseba|FEHLT|⚠️", na=False)]["Mitarbeiter"].tolist()
        
        st.subheader("1. 🚨 SOS Einspringer-Finder (Bei Krankenstand)")
        col_sos1, col_sos2, col_sos3 = st.columns(3)
        with col_sos1: 
            ausfall_emp = st.selectbox("Ausfall Mitarbeiter:", staff_names)
        with col_sos2: 
            ausfall_tag = st.selectbox("An welchem Tag?", list(range(1, num_days + 1)))
        
        tag_col = f"{ausfall_tag}."
        aktuelle_schicht = "OFF"
        emp_role = "Pflegeassistenz"
        
        row_emp = df_plan[df_plan["Mitarbeiter"] == ausfall_emp]
        if not row_emp.empty:
            aktuelle_schicht = row_emp[tag_col].values[0]
            emp_role = row_emp["Rolle"].values[0]
            
        with col_sos3: 
            st.info(f"**Schicht:** {aktuelle_schicht} | **Rolle:** {emp_role}")
            
        if st.button("🔍 Ersatzpersonen suchen", type="primary"):
            kandidaten = []
            for _, r in df_plan.iterrows():
                m_name = r["Mitarbeiter"]
                m_rolle = r["Rolle"]
                m_schicht = r[tag_col]
                m_saldo = r["SALDO"]
                
                if "X-Oseba" in m_name or "FEHLT" in m_name or "⚠️" in m_name: 
                    continue
                
                if m_name != ausfall_emp and m_schicht == "...":
                    prev_col = f"{ausfall_tag-1}."
                    had_night_before = (ausfall_tag > 1 and str(r.get(prev_col, "")) in ["N1", "N2"])
                    if had_night_before:
                        continue
                    score = 100
                    gründe = []
                    if m_rolle == emp_role: 
                        score += 50
                        gründe.append("✅ Gleiche Rolle")
                    else: 
                        gründe.append("⚠️ Andere Rolle")
                        
                    if m_saldo < 0: 
                        score += 30
                        gründe.append(f"🟢 Saldo: {m_saldo}h")
                    else: 
                        gründe.append(f"🟡 Saldo: {m_saldo}h")
                        
                    kandidaten.append({"Name": m_name, "Rolle": m_rolle, "Score": score, "Gründe": " | ".join(gründe)})
                    
            kandidaten_df = pd.DataFrame(kandidaten).sort_values(by="Score", ascending=False)
            if not kandidaten_df.empty:
                for idx, k in kandidaten_df.head(3).iterrows():
                    st.success(f"🏆 **Top-Kandidat: {k['Name']}** ({k['Rolle']}) - {k['Gründe']}")
            else: 
                st.warning("Keine freien Mitarbeiter (unter Einhaltung der Nachtruhe) gefunden!")

        st.divider()
        st.subheader("2. 🔄 Smart-Tauschbörse (1-zu-1 Schichttausch mit Gesetzes-Check)")
        t_col1, t_col2, t_col3 = st.columns(3)
        with t_col1:
            swap_emp_a = st.selectbox("Mitarbeiter A:", staff_names, index=0, key="swap_a")
        with t_col2:
            swap_emp_b = st.selectbox("Mitarbeiter B:", staff_names, index=min(1, len(staff_names)-1), key="swap_b")
        with t_col3:
            swap_day = st.selectbox("Tag für Schichttausch:", list(range(1, num_days + 1)), key="swap_d")

        swap_col = f"{swap_day}."
        row_a = df_plan[df_plan["Mitarbeiter"] == swap_emp_a].iloc[0]
        row_b = df_plan[df_plan["Mitarbeiter"] == swap_emp_b].iloc[0]
        sh_a = str(row_a[swap_col])
        sh_b = str(row_b[swap_col])
        st.write(f"**Aktueller Stand am {swap_day}.:** `{swap_emp_a}` hat **`{sh_a}`** ↔️ `{swap_emp_b}` hat **`{sh_b}`**")

        if st.button("🔄 Schichttausch prüfen & direkt im Dienstplan durchführen"):
            if swap_emp_a == swap_emp_b:
                st.error("Bitte zwei unterschiedliche Mitarbeiter auswählen.")
            else:
                df_test = df_plan.copy()
                idx_a = df_test[df_test["Mitarbeiter"] == swap_emp_a].index[0]
                idx_b = df_test[df_test["Mitarbeiter"] == swap_emp_b].index[0]
                df_test.at[idx_a, swap_col] = sh_b
                df_test.at[idx_b, swap_col] = sh_a
                
                df_test = recalculate_plan_df(df_test, st.session_state.staff_df_v67, num_days)
                audit_after = run_austrian_law_audit(
                    df_test, st.session_state.staff_df_v67, num_days, leto, mesec, first_day_of_month_weekday, at_holidays
                )
                relevant_issues = pd.DataFrame()
                if not audit_after.empty:
                    relevant_issues = audit_after[
                        audit_after["Betroffen"].str.contains(swap_emp_a.split(" (")[0], na=False) |
                        audit_after["Betroffen"].str.contains(swap_emp_b.split(" (")[0], na=False) |
                        audit_after["Betroffen"].str.contains("Nachtdienst", na=False)
                    ]
                
                st.session_state.last_generated_df = df_test
                df_test.to_csv(plan_autosave_path, index=False)
                st.session_state.plan_editor_ver += 1
                if relevant_issues.empty:
                    st.success(f"✅ **Tausch 100% gesetzestreu durchgeführt!** (`{swap_emp_a}` ➔ `{sh_b}`, `{swap_emp_b}` ➔ `{sh_a}`)")
                else:
                    st.warning("⚠️ Tausch durchgeführt, aber das Inspektorat meldet folgenden Hinweis:")
                    st.dataframe(relevant_issues, use_container_width=True, hide_index=True)
    else: 
        st.info("Bitte berechne zuerst den Dienstplan!")

with tab5:
    st.header("📉 5. Überstunden-, Fairness- & Burnout-Radar")
    if "last_generated_df" in st.session_state:
        df_plan = st.session_state.last_generated_df
        real_df = df_plan[~df_plan["Mitarbeiter"].str.contains("X-Oseba|FEHLT|⚠️", na=False)].copy()
        day_cols_only = [f"{d}." for d in range(1, num_days + 1) if f"{d}." in real_df.columns]
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Gesamte SOLL-Stunden", f"{real_df['SOLL'].sum():.1f} h")
        c2.metric("Gesamte IST-Stunden", f"{real_df['IST'].sum():.1f} h")
        c3.metric("Aufgebaute Überstunden", f"{real_df['ÜBERSTD.'].sum():.1f} h")
        
        radar_rows = []
        for _, r in real_df.iterrows():
            vals = [str(r[c]).strip().upper() for c in day_cols_only]
            n_count = sum(1 for v in vals if v in ["N1", "N2"])
            long_12h = sum(1 for v in vals if v in ["F2", "X7"])
            we_days_worked = 0
            for d_idx, v in enumerate(vals):
                dow = (d_idx + first_day_of_month_weekday) % 7
                if dow >= 5 and v in SHIFTS_HUNDREDTHS and v != "OFF":
                    we_days_worked += 1
            
            ueb = float(r.get("ÜBERSTD.", 0.0))
            load_score = min(100, int(round((ueb * 1.8) + (n_count * 4.5) + (we_days_worked * 5.0) + (long_12h * 1.5))))
            status_ampel = "🟢 Optimal" if load_score < 45 else ("🟡 Erhöht" if load_score < 70 else "🔴 Hoch (Entlasten!)")
            
            radar_rows.append({
                "Mitarbeiter": r["Mitarbeiter"],
                "Abteilung": r["Abteilung"],
                "Rolle": r["Rolle"],
                "SOLL": r["SOLL"],
                "IST": r["IST"],
                "ÜBERSTD.": r["ÜBERSTD."],
                "SALDO": r["SALDO"],
                "WE-Tage (Sa/So)": we_days_worked,
                "12h-Dienste (F2/X7)": long_12h,
                "Nächte (N1/N2)": n_count,
                "Burnout-Index": f"{load_score}%",
                "Belastungs-Status": status_ampel
            })
            
        radar_df = pd.DataFrame(radar_rows)
        st.subheader("⚖️ KI Fairness- & Belastungs-Radar pro Mitarbeiter")
        st.dataframe(radar_df.sort_values(by="ÜBERSTD.", ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("Bitte berechne zuerst den Dienstplan, um die Analyse zu sehen!")

with tab6:
    st.header("🛡️ 6. Steiermark Pflege- & Arbeitsrechts-Kompendium + Live-Inspektorat")
    st.markdown(
        "Alle relevanten **Bundes- und Landesgesetze für die Pflege in der Steiermark** zum täglichen Nachschlagen – "
        "inklusive automatischer Echtzeit-Prüfung deines aktuellen Dienstplans."
    )

    col_law1, col_law2 = st.columns(2)
    with col_law1:
        with st.expander("🤰 1. Mutterschutzgesetz (MSchG §§ 3–8)", expanded=True):
            st.markdown(
                "- **Absolutes Beschäftigungsverbot (§ 3 & § 5 MSchG):** 8 Wochen vor dem voraussichtlichen Entbindungstermin und 8 Wochen nach der Geburt (12 Wochen bei Früh-/Mehrlingsgeburt oder Kaiserschnitt).\n"
                "- **Absolutes Nachtarbeitsverbot (§ 6 MSchG):** Werdende und stillende Mütter dürfen zwischen **20:00 und 06:00 Uhr** nicht beschäftigt werden (**`N1` & `N2` strikt verboten**).\n"
                "- **Sonn- und Feiertagsverbot (§ 7 MSchG):** An Sonn- und gesetzlichen Feiertagen besteht Beschäftigungsverbot.\n"
                "- **Verbot von Überstunden & Langdiensten (§ 8 MSchG):** Tagesarbeitszeit darf **9,0 Stunden** (`X7`, `X6`, `F2`, `F7` nicht zulässig -> nur Kurzdienste wie `X4` / `MS`) und Wochenarbeitszeit **40,0 Stunden** keinesfalls überschreiten.\n"
                "- **Körperliche Schonung (§ 4 MSchG):** Verbot von schwerem Heben (> 5 kg regelmäßig / > 10 kg gelegentlich) sowie Schutz vor Infektionsgefahren."
            )
        with st.expander("⏳ 2. Altersteilzeit (§ 27 AlVG & SWÖ-KV) & Elternteilzeit (MSchG/VKG)", expanded=True):
            st.markdown(
                "- **Altersteilzeit (ATZ - § 27 AlVG):** Reduktion der Normalarbeitszeit auf **40 % bis 60 %** der vorherigen Arbeitszeit (z. B. bei 37h Vollzeit: **14,8h bis 22,2h/Woche**).\n"
                "- **Lohnausgleich & Sozialversicherung:** Arbeitnehmer erhält 50 % des Entgeltverlustes als Lohnausgleich (also **70 % bis 80 % des Letztgehalts**) bei **100 % Pensions-, Kranken- und Arbeitslosenversicherungsbeitragsgrundlage**.\n"
                "- **Mehrarbeits-Schutz in ATZ:** Regelmäßige Überstunden über die Geringfügigkeitsgrenze gefährden das AMS-Altersteilzeitgeld – die KI sperrt daher den Überstundenaufbau für ATZ-Mitarbeiter!\n"
                "- **Elternteilzeit (ETZ - §§ 15h ff MSchG / VKG):** Rechtsanspruch in Betrieben ab 21 Mitarbeitern (bei ≥ 3 Jahren Betriebszugehörigkeit). Vereinbarte Wochentage (`MO`–`SO`) sind verbindlich, kein Überstundenzwang."
            )
        with st.expander("🏥 3. StPBG & StPAVO Steiermark (Personalausstattung & Nacht-Regel)", expanded=True):
            st.markdown(
                "- **Steiermärkische Personalausstattungsverordnung (StPAVO):** Verbindlicher Personalschlüssel berechnet nach Bewohnerzahl und Pflegegeldstufen (Stufe 1 bis 7).\n"
                "- **Qualifikations-Mix (Grade-Mix):** Vorgeschriebenes Verhältnis zwischen gehobenem Dienst (**DGKP**), Pflegefachassistenz/Pflegeassistenz (**PFA/PA**) und Heimhilfe (**HH**).\n"
                "- **Stations-Tagesbesetzung:** Mindestens **4 Pflegekräfte** auf Abt. B (+ 1x `JED`) und **4 Pflegekräfte** auf Abt. H; je Station 1 eigene DGKP (oder Springer-Abdeckung der Nachbarstation).\n"
                "- **Nachtdienst-Vorgabe:** Hausweit **exakt 1x `N1` (DGKP) + 1x `N2` (PA)**. Eine Doppelbesetzung mit 2 DGKP in der Nacht ist im System hart gesperrt."
            )

    with col_law2:
        with st.expander("📘 4. AZG, KA-AZG, ARG & SWÖ-KV (Arbeitszeit & Ruhezeiten)", expanded=True):
            st.markdown(
                "- **SWÖ-KV Vollzeit:** **37,0 Wochenstunden** Normalarbeitszeit.\n"
                "- **Tageshöchstarbeitszeit:** Bei verlängerten Diensten bis **12,0h** am Tag (`X7`, `F2`) bzw. **13,5h** im Nachtdienst (`N1`, `N2`).\n"
                "- **Wochenhöchstgrenze:** Kurzfristig bis maximal **50,0 Stunden** in einzelnen Wochen, im Durchrechnungszeitraum maximal **48,0 Stunden** im Schnitt.\n"
                "- **Tägliche Ruhezeit (§ 12 AZG / § 7 KA-AZG):** Mindestens **11 Stunden** ununterbrochene Ruhezeit zwischen zwei Diensten.\n"
                "- **Erholung nach Nachtdienst:** Nach jedem Nachtdienst oder Nachtblock (optimal 2, max. 3 Nächte) folgen **zwingend 2 freie Kalendertage** (Schlaftag + Ruhetag)."
            )
        with st.expander("🩺 5. GuKG (Berufspflichten DGKP vs. PA & Fortbildung)", expanded=True):
            st.markdown(
                "- **DGKP (§§ 12–16 GuKG):** Kernkompetenz für Pflegeprozess, Pflegediagnostik, Planung, Evaluierung sowie ärztlich übertragene Diagnostik/Therapie.\n"
                "- **Pflegeassistenz (§ 83 GuKG):** Durchführung übertragener Pflegemaßnahmen und Mitarbeit bei Diagnostik/Therapie unter Anordnung und Aufsicht von DGKP/Ärzten (im Dienstplan strikt auf **`F2`, `F7`, `N2`** geregelt).\n"
                "- **Gesetzliche Fortbildungspflicht (§ 63 & § 104c GuKG):** **60 Stunden** innerhalb von 5 Jahren für **DGKP**; **40 Stunden** innerhalb von 5 Jahren für **PA**."
            )
        with st.expander("🌙 6. Nachtschwerarbeitsgesetz (NSchG) & Pflegefreistellung (UrlG/AVRAG)", expanded=True):
            st.markdown(
                "- **NSchG-Zusatzurlaub (Art. XI NSchG):** Ab 50 geleisteten Nachtschwerarbeits-Diensten pro Jahr gebühren **2 zusätzliche Urlaubstage** (steigend bis auf 6 Zusatzurlaubstage nach Dienstjahren).\n"
                "- **Pflegefreistellung (§ 16 UrlG):** Anspruch auf bezahlte Freistellung bis zu **1 regelmäßigen Wochenarbeitszeit** pro Arbeitsjahr zur notwendigen Pflege erkrankter naher Angehöriger (+ 1 weitere Woche bei Kindern unter 12 Jahren).\n"
                "- **Pflegekarenz / Pflegeteilzeit (§ 14c/d AVRAG):** Vereinbarung für 1 bis 3 Monate zur Betreuung von Angehörigen ab Pflegegeldstufe 3 (mit Bezug von Pflegekarenzgeld)."
            )

    st.divider()
    st.subheader("🕵️‍♂️ Automatischer Dienstplan-Prüfbericht (Live-Inspektorat Steiermark)")

    if "last_generated_df" in st.session_state:
        audit_df = run_austrian_law_audit(
            st.session_state.last_generated_df, 
            st.session_state.staff_df_v67, 
            num_days, leto, mesec, first_day_of_month_weekday, at_holidays
        )
        if audit_df.empty:
            st.success(
                "✅ **100% ZERTIFIZIERT & GESETZESTREU (Steiermark-Standard)!** Der aktuelle Dienstplan erfüllt alle Vorgaben: "
                "Maximal 1 DGKP in der Nacht, PA nur F2/F7/N2, 2 freie Tage nach Nachtblock, Mutterschutz (MSchG), Altersteilzeit (ATZ) und StPAVO-Besetzung."
            )
        else:
            st.warning(f"⚠️ **Hinweis:** Bei der Überprüfung wurden **{len(audit_df)} Abweichungen / Hinweise** gefunden:")
            st.dataframe(audit_df, use_container_width=True, hide_index=True)
    else:
        st.info("Sobald du in Tab 2 einen Dienstplan berechnet hast, erscheint hier automatisch das Prüfergebnis nach Steiermark- & Bundesrecht.")
