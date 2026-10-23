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

st.set_page_config(page_title="KI-Dienstplan PRO 69.0", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 69.0 - StPAVO Rechner, PFA & Kompakt-Kalender)")
st.markdown(
    "**System-Architektur (StPAVO Steiermark Berechnung, PFA-Integration & Kompakt-Kalender):** \n"
    "- 🧮 **NEU: Tab 3 – StPAVO Personalrechner:** Berechnet aus den **Pflegestufen (0–7)** exakt die nötigen **VZÄ**, den **täglichen Schichtbedarf pro Station** sowie den **Prozent-Mix (DGKP, PFA, PA, HH)** nach steirischem Gesetz.\n"
    "- 💉 **Pflegefachassistenz (PFA) integriert:** Neue Rolle `PFA` im gesamten System (Team, Dienste-Studio, StPAVO & KI-Planer) verfügbar.\n"
    "- 🗓️ **NEU: Tab 4 – Kompakte Urlaubs- & Wunsch-Tabellen:** Aufgeteilt in kleinere Stations-Tabellen mit schmalen Spalten (`1`–`31`) und Farbcodierung für volle Monatsübersicht auf einen Blick."
)

PAID_ABSENCES = ["URL", "SU", "ENT", "KRA", "PFLEGE"]
GESETZ_STATUS_OPTIONS = [
    "Normal",
    "Altersteilzeit (ATZ)",
    "Mutterschutz (MSchG)",
    "Elternteilzeit (ETZ)",
    "Pflegekarenz / Teilzeit",
    "Nachtschwerarbeit (NSchG)"
]
ROLE_OPTIONS = ["Leitung", "DGKP", "PFA", "Pflegeassistenz", "Heimhelfer"]

# Standard-Personalschlüssel nach StPAVO Steiermark (1 VZÄ pro X Bewohner je Pflegestufe)
DEFAULT_PAVO_KEYS = {
    "Stufe_0": 24.0,
    "Stufe_1": 12.0,
    "Stufe_2": 7.5,
    "Stufe_3": 4.0,
    "Stufe_4": 2.5,
    "Stufe_5": 2.0,
    "Stufe_6": 1.5,
    "Stufe_7": 1.5
}

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

def get_default_shifts_df():
    return pd.DataFrame([
        {"Kürzel": "X7", "Bezeichnung": "DGKP Langdienst", "Stunden": 12.0, "Typ": "Tagdienst Pflege", "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "X6", "Bezeichnung": "DGKP Tagdienst", "Stunden": 11.0, "Typ": "Tagdienst Pflege", "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "X4", "Bezeichnung": "DGKP Kurzdienst", "Stunden": 8.25, "Typ": "Tagdienst Pflege", "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "F2", "Bezeichnung": "PFA/PA/HH Langdienst", "Stunden": 12.0, "Typ": "Tagdienst Pflege", "Erlaubt_DGKP": False, "Erlaubt_PFA": True, "Erlaubt_PA": True, "Erlaubt_HH": True},
        {"Kürzel": "F7", "Bezeichnung": "PFA/PA/HH Tagdienst", "Stunden": 11.0, "Typ": "Tagdienst Pflege", "Erlaubt_DGKP": False, "Erlaubt_PFA": True, "Erlaubt_PA": True, "Erlaubt_HH": True},
        {"Kürzel": "N1", "Bezeichnung": "Nachtdienst DGKP", "Stunden": 13.5, "Typ": "Nachtdienst", "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "N2", "Bezeichnung": "Nachtdienst PFA/PA", "Stunden": 13.5, "Typ": "Nachtdienst", "Erlaubt_DGKP": False, "Erlaubt_PFA": True, "Erlaubt_PA": True, "Erlaubt_HH": False},
        {"Kürzel": "JED", "Bezeichnung": "Speisesaal Dienst", "Stunden": 10.5, "Typ": "Speisesaal / Sonder", "Erlaubt_DGKP": False, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": True},
        {"Kürzel": "SM", "Bezeichnung": "Mitteldienst SM", "Stunden": 10.75, "Typ": "Tagdienst Pflege", "Erlaubt_DGKP": False, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": True},
        {"Kürzel": "MS", "Bezeichnung": "Kurzdienst MS", "Stunden": 7.0, "Typ": "Tagdienst Pflege", "Erlaubt_DGKP": False, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": True},
    ])

def sanitize_shifts_df(df):
    if df is None or df.empty:
        return get_default_shifts_df()
    df = df.copy()
    if "Kürzel" not in df.columns:
        return get_default_shifts_df()
    df = df.dropna(subset=["Kürzel"])
    df["Kürzel"] = df["Kürzel"].astype(str).str.strip().str.upper()
    df = df[~df["Kürzel"].isin(["", "NAN", "NONE", "OFF", "..."])]
    df = df.drop_duplicates(subset=["Kürzel"], keep="last")
    
    if "Bezeichnung" not in df.columns:
        df["Bezeichnung"] = "Dienst"
    df["Bezeichnung"] = df["Bezeichnung"].fillna("Dienst").astype(str).str.strip()
    
    if "Stunden" not in df.columns:
        df["Stunden"] = 8.0
    df["Stunden"] = pd.to_numeric(df["Stunden"], errors="coerce").fillna(8.0).clip(lower=0.5, upper=24.0).round(2)
    
    valid_types = ["Tagdienst Pflege", "Nachtdienst", "Speisesaal / Sonder"]
    if "Typ" not in df.columns:
        df["Typ"] = "Tagdienst Pflege"
    df["Typ"] = df["Typ"].fillna("Tagdienst Pflege").astype(str).str.strip()
    df.loc[~df["Typ"].isin(valid_types), "Typ"] = "Tagdienst Pflege"
    
    if "Erlaubt_PA" in df.columns and "Erlaubt_PFA" not in df.columns:
        df["Erlaubt_PFA"] = df["Erlaubt_PA"]
        
    for b_col, def_val in [("Erlaubt_DGKP", True), ("Erlaubt_PFA", True), ("Erlaubt_PA", True), ("Erlaubt_HH", False)]:
        if b_col not in df.columns:
            df[b_col] = def_val
        else:
            df[b_col] = df[b_col].apply(lambda x: False if str(x).strip().lower() in ["false", "0", "no", "nein", "falsch"] else True)
            
    cols = ["Kürzel", "Bezeichnung", "Stunden", "Typ", "Erlaubt_DGKP", "Erlaubt_PFA", "Erlaubt_PA", "Erlaubt_HH"]
    return df[cols].reset_index(drop=True)

if "shifts_df_v69" not in st.session_state:
    if os.path.exists("shifts_data.csv"):
        try:
            with open("shifts_data.csv", "rb") as f:
                st.session_state.shifts_df_v69 = sanitize_shifts_df(read_csv_smart(f.read(), is_index_col=False))
        except Exception:
            st.session_state.shifts_df_v69 = get_default_shifts_df()
    else:
        st.session_state.shifts_df_v69 = get_default_shifts_df()

SHIFTS_DF_CURRENT = sanitize_shifts_df(st.session_state.shifts_df_v69)
SHIFTS_HUNDREDTHS = {
    row["Kürzel"]: int(round(float(row["Stunden"]) * 100)) 
    for _, row in SHIFTS_DF_CURRENT.iterrows()
}
SHIFTS_HUNDREDTHS["OFF"] = 0

SHIFT_LABELS = {
    row["Kürzel"]: f"{row['Kürzel']} ({row['Stunden']}h – {row['Bezeichnung']})" 
    for _, row in SHIFTS_DF_CURRENT.iterrows()
}
DAY_CARE_SHIFTS = SHIFTS_DF_CURRENT[SHIFTS_DF_CURRENT["Typ"] == "Tagdienst Pflege"]["Kürzel"].tolist()
NIGHT_SHIFTS = SHIFTS_DF_CURRENT[SHIFTS_DF_CURRENT["Typ"] == "Nachtdienst"]["Kürzel"].tolist()
if not NIGHT_SHIFTS:
    NIGHT_SHIFTS = ["N1", "N2"]
DGKP_DAY_SHIFTS = SHIFTS_DF_CURRENT[
    (SHIFTS_DF_CURRENT["Typ"] == "Tagdienst Pflege") & (SHIFTS_DF_CURRENT["Erlaubt_DGKP"] == True)
]["Kürzel"].tolist()
MANUAL_SHIFT_CODES = SHIFTS_DF_CURRENT["Kürzel"].tolist()

def get_default_pavo_df():
    return pd.DataFrame([
        {"Abteilung": "Abteilung B", "Stufe_0": 0, "Stufe_1": 2, "Stufe_2": 4, "Stufe_3": 6, "Stufe_4": 6, "Stufe_5": 4, "Stufe_6": 2, "Stufe_7": 0},
        {"Abteilung": "Abteilung H", "Stufe_0": 0, "Stufe_1": 1, "Stufe_2": 4, "Stufe_3": 7, "Stufe_4": 6, "Stufe_5": 4, "Stufe_6": 1, "Stufe_7": 1},
    ])

if "pavo_df_v69" not in st.session_state:
    if os.path.exists("pavo_data.csv"):
        try:
            st.session_state.pavo_df_v69 = pd.read_csv("pavo_data.csv")
        except Exception:
            st.session_state.pavo_df_v69 = get_default_pavo_df()
    else:
        st.session_state.pavo_df_v69 = get_default_pavo_df()

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

def resolve_allowed_shifts_for_person(s, shifts_df):
    """Ermittelt erlaubte Schichten pro Person inkl. Rolle PFA & Pflegeassistenz."""
    allowed_shifts = ["OFF"]
    nur_nacht = bool(s.get("Nur_Nacht", False))
    spez = str(s.get("Spezialdienst", "Ohne")).upper().strip()
    rolle = str(s.get("Rolle", "Pflegeassistenz")).strip()
    gesetz = str(s.get("Gesetz_Status", "Normal")).strip()
    max_n = int(s.get("Max_Nacht", 0))

    day_df = shifts_df[shifts_df["Typ"] != "Nachtdienst"]
    night_df = shifts_df[shifts_df["Typ"] == "Nachtdienst"]

    if gesetz == "Mutterschutz (MSchG)":
        if rolle in ["DGKP", "Leitung"]:
            short_dg = day_df[(day_df["Erlaubt_DGKP"] == True) & (day_df["Stunden"] <= 9.0)]["Kürzel"].tolist()
            allowed_shifts.extend(short_dg if short_dg else ["X4"])
        elif rolle in ["PFA", "Pflegeassistenz"]:
            col_r = "Erlaubt_PFA" if rolle == "PFA" else "Erlaubt_PA"
            short_pa = day_df[(day_df[col_r] == True) & (day_df["Stunden"] <= 9.0)]["Kürzel"].tolist()
            allowed_shifts.extend(short_pa if short_pa else ["F7"])
        else:
            short_hh = day_df[(day_df["Erlaubt_HH"] == True) & (day_df["Stunden"] <= 9.0)]["Kürzel"].tolist()
            allowed_shifts.extend(short_hh if short_hh else ["MS"])
        return list(set(allowed_shifts))

    explicit_day_codes = []
    if spez not in ["OHNE", "NUR WE UND FEIERTAGE", ""]:
        tokens = [t.strip() for t in spez.replace(";", ",").replace(" ", ",").split(",") if t.strip()]
        for sh_c in day_df["Kürzel"].tolist():
            if sh_c in tokens or sh_c in spez:
                explicit_day_codes.append(sh_c)

    if rolle in ["Pflegeassistenz", "PFA"]:
        role_col = "Erlaubt_PFA" if rolle == "PFA" else "Erlaubt_PA"
        pa_valid_day = day_df[day_df[role_col] == True]["Kürzel"].tolist()
        if not pa_valid_day:
            pa_valid_day = ["F2", "F7"]
        if not nur_nacht:
            if explicit_day_codes:
                pa_chosen = [c for c in explicit_day_codes if c in pa_valid_day]
                allowed_shifts.extend(pa_chosen if pa_chosen else pa_valid_day)
            else:
                allowed_shifts.extend(pa_valid_day)
        if max_n > 0 or nur_nacht:
            pa_nights = night_df[night_df[role_col] == True]["Kürzel"].tolist()
            allowed_shifts.extend(pa_nights if pa_nights else ["N2"])
        return list(set(allowed_shifts))

    if not nur_nacht:
        if explicit_day_codes:
            allowed_shifts.extend(explicit_day_codes)
            if spez == "JED" and rolle == "Heimhelfer":
                hh_backs = [c for c in ["F2", "F7"] if c in day_df["Kürzel"].values]
                allowed_shifts.extend(hh_backs)
        else:
            if rolle in ["DGKP", "Leitung"]:
                dg_days = day_df[day_df["Erlaubt_DGKP"] == True]["Kürzel"].tolist()
                allowed_shifts.extend(dg_days if dg_days else ["X4", "X6", "X7"])
            else:
                hh_days = day_df[day_df["Erlaubt_HH"] == True]["Kürzel"].tolist()
                allowed_shifts.extend(hh_days if hh_days else ["JED", "F2", "F7"])

    if (max_n > 0 or nur_nacht) and rolle != "Leitung":
        if rolle == "DGKP":
            dg_nights = night_df[night_df["Erlaubt_DGKP"] == True]["Kürzel"].tolist()
            allowed_shifts.extend(dg_nights if dg_nights else ["N1"])
        else:
            hh_nights = night_df[night_df["Erlaubt_HH"] == True]["Kürzel"].tolist()
            if hh_nights:
                allowed_shifts.extend(hh_nights)

    return list(set(allowed_shifts))

def normalize_cal_cell(val):
    """Wandelt lange Kalender-Einträge in ultra-kompakte Kürzel für die Monatsübersicht um."""
    if pd.isna(val):
        return ""
    s = str(val).strip().upper()
    if s in ["", "NAN", "NONE", "<NA>", "NULL", "..."]:
        return ""
    s_clean = s.replace("📌", "").replace("🔴", "").replace("🟠", "").replace("🟣", "").replace("🔵", "").replace("⚫", "").replace("🟢", "").replace("⚪", "").strip()
    for sh_c in MANUAL_SHIFT_CODES:
        if s_clean == sh_c or s_clean.startswith(sh_c + " "):
            return sh_c
    if "URL" in s_clean: return "URL"
    if "KRA" in s_clean: return "KRA"
    if "ZA" in s_clean: return "ZA"
    if "SU" in s_clean: return "SU"
    if "ENT" in s_clean: return "ENT"
    if "PFLEGE" in s_clean: return "PFL"
    if "WUN" in s_clean or "FREI" in s_clean: return "WUN"
    if "MUS" in s_clean: return "MUS"
    return s_clean[:4]

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
                if clean_v == "PFL": clean_v = "PFLEGE"
                if clean_v == "WUN": clean_v = "WUNSCH"
                if clean_v == "MUS": clean_v = "MUSS"
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

def build_coverage_summary_df(full_df, dept_name, num_days, min_b=4, min_h=4):
    """Erstellt die Kontrollzeilen inkl. automatischer Springer-Erkennung bei DGKP."""
    day_cols_only = [f"{d}." for d in range(1, num_days + 1)]
    real_full = full_df[~full_df["Mitarbeiter"].astype(str).str.contains("X-Oseba|FEHLT|⚠️", na=False)]
    real_dept = real_full[real_full["Abteilung"] == dept_name]

    summary_rows = []
    target_min = min_b if dept_name == "Abteilung B" else min_h

    if dept_name in ["Abteilung B", "Abteilung H"]:
        row_care = {"Kontroll-Kategorie": f"👥 Pflege Tag (Min. {target_min})"}
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
        row_n2 = {"Kontroll-Kategorie": "🌙 Hausweit N2 - PFA/PA (Exakt 1)"}
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
        min_ needed = 4
        if "Min. " in kat:
            try:
                min_needed = int(kat.split("Min. ")[1].split(")")[0])
            except Exception:
                min_needed = 1
        for col in df_sum.columns[1:]:
            val = row[col]
            if isinstance(val, str) and "Springer" in val:
                styles.append("background-color: #fff3cd; color: #856404; font-weight: bold; text-align: center; border: 1px solid #ffeeba;")
                continue
            if not isinstance(val, (int, float, np.integer)):
                styles.append("text-align: center;")
                continue
            if "Min. " in kat:
                if val < min_needed:
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

def run_austrian_law_audit(df_plan, staff_df, shifts_df, num_days, leto, mesec, first_day_weekday, at_holidays, min_b=4, min_h=4):
    """Prüft den Dienstplan nach Steiermark- & Österreich-Recht."""
    issues = []
    day_cols_only = [f"{d}." for d in range(1, num_days + 1) if f"{d}." in df_plan.columns]
    real_df = df_plan[~df_plan["Mitarbeiter"].astype(str).str.contains("X-Oseba|FEHLT|⚠️", na=False)]
    pa_allowed_codes = shifts_df[shifts_df["Erlaubt_PA"] == True]["Kürzel"].tolist() + ["OFF"]
    pfa_allowed_codes = shifts_df[shifts_df["Erlaubt_PFA"] == True]["Kürzel"].tolist() + ["OFF"]

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

        if rolle == "Pflegeassistenz":
            for d, v in enumerate(vals):
                if v in SHIFTS_HUNDREDTHS and v not in pa_allowed_codes:
                    issues.append({
                        "Kategorie": "🛑 Ungültiger PA-Dienst",
                        "Betroffen": f"{emp} ({abt})",
                        "Zeitraum": f"Tag {d+1}.",
                        "Details": f"Pflegeassistenz hat Dienst '{v}' (Nicht für PA freigegeben)."
                    })
        elif rolle == "PFA":
            for d, v in enumerate(vals):
                if v in SHIFTS_HUNDREDTHS and v not in pfa_allowed_codes:
                    issues.append({
                        "Kategorie": "🛑 Ungültiger PFA-Dienst",
                        "Betroffen": f"{emp} ({abt})",
                        "Zeitraum": f"Tag {d+1}.",
                        "Details": f"PFA hat Dienst '{v}' (Nicht für PFA freigegeben)."
                    })

        if gesetz_st == "Mutterschutz (MSchG)":
            for d, v in enumerate(vals):
                dow = (d + first_day_weekday) % 7
                is_hol = (date(leto, mesec, d+1) in at_holidays) or (mesec == 12 and (d+1 in [24, 31]))
                if v in NIGHT_SHIFTS:
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

        if gesetz_st in ["Altersteilzeit (ATZ)", "Elternteilzeit (ETZ)"] and float(row.get("ÜBERSTD.", 0.0)) > 2.0:
            issues.append({
                "Kategorie": f"⚠️ {gesetz_st} Mehrarbeit",
                "Betroffen": f"{emp} ({abt})",
                "Zeitraum": "Gesamter Monat",
                "Details": f"{row['ÜBERSTD.']}h Überstunden geplant (Bei {gesetz_st} sollte SOLL exakt eingehalten werden)."
            })

        for d in range(len(vals) - 1):
            if vals[d] in NIGHT_SHIFTS and vals[d+1] not in NIGHT_SHIFTS:
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

        n_streak = 0
        for d, v in enumerate(vals):
            if v in NIGHT_SHIFTS:
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

    for d, c in enumerate(day_cols_only):
        b_rows = real_df[real_df["Abteilung"] == "Abteilung B"]
        h_rows = real_df[real_df["Abteilung"] == "Abteilung H"]
        dgkp_rows = real_df[real_df["Rolle"].isin(["DGKP", "Leitung"])]
        
        b_care = sum(1 for v in b_rows[c].astype(str).str.strip() if v in DAY_CARE_SHIFTS)
        h_care = sum(1 for v in h_rows[c].astype(str).str.strip() if v in DAY_CARE_SHIFTS)
        all_n1 = sum(1 for v in real_df[c].astype(str).str.strip() if v == "N1")
        all_n2 = sum(1 for v in real_df[c].astype(str).str.strip() if v == "N2")
        dgkp_in_night = sum(1 for v in dgkp_rows[c].astype(str).str.strip() if v in NIGHT_SHIFTS)

        if dgkp_in_night > 1:
            issues.append({
                "Kategorie": "🛑 2 DGKP im Nachtdienst (Verboten!)",
                "Betroffen": "Nachtdienst",
                "Zeitraum": f"Nacht am {d+1}.",
                "Details": f"Es sind {dgkp_in_night} DGKP gleichzeitig in der Nacht eingeteilt (Maximal 1 DGKP erlaubt!)."
            })
        if b_care < min_b:
            issues.append({
                "Kategorie": "🚨 StPAVO Mindestbesetzung",
                "Betroffen": "Abteilung B",
                "Zeitraum": f"Tag {d+1}.",
                "Details": f"Nur {b_care} Pflegekräfte im Tagdienst (Mindestens {min_b} erforderlich)."
            })
        if h_care < min_h:
            issues.append({
                "Kategorie": "🚨 StPAVO Mindestbesetzung",
                "Betroffen": "Abteilung H",
                "Zeitraum": f"Tag {d+1}.",
                "Details": f"Nur {h_care} Pflegekräfte im Tagdienst (Mindestens {min_h} erforderlich)."
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
if "shifts_editor_ver" not in st.session_state:
    st.session_state.shifts_editor_ver = 0
if "cal_editor_ver" not in st.session_state:
    st.session_state.cal_editor_ver = 0
if "plan_editor_ver" not in st.session_state:
    st.session_state.plan_editor_ver = 0
if "target_min_b" not in st.session_state:
    st.session_state.target_min_b = 4
if "target_min_h" not in st.session_state:
    st.session_state.target_min_h = 4

tab1, tab_shifts, tab_pavo, tab3, tab2, tab4, tab5, tab6 = st.tabs([
    "⚙️ 1. Team & Verträge", 
    "⏱️ 2. Dienste-Studio",
    "🧮 3. StPAVO Personalrechner",
    "🗓️ 4. Kompakt-Kalender (Urlaub/Wünsche)", 
    "📅 5. Dienstplan", 
    "🚨 6. SOS & Tauschbörse", 
    "📉 7. Analyse & Fairness", 
    "🛡️ 8. Inspektorat Steiermark"
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
    st.header("2. Team, Rollen (inkl. PFA), Gesetzlicher Status & Erlaubte Dienste")
    
    if "staff_df_v69" not in st.session_state:
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
            for i in range(1, 3): initial_staff.append({"ID": len(initial_staff), "Name": f"PFA B-{i}", "Abteilung": "Abteilung B", "Rolle": "PFA", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 3): initial_staff.append({"ID": len(initial_staff), "Name": f"PFA H-{i}", "Abteilung": "Abteilung H", "Rolle": "PFA", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 7): initial_staff.append({"ID": len(initial_staff), "Name": f"PA B-{i}", "Abteilung": "Abteilung B", "Rolle": "Pflegeassistenz", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 7): initial_staff.append({"ID": len(initial_staff), "Name": f"PA H-{i}", "Abteilung": "Abteilung H", "Rolle": "Pflegeassistenz", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 4): initial_staff.append({"ID": len(initial_staff), "Name": f"HH B-{i}", "Abteilung": "Abteilung B", "Rolle": "Heimhelfer", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "JED"})
            for i in range(1, 3): initial_staff.append({"ID": len(initial_staff), "Name": f"HH H-{i}", "Abteilung": "Abteilung H", "Rolle": "Heimhelfer", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "JED"})
            
            st.session_state.staff_df_v69 = pd.DataFrame(initial_staff)
        else:
            st.session_state.staff_df_v69 = loaded_df

    col_import, col_export = st.columns(2)
    with col_export:
        st.download_button(
            label="📥 Aktuelles Team als Backup speichern", 
            data=st.session_state.staff_df_v69.to_csv(index=False).encode('utf-8'), 
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
                    st.session_state.staff_df_v69 = uploaded_team
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
        for f_path in ["team_data.csv", "shifts_data.csv", "pavo_data.csv", cal_autosave_path, plan_autosave_path]:
            if os.path.exists(f_path): 
                os.remove(f_path)
        for k in ["staff_df_v69", "shifts_df_v69", "pavo_df_v69", "abs_matrix_v69", "raw_uploaded_cal", "last_generated_df"]:
            if k in st.session_state: 
                del st.session_state[k]
        st.session_state.team_editor_ver += 1
        st.session_state.shifts_editor_ver += 1
        st.session_state.cal_editor_ver += 1
        st.session_state.plan_editor_ver += 1
        st.rerun()

    st.subheader("🎛️ Individueller Dienst-, Stunden- & Schutzstatus-Konfigurator")
    current_staff_tab1 = st.session_state.staff_df_v69["Name"].dropna().astype(str).str.strip().tolist()
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
            df_mod = st.session_state.staff_df_v69.copy()
            for emp_n in sel_staff_custom:
                mask = df_mod["Name"] == emp_n
                if sel_shifts_custom:
                    day_codes = [c for c in sel_shifts_custom if c not in NIGHT_SHIFTS]
                    if day_codes:
                        df_mod.loc[mask, "Spezialdienst"] = ", ".join(day_codes)
                    if any(c in NIGHT_SHIFTS for c in sel_shifts_custom):
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
            st.session_state.staff_df_v69 = df_mod
            df_mod.to_csv("team_data.csv", index=False)
            st.session_state.team_editor_ver += 1
            st.success("✅ Einstellungen erfolgreich auf Mitarbeiter übertragen!")
            st.rerun()

    with st.form("team_editor_form"):
        edited_data = st.data_editor(
            st.session_state.staff_df_v69, 
            num_rows="dynamic", 
            key=f"tabelle_mitarbeiter_v69_{st.session_state.team_editor_ver}",
            column_config={
                "ID": None,
                "Abteilung": st.column_config.SelectboxColumn("Abteilung", options=["Abteilung B", "Abteilung H", "Abteilung F"]),
                "Rolle": st.column_config.SelectboxColumn("Rolle", options=ROLE_OPTIONS),
                "Qualifikation": st.column_config.SelectboxColumn("Zusatzqualifikation", options=["Keine", "Wundmanager", "Praxisanleiter", "Palliativ"]),
                "Gesetz_Status": st.column_config.SelectboxColumn("Gesetzl. Status (Steiermark)", options=GESETZ_STATUS_OPTIONS, width="medium"),
                "Wochenstd": st.column_config.NumberColumn("Wochenstd.", min_value=1.0, max_value=60.0, default=37.0, step=0.5),
                "Prozent": st.column_config.NumberColumn("Anst. (%)", disabled=True), 
                "Max_Nacht": st.column_config.NumberColumn("Max Nacht", min_value=0, max_value=20, default=0),
                "Spezialdienst": st.column_config.TextColumn(
                    "Erlaubte Dienste (z.B. Ohne, F2, F7, X6, X7)", 
                    width="medium"
                ),
                "URL_Gesamt": st.column_config.NumberColumn("Urlaub Gesamt", min_value=0.0, max_value=50.0, default=25.0),
                "URL_Rest": st.column_config.NumberColumn("Urlaub Rest", min_value=0.0, max_value=50.0, default=25.0)
            }, 
            use_container_width=True, 
            height=600
        )
        if st.form_submit_button("💾 Spremembe ekipe potrdi", type="primary"):
            clean_edited = sanitize_team_df(edited_data)
            clean_edited["URL_Rest"] = clean_edited.apply(lambda row: min(row["URL_Gesamt"], row["URL_Rest"]), axis=1)
            st.session_state.staff_df_v69 = clean_edited
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

with tab_shifts:
    st.header("⏱️ 2. Dienste-Studio (Schichten schnell erstellen & Stunden festlegen)")
    with st.container(border=True):
        st.subheader("➕ Neuen Dienst erstellen (oder bestehenden überschreiben)")
        with st.form("quick_create_shift_form"):
            sc1, sc2, sc3, sc4 = st.columns([1.2, 2.2, 1.3, 1.8])
            with sc1:
                new_sh_code = st.text_input("1. Dienst-Kürzel:", placeholder="z. B. F3, X8, T6").strip().upper()
            with sc2:
                new_sh_name = st.text_input("2. Name / Beschreibung:", placeholder="z. B. Zwischendienst / Kurzdienst").strip()
            with sc3:
                new_sh_hours = st.number_input("3. Dauer in Stunden (h):", min_value=0.5, max_value=24.0, value=8.0, step=0.25, format="%.2f")
            with sc4:
                new_sh_type = st.selectbox("4. Dienst-Kategorie:", ["Tagdienst Pflege", "Nachtdienst", "Speisesaal / Sonder"])

            st.markdown("**5. Welche Berufsgruppen dürfen diesen Dienst standardmäßig arbeiten?**")
            rc1, rc2, rc3, rc4, rc5 = st.columns([1, 1, 1, 1, 1.4])
            with rc1:
                allow_dgkp = st.checkbox("🩺 DGKP / Leitung", value=True)
            with rc2:
                allow_pfa = st.checkbox("💉 PFA", value=True)
            with rc3:
                allow_pa = st.checkbox("🏥 PA", value=False)
            with rc4:
                allow_hh = st.checkbox("🍽️ HH", value=False)
            with rc5:
                save_new_shift_btn = st.form_submit_button("💾 Dienst sofort anlegen", type="primary", use_container_width=True)

            if save_new_shift_btn:
                if not new_sh_code or new_sh_code in ["OFF", "..."]:
                    st.error("Bitte ein gültiges Dienst-Kürzel eingeben!")
                else:
                    df_sh = st.session_state.shifts_df_v69.copy()
                    new_entry = pd.DataFrame([{
                        "Kürzel": new_sh_code,
                        "Bezeichnung": new_sh_name if new_sh_name else f"Dienst {new_sh_code}",
                        "Stunden": float(new_sh_hours),
                        "Typ": new_sh_type,
                        "Erlaubt_DGKP": bool(allow_dgkp),
                        "Erlaubt_PFA": bool(allow_pfa),
                        "Erlaubt_PA": bool(allow_pa),
                        "Erlaubt_HH": bool(allow_hh)
                    }])
                    df_sh = pd.concat([df_sh, new_entry], ignore_index=True)
                    df_sh = sanitize_shifts_df(df_sh)
                    st.session_state.shifts_df_v69 = df_sh
                    df_sh.to_csv("shifts_data.csv", index=False)
                    st.session_state.shifts_editor_ver += 1
                    st.success(f"✅ Dienst **{new_sh_code}** ({new_sh_hours}h) wurde erfolgreich gespeichert!")
                    st.rerun()

    st.divider()
    st.subheader("📋 Alle aktiven Dienste im System (Direkt editierbar & löschbar)")
    with st.form("edit_all_shifts_form"):
        edited_shifts_df = st.data_editor(
            st.session_state.shifts_df_v69,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key=f"shifts_table_editor_{st.session_state.shifts_editor_ver}",
            column_config={
                "Kürzel": st.column_config.TextColumn("Dienst-Kürzel", width="small", required=True),
                "Bezeichnung": st.column_config.TextColumn("Bezeichnung / Name", width="medium"),
                "Stunden": st.column_config.NumberColumn("Stunden (h)", min_value=0.5, max_value=24.0, step=0.25, format="%.2f"),
                "Typ": st.column_config.SelectboxColumn("Kategorie", options=["Tagdienst Pflege", "Nachtdienst", "Speisesaal / Sonder"], width="medium"),
                "Erlaubt_DGKP": st.column_config.CheckboxColumn("Für DGKP/Leitung"),
                "Erlaubt_PFA": st.column_config.CheckboxColumn("Für PFA"),
                "Erlaubt_PA": st.column_config.CheckboxColumn("Für PA"),
                "Erlaubt_HH": st.column_config.CheckboxColumn("Für HH")
            }
        )
        col_sh_btn1, col_sh_btn2 = st.columns([2, 1])
        with col_sh_btn1:
            save_table_shifts = st.form_submit_button("💾 Änderungen an der Dienste-Tabelle speichern", type="primary", use_container_width=True)
        with col_sh_btn2:
            reset_shifts_btn = st.form_submit_button("🔄 Standard-Dienste wiederherstellen", use_container_width=True)

        if save_table_shifts:
            clean_sh = sanitize_shifts_df(edited_shifts_df)
            st.session_state.shifts_df_v69 = clean_sh
            clean_sh.to_csv("shifts_data.csv", index=False)
            st.session_state.shifts_editor_ver += 1
            st.success("✅ Dienste-Katalog aktualisiert!")
            st.rerun()

        if reset_shifts_btn:
            default_sh = get_default_shifts_df()
            st.session_state.shifts_df_v69 = default_sh
            default_sh.to_csv("shifts_data.csv", index=False)
            st.session_state.shifts_editor_ver += 1
            st.rerun()

# --- NEUER TAB 3: StPAVO PERSONALRECHNER (STEIERMARK) ---
with tab_pavo:
    st.header("🧮 3. StPAVO Steiermark – Personalberechnung nach Pflegestufen & Qualifikations-Mix")
    st.markdown(
        "Trage hier die aktuelle Anzahl der **Bewohnerinnen und Bewohner je Pflegegeldstufe (Stufe 0 bis 7)** für **Abteilung B** und **Abteilung H** ein. "
        "Das System berechnet sofort den gesetzlichen **SOLL-Personalbedarf in VZÄ (37h)**, den **täglichen Personalbedarf auf der Station** "
        "sowie die **prozentuale Aufteilung (DGKP, PFA, PA, Heimhilfe)** im Vergleich zu deinem aktuellen Team!"
    )

    st.subheader("1. Bewohneranzahl nach Pflegegeldstufen (Stufe 0 bis 7) eingeben")
    edited_pavo = st.data_editor(
        st.session_state.pavo_df_v69,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Abteilung": st.column_config.TextColumn("Wohnbereich / Station", disabled=True),
            "Stufe_0": st.column_config.NumberColumn("Stufe 0 (Ohne)", min_value=0, max_value=100, step=1),
            "Stufe_1": st.column_config.NumberColumn("Stufe 1", min_value=0, max_value=100, step=1),
            "Stufe_2": st.column_config.NumberColumn("Stufe 2", min_value=0, max_value=100, step=1),
            "Stufe_3": st.column_config.NumberColumn("Stufe 3", min_value=0, max_value=100, step=1),
            "Stufe_4": st.column_config.NumberColumn("Stufe 4", min_value=0, max_value=100, step=1),
            "Stufe_5": st.column_config.NumberColumn("Stufe 5", min_value=0, max_value=100, step=1),
            "Stufe_6": st.column_config.NumberColumn("Stufe 6", min_value=0, max_value=100, step=1),
            "Stufe_7": st.column_config.NumberColumn("Stufe 7", min_value=0, max_value=100, step=1),
        },
        key="pavo_editor_table"
    )
    if not edited_pavo.equals(st.session_state.pavo_df_v69):
        st.session_state.pavo_df_v69 = edited_pavo
        edited_pavo.to_csv("pavo_data.csv", index=False)

    with st.expander("⚙️ StPAVO Steiermark Schlüssel & Qualifikations-Prozente feinjustieren (Optional)", expanded=False):
        p_col1, p_col2, p_col3, p_col4 = st.columns(4)
        with p_col1:
            pct_dgkp = st.number_input("Ziel-Quote DGKP (% min.):", min_value=10.0, max_value=60.0, value=20.0, step=1.0)
        with p_col2:
            pct_pfa = st.number_input("Ziel-Quote PFA (% Richtwert):", min_value=0.0, max_value=60.0, value=15.0, step=1.0)
        with p_col3:
            pct_pa = st.number_input("Ziel-Quote PA (% Richtwert):", min_value=10.0, max_value=80.0, value=45.0, step=1.0)
        with p_col4:
            pct_hh = st.number_input("Ziel-Quote Heimhilfe (% max.):", min_value=0.0, max_value=40.0, value=20.0, step=1.0)
        st.caption(
            "Standard-Personalschlüssel StPAVO (Bewohner pro 1 VZÄ): "
            "Stufe 0 = 1:24 | Stufe 1 = 1:12 | Stufe 2 = 1:7,5 | Stufe 3 = 1:4,0 | Stufe 4 = 1:2,5 | Stufe 5 = 1:2,0 | Stufe 6 = 1:1,5 | Stufe 7 = 1:1,5"
        )

    # Berechnung der VZÄ je Station nach StPAVO
    stufen_cols = ["Stufe_0", "Stufe_1", "Stufe_2", "Stufe_3", "Stufe_4", "Stufe_5", "Stufe_6", "Stufe_7"]
    station_results = []
    total_residents = 0
    total_soll_vza = 0.0

    for _, p_row in st.session_state.pavo_df_v69.iterrows():
        abt_n = str(p_row["Abteilung"])
        bew_sum = sum(int(p_row.get(sc, 0)) for sc in stufen_cols)
        vza_sum = sum(float(p_row.get(sc, 0)) / DEFAULT_PAVO_KEYS[sc] for sc in stufen_cols)
        
        # Umrechnung VZÄ -> Täglicher Schichtbedarf im Tagdienst:
        # Netto-Arbeitsstunden pro VZÄ pro Woche (inkl. Urlaub/Krankenstand/Fortbildung ~80% Anwesenheit = ca. 29.6h/Woche netto)
        # Nachtdienst (1x N1 + 1x N2 hausweit) bindet ca. 3.3 VZÄ pro Station (6.6 VZÄ gesamt).
        netto_tag_vza = max(1.0, vza_sum - 3.2)
        daily_netto_hours = (netto_tag_vza * 29.8) / 7.0
        # Bei durchschnittlich ~11.2h Schichtlänge im Tagdienst:
        daily_persons_tag = max(1, int(round(daily_netto_hours / 11.2)))
        
        total_residents += bew_sum
        total_soll_vza += vza_sum
        station_results.append({
            "Wohnbereich": abt_n,
            "Bewohner Gesamt": bew_sum,
            "Gesetzl. SOLL (VZÄ à 37h)": round(vza_sum, 2),
            "SOLL Wochenstunden": round(vza_sum * 37.0, 1),
            "Empfohlene Tagdienst-Besetzung (Köpfe/Tag)": f"{daily_persons_tag} Pflegekräfte / Tag",
            "Empf_Int": daily_persons_tag
        })

    df_stat_res = pd.DataFrame(station_results)

    # Vergleich mit IST-Personalstand aus Tab 1
    df_team_curr = sanitize_team_df(st.session_state.staff_df_v69)
    ist_vza_total = (df_team_curr["Wochenstd"].sum() / 37.0)
    diff_vza = ist_vza_total - total_soll_vza

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("👥 Bewohner Gesamt (B + H)", f"{total_residents} Pers.")
    m2.metric("⚖️ StPAVO SOLL-Personal", f"{total_soll_vza:.2f} VZÄ")
    m3.metric("🏥 Dein IST-Personal (Tab 1)", f"{ist_vza_total:.2f} VZÄ")
    m4.metric("📊 Differenz (IST - SOLL)", f"{diff_vza:+.2f} VZÄ")

    st.subheader("2. Täglicher Personalbedarf pro Station (auf Basis der Pflegestufen)")
    st.dataframe(df_stat_res.drop(columns=["Empf_Int"]), use_container_width=True, hide_index=True)

    col_apply_pavo1, col_apply_pavo2 = st.columns([2, 1])
    with col_apply_pavo1:
        empf_b = df_stat_res.loc[df_stat_res["Wohnbereich"] == "Abteilung B", "Empf_Int"].values[0] if len(df_stat_res) > 0 else 4
        empf_h = df_stat_res.loc[df_stat_res["Wohnbereich"] == "Abteilung H", "Empf_Int"].values[0] if len(df_stat_res) > 1 else 4
        st.info(
            f"💡 **Täglicher Besetzungs-Richtwert laut Pflegestufen:** "
            f"**Abteilung B:** `{empf_b}` Personen/Tag (+ Speisesaal) | **Abteilung H:** `{empf_h}` Personen/Tag | "
            f"**Nachtdienst hausweit:** `1x N1 (DGKP) + 1x N2 (PFA/PA)` (Aktuell im KI-Planer aktiv: B={st.session_state.target_min_b}, H={st.session_state.target_min_h})."
        )
    with col_apply_pavo2:
        if st.button("🔗 Diesen Tagesbedarf für KI-Dienstplan übernehmen", type="primary", use_container_width=True):
            st.session_state.target_min_b = int(empf_b)
            st.session_state.target_min_h = int(empf_h)
            st.success(f"✅ Tagesbedarf (Abt. B = {empf_b}, Abt. H = {empf_h}) wurde für den KI-Planer übernommen!")

    st.divider()
    st.subheader("3. Prozentuale Aufteilung nach Berufsgruppen (StPAVO Qualifikations-Mix: SOLL vs. IST)")

    # IST VZÄ & Prozente nach Rollen berechnen
    vza_dgkp_ist = df_team_curr[df_team_curr["Rolle"].isin(["DGKP", "Leitung"])]["Wochenstd"].sum() / 37.0
    vza_pfa_ist = df_team_curr[df_team_curr["Rolle"] == "PFA"]["Wochenstd"].sum() / 37.0
    vza_pa_ist = df_team_curr[df_team_curr["Rolle"] == "Pflegeassistenz"]["Wochenstd"].sum() / 37.0
    vza_hh_ist = df_team_curr[df_team_curr["Rolle"] == "Heimhelfer"]["Wochenstd"].sum() / 37.0

    pct_dgkp_ist = (vza_dgkp_ist / ist_vza_total * 100.0) if ist_vza_total > 0 else 0.0
    pct_pfa_ist = (vza_pfa_ist / ist_vza_total * 100.0) if ist_vza_total > 0 else 0.0
    pct_pa_ist = (vza_pa_ist / ist_vza_total * 100.0) if ist_vza_total > 0 else 0.0
    pct_hh_ist = (vza_hh_ist / ist_vza_total * 100.0) if ist_vza_total > 0 else 0.0

    soll_dgkp_vza = total_soll_vza * (pct_dgkp / 100.0)
    soll_pfa_vza = total_soll_vza * (pct_pfa / 100.0)
    soll_pa_vza = total_soll_vza * (pct_pa / 100.0)
    soll_hh_vza = total_soll_vza * (pct_hh / 100.0)

    qual_mix_df = pd.DataFrame([
        {
            "Berufsgruppe (StPAVO Steiermark)": "🩺 DGKP (inkl. Leitung)",
            "Gesetzl. Vorgabe (%)": f"mind. {pct_dgkp:.1f} %",
            "IST-Anteil im Team (%)": f"{pct_dgkp_ist:.1f} %",
            "SOLL (VZÄ)": round(soll_dgkp_vza, 2),
            "IST (VZÄ)": round(vza_dgkp_ist, 2),
            "Differenz (VZÄ)": round(vza_dgkp_ist - soll_dgkp_vza, 2),
            "Täglich im Tagdienst (Hausweit)": f"mind. {max(2, int(round((empf_b + empf_h) * (pct_dgkp / 100.0))))} Pers./Tag",
            "StPAVO Status": "🟢 Erfüllt" if pct_dgkp_ist >= pct_dgkp and vza_dgkp_ist >= soll_dgkp_vza - 0.2 else "🔴 Zu wenig DGKP"
        },
        {
            "Berufsgruppe (StPAVO Steiermark)": "💉 Pflegefachassistenz (PFA)",
            "Gesetzl. Vorgabe (%)": f"Richtwert {pct_pfa:.1f} %",
            "IST-Anteil im Team (%)": f"{pct_pfa_ist:.1f} %",
            "SOLL (VZÄ)": round(soll_pfa_vza, 2),
            "IST (VZÄ)": round(vza_pfa_ist, 2),
            "Differenz (VZÄ)": round(vza_pfa_ist - soll_pfa_vza, 2),
            "Täglich im Tagdienst (Hausweit)": f"ca. {max(1, int(round((empf_b + empf_h) * (pct_pfa / 100.0))))} Pers./Tag",
            "StPAVO Status": "🟢 Optimal" if vza_pfa_ist >= soll_pfa_vza - 0.5 else "🟡 Ausbaufähig (durch DGKP/PA kompensierbar)"
        },
        {
            "Berufsgruppe (StPAVO Steiermark)": "🏥 Pflegeassistenz (PA)",
            "Gesetzl. Vorgabe (%)": f"Richtwert {pct_pa:.1f} %",
            "IST-Anteil im Team (%)": f"{pct_pa_ist:.1f} %",
            "SOLL (VZÄ)": round(soll_pa_vza, 2),
            "IST (VZÄ)": round(vza_pa_ist, 2),
            "Differenz (VZÄ)": round(vza_pa_ist - soll_pa_vza, 2),
            "Täglich im Tagdienst (Hausweit)": f"ca. {max(2, int(round((empf_b + empf_h) * (pct_pa / 100.0))))} Pers./Tag",
            "StPAVO Status": "🟢 Erfüllt" if (pct_dgkp_ist + pct_pfa_ist + pct_pa_ist) >= (pct_dgkp + pct_pfa + pct_pa - 1.0) else "🔴 Pflege-Quote (<80%) prüfen"
        },
        {
            "Berufsgruppe (StPAVO Steiermark)": "🍽️ Heimhilfe (HH)",
            "Gesetzl. Vorgabe (%)": f"max. {pct_hh:.1f} %",
            "IST-Anteil im Team (%)": f"{pct_hh_ist:.1f} %",
            "SOLL (VZÄ)": round(soll_hh_vza, 2),
            "IST (VZÄ)": round(vza_hh_ist, 2),
            "Differenz (VZÄ)": round(vza_hh_ist - soll_hh_vza, 2),
            "Täglich im Tagdienst (Hausweit)": f"max. {max(1, int(round((empf_b + empf_h) * (pct_hh / 100.0))))} Pers./Tag",
            "StPAVO Status": "🟢 Gesetzestreu (≤ Max)" if pct_hh_ist <= pct_hh + 1.0 else "⚠️ Über Max.-Quote (Max. 20%)"
        }
    ])
    st.dataframe(qual_mix_df, use_container_width=True, hide_index=True)

# --- TAB 4: KOMPAKTER MONATSKALENDER (GETEILTE KLEINERE TABELLEN FÜR BESSERE ÜBERSICHT) ---
with tab3:
    st.header("🗓️ 4. Kompakt-Kalender für Urlaub, Wünsche & Fix-Dienste (Monatsübersicht)")
    st.markdown(
        "**Kompakt-Design für volle Monatsübersicht:** Die Tabellen sind nun in **kleinere Stations-Blöcke (Abteilung B, H, F)** unterteilt "
        "und nutzen kurze 3-Buchstaben-Codes (`URL`, `KRA`, `ZA`, `SU`, `ENT`, `WUN`, `MUS` oder Schichtkürzel wie `F2`, `X7`, `N1`), "
        "damit **alle 31 Tage nebeneinander auf den Bildschirm passen**!"
    )
    
    current_staff = st.session_state.staff_df_v69["Name"].dropna().astype(str).str.strip().tolist()
    
    # Ultra-kompakte Spaltenüberschriften (damit 31 Tage ohne langes Scrollen passen)
    day_cols = []
    weekend_or_hol_days = []
    for d in range(1, num_days + 1):
        dow = (d - 1 + first_day_of_month_weekday) % 7
        is_holiday = (date(leto, mesec, d) in at_holidays) or (mesec == 12 and d in [24, 31])
        if is_holiday: 
            col_name = f"{d}⭐"
            weekend_or_hol_days.append(col_name)
        elif dow >= 5: 
            col_name = f"{d}🔴"
            weekend_or_hol_days.append(col_name)
        else: 
            col_name = f"{d}."
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
                    val_cell = normalize_cal_cell(row_data.iloc[i])
                    new_mat.at[emp, target_day_cols[i]] = val_cell
        return new_mat

    if "abs_matrix_v69" not in st.session_state:
        if os.path.exists(cal_autosave_path):
            try:
                with open(cal_autosave_path, "rb") as f:
                    saved_cal = read_csv_smart(f.read(), is_index_col=True)
                st.session_state.raw_uploaded_cal = saved_cal
                st.session_state.abs_matrix_v69 = sync_calendar_df(saved_cal, current_staff, day_cols)
            except Exception:
                st.session_state.abs_matrix_v69 = pd.DataFrame("", index=current_staff, columns=day_cols)
        else:
            st.session_state.abs_matrix_v69 = pd.DataFrame("", index=current_staff, columns=day_cols)
    else:
        if st.session_state.get("needs_cal_resync") and "raw_uploaded_cal" in st.session_state:
            st.session_state.abs_matrix_v69 = sync_calendar_df(st.session_state.raw_uploaded_cal, current_staff, day_cols)
            st.session_state.needs_cal_resync = False
        else:
            st.session_state.abs_matrix_v69 = sync_calendar_df(st.session_state.abs_matrix_v69, current_staff, day_cols)

    dynamic_fix_options = [
        f"📌 {row['Kürzel']} (Fix {row['Stunden']}h – {row['Bezeichnung']})"
        for _, row in SHIFTS_DF_CURRENT.iterrows()
    ]
    entry_options = [
        "", 
        "URL (Urlaub)", "SU (Sonderurlaub)", "ENT (Entlastung)", "KRA (Krank)", 
        "ZA (Zeitausgleich)", "WUN (Wunsch-Frei)", "MUS (Muss arbeiten)"
    ] + dynamic_fix_options + ["🗑️ LÖSCHEN (Zelle leeren)"]

    col_bak1, col_bak2 = st.columns(2)
    with col_bak1:
        st.download_button(
            label="📥 Kalender / Fix-Dienste als Backup speichern", 
            data=st.session_state.abs_matrix_v69.to_csv(index=True).encode('utf-8'), 
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
            force_cal_btn = st.button("🔄 Hochgeladenen Kalender jetzt erzwingend übernehmen", type="secondary")
            if st.session_state.get("last_cal_hash") != cal_hash or force_cal_btn:
                try:
                    uploaded_cal = read_csv_smart(raw_cal_bytes, is_index_col=True)
                    st.session_state.raw_uploaded_cal = uploaded_cal
                    synced_cal = sync_calendar_df(uploaded_cal, current_staff, day_cols)
                    st.session_state.abs_matrix_v69 = synced_cal
                    synced_cal.to_csv(cal_autosave_path, index=True)
                    st.session_state.last_cal_hash = cal_hash
                    st.session_state.cal_editor_ver += 1
                    st.success("✅ Kalender sofort geladen und auf Kompakt-Format optimiert!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Fehler beim Laden des Kalenders: {e}")

    st.subheader("⚡ Schnelleingabe (Urlaube, Wünsche & Fix-Dienste eintragen)")
    with st.form("bulk_add_form"):
        b_col1, b_col2, b_col3, b_col4 = st.columns([2, 2, 1.8, 1])
        with b_col1: 
            selected_emps = st.multiselect("1. Mitarbeiter auswählen:", current_staff)
        with b_col2: 
            d_start, d_end = st.slider("2. Von Tag bis Tag:", 1, num_days, (1, 5))
        with b_col3: 
            selected_reason = st.selectbox("3. Urlaub, Wunsch oder Fix-Dienst:", entry_options[1:])
        with b_col4: 
            st.write("")
            st.write("")
            submit_bulk = st.form_submit_button("➕ Eintragen", type="primary", use_container_width=True)
            
        if submit_bulk and selected_emps:
            val_to_write = ""
            if "LÖSCHEN" in selected_reason:
                val_to_write = ""
            elif selected_reason.startswith("📌"):
                val_to_write = selected_reason.split(" ")[1].strip()
            else:
                val_to_write = selected_reason.split(" ")[0].strip()
            for emp in selected_emps:
                for d in range(d_start, d_end + 1):
                    target_col = day_cols[d-1]
                    st.session_state.abs_matrix_v69.at[emp, target_col] = val_to_write
            st.session_state.raw_uploaded_cal = st.session_state.abs_matrix_v69.copy()
            st.session_state.abs_matrix_v69.to_csv(cal_autosave_path, index=True)
            st.session_state.cal_editor_ver += 1
            st.success("✅ Erfolgreich eingetragen & gespeichert!")
            st.rerun()

    st.caption(
        "🎨 **Kürzel-Legende:** `URL` = Urlaub (Blau) | `KRA` = Krank (Rot) | `ZA` = Zeitausgleich (Dunkel) | `SU`/`ENT` = Sonderurlaub/Entlastung | "
        "`WUN` = Wunsch-Frei (Grün) | `MUS` = Muss arbeiten | `F2`, `F7`, `X7`, `N1`... = Fixierter Dienst (Gelb)"
    )

    def style_compact_cal(val, col_name):
        style = "text-align: center; font-size: 12px; "
        v = str(val).strip().upper()
        if v == "URL":
            style += "background-color: #d1ecf1; color: #0c5460; font-weight: bold; "
        elif v == "KRA":
            style += "background-color: #f8d7da; color: #721c24; font-weight: bold; "
        elif v == "ZA":
            style += "background-color: #343a40; color: white; font-weight: bold; "
        elif v in ["SU", "PFL"]:
            style += "background-color: #ffebd6; color: #cc5500; font-weight: bold; "
        elif v == "ENT":
            style += "background-color: #f3e8ff; color: #4b0082; font-weight: bold; "
        elif v == "WUN":
            style += "background-color: #d4edda; color: #155724; font-weight: bold; "
        elif v == "MUS":
            style += "background-color: #e2e3e5; color: #383d41; font-weight: bold; "
        elif v in SHIFTS_HUNDREDTHS and v != "OFF":
            style += "background-color: #fff3cd; color: #856404; font-weight: bold; "
        elif col_name in weekend_or_hol_days:
            style += "background-color: #f4f4f8; "
        return style

    def apply_cal_styles(df):
        return df.style.apply(lambda x: [style_compact_cal(v, x.name) for v in x], axis=0)

    cal_col_config = {}
    for c in day_cols:
        cal_col_config[c] = st.column_config.TextColumn(c, width="small")

    view_mode_cal = st.radio(
        "Ansichts-Modus wählen:",
        ["🏥 Aufgeteilt in 3 kompakte Stations-Tabellen (Abt. B, H, F – Empfohlen)", "📋 Alle Mitarbeiter in einer Kompakt-Tabelle"],
        horizontal=True
    )

    def render_compact_cal_block(staff_subset, block_key):
        sub_cal = st.session_state.abs_matrix_v69.loc[staff_subset].copy()
        row_h = min(480, max(140, int(len(staff_subset) * 36 + 45)))
        try:
            edited_sub_cal = st.data_editor(
                apply_cal_styles(sub_cal),
                column_config=cal_col_config,
                use_container_width=True,
                height=row_h,
                key=f"cal_ed_{block_key}_{st.session_state.cal_editor_ver}"
            )
        except Exception:
            edited_sub_cal = st.data_editor(
                sub_cal,
                column_config=cal_col_config,
                use_container_width=True,
                height=row_h,
                key=f"cal_ed_{block_key}_{st.session_state.cal_editor_ver}"
            )
        cleaned_sub = edited_sub_cal.applymap(normalize_cal_cell)
        if not cleaned_sub.equals(sub_cal):
            st.session_state.abs_matrix_v69.loc[staff_subset, day_cols] = cleaned_sub[day_cols].values
            st.session_state.raw_uploaded_cal = st.session_state.abs_matrix_v69.copy()
            st.session_state.abs_matrix_v69.to_csv(cal_autosave_path, index=True)
            st.session_state.cal_editor_ver += 1
            st.rerun()

    if "Aufgeteilt" in view_mode_cal:
        for dept_label, dept_icon in [("Abteilung B", "🔵"), ("Abteilung H", "🟢"), ("Abteilung F", "🟣")]:
            dept_emps = st.session_state.staff_df_v69[
                st.session_state.staff_df_v69["Abteilung"] == dept_label
            ]["Name"].dropna().astype(str).str.strip().tolist()
            dept_emps = [e for e in dept_emps if e in st.session_state.abs_matrix_v69.index]
            if dept_emps:
                st.markdown(f"**{dept_icon} {dept_label} ({len(dept_emps)} Mitarbeiter)**")
                render_compact_cal_block(dept_emps, dept_label.replace(" ", "_"))
    else:
        render_compact_cal_block(current_staff, "all_staff")

with tab2:
    st.header("📅 5. Automatische Dienstplangenerierung & Live-Editor")
    
    if "last_generated_df" not in st.session_state and os.path.exists(plan_autosave_path):
        try:
            loaded_plan = pd.read_csv(plan_autosave_path)
            st.session_state.last_generated_df = recalculate_plan_df(
                loaded_plan, st.session_state.staff_df_v69, num_days
            )
        except Exception:
            pass
    
    if st.button("🚀 Dienstplan neu berechnen (KI-Optimierung)", type="primary", use_container_width=True):
        
        try:
            with st.spinner("⏳ KI berechnet optimalen Dienstplan (Max. 1 DGKP in Nacht, StPAVO-Tagesbedarf, PFA/PA & Fix-Dienste aktiv)..."):
                
                df_clean = sanitize_team_df(st.session_state.staff_df_v69)
                staff_list = df_clean.to_dict("records")
                
                st.session_state.absences_v69 = []
                st.session_state.work_rules_v69 = []
                st.session_state.fixed_shifts_v69 = []
                
                for emp_name in current_staff:
                    emp_id_list = df_clean.loc[df_clean["Name"] == emp_name, "ID"].values
                    if len(emp_id_list) == 0: 
                        continue
                    emp_id = int(emp_id_list[0])
                    emp_role_val = str(df_clean.loc[df_clean["ID"] == emp_id, "Rolle"].values[0]).strip()
                    
                    for d in range(1, num_days + 1):
                        col_name = day_cols[d-1]
                        val = st.session_state.abs_matrix_v69.at[emp_name, col_name]
                        
                        if pd.notna(val) and str(val).strip() != "":
                            val_str = str(val).upper().replace("📌", "").strip()
                            if val_str in ["NAN", "NONE", "<NA>", "NULL", ""]: 
                                continue
                                
                            day_idx = d - 1
                            reason = ""
                            
                            matched_manual_sh = None
                            for sh_c in MANUAL_SHIFT_CODES:
                                if val_str == sh_c or val_str.startswith(sh_c + " "):
                                    matched_manual_sh = sh_c
                                    break
                                    
                            if matched_manual_sh is not None:
                                if emp_role_val in ["DGKP", "Leitung"] and matched_manual_sh == "N2":
                                    matched_manual_sh = "N1"
                                st.session_state.fixed_shifts_v69.append({
                                    "emp_id": emp_id, "emp_name": emp_name, "day": day_idx, "shift": matched_manual_sh
                                })
                                continue

                            if "URL" in val_str: reason = "URL"
                            elif "SU" in val_str: reason = "SU"
                            elif "ENT" in val_str: reason = "ENT"
                            elif "KRA" in val_str: reason = "KRA"
                            elif "ZA" in val_str: reason = "ZA"
                            elif "PFL" in val_str: reason = "PFLEGE"
                            elif "WUN" in val_str or "FREI" in val_str: reason = "WUNSCH-FREI"
                            elif "MUS" in val_str: reason = "MUSS-ARBEITEN"
                            
                            if reason in ["URL", "SU", "ENT", "KRA", "ZA", "PFLEGE", "WUNSCH-FREI"]:
                                st.session_state.absences_v69.append({"emp_id": emp_id, "emp_name": emp_name, "day": day_idx, "reason": reason})
                            elif reason == "MUSS-ARBEITEN":
                                st.session_state.work_rules_v69.append({"emp_id": emp_id, "emp_name": emp_name, "day": day_idx, "rule": reason})

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
                                if v_last in NIGHT_SHIFTS:
                                    prev_month_last_day_night[s["ID"]] = True
                                if v_sec in NIGHT_SHIFTS:
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
                        model.Add(night_d == sum(work[(s["ID"], d, n_sh)] for n_sh in NIGHT_SHIFTS if n_sh in shifts))
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

                for r in st.session_state.work_rules_v69:
                    if r["day"] < num_days:
                        hour_deviations.append(work[(r["emp_id"], r["day"], "OFF")] * 800000)

                fixed_Set = set()
                for fx in st.session_state.fixed_shifts_v69:
                    if fx["day"] < num_days and fx["shift"] in shifts:
                        fixed_Set.add((fx["emp_id"], fx["day"]))
                        hour_deviations.append((1 - work[(fx["emp_id"], fx["day"], fx["shift"])]) * 1800000)

                dow_keys = ["MO", "DI", "MI", "DO", "FR", "SA", "SO"]
                for s in staff_list:
                    allowed_shifts = resolve_allowed_shifts_for_person(s, SHIFTS_DF_CURRENT)
                    for fx in st.session_state.fixed_shifts_v69:
                        if fx["emp_id"] == s["ID"] and fx["shift"] in shifts and fx["shift"] not in allowed_shifts:
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

                        if gesetz == "Mutterschutz (MSchG)":
                            for n_sh in NIGHT_SHIFTS:
                                if n_sh in shifts:
                                    model.Add(work[(s["ID"], d, n_sh)] == 0)
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
                                has_muss = any(r["day"] == d and r["emp_id"] == s["ID"] for r in st.session_state.work_rules_v69)
                                if not has_muss:
                                    model.Add(work[(s["ID"], d, "OFF")] == 1)
                                
                        if s["Rolle"] == "DGKP" and (s["ID"], d) not in fixed_Set:
                            if dow >= 5 or is_holiday:
                                if "X7" in allowed_shifts and "X7" in shifts:
                                    for sh in ["X4", "X6", "F2", "F7", "JED", "MS", "SM", "N2"]:
                                        if sh in shifts:
                                            model.Add(work[(s["ID"], d, sh)] == 0)

                    if s["Max_Nacht"] > 0 and gesetz != "Mutterschutz (MSchG)":
                        over_nacht = model.NewIntVar(0, 31, f'over_n_{s["ID"]}')
                        model.Add(sum(is_night[(s["ID"], d)] for d in range(num_days)) - int(s["Max_Nacht"]) <= over_nacht)
                        hour_deviations.append(over_nacht * 50000)

                for a in st.session_state.absences_v69:
                    if a["day"] < num_days: 
                        model.Add(work[(a["emp_id"], a["day"], "OFF")] == 1)

                for s in staff_list:
                    w_std = float(s.get("Wochenstd", 37.0))
                    daily_avg = w_std / 7.0
                    standard_target = daily_avg * num_days
                    saldo_alt = float(s.get("Saldo_Alt", 0.0))
                    gesetz = str(s.get("Gesetz_Status", "Normal")).strip()
                    
                    emp_paid_abs_days = sum(
                        1 for a in st.session_state.absences_v69 
                        if a["emp_id"] == s["ID"] and a["reason"] in PAID_ABSENCES
                    )
                    paid_abs_hours_100 = int(round(emp_paid_abs_days * daily_avg * 100))
                    adjusted_target = max(0, int(round((standard_target - saldo_alt) * 100)) - paid_abs_hours_100)
                    
                    total_worked = model.NewIntVar(0, 40000, f'tot_{s["ID"]}')
                    model.Add(total_worked == sum(work[(s["ID"], d, sh)] * shifts[sh] for d in range(num_days) for sh in shifts.keys()))

                    under_work = model.NewIntVar(0, 30000, f'under_{s["ID"]}')
                    over_work = model.NewIntVar(0, 30000, f'over_{s["ID"]}')
                    
                    model.Add(under_work >= adjusted_target - total_worked)
                    model.Add(over_work >= total_worked - adjusted_target)
                    
                    hour_deviations.append(under_work * 250) 
                    if gesetz in ["Altersteilzeit (ATZ)", "Elternteilzeit (ETZ)", "Mutterschutz (MSchG)", "Pflegekarenz / Teilzeit"]:
                        hour_deviations.append(over_work * 300)
                    else:
                        hour_deviations.append(over_work * 12)

                # --- STATIONS-ABDECKUNG (INKL. StPAVO TAGESBEDARF & PFA/PA) ---
                day_sh = [sh for sh in DAY_CARE_SHIFTS if sh in shifts]
                dgkp_shifts = [sh for sh in DGKP_DAY_SHIFTS if sh in shifts]
                
                o_b_all = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B"]
                o_h_all = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H"]
                o_dgkp_b = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] in ["DGKP", "Leitung"]]
                o_dgkp_h = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] in ["DGKP", "Leitung"]]
                o_dgkp_f = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung F" and s["Rolle"] in ["DGKP", "Leitung"]]
                o_dgkp_all = [s["ID"] for s in staff_list if s["Rolle"] in ["DGKP", "Leitung"]]
                o_pa_all = [s["ID"] for s in staff_list if s["Rolle"] in ["Pflegeassistenz", "PFA"]]
                
                b_shorts, h_shorts, jed_shorts, dg_shorts, n1_shorts, n2_shorts = {}, {}, {}, {}, {}, {}
                min_b_req = int(st.session_state.target_min_b)
                min_h_req = int(st.session_state.target_min_h)

                for d in range(num_days):
                    b_day = sum(work[(e, d, sh)] for e in o_b_all for sh in day_sh)
                    b_short = model.NewIntVar(0, 10, f'b_short_{d}')
                    model.Add(b_day + b_short >= min_b_req)
                    hour_deviations.append(b_short * 80000)
                    b_shorts[d] = b_short
                    
                    if "JED" in shifts:
                        jed_b = sum(work[(e, d, "JED")] for e in o_b_all)
                    else:
                        jed_b = 0
                    jed_short = model.NewIntVar(0, 10, f'jed_short_{d}')
                    model.Add(jed_b + jed_short >= 1)
                    hour_deviations.append(jed_short * 80000)
                    jed_shorts[d] = jed_short
                    
                    h_day = sum(work[(e, d, sh)] for e in o_h_all for sh in day_sh)
                    h_short = model.NewIntVar(0, 10, f'h_short_{d}')
                    model.Add(h_day + h_short >= min_h_req)
                    hour_deviations.append(h_short * 80000)
                    h_shorts[d] = h_short
                    
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
                    if "N2" in shifts:
                        for e_dg in o_dgkp_all:
                            model.Add(work[(e_dg, d, "N2")] == 0)
                    
                    dgkp_night_sum = sum(is_night[(e, d)] for e in o_dgkp_all)
                    model.Add(dgkp_night_sum <= 1)
                    n1_short = model.NewIntVar(0, 1, f'n1_short_{d}')
                    model.Add(dgkp_night_sum + n1_short >= 1)
                    hour_deviations.append(n1_short * 250000)
                    n1_shorts[d] = n1_short
                    
                    pa_night_sum = sum(is_night[(e, d)] for e in o_pa_all)
                    model.Add(pa_night_sum <= 1)
                    n2_short = model.NewIntVar(0, 1, f'n2_short_{d}')
                    model.Add(pa_night_sum + n2_short >= 1)
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
                                    for a in st.session_state.absences_v69:
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
                    st.success("🎉 Dienstplan erfolgreich generiert!")
                    st.rerun()
                else:
                    st.error("🚨 UNBEKANNTER FEHLER: Modell konnte nicht gelöst werden.")
        except Exception as e: 
            st.error(f"⚠️ KRITISCHER SYSTEMFEHLER: {e}")

    if "last_generated_df" in st.session_state:
        df_rezultat = st.session_state.last_generated_df
        
        st.info(
            "✏️ **Live-Editor & Besetzungs-Check aktiv:** Doppelklicke auf eine beliebige Tageszelle (`1.` bis `31.`), tippe ein Schichtkürzel ein "
            "und drücke **Enter**. Die Stunden (`IST`, `ÜBERSTD.`, `SALDO`) und die Kontrollzeile aktualisieren sich sofort!"
        )
        
        def style_cells(val, col_name):
            style = ""
            if isinstance(val, str):
                if val == "...": style += "color: #b3b3b3; text-align: center; " 
                elif "🚨" in val: style += "background-color: #ffcccc; color: #cc0000; font-weight: bold; text-align: center; border: 2px solid red; " 
                elif "⚠️" in val: style += "color: #cc0000; font-weight: bold; " 
                elif "Wundmanager" in val or "Praxisanleiter" in val: style += "font-weight: bold; color: #0056b3; "
                elif val in NIGHT_SHIFTS: style += "background-color: #1e3a8a; color: white; font-weight: bold; text-align: center; border-radius: 4px; "
                elif "KRA" in val: style += "background-color: #f8d7da; color: #721c24; font-weight: bold; text-align: center; "
                elif "URL" in val: style += "background-color: #d1ecf1; color: #0c5460; font-weight: bold; text-align: center; "
                elif "SU" in val or "PFLEGE" in val: style += "background-color: #ffebd6; color: #cc5500; font-weight: bold; text-align: center; border: 1px solid #ffcc99; "
                elif "ENT" in val: style += "background-color: #f3e8ff; color: #4b0082; font-weight: bold; text-align: center; border: 1px solid #d8b4fe; "
                elif "ZA" in val: style += "background-color: #333333; color: white; font-weight: bold; text-align: center; border-radius: 4px; "
                elif "WUNSCH" in val: style += "background-color: #d4edda; color: #155724; font-weight: bold; text-align: center; "
                elif val in SHIFTS_HUNDREDTHS: style += "color: black; font-weight: 500; text-align: center; "

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
            "Rolle": st.column_config.TextColumn("Rolle", disabled=True, width="small"),
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
                recalculated_full = recalculate_plan_df(full_updated, st.session_state.staff_df_v69, num_days)
                st.session_state.last_generated_df = recalculated_full
                recalculated_full.to_csv(plan_autosave_path, index=False)
                st.session_state.plan_editor_ver += 1
                st.rerun()

            st.caption(f"📊 **Tägliche Besetzungs-Kontrolle ({dept_name} – reale Mitarbeiter):** Grün = Ziel erreicht | Gelb = Springer-Deckung | Rot = Abweichung")
            cov_df = build_coverage_summary_df(
                df_rezultat, dept_name, num_days, st.session_state.target_min_b, st.session_state.target_min_h
            )
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
    st.header("🚨 6. SOS Einspringer-Finder & 🔄 Smart-Tauschbörse")
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
                    had_night_before = (ausfall_tag > 1 and str(r.get(prev_col, "")) in NIGHT_SHIFTS)
                    if had_night_before:
                        continue
                    score = 100
                    gründe = []
                    if m_rolle == emp_role: 
                        score += 50
                        gründe.append("✅ Gleiche Rolle")
                    elif emp_role in ["PFA", "Pflegeassistenz"] and m_rolle in ["PFA", "Pflegeassistenz"]:
                        score += 40
                        gründe.append("✅ Kompatible Pflege-Rolle (PFA/PA)")
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
                
                df_test = recalculate_plan_df(df_test, st.session_state.staff_df_v69, num_days)
                audit_after = run_austrian_law_audit(
                    df_test, st.session_state.staff_df_v69, SHIFTS_DF_CURRENT, num_days, leto, mesec, first_day_of_month_weekday, at_holidays,
                    st.session_state.target_min_b, st.session_state.target_min_h
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
    st.header("📉 7. Überstunden-, Fairness- & Burnout-Radar")
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
            n_count = sum(1 for v in vals if v in NIGHT_SHIFTS)
            long_12h = sum(1 for v in vals if SHIFTS_HUNDREDTHS.get(v, 0) >= 1200 and v not in NIGHT_SHIFTS)
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
                "12h-Tagdienste": long_12h,
                "Nächte": n_count,
                "Burnout-Index": f"{load_score}%",
                "Belastungs-Status": status_ampel
            })
            
        radar_df = pd.DataFrame(radar_rows)
        st.subheader("⚖️ KI Fairness- & Belastungs-Radar pro Mitarbeiter")
        st.dataframe(radar_df.sort_values(by="ÜBERSTD.", ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("Bitte berechne zuerst den Dienstplan, um die Analyse zu sehen!")

with tab6:
    st.header("🛡️ 8. Steiermark Pflege- & Arbeitsrechts-Kompendium + Live-Inspektorat")
    st.markdown(
        "Alle relevanten **Bundes- und Landesgesetze für die Pflege in der Steiermark** zum täglichen Nachschlagen – "
        "inklusive automatischer Echtzeit-Prüfung deines aktuellen Dienstplans."
    )

    col_law1, col_law2 = st.columns(2)
    with col_law1:
        with st.expander("🤰 1. Mutterschutzgesetz (MSchG §§ 3–8)", expanded=True):
            st.markdown(
                "- **Absolutes Beschäftigungsverbot (§ 3 & § 5 MSchG):** 8 Wochen vor dem voraussichtlichen Entbindungstermin und 8 Wochen nach der Geburt (12 Wochen bei Früh-/Mehrlingsgeburt oder Kaiserschnitt).\n"
                "- **Absolutes Nachtarbeitsverbot (§ 6 MSchG):** Werdende und stillende Mütter dürfen zwischen **20:00 und 06:00 Uhr** nicht beschäftigt werden.\n"
                "- **Sonn- und Feiertagsverbot (§ 7 MSchG):** An Sonn- und gesetzlichen Feiertagen besteht Beschäftigungsverbot.\n"
                "- **Verbot von Überstunden & Langdiensten (§ 8 MSchG):** Tagesarbeitszeit darf **9,0 Stunden** und Wochenarbeitszeit **40,0 Stunden** keinesfalls überschreiten.\n"
                "- **Körperliche Schonung (§ 4 MSchG):** Verbot von schwerem Heben (> 5 kg regelmäßig / > 10 kg gelegentlich) sowie Schutz vor Infektionsgefahren."
            )
        with st.expander("⏳ 2. Altersteilzeit (§ 27 AlVG & SWÖ-KV) & Elternteilzeit (MSchG/VKG)", expanded=True):
            st.markdown(
                "- **Altersteilzeit (ATZ - § 27 AlVG):** Reduktion der Normalarbeitszeit auf **40 % bis 60 %** der vorherigen Arbeitszeit (z. B. bei 37h Vollzeit: **14,8h bis 22,2h/Woche**).\n"
                "- **Lohnausgleich & Sozialversicherung:** Arbeitnehmer erhält 50 % des Entgeltverlustes als Lohnausgleich (also **70 % bis 80 % des Letztgehalts**) bei **100 % Pensions-, Kranken- und Arbeitslosenversicherungsbeitragsgrundlage**.\n"
                "- **Mehrarbeits-Schutz in ATZ:** Regelmäßige Überstunden über die Geringfügigkeitsgrenze gefährden das AMS-Altersteilzeitgeld – die KI sperrt daher den Überstundenaufbau für ATZ-Mitarbeiter!\n"
                "- **Elternteilzeit (ETZ - §§ 15h ff MSchG / VKG):** Rechtsanspruch in Betrieben ab 21 Mitarbeitern (bei ≥ 3 Jahren Betriebszugehörigkeit). Vereinbarte Wochentage (`MO`–`SO`) sind verbindlich."
            )
        with st.expander("🏥 3. StPBG & StPAVO Steiermark (Personalschlüssel & Grade-Mix)", expanded=True):
            st.markdown(
                "- **Steiermärkische Personalausstattungsverordnung (StPAVO):** Verbindlicher Personalschlüssel nach Pflegegeldstufen (Stufe 0: 1:24 | Stufe 1: 1:12 | Stufe 2: 1:7,5 | Stufe 3: 1:4 | Stufe 4: 1:2,5 | Stufe 5: 1:2 | Stufe 6 & 7: 1:1,5).\n"
                "- **Qualifikations-Mix (Prozentuale Verteilung):** Mindestens **20 % DGKP**, ca. **60 % PFA & PA** (Gesamt-Pflegepersonal DGKP+PFA+PA mind. **80 %**), maximal **20 % Heimhilfe (HH)**.\n"
                "- **Nachtdienst-Vorgabe:** Hausweit **exakt 1x DGKP (`N1`) + 1x PFA/PA (`N2`)**. Eine Doppelbesetzung mit 2 DGKP in der Nacht ist im System hart gesperrt."
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
        with st.expander("🩺 5. GuKG (Kompetenzen DGKP, PFA & PA + Fortbildung)", expanded=True):
            st.markdown(
                "- **DGKP (§§ 12–16 GuKG):** Gesamtverantwortung für den Pflegeprozess, Pflegediagnostik, Planung und Evaluierung.\n"
                "- **Pflegefachassistenz (PFA - §§ 83a ff GuKG):** Eigenverantwortliche Durchführung übertragener Aufgaben in der Pflege und Diagnostik/Therapie ohne zwingende permanente Vor-Ort-Aufsicht.\n"
                "- **Pflegeassistenz (PA - § 83 GuKG):** Durchführung standardisierter Pflegemaßnahmen und Mitarbeit bei Diagnostik/Therapie unter Anordnung und Aufsicht.\n"
                "- **Gesetzliche Fortbildungspflicht (§ 63 & § 104c GuKG):** **60 Stunden** / 5 Jahre für **DGKP**; **40 Stunden** / 5 Jahre für **PFA & PA**."
            )
        with st.expander("🌙 6. Nachtschwerarbeitsgesetz (NSchG) & Pflegefreistellung (UrlG/AVRAG)", expanded=True):
            st.markdown(
                "- **NSchG-Zusatzurlaub (Art. XI NSchG):** Ab 50 geleisteten Nachtschwerarbeits-Diensten pro Jahr gebühren **2 zusätzliche Urlaubstage** (steigend bis auf 6 Zusatzurlaubstage).\n"
                "- **Pflegefreistellung (§ 16 UrlG):** Anspruch auf bezahlte Freistellung bis zu **1 regelmäßigen Wochenarbeitszeit** pro Arbeitsjahr zur notwendigen Pflege erkrankter naher Angehöriger.\n"
                "- **Pflegekarenz / Pflegeteilzeit (§ 14c/d AVRAG):** Vereinbarung für 1 bis 3 Monate zur Betreuung von Angehörigen ab Pflegegeldstufe 3."
            )

    st.divider()
    st.subheader("🕵️‍♂️ Automatischer Dienstplan-Prüfbericht (Live-Inspektorat Steiermark)")

    if "last_generated_df" in st.session_state:
        audit_df = run_austrian_law_audit(
            st.session_state.last_generated_df, 
            st.session_state.staff_df_v69, 
            SHIFTS_DF_CURRENT,
            num_days, leto, mesec, first_day_of_month_weekday, at_holidays,
            st.session_state.target_min_b, st.session_state.target_min_h
        )
        if audit_df.empty:
            st.success(
                "✅ **100% ZERTIFIZIERT & GESETZESTREU (Steiermark-Standard)!** Der aktuelle Dienstplan erfüllt alle Vorgaben: "
                "Maximal 1 DGKP in der Nacht, 2 freie Tage nach Nachtblock, Mutterschutz (MSchG), Altersteilzeit (ATZ) und StPAVO-Besetzung."
            )
        else:
            st.warning(f"⚠️ **Hinweis:** Bei der Überprüfung wurden **{len(audit_df)} Abweichungen / Hinweise** gefunden:")
            st.dataframe(audit_df, use_container_width=True, hide_index=True)
    else:
        st.info("Sobald du einen Dienstplan berechnet hast, erscheint hier automatisch das Prüfergebnis nach Steiermark- & Bundesrecht.")
