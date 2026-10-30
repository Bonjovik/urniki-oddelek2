import calendar
from datetime import date, time
import hashlib
import io
import os
import re
import holidays
import numpy as np
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KI-Dienstplan PRO 76.0", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 76.0 - § 11 AZG Pausen-Automatik Edition)")
st.markdown(
    "**System-Architektur (§ 11 AZG Pausen-Automatik, Live-Arbeitszeitrechner, WBL-Reserve bis 15:30 & Steiermark-Recht):** \n"
    "- ⚖️ **NEU in Tab 2 – Automatischer Pausen-Vorschlag nach § 11 AZG:** Der Zeitrechner erkennt automatisch die Brutto-Dauer und schlägt die passende Pause vor (**`0 Min.`** bis 6h | **`30 Min.`** über 6h | **`45 Min.`** bei Langdiensten ab 10h).\n"
    "- 🕒 **Live-Arbeitszeitrechner:** Berechnet aus **Beginn**, **Ende** und **Pause** sofort die exakten **Netto-Stunden** (inkl. Über-Nacht-Erkennung).\n"
    "- 👨‍⚕️ **Stationsleitung (WBL) als Reserve-DGKP bis 15:30 (Mo–Fr):** Regulär `WBL` (Büro bis 15:30); nur bei Ausfall aller anderen DGKPs wirst du Mo–Fr automatisch als Reserve (`WBL-P` bis 15:30) eingesetzt."
)

PAID_ABSENCES = ["URL", "SU", "ENT", "KRA", "PFLEGE", "FO"]
HARD_ABSENCES = ["URL", "SU", "ENT", "KRA", "PFLEGE", "FO", "ZA"]
GESETZ_STATUS_OPTIONS = [
    "Normal",
    "Altersteilzeit (ATZ)",
    "Mutterschutz (MSchG)",
    "Elternteilzeit (ETZ)",
    "Pflegekarenz / Teilzeit",
    "Nachtschwerarbeit (NSchG)"
]
ROLE_OPTIONS = ["Leitung", "DGKP", "PFA", "Pflegeassistenz", "Heimhelfer"]
MONTH_NAMES_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni", 
    "Juli", "August", "September", "Oktober", "November", "Dezember"
]

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

# --- HILFSFUNKTIONEN FÜR ZEITBERECHNUNG, § 11 AZG PAUSE & DATENBEREINIGUNG ---
def parse_hhmm_to_minutes(t_val):
    """Wandelt einen 'HH:MM'-Text oder ein datetime.time-Objekt in Minuten seit Mitternacht um."""
    if isinstance(t_val, time):
        return t_val.hour * 60 + t_val.minute
    s = str(t_val).strip()
    m = re.match(r"^(\d{1,2})[:\.](\d{2})$", s)
    if m:
        hh = int(m.group(1)) % 24
        mm = min(59, max(0, int(m.group(2))))
        return hh * 60 + mm
    return None

def get_brutto_hours_and_overnight(von_val, bis_val):
    """Berechnet die reine Brutto-Dauer zwischen Beginn und Ende (inkl. Mitternachts-Übertritt)."""
    start_m = parse_hhmm_to_minutes(von_val)
    end_m = parse_hhmm_to_minutes(bis_val)
    if start_m is None or end_m is None:
        return 8.5, False
    overnight = False
    if end_m <= start_m:
        end_m += 24 * 60
        overnight = True
    brutto_min = end_m - start_m
    return round(brutto_min / 60.0, 2), overnight

def get_azg_pause_suggestion(brutto_h, sh_type="Tagdienst Pflege"):
    """
    Ermittelt den automatischen Pausenvorschlag nach § 11 AZG / KA-AZG:
    - Unter / bis 6,0h Brutto: 0 Min.
    - Über 6,0h bis unter 10,0h Brutto: 30 Min.
    - Langdienste ab 10,0h Brutto: 45 Min.
    - Nachtdienst: 0 Min. (falls bezahlte Ruhebereitschaft) mit Hinweis auf 30/45 Min.
    """
    if sh_type == "Nachtdienst":
        return 0, "🌙 **Nachtdienst-Regel:** Standard `0 Min.` Abzug (bezahlte Arbeitsbereitschaft), bei unbezahlter Pause manuell auf `30` oder `45 Min.` anpassbar."
    if brutto_h <= 6.0:
        return 0, f"🟢 **§ 11 AZG Vorschlag (Brutto {brutto_h:.2f}h ≤ 6,0h):** **`0 Min.`** Pause (unter 6 Stunden keine gesetzliche Pflichtpause)."
    if brutto_h < 10.0:
        return 30, f"⚖️ **§ 11 AZG Vorschlag (Brutto {brutto_h:.2f}h > 6,0h):** **`30 Min.`** gesetzliche Ruhepause."
    return 45, f"⚖️ **§ 11 AZG / KA-AZG Vorschlag (Langdienst Brutto {brutto_h:.2f}h ≥ 10,0h):** **`45 Min.`** Ruhepause für lange Dienste."

def calculate_shift_hours_from_times(von_val, bis_val, pause_min):
    """Berechnet aus Beginn (HH:MM), Ende (HH:MM) und Pause (Minuten) die Brutto- und Netto-Stunden."""
    brutto_h, overnight = get_brutto_hours_and_overnight(von_val, bis_val)
    brutto_min = int(round(brutto_h * 60))
    netto_min = max(15, brutto_min - int(pause_min))
    return brutto_h, round(netto_min / 60.0, 2), overnight

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
        {"Kürzel": "X7", "Bezeichnung": "DGKP Langdienst", "Von": "06:00", "Bis": "18:30", "Pause_Min": 30, "Stunden": 12.0, "Typ": "Tagdienst Pflege", "Auto_Standard": True, "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "X6", "Bezeichnung": "DGKP Tagdienst", "Von": "06:00", "Bis": "17:30", "Pause_Min": 30, "Stunden": 11.0, "Typ": "Tagdienst Pflege", "Auto_Standard": True, "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "X4", "Bezeichnung": "DGKP Kurzdienst", "Von": "07:00", "Bis": "15:45", "Pause_Min": 30, "Stunden": 8.25, "Typ": "Tagdienst Pflege", "Auto_Standard": True, "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "WBL", "Bezeichnung": "Stationsleitung Büro (Mo-Fr)", "Von": "07:30", "Bis": "15:30", "Pause_Min": 30, "Stunden": 7.5, "Typ": "Leitung / Büro", "Auto_Standard": False, "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "WBL-P", "Bezeichnung": "Leitung Reserve-DGKP (Mo-Fr)", "Von": "07:00", "Bis": "15:30", "Pause_Min": 30, "Stunden": 8.0, "Typ": "Tagdienst Pflege", "Auto_Standard": False, "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "F2", "Bezeichnung": "PFA/PA/HH Langdienst", "Von": "06:00", "Bis": "18:30", "Pause_Min": 30, "Stunden": 12.0, "Typ": "Tagdienst Pflege", "Auto_Standard": True, "Erlaubt_DGKP": False, "Erlaubt_PFA": True, "Erlaubt_PA": True, "Erlaubt_HH": True},
        {"Kürzel": "F7", "Bezeichnung": "PFA/PA/HH Tagdienst", "Von": "06:00", "Bis": "17:30", "Pause_Min": 30, "Stunden": 11.0, "Typ": "Tagdienst Pflege", "Auto_Standard": True, "Erlaubt_DGKP": False, "Erlaubt_PFA": True, "Erlaubt_PA": True, "Erlaubt_HH": True},
        {"Kürzel": "N1", "Bezeichnung": "Nachtdienst DGKP", "Von": "18:15", "Bis": "07:45", "Pause_Min": 0, "Stunden": 13.5, "Typ": "Nachtdienst", "Auto_Standard": True, "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "N2", "Bezeichnung": "Nachtdienst PFA/PA", "Von": "18:15", "Bis": "07:45", "Pause_Min": 0, "Stunden": 13.5, "Typ": "Nachtdienst", "Auto_Standard": True, "Erlaubt_DGKP": False, "Erlaubt_PFA": True, "Erlaubt_PA": True, "Erlaubt_HH": False},
        {"Kürzel": "JED", "Bezeichnung": "Speisesaal Dienst", "Von": "07:00", "Bis": "18:00", "Pause_Min": 30, "Stunden": 10.5, "Typ": "Speisesaal / Sonder", "Auto_Standard": True, "Erlaubt_DGKP": False, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": True},
        {"Kürzel": "SM", "Bezeichnung": "Sonderdienst SM (nur Zuweisung)", "Von": "07:00", "Bis": "18:15", "Pause_Min": 30, "Stunden": 10.75, "Typ": "Tagdienst Pflege", "Auto_Standard": False, "Erlaubt_DGKP": False, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": True},
        {"Kürzel": "MS", "Bezeichnung": "Kurzdienst MS (nur Zuweisung)", "Von": "07:00", "Bis": "14:30", "Pause_Min": 30, "Stunden": 7.0, "Typ": "Tagdienst Pflege", "Auto_Standard": False, "Erlaubt_DGKP": False, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": True},
    ])

def sanitize_shifts_df(df, recalc_from_time=False):
    if df is None or df.empty:
        return get_default_shifts_df()
    df = df.copy()
    if "Kürzel" not in df.columns:
        return get_default_shifts_df()
    df = df.dropna(subset=["Kürzel"])
    df["Kürzel"] = df["Kürzel"].astype(str).str.strip().str.upper()
    df = df[~df["Kürzel"].isin(["", "NAN", "NONE", "OFF", "..."])]
    df = df.drop_duplicates(subset=["Kürzel"], keep="last")

    for req_code, req_name, r_von, r_bis, r_p, req_hrs, req_typ in [
        ("WBL", "Stationsleitung Büro (Mo-Fr)", "07:30", "15:30", 30, 7.5, "Leitung / Büro"),
        ("WBL-P", "Leitung Reserve-DGKP (Mo-Fr)", "07:00", "15:30", 30, 8.0, "Tagdienst Pflege")
    ]:
        if req_code not in df["Kürzel"].values:
            add_r = pd.DataFrame([{
                "Kürzel": req_code, "Bezeichnung": req_name, "Von": r_von, "Bis": r_bis, "Pause_Min": r_p,
                "Stunden": req_hrs, "Typ": req_typ, "Auto_Standard": False,
                "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False
            }])
            df = pd.concat([df, add_r], ignore_index=True)
    
    if "Bezeichnung" not in df.columns:
        df["Bezeichnung"] = "Dienst"
    df["Bezeichnung"] = df["Bezeichnung"].fillna("Dienst").astype(str).str.strip()

    default_times_map = {
        "X7": ("06:00", "18:30", 30), "X6": ("06:00", "17:30", 30), "X4": ("07:00", "15:45", 30),
        "WBL": ("07:30", "15:30", 30), "WBL-P": ("07:00", "15:30", 30),
        "F2": ("06:00", "18:30", 30), "F7": ("06:00", "17:30", 30),
        "N1": ("18:15", "07:45", 0), "N2": ("18:15", "07:45", 0),
        "JED": ("07:00", "18:00", 30), "SM": ("07:00", "18:15", 30), "MS": ("07:00", "14:30", 30)
    }
    if "Von" not in df.columns:
        df["Von"] = df["Kürzel"].apply(lambda k: default_times_map.get(k, ("07:00", "15:30", 30))[0])
    else:
        df["Von"] = df["Von"].fillna("07:00").astype(str).str.strip()

    if "Bis" not in df.columns:
        df["Bis"] = df["Kürzel"].apply(lambda k: default_times_map.get(k, ("07:00", "15:30", 30))[1])
    else:
        df["Bis"] = df["Bis"].fillna("15:30").astype(str).str.strip()

    if "Pause_Min" not in df.columns:
        df["Pause_Min"] = df["Kürzel"].apply(lambda k: default_times_map.get(k, ("07:00", "15:30", 30))[2])
    else:
        df["Pause_Min"] = pd.to_numeric(df["Pause_Min"], errors="coerce").fillna(30).clip(lower=0, upper=180).astype(int)
    
    if "Stunden" not in df.columns:
        df["Stunden"] = 8.0
    df["Stunden"] = pd.to_numeric(df["Stunden"], errors="coerce").fillna(8.0).clip(lower=0.25, upper=24.0).round(2)

    if recalc_from_time:
        new_hrs = []
        for _, r in df.iterrows():
            _, net_h, _ = calculate_shift_hours_from_times(r["Von"], r["Bis"], r["Pause_Min"])
            new_hrs.append(net_h)
        df["Stunden"] = new_hrs
    
    valid_types = ["Tagdienst Pflege", "Nachtdienst", "Speisesaal / Sonder", "Leitung / Büro"]
    if "Typ" not in df.columns:
        df["Typ"] = "Tagdienst Pflege"
    df["Typ"] = df["Typ"].fillna("Tagdienst Pflege").astype(str).str.strip()
    df.loc[~df["Typ"].isin(valid_types), "Typ"] = "Tagdienst Pflege"
    
    if "Auto_Standard" not in df.columns:
        core_codes = ["X7", "X6", "X4", "F2", "F7", "N1", "N2", "JED"]
        df["Auto_Standard"] = df["Kürzel"].isin(core_codes)
    else:
        df["Auto_Standard"] = df["Auto_Standard"].apply(lambda x: False if str(x).strip().lower() in ["false", "0", "no", "nein", "falsch"] else True)

    if "Erlaubt_PA" in df.columns and "Erlaubt_PFA" not in df.columns:
        df["Erlaubt_PFA"] = df["Erlaubt_PA"]
        
    for b_col, def_val in [("Erlaubt_DGKP", True), ("Erlaubt_PFA", True), ("Erlaubt_PA", True), ("Erlaubt_HH", False)]:
        if b_col not in df.columns:
            df[b_col] = def_val
        else:
            df[b_col] = df[b_col].apply(lambda x: False if str(x).strip().lower() in ["false", "0", "no", "nein", "falsch"] else True)
            
    cols = ["Kürzel", "Bezeichnung", "Von", "Bis", "Pause_Min", "Stunden", "Typ", "Auto_Standard", "Erlaubt_DGKP", "Erlaubt_PFA", "Erlaubt_PA", "Erlaubt_HH"]
    return df[cols].reset_index(drop=True)

if "shifts_df_v76" not in st.session_state:
    if os.path.exists("shifts_data.csv"):
        try:
            with open("shifts_data.csv", "rb") as f:
                st.session_state.shifts_df_v76 = sanitize_shifts_df(read_csv_smart(f.read(), is_index_col=False))
        except Exception:
            st.session_state.shifts_df_v76 = get_default_shifts_df()
    else:
        st.session_state.shifts_df_v76 = get_default_shifts_df()

SHIFTS_DF_CURRENT = sanitize_shifts_df(st.session_state.shifts_df_v76)
SHIFTS_HUNDREDTHS = {
    row["Kürzel"]: int(round(float(row["Stunden"]) * 100)) 
    for _, row in SHIFTS_DF_CURRENT.iterrows()
}
SHIFTS_HUNDREDTHS["OFF"] = 0

SHIFT_LABELS = {
    row["Kürzel"]: f"{row['Kürzel']} ({row['Von']}–{row['Bis']} | {row['Stunden']}h – {row['Bezeichnung']})" 
    for _, row in SHIFTS_DF_CURRENT.iterrows()
}
SHIFT_TIME_LOOKUP = {
    row["Kürzel"]: f"{row['Von']}–{row['Bis']} ({row['Pause_Min']}m Pause)"
    for _, row in SHIFTS_DF_CURRENT.iterrows()
}
DAY_CARE_SHIFTS = SHIFTS_DF_CURRENT[SHIFTS_DF_CURRENT["Typ"] == "Tagdienst Pflege"]["Kürzel"].tolist()
NIGHT_SHIFTS = SHIFTS_DF_CURRENT[SHIFTS_DF_CURRENT["Typ"] == "Nachtdienst"]["Kürzel"].tolist()
if not NIGHT_SHIFTS:
    NIGHT_SHIFTS = ["N1", "N2"]
DGKP_DAY_SHIFTS = SHIFTS_DF_CURRENT[
    (SHIFTS_DF_CURRENT["Typ"] == "Tagdienst Pflege") & (SHIFTS_DF_CURRENT["Erlaubt_DGKP"] == True)
]["Kürzel"].tolist()
if "WBL-P" not in DGKP_DAY_SHIFTS:
    DGKP_DAY_SHIFTS.append("WBL-P")
PA_PFA_DAY_SHIFTS = SHIFTS_DF_CURRENT[
    (SHIFTS_DF_CURRENT["Typ"] == "Tagdienst Pflege") & ((SHIFTS_DF_CURRENT["Erlaubt_PA"] == True) | (SHIFTS_DF_CURRENT["Erlaubt_PFA"] == True))
]["Kürzel"].tolist()
MANUAL_SHIFT_CODES = SHIFTS_DF_CURRENT["Kürzel"].tolist()

def extract_base_shift(val_str):
    """Extrahiert das reine Schichtkürzel aus Zellen wie 'F2 ➔ H', '*F2', '🚨 F2' oder '⬅️ PA B-1 (F2)'."""
    s = str(val_str).strip().upper()
    if s.startswith("⬅️"):
        return "AUSHILFE_INFO"
    s = s.replace("🚨", "").replace("📌", "").replace("*", "").strip()
    if "➔" in s:
        s = s.split("➔")[0].strip()
    elif "->" in s:
        s = s.split("->")[0].strip()
    return s

def get_default_pavo_df():
    return pd.DataFrame([
        {"Abteilung": "Abteilung B", "Stufe_0": 0, "Stufe_1": 2, "Stufe_2": 4, "Stufe_3": 6, "Stufe_4": 6, "Stufe_5": 4, "Stufe_6": 2, "Stufe_7": 0},
        {"Abteilung": "Abteilung H", "Stufe_0": 0, "Stufe_1": 1, "Stufe_2": 4, "Stufe_3": 7, "Stufe_4": 6, "Stufe_5": 4, "Stufe_6": 1, "Stufe_7": 1},
    ])

if "pavo_df_v76" not in st.session_state:
    if os.path.exists("pavo_data.csv"):
        try:
            st.session_state.pavo_df_v76 = pd.read_csv("pavo_data.csv")
        except Exception:
            st.session_state.pavo_df_v76 = get_default_pavo_df()
    else:
        st.session_state.pavo_df_v76 = get_default_pavo_df()

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

def parse_explicit_shifts(spez_str, all_valid_codes):
    if not spez_str:
        return []
    s_up = str(spez_str).upper().strip()
    if s_up in ["OHNE", "NUR WE UND FEIERTAGE", "STANDARD", ""]:
        return []
    tokens = [t.strip() for t in s_up.replace(";", ",").replace("/", ",").replace("+", ",").replace(" ", ",").split(",") if t.strip()]
    found = [t for t in tokens if t in all_valid_codes]
    return list(dict.fromkeys(found))

def resolve_allowed_shifts_for_person(s, shifts_df):
    allowed_shifts = ["OFF"]
    nur_nacht = bool(s.get("Nur_Nacht", False))
    spez = str(s.get("Spezialdienst", "Ohne")).upper().strip()
    rolle = str(s.get("Rolle", "Pflegeassistenz")).strip()
    abt = str(s.get("Abteilung", "Abteilung B")).strip()
    gesetz = str(s.get("Gesetz_Status", "Normal")).strip()
    max_n = int(s.get("Max_Nacht", 0))

    all_codes = shifts_df["Kürzel"].tolist()
    day_df = shifts_df[shifts_df["Typ"] != "Nachtdienst"]
    night_df = shifts_df[shifts_df["Typ"] == "Nachtdienst"]
    std_day_df = day_df[day_df["Auto_Standard"] == True]
    std_night_df = night_df[night_df["Auto_Standard"] == True]

    explicit_codes = parse_explicit_shifts(spez, all_codes)

    if rolle == "Leitung":
        if explicit_codes:
            allowed_shifts.extend(explicit_codes)
        else:
            allowed_shifts.extend(["WBL", "WBL-P"])
        if "WBL" not in allowed_shifts and "WBL" in all_codes:
            allowed_shifts.append("WBL")
        if "WBL-P" not in allowed_shifts and "WBL-P" in all_codes:
            allowed_shifts.append("WBL-P")
        return list(set(allowed_shifts))

    if abt == "Abteilung F":
        if gesetz == "Mutterschutz (MSchG)":
            return ["OFF"]
        explicit_nights = [c for c in explicit_codes if c in night_df["Kürzel"].values]
        if explicit_nights:
            allowed_shifts.extend(explicit_nights)
        elif rolle == "DGKP":
            dg_n = std_night_df[std_night_df["Erlaubt_DGKP"] == True]["Kürzel"].tolist()
            allowed_shifts.extend(dg_n if dg_n else ["N1"])
        else:
            role_col = "Erlaubt_PFA" if rolle == "PFA" else "Erlaubt_PA"
            pa_n = std_night_df[std_night_df[role_col] == True]["Kürzel"].tolist()
            allowed_shifts.extend(pa_n if pa_n else ["N2"])
        return list(set(allowed_shifts))

    if gesetz == "Mutterschutz (MSchG)":
        explicit_day = [c for c in explicit_codes if c in day_df["Kürzel"].values]
        if explicit_day:
            allowed_shifts.extend(explicit_day)
        elif rolle == "DGKP":
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

    if explicit_codes:
        explicit_days = [c for c in explicit_codes if c in day_df["Kürzel"].values]
        explicit_nights = [c for c in explicit_codes if c in night_df["Kürzel"].values]

        if not nur_nacht and explicit_days:
            allowed_shifts.extend(explicit_days)
            if spez == "JED" and rolle == "Heimhelfer":
                for c_b in ["F2", "F7"]:
                    if c_b in std_day_df["Kürzel"].values and c_b not in allowed_shifts:
                        allowed_shifts.append(c_b)

        if explicit_nights:
            if rolle == "DGKP":
                allowed_shifts.extend([c for c in explicit_nights if c != "N2"])
            else:
                allowed_shifts.extend([c for c in explicit_nights if c != "N1"])
        elif (max_n > 0 or nur_nacht):
            if rolle == "DGKP":
                dg_n = std_night_df[std_night_df["Erlaubt_DGKP"] == True]["Kürzel"].tolist()
                allowed_shifts.extend(dg_n if dg_n else ["N1"])
            elif rolle in ["PFA", "Pflegeassistenz"]:
                role_col = "Erlaubt_PFA" if rolle == "PFA" else "Erlaubt_PA"
                pa_n = std_night_df[std_night_df[role_col] == True]["Kürzel"].tolist()
                allowed_shifts.extend(pa_n if pa_n else ["N2"])

        return list(set(allowed_shifts))

    if not nur_nacht:
        if rolle == "DGKP":
            dg_d = std_day_df[std_day_df["Erlaubt_DGKP"] == True]["Kürzel"].tolist()
            allowed_shifts.extend(dg_d if dg_d else ["X4", "X6", "X7"])
        elif rolle in ["PFA", "Pflegeassistenz"]:
            role_col = "Erlaubt_PFA" if rolle == "PFA" else "Erlaubt_PA"
            pa_d = std_day_df[std_day_df[role_col] == True]["Kürzel"].tolist()
            allowed_shifts.extend(pa_d if pa_d else ["F2", "F7"])
        elif rolle == "Heimhelfer":
            hh_d = std_day_df[std_day_df["Erlaubt_HH"] == True]["Kürzel"].tolist()
            allowed_shifts.extend(hh_d if hh_d else ["JED", "F2", "F7"])

    if max_n > 0 or nur_nacht:
        if rolle == "DGKP":
            dg_n = std_night_df[std_night_df["Erlaubt_DGKP"] == True]["Kürzel"].tolist()
            allowed_shifts.extend(dg_n if dg_n else ["N1"])
        elif rolle in ["PFA", "Pflegeassistenz"]:
            role_col = "Erlaubt_PFA" if rolle == "PFA" else "Erlaubt_PA"
            pa_n = std_night_df[std_night_df[role_col] == True]["Kürzel"].tolist()
            allowed_shifts.extend(pa_n if pa_n else ["N2"])

    return list(set(allowed_shifts))

def normalize_cal_cell(val):
    if pd.isna(val):
        return ""
    s = str(val).strip().upper()
    if s in ["", "NAN", "NONE", "<NA>", "NULL", "..."]:
        return ""
    s_clean = s.replace("📌", "").replace("🔴", "").replace("🟠", "").replace("🟣", "").replace("🔵", "").replace("⚫", "").replace("🟢", "").replace("⚪", "").strip()
    for sh_c in sorted(MANUAL_SHIFT_CODES, key=len, reverse=True):
        if s_clean == sh_c or s_clean.startswith(sh_c + " "):
            return sh_c
    if "URL" in s_clean: return "URL"
    if "KRA" in s_clean: return "KRA"
    if "ZA" in s_clean: return "ZA"
    if "SU" in s_clean: return "SU"
    if "ENT" in s_clean: return "ENT"
    if "PFLEGE" in s_clean or "PFL" in s_clean: return "PFL"
    if "FO" in s_clean or "FORT" in s_clean: return "FO"
    if "WUN" in s_clean or "FREI" in s_clean: return "WUN"
    if "MUS" in s_clean: return "MUS"
    return s_clean[:8]

def build_vacation_quota_summary_df(cal_df, staff_df, day_cols, max_per_station=2):
    dept_map = {}
    role_map = {}
    for _, r in staff_df.iterrows():
        n = str(r["Name"]).strip()
        dept_map[n] = str(r["Abteilung"]).strip()
        role_map[n] = str(r["Rolle"]).strip()

    row_b = {"Kontingent-Check": f"🔵 Abt. B Fix-Abwesend (Max. {max_per_station})"}
    row_h = {"Kontingent-Check": f"🟢 Abt. H Fix-Abwesend (Max. {max_per_station})"}
    row_dgkp = {"Kontingent-Check": "🩺 DGKP B+H Abwesend (Max. 2)"}
    row_hh = {"Kontingent-Check": "🍽️ Heimhilfe Abwesend (Max. 1!)"}
    row_f = {"Kontingent-Check": "🟣 Abt. F Nachtpool Abwesend (Max. 1)"}
    row_wun = {"Kontingent-Check": "🟢 Zusatz Wunsch-Frei (WUN Gesamt)"}

    for c in day_cols:
        b_abs, h_abs, dg_abs, hh_abs, f_abs, wun_tot = 0, 0, 0, 0, 0, 0
        for emp in cal_df.index:
            val = normalize_cal_cell(cal_df.at[emp, c])
            if not val:
                continue
            abt = dept_map.get(emp, "Abteilung B")
            rol = role_map.get(emp, "Pflegeassistenz")

            if val == "WUN":
                wun_tot += 1
            elif val in ["URL", "SU", "ENT", "KRA", "ZA", "PFL", "FO"]:
                if abt == "Abteilung B":
                    b_abs += 1
                elif abt == "Abteilung H":
                    h_abs += 1
                elif abt == "Abteilung F":
                    f_abs += 1

                if rol == "DGKP" and abt in ["Abteilung B", "Abteilung H"]:
                    dg_abs += 1
                elif rol == "Heimhelfer":
                    hh_abs += 1

        row_b[c] = b_abs
        row_h[c] = h_abs
        row_dgkp[c] = dg_abs
        row_hh[c] = hh_abs
        row_f[c] = f_abs
        row_wun[c] = wun_tot

    return pd.DataFrame([row_b, row_h, row_dgkp, row_hh, row_f, row_wun])

def style_vacation_quota_df(df_q, max_per_station=2):
    def color_q_row(row):
        kat = str(row["Kontingent-Check"])
        styles = ["font-weight: bold; background-color: #f8f9fa; color: #212529;"]
        limit = max_per_station
        if "Max. 1" in kat:
            limit = 1
        elif "Max. 2" in kat:
            limit = 2

        for col in df_q.columns[1:]:
            val = int(row[col])
            if "Wunsch-Frei" in kat:
                if val >= 5:
                    styles.append("background-color: #fff3cd; color: #856404; font-weight: bold; text-align: center;")
                else:
                    styles.append("background-color: #eef2f7; color: #333; text-align: center;")
            else:
                if val > limit:
                    styles.append("background-color: #f8d7da; color: #721c24; font-weight: bold; text-align: center; border: 1px solid #f5c6cb;")
                elif val == limit:
                    styles.append("background-color: #fff3cd; color: #856404; font-weight: bold; text-align: center;")
                else:
                    styles.append("background-color: #d4edda; color: #155724; font-weight: bold; text-align: center;")
        return styles
    return df_q.style.apply(color_q_row, axis=1)

def recalculate_plan_df(df_plan, staff_df, num_days):
    df_out = df_plan.copy()
    df_out = df_out[~df_out["Mitarbeiter"].astype(str).str.startswith("🤝 Aushilfe")].reset_index(drop=True)
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

    aushilfe_for_b = {c: [] for c in day_cols_plan}
    aushilfe_for_h = {c: [] for c in day_cols_plan}

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
                    base_sh = extract_base_shift(clean_v)
                    if not clean_v.startswith("🚨") and base_sh in SHIFTS_HUNDREDTHS:
                        clean_v = f"🚨 {base_sh}"
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
        base_emp_name = emp_display.split(" (")[0].strip()
        emp_info = staff_lookup.get(emp_display.lower(), staff_lookup.get(base_emp_name.lower(), {"Wochenstd": 37.0, "Saldo_Alt": 0.0}))
        
        w_std = emp_info["Wochenstd"]
        saldo_alt = emp_info["Saldo_Alt"]
        daily_avg = w_std / 7.0
        
        total_hours_100 = 0
        for c in day_cols_plan:
            raw_val = row[c]
            if pd.isna(raw_val) or str(raw_val).strip().upper() in ["", "...", "OFF", "NAN", "NONE"]:
                clean_v = "..."
            else:
                clean_v = str(raw_val).strip().upper().replace("📌", "").replace("->", "➔").strip()
                if clean_v == "PFL": clean_v = "PFLEGE"
                if clean_v == "WUN": clean_v = "WUNSCH"
                if clean_v == "MUS": clean_v = "MUSS"
                if "➔" not in clean_v and not clean_v.startswith("*"):
                    for code in ["URL", "SU", "ENT", "KRA", "ZA", "PFLEGE", "FO", "WUNSCH", "MUSS"]:
                        if code == clean_v or clean_v.startswith(code + " "):
                            clean_v = code
                            break
            df_out.at[idx, c] = clean_v
            
            sh_check = extract_base_shift(clean_v)
            if sh_check in SHIFTS_HUNDREDTHS and sh_check != "OFF":
                total_hours_100 += SHIFTS_HUNDREDTHS[sh_check]
                if "➔ H" in clean_v:
                    aushilfe_for_h[c].append(f"⬅️ {base_emp_name} ({sh_check})")
                elif "➔ B" in clean_v:
                    aushilfe_for_b[c].append(f"⬅️ {base_emp_name} ({sh_check})")
            elif any(pa == clean_v for pa in PAID_ABSENCES):
                total_hours_100 += int(round(daily_avg * 100))
                
        soll_exact = daily_avg * num_days
        ist_std = round(total_hours_100 / 100.0, 1)
        ueberstd = round(max(0.0, ist_std - soll_exact), 1)
        saldo_neu = round(ist_std - soll_exact + saldo_alt, 1)
        
        df_out.at[idx, "SOLL"] = round(soll_exact, 1)
        df_out.at[idx, "IST"] = ist_std
        df_out.at[idx, "ÜBERSTD."] = ueberstd
        df_out.at[idx, "SALDO"] = saldo_neu
        
    df_cleaned = df_out.loc[rows_to_keep].reset_index(drop=True)

    extra_aushilfe_rows = []
    if any(len(v) > 0 for v in aushilfe_for_b.values()):
        row_b_help = {
            "Abteilung": "Abteilung B",
            "Rolle": "Springer",
            "Mitarbeiter": "🤝 Aushilfe von Abt. H",
            "SOLL": 0.0, "IST": 0.0, "ÜBERSTD.": 0.0, "SALDO": 0.0
        }
        for c in day_cols_plan:
            row_b_help[c] = " | ".join(aushilfe_for_b[c]) if aushilfe_for_b[c] else "..."
        extra_aushilfe_rows.append(row_b_help)

    if any(len(v) > 0 for v in aushilfe_for_h.values()):
        row_h_help = {
            "Abteilung": "Abteilung H",
            "Rolle": "Springer",
            "Mitarbeiter": "🤝 Aushilfe von Abt. B",
            "SOLL": 0.0, "IST": 0.0, "ÜBERSTD.": 0.0, "SALDO": 0.0
        }
        for c in day_cols_plan:
            row_h_help[c] = " | ".join(aushilfe_for_h[c]) if aushilfe_for_h[c] else "..."
        extra_aushilfe_rows.append(row_h_help)

    if extra_aushilfe_rows:
        df_cleaned = pd.concat([df_cleaned, pd.DataFrame(extra_aushilfe_rows)], ignore_index=True)

    return df_cleaned

def build_coverage_summary_df(full_df, dept_name, num_days, min_b=4, min_h=4):
    day_cols_only = [f"{d}." for d in range(1, num_days + 1)]
    real_full = full_df[~full_df["Mitarbeiter"].astype(str).str.contains("X-Oseba|FEHLT|⚠️|🤝 Aushilfe", na=False)]

    summary_rows = []

    if dept_name in ["Abteilung B", "Abteilung H"]:
        target_Code = "B" if dept_name == "Abteilung B" else "H"
        other_Code = "H" if dept_name == "Abteilung B" else "B"
        min_pa_target = min_b if dept_name == "Abteilung B" else min_h

        row_dgkp = {"Kontroll-Kategorie": "🩺 DGKP Tag (Min. 1)"}
        if dept_name == "Abteilung B":
            row_pa = {"Kontroll-Kategorie": f"🏥 PA / PFA (+ HH-Hilfe) Tag (Min. {min_pa_target} | Ideal 5)"}
            row_jed = {"Kontroll-Kategorie": "🍽️ Heimhelfer Speisesaal JED (Min. 1 - Pflicht!)"}
        else:
            row_pa = {"Kontroll-Kategorie": f"🏥 PA / PFA (+ HH-Hilfe) Tag (Min. {min_pa_target})"}

        for c in day_cols_only:
            dgkp_present = 0
            wbl_reserve_used = False
            pa_present = 0
            jed_present = 0
            springer_in_count = 0

            for _, r in real_full.iterrows():
                emp_abt = str(r["Abteilung"]).strip()
                emp_role = str(r["Rolle"]).strip()
                raw_cell = str(r[c]).strip().upper()
                base_sh = extract_base_shift(raw_cell)

                if base_sh not in SHIFTS_HUNDREDTHS or base_sh in ["OFF", "WBL"] + NIGHT_SHIFTS:
                    continue

                if f"➔ {target_Code}" in raw_cell:
                    effective_abt = dept_name
                    is_incoming_springer = True
                elif f"➔ {other_Code}" in raw_cell:
                    effective_abt = f"Abteilung {other_Code}"
                    is_incoming_springer = False
                else:
                    effective_abt = emp_abt
                    is_incoming_springer = False

                if base_sh == "JED":
                    jed_present += 1
                    continue

                if effective_abt != dept_name:
                    continue

                if is_incoming_springer:
                    springer_in_count += 1

                if emp_role in ["DGKP", "Leitung"] and base_sh in DGKP_DAY_SHIFTS:
                    dgkp_present += 1
                    if emp_role == "Leitung" or base_sh == "WBL-P":
                        wbl_reserve_used = True
                elif base_sh in DAY_CARE_SHIFTS:
                    pa_present += 1

            if wbl_reserve_used:
                row_dgkp[c] = f"{dgkp_present} (👨‍⚕️ WBL 15:30)"
            else:
                row_dgkp[c] = dgkp_present

            if springer_in_count > 0:
                row_pa[c] = f"{pa_present} (inkl. {springer_in_count} 🤝)"
            else:
                row_pa[c] = pa_present
            if dept_name == "Abteilung B":
                row_jed[c] = jed_present

        summary_rows.append(row_dgkp)
        summary_rows.append(row_pa)
        if dept_name == "Abteilung B":
            summary_rows.append(row_jed)

    else:
        row_n1 = {"Kontroll-Kategorie": "🌙 Hausweit N1 - DGKP (Exakt 1)"}
        row_n2 = {"Kontroll-Kategorie": "🌙 Hausweit N2 - PFA/PA (Exakt 1)"}
        for c in day_cols_only:
            vals_all = [extract_base_shift(v) for v in real_full[c].astype(str).tolist()]
            row_n1[c] = sum(1 for v in vals_all if v == "N1")
            row_n2[c] = sum(1 for v in vals_all if v == "N2")
            
        summary_rows.append(row_n1)
        summary_rows.append(row_n2)

    return pd.DataFrame(summary_rows)

def style_coverage_summary(df_sum):
    def color_row(row):
        kat = str(row.get("Kontroll-Kategorie", ""))
        styles = ["font-weight: bold; background-color: #f8f9fa; color: #212529;"]
        min_needed = 4
        if "Min. " in kat:
            try:
                min_needed = int(kat.split("Min. ")[1].split(" ")[0].split(")")[0])
            except Exception:
                min_needed = 1
        for col in df_sum.columns[1:]:
            val = row[col]
            num_val = None
            has_springer = False
            has_wbl = False
            if isinstance(val, (int, float, np.integer)):
                num_val = int(val)
            elif isinstance(val, str):
                if "🤝" in val or "Springer" in val:
                    has_springer = True
                if "WBL" in val:
                    has_wbl = True
                first_part = val.split(" ")[0].strip()
                if first_part.isdigit():
                    num_val = int(first_part)

            if num_val is None:
                styles.append("text-align: center;")
                continue

            if "Min. " in kat:
                if num_val < min_needed:
                    styles.append("background-color: #f8d7da; color: #721c24; font-weight: bold; text-align: center; border: 1px solid #f5c6cb;")
                elif has_wbl:
                    styles.append("background-color: #fff3cd; color: #856404; font-weight: bold; text-align: center; border: 1px solid #ffeeba;")
                elif has_springer:
                    styles.append("background-color: #d1ecf1; color: #0c5460; font-weight: bold; text-align: center; border: 1px solid #bee5eb;")
                else:
                    styles.append("background-color: #d4edda; color: #155724; font-weight: bold; text-align: center;")
            elif "Exakt 1" in kat:
                if num_val == 1:
                    styles.append("background-color: #d4edda; color: #155724; font-weight: bold; text-align: center;")
                else:
                    styles.append("background-color: #f8d7da; color: #721c24; font-weight: bold; text-align: center; border: 1px solid #f5c6cb;")
            else:
                styles.append("background-color: #eef2f7; color: #333333; font-weight: bold; text-align: center;")
        return styles

    return df_sum.style.apply(color_row, axis=1)

# --- GEOCON ZUSCHLÄGE-MATRIX & DRUCKGENERATOR (HTML / PDF READY) ---
def build_geocon_zuschlaege_df(df_plan, staff_df, num_days, leto, mesec, first_day_weekday, at_holidays):
    day_cols_only = [f"{d}." for d in range(1, num_days + 1) if f"{d}." in df_plan.columns]
    real_df = df_plan[~df_plan["Mitarbeiter"].astype(str).str.contains("X-Oseba|FEHLT|⚠️|🤝 Aushilfe", na=False)].copy()

    url_lookup = {}
    status_lookup = {}
    for _, s_r in staff_df.iterrows():
        b_n = str(s_r["Name"]).strip().lower()
        url_lookup[b_n] = float(s_r.get("URL_Rest", 25.0))
        status_lookup[b_n] = str(s_r.get("Gesetz_Status", "Normal")).strip()

    rows = []
    for _, r in real_df.iterrows():
        emp_disp = str(r["Mitarbeiter"]).strip()
        base_emp = emp_disp.split(" (")[0].strip().lower()
        url_rest_alt = url_lookup.get(base_emp, 25.0)
        gesetz_st = status_lookup.get(base_emp, "Normal")

        nacht_dienste = 0
        nacht_std_100 = 0
        so_std_100 = 0
        ft_std_100 = 0
        sa_dienste = 0
        springer_tage = 0
        url_tage = 0
        ent_tage = 0
        kra_tage = 0
        za_tage = 0
        fo_tage = 0

        for d_idx, c in enumerate(day_cols_only):
            raw_v = str(r[c]).strip().upper()
            base_sh = extract_base_shift(raw_v)
            dow = (d_idx + first_day_weekday) % 7
            is_hol = (date(leto, mesec, d_idx + 1) in at_holidays) or (mesec == 12 and (d_idx + 1 in [24, 31]))

            if "➔" in raw_v:
                springer_tage += 1

            if base_sh == "URL":
                url_tage += 1
            elif base_sh == "ENT":
                ent_tage += 1
            elif base_sh == "KRA":
                kra_tage += 1
            elif base_sh == "ZA":
                za_tage += 1
            elif base_sh == "FO":
                fo_tage += 1
            elif base_sh in SHIFTS_HUNDREDTHS and base_sh != "OFF":
                sh_dur = SHIFTS_HUNDREDTHS[base_sh]
                if base_sh in NIGHT_SHIFTS:
                    nacht_dienste += 1
                    nacht_std_100 += sh_dur
                if is_hol:
                    ft_std_100 += sh_dur
                elif dow == 6:
                    so_std_100 += sh_dur
                elif dow == 5:
                    sa_dienste += 1

        saldo_val = float(r.get("SALDO", 0.0))
        if saldo_val > 25.0:
            ampel = "🔴 Über Limit (>+25h)"
        elif saldo_val > 12.0:
            ampel = "🟡 Erhöht (+12h bis +25h)"
        elif saldo_val < -15.0:
            ampel = "🔴 Starkes Minus (<-15h)"
        else:
            ampel = "🟢 Im Zielkorridor"

        rows.append({
            "Mitarbeiter": emp_disp,
            "Abteilung": r["Abteilung"],
            "Rolle": r["Rolle"],
            "Status": gesetz_st,
            "SOLL (h)": r["SOLL"],
            "IST (h)": r["IST"],
            "ÜBERSTD. (h)": r["ÜBERSTD."],
            "SALDO Neu (h)": saldo_val,
            "Zeitkonto-Ampel": ampel,
            "🌙 Nachtdienste (Anz.)": nacht_dienste,
            "🌙 Nacht-Stunden (h)": round(nacht_std_100 / 100.0, 2),
            "☀️ SO-Stunden (Zuschlag)": round(so_std_100 / 100.0, 2),
            "⭐ FT-Stunden (Feiertag)": round(ft_std_100 / 100.0, 2),
            "📅 SA-Dienste (Anz.)": sa_dienste,
            "🤝 Springer-Tage (➔)": springer_tage,
            "🏝️ URL verbraucht": url_tage,
            "🏝️ URL Rest Neu": round(max(0.0, url_rest_alt - url_tage), 1),
            "🟣 ENT Tage": ent_tage,
            "⚫ ZA Tage": za_tage,
            "🔵 KRA Tage": kra_tage,
            "🎓 FO Tage": fo_tage
        })
    return pd.DataFrame(rows)

def generate_printable_aushang_html(df_plan, num_days, leto, mesec, first_day_weekday, at_holidays, min_b=4, min_h=4):
    monat_str = MONTH_NAMES_DE[mesec - 1]
    dow_short = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    html_parts = [f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Dienstplan {monat_str} {leto}</title>
<style>
    @page {{ size: A4 landscape; margin: 8mm; }}
    body {{ font-family: Arial, Helvetica, sans-serif; font-size: 9pt; color: #111; margin: 0; padding: 10px; }}
    h1 {{ font-size: 14pt; margin: 0 0 4px 0; color: #1e3a8a; }}
    h2 {{ font-size: 11pt; margin: 12px 0 4px 0; padding: 4px 8px; background: #e9ecef; border-left: 5px solid #1e3a8a; }}
    .meta {{ font-size: 8.5pt; color: #444; margin-bottom: 8px; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 10px; table-layout: fixed; }}
    th, td {{ border: 1px solid #888; padding: 2px 1px; text-align: center; font-size: 7.5pt; overflow: hidden; white-space: nowrap; }}
    th.name-col, td.name-col {{ width: 135px; text-align: left; padding-left: 4px; font-weight: bold; }}
    th.role-col, td.role-col {{ width: 58px; text-align: left; padding-left: 3px; font-size: 7pt; }}
    th.sum-col, td.sum-col {{ width: 34px; font-weight: bold; background: #f8f9fa; }}
    .we-col {{ background-color: #ececf4; }}
    .hol-col {{ background-color: #fff0f0; }}
    .sh-night {{ background-color: #1e3a8a !important; color: #fff !important; font-weight: bold; }}
    .sh-wblp {{ background-color: #ffe8cc !important; color: #994d00 !important; font-weight: bold; border: 1.5px solid #ff8800; }}
    .sh-springer {{ background-color: #d4edda !important; color: #005c15 !important; font-weight: bold; border: 1.5px solid #28a745; }}
    .sh-url {{ background-color: #d1ecf1 !important; color: #0c5460 !important; font-weight: bold; }}
    .sh-kra {{ background-color: #f8d7da !important; color: #721c24 !important; font-weight: bold; }}
    .sh-za {{ background-color: #343a40 !important; color: #fff !important; font-weight: bold; }}
    .sh-alarm {{ background-color: #ffcccc !important; color: #cc0000 !important; font-weight: bold; }}
    .sig-box {{ display: flex; justify-content: space-between; margin-top: 18px; padding-top: 8px; font-size: 9pt; }}
    .sig-line {{ width: 28%; border-top: 1px solid #333; padding-top: 4px; text-align: center; }}
    @media print {{
        .no-print {{ display: none; }}
        body {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    }}
</style>
</head>
<body>
<div class="no-print" style="background:#eef2ff;padding:10px;margin-bottom:12px;border:1px solid #1e3a8a;border-radius:6px;">
    <strong>🖨️ Druck-Vorschau:</strong> Drücke jetzt <strong>Strg + P</strong> (oder klicke auf <button onclick="window.print()" style="padding:4px 10px;font-weight:bold;cursor:pointer;">🖨️ Jetzt drucken / Als PDF speichern</button>), wähle <em>Querformat (Landscape)</em> und <em>Hintergrundgrafiken drucken</em>.
</div>
<h1>🏥 Offizieller Dienstplan – {monat_str} {leto}</h1>
<div class="meta">Steiermark StPAVO & KA-AZG/SWÖ-KV zertifiziert | Legende: <strong>X7/X6/X4</strong> = DGKP Tag | <strong>WBL / WBL-P</strong> = Leitung bis 15:30 (Reserve-DGKP) | <strong>F2/F7</strong> = PFA/PA Tag | <strong>JED</strong> = Speisesaal | <strong>N1/N2</strong> = Nacht | <strong>➔ H / ➔ B</strong> = Aushilfe</div>
"""]

    for dept_name in ["Abteilung B", "Abteilung H", "Abteilung F"]:
        sub_df = df_plan[df_plan["Abteilung"] == dept_name].copy()
        if sub_df.empty:
            continue

        html_parts.append(f"<h2>{dept_name} – Monatsübersicht ({monat_str} {leto})</h2>")
        html_parts.append("<table><thead><tr>")
        html_parts.append('<th class="role-col">Rolle</th><th class="name-col">Mitarbeiter</th>')

        for d in range(1, num_days + 1):
            dow = (d - 1 + first_day_weekday) % 7
            is_hol = (date(leto, mesec, d) in at_holidays) or (mesec == 12 and d in [24, 31])
            cls = "hol-col" if is_hol else ("we-col" if dow >= 5 else "")
            html_parts.append(f'<th class="{cls}">{d}<br><span style="font-size:6.5pt;font-weight:normal;">{dow_short[dow]}</span></th>')

        html_parts.append('<th class="sum-col">SOLL</th><th class="sum-col">IST</th><th class="sum-col">ÜB.</th><th class="sum-col">SALDO</th></tr></thead><tbody>')

        for _, r in sub_df.iterrows():
            html_parts.append("<tr>")
            html_parts.append(f'<td class="role-col">{r["Rolle"]}</td>')
            html_parts.append(f'<td class="name-col">{r["Mitarbeiter"]}</td>')
            for d in range(1, num_days + 1):
                c = f"{d}."
                val = str(r.get(c, "...")).strip()
                base_sh = extract_base_shift(val)
                dow = (d - 1 + first_day_weekday) % 7
                is_hol = (date(leto, mesec, d) in at_holidays) or (mesec == 12 and d in [24, 31])
                cell_cls = "hol-col" if is_hol else ("we-col" if dow >= 5 else "")

                if base_sh in NIGHT_SHIFTS:
                    cell_cls = "sh-night"
                elif base_sh == "WBL-P":
                    cell_cls = "sh-wblp"
                elif "➔" in val or "⬅️" in val:
                    cell_cls = "sh-springer"
                elif val == "URL":
                    cell_cls = "sh-url"
                elif val == "KRA":
                    cell_cls = "sh-kra"
                elif val == "ZA":
                    cell_cls = "sh-za"
                elif "🚨" in val:
                    cell_cls = "sh-alarm"

                disp_val = "" if val == "..." else val
                html_parts.append(f'<td class="{cell_cls}">{disp_val}</td>')

            html_parts.append(f'<td class="sum-col">{r["SOLL"]:.1f}</td>')
            html_parts.append(f'<td class="sum-col">{r["IST"]:.1f}</td>')
            html_parts.append(f'<td class="sum-col">{r["ÜBERSTD."]:.1f}</td>')
            html_parts.append(f'<td class="sum-col">{r["SALDO"]:.1f}</td>')
            html_parts.append("</tr>")

        cov_df = build_coverage_summary_df(df_plan, dept_name, num_days, min_b, min_h)
        for _, c_row in cov_df.iterrows():
            kat_name = str(c_row["Kontroll-Kategorie"])
            html_parts.append('<tr><td class="role-col" style="background:#e9ecef;font-weight:bold;">Check</td>')
            html_parts.append(f'<td class="name-col" style="background:#e9ecef;">{kat_name}</td>')
            for d in range(1, num_days + 1):
                c = f"{d}."
                cv = c_row[c]
                html_parts.append(f'<td style="background:#f1f3f5;font-weight:bold;">{cv}</td>')
            html_parts.append('<td colspan="4" style="background:#e9ecef;"></td></tr>')

        html_parts.append("</tbody></table>")

    html_parts.append(f"""
<div class="sig-box">
    <div class="sig-line">Datum: {date.today().strftime('%d.%m.%Y')}</div>
    <div class="sig-line">Unterschrift WBL / Stationsleitung (Uroš Ruis, DGKP)</div>
    <div class="sig-line">Genehmigung Pflegedienstleitung (PDL)</div>
</div>
</body></html>""")
    return "\n".join(html_parts)

def generate_employee_stundenzettel_html(emp_row, emp_zuschlag_row, num_days, leto, mesec, first_day_weekday, at_holidays):
    monat_str = MONTH_NAMES_DE[mesec - 1]
    dow_short = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
    emp_name = str(emp_row["Mitarbeiter"])
    abt = str(emp_row["Abteilung"])
    rolle = str(emp_row["Rolle"])

    rows_html = []
    for d in range(1, num_days + 1):
        c = f"{d}."
        raw_v = str(emp_row.get(c, "...")).strip()
        base_sh = extract_base_shift(raw_v)
        dow = (d - 1 + first_day_weekday) % 7
        is_hol = (date(leto, mesec, d) in at_holidays) or (mesec == 12 and d in [24, 31])
        hrs = SHIFTS_HUNDREDTHS.get(base_sh, 0) / 100.0 if base_sh in SHIFTS_HUNDREDTHS else 0.0
        time_info = SHIFT_TIME_LOOKUP.get(base_sh, "")
        bg = "#fff0f0" if is_hol else ("#f2f2f7" if dow >= 5 else "#ffffff")
        bemerkung = time_info
        if is_hol:
            bemerkung += " | Feiertag" if bemerkung else "Feiertag"
        elif dow >= 5:
            bemerkung += " | Wochenende" if bemerkung else "Wochenende"
        if "➔" in raw_v:
            bemerkung += f" | Aushilfe ({raw_v})"
        if base_sh == "WBL-P":
            bemerkung += " | Leitung als Diplom-Reserve bis 15:30"
        rows_html.append(
            f"<tr style='background:{bg};'>"
            f"<td>{d:02d}.{mesec:02d}.{leto}</td>"
            f"<td>{dow_short[dow]}</td>"
            f"<td style='font-weight:bold;'>{'' if raw_v == '...' else raw_v}</td>"
            f"<td>{hrs:.2f} h</td>"
            f"<td>{bemerkung}</td></tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><title>Stundennachweis {emp_name}</title>
<style>
    @page {{ size: A4 portrait; margin: 12mm; }}
    body {{ font-family: Arial, sans-serif; font-size: 9.5pt; color: #111; }}
    h1 {{ font-size: 14pt; color: #1e3a8a; margin-bottom: 4px; }}
    .box {{ border: 1px solid #888; padding: 8px; margin-bottom: 10px; background: #f8f9fa; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 6px; }}
    th, td {{ border: 1px solid #999; padding: 3px 6px; text-align: left; font-size: 8.5pt; }}
    th {{ background: #e9ecef; }}
    .sig {{ display: flex; justify-content: space-between; margin-top: 28px; }}
    .sig div {{ width: 42%; border-top: 1px solid #222; padding-top: 4px; text-align: center; }}
    @media print {{ .no-print {{ display: none; }} }}
</style></head><body>
<div class="no-print" style="margin-bottom:10px;">
    <button onclick="window.print()" style="padding:6px 12px;font-weight:bold;cursor:pointer;">🖨️ Stundennachweis drucken / PDF</button>
</div>
<h1>📄 Persönlicher Monats-Stundennachweis – {monat_str} {leto}</h1>
<div class="box">
    <strong>Mitarbeiter:</strong> {emp_name} &nbsp;|&nbsp; <strong>Station:</strong> {abt} &nbsp;|&nbsp; <strong>Rolle:</strong> {rolle}<br>
    <strong>SOLL-Stunden:</strong> {emp_row['SOLL']:.1f} h &nbsp;|&nbsp; <strong>IST-Stunden:</strong> {emp_row['IST']:.1f} h &nbsp;|&nbsp;
    <strong>Überstunden:</strong> {emp_row['ÜBERSTD.']:.1f} h &nbsp;|&nbsp; <strong>Neuer Gesamtsaldo:</strong> {emp_row['SALDO']:.1f} h<br>
    <strong>Nachtdienste:</strong> {emp_zuschlag_row['🌙 Nachtdienste (Anz.)']} ({emp_zuschlag_row['🌙 Nacht-Stunden (h)']} h) &nbsp;|&nbsp;
    <strong>SO-Stunden:</strong> {emp_zuschlag_row['☀️ SO-Stunden (Zuschlag)']} h &nbsp;|&nbsp;
    <strong>FT-Stunden:</strong> {emp_zuschlag_row['⭐ FT-Stunden (Feiertag)']} h &nbsp;|&nbsp;
    <strong>Resturlaub neu:</strong> {emp_zuschlag_row['🏝️ URL Rest Neu']} Tage
</div>
<table>
    <thead><tr><th>Datum</th><th>Wochentag</th><th>Dienst / Abwesenheit</th><th>Netto-Arbeitszeit</th><th>Uhrzeit / Pause / Bemerkung</th></tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
</table>
<div class="sig">
    <div>Datum, Unterschrift Mitarbeiter/in ({emp_name})</div>
    <div>Unterschrift WBL / Stationsleitung</div>
</div>
</body></html>"""

def run_austrian_law_audit(df_plan, staff_df, shifts_df, num_days, leto, mesec, first_day_weekday, at_holidays, min_b=4, min_h=4):
    issues = []
    day_cols_only = [f"{d}." for d in range(1, num_days + 1) if f"{d}." in df_plan.columns]
    real_df = df_plan[~df_plan["Mitarbeiter"].astype(str).str.contains("X-Oseba|FEHLT|⚠️|🤝 Aushilfe", na=False)]

    status_map = {}
    for _, s_r in staff_df.iterrows():
        b_n = str(s_r["Name"]).strip().lower()
        status_map[b_n] = str(s_r.get("Gesetz_Status", "Normal")).strip()

    for _, row in real_df.iterrows():
        emp = str(row["Mitarbeiter"])
        base_emp = emp.split(" (")[0].strip().lower()
        gesetz_st = status_map.get(base_emp, "Normal")
        abt = str(row["Abteilung"])
        vals = [extract_base_shift(row[c]) for c in day_cols_only]

        if abt == "Abteilung F":
            for d, v in enumerate(vals):
                if v in SHIFTS_HUNDREDTHS and v not in NIGHT_SHIFTS + ["OFF"]:
                    issues.append({
                        "Kategorie": "🛑 Abt. F Tagdienst-Sperre",
                        "Betroffen": f"{emp} ({abt})",
                        "Zeitraum": f"Tag {d+1}.",
                        "Details": f"Mitarbeiter auf Abt. F hat Tagdienst '{v}' (Abt. F ist nur für Nachtdienste vorgesehen)."
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
        dgkp_rows = real_df[real_df["Rolle"].isin(["DGKP", "Leitung"])]
        hh_rows = real_df[real_df["Rolle"] == "Heimhelfer"]
        all_n1 = sum(1 for v in real_df[c].astype(str) if extract_base_shift(v) == "N1")
        all_n2 = sum(1 for v in real_df[c].astype(str) if extract_base_shift(v) == "N2")
        dgkp_in_night = sum(1 for v in dgkp_rows[c].astype(str) if extract_base_shift(v) in NIGHT_SHIFTS)
        jed_count = sum(1 for v in hh_rows[c].astype(str) if extract_base_shift(v) == "JED")
        hh_in_care = sum(1 for v in hh_rows[c].astype(str) if extract_base_shift(v) in DAY_CARE_SHIFTS)

        if jed_count == 0 and hh_in_care > 0:
            issues.append({
                "Kategorie": "🛑 Heimhelfer-Priorität (JED fehlt!)",
                "Betroffen": "Speisesaal (Abt. B)",
                "Zeitraum": f"Tag {d+1}.",
                "Details": "Ein Heimhelfer arbeitet in der Pflege, obwohl der Speisesaal (JED) noch nicht besetzt ist!"
            })

        if dgkp_in_night > 1:
            issues.append({
                "Kategorie": "🛑 2 DGKP im Nachtdienst (Verboten!)",
                "Betroffen": "Nachtdienst",
                "Zeitraum": f"Nacht am {d+1}.",
                "Details": f"Es sind {dgkp_in_night} DGKP gleichzeitig in der Nacht eingeteilt (Maximal 1 DGKP erlaubt!)."
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
if "max_vac_per_station" not in st.session_state:
    st.session_state.max_vac_per_station = 2

tab1, tab_shifts, tab_pavo, tab3, tab2, tab_print, tab4, tab5, tab6 = st.tabs([
    "⚙️ 1. Team & Verträge", 
    "⏱️ 2. Dienste-Studio & Zeitrechner",
    "🧮 3. StPAVO Rechner",
    "🗓️ 4. Kompakt-Kalender & Kontingent", 
    "📅 5. Dienstplan", 
    "🖨️ 6. Geocon & Druck-Studio",
    "🚨 7. SOS & Tauschbörse", 
    "📉 8. Analyse & Wunsch-Quote", 
    "🛡️ 9. Inspektorat Steiermark"
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
            format_func=lambda x: MONTH_NAMES_DE[x - 1]
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
    st.header("2. Team, Rollen (inkl. Leitung-Reserve & PFA), Gesetzlicher Status & Erlaubte Dienste")
    
    if "staff_df_v76" not in st.session_state:
        loaded_df = None
        if os.path.exists("team_data.csv"):
            try:
                with open("team_data.csv", "rb") as f:
                    loaded_df = sanitize_team_df(read_csv_smart(f.read(), is_index_col=False))
            except Exception: 
                loaded_df = None

        if loaded_df is None or loaded_df.empty:
            initial_staff = []
            initial_staff.append({"ID": len(initial_staff), "Name": "WBL Uroš", "Abteilung": "Abteilung H", "Rolle": "Leitung", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 30.0, "URL_Rest": 30.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": False, "SO": False, "FT": False, "Spezialdienst": "WBL, WBL-P"})
            for i in range(1, 6): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP B-{i}", "Abteilung": "Abteilung B", "Rolle": "DGKP", "Qualifikation": "Wundmanager" if i==1 else "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 5): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP H-{i}", "Abteilung": "Abteilung H", "Rolle": "DGKP", "Qualifikation": "Praxisanleiter" if i==1 else "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 5): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP F-{i}", "Abteilung": "Abteilung F", "Rolle": "DGKP", "Qualifikation": "Keine", "Gesetz_Status": "Nachtschwerarbeit (NSchG)", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 12, "Nur_Nacht": True, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 3): initial_staff.append({"ID": len(initial_staff), "Name": f"PFA B-{i}", "Abteilung": "Abteilung B", "Rolle": "PFA", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 3): initial_staff.append({"ID": len(initial_staff), "Name": f"PFA H-{i}", "Abteilung": "Abteilung H", "Rolle": "PFA", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 7): initial_staff.append({"ID": len(initial_staff), "Name": f"PA B-{i}", "Abteilung": "Abteilung B", "Rolle": "Pflegeassistenz", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 7): initial_staff.append({"ID": len(initial_staff), "Name": f"PA H-{i}", "Abteilung": "Abteilung H", "Rolle": "Pflegeassistenz", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 4): initial_staff.append({"ID": len(initial_staff), "Name": f"HH B-{i}", "Abteilung": "Abteilung B", "Rolle": "Heimhelfer", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "JED"})
            for i in range(1, 3): initial_staff.append({"ID": len(initial_staff), "Name": f"HH H-{i}", "Abteilung": "Abteilung H", "Rolle": "Heimhelfer", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "JED"})
            
            st.session_state.staff_df_v76 = pd.DataFrame(initial_staff)
        else:
            st.session_state.staff_df_v76 = loaded_df

    col_import, col_export = st.columns(2)
    with col_export:
        st.download_button(
            label="📥 Aktuelles Team als Backup speichern", 
            data=st.session_state.staff_df_v76.to_csv(index=False).encode('utf-8'), 
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
                    st.session_state.staff_df_v76 = uploaded_team
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
        for k in ["staff_df_v76", "shifts_df_v76", "pavo_df_v76", "abs_matrix_v76", "raw_uploaded_cal", "last_generated_df"]:
            if k in st.session_state: 
                del st.session_state[k]
        st.session_state.team_editor_ver += 1
        st.session_state.shifts_editor_ver += 1
        st.session_state.cal_editor_ver += 1
        st.session_state.plan_editor_ver += 1
        st.rerun()

    st.subheader("🎛️ Individueller Dienst-, Stunden- & Schutzstatus-Konfigurator")
    current_staff_tab1 = st.session_state.staff_df_v76["Name"].dropna().astype(str).str.strip().tolist()
    with st.form("custom_shift_builder_form"):
        cb1, cb2, cb3, cb4, cb5 = st.columns([1.8, 2.2, 1.3, 1.3, 0.9])
        with cb1:
            sel_staff_custom = st.multiselect("1. Mitarbeiter:", current_staff_tab1)
        with cb2:
            sel_shifts_custom = st.multiselect(
                "2. Erlaubte Schichten (auch Sonderdienste):",
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
            df_mod = st.session_state.staff_df_v76.copy()
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
            st.session_state.staff_df_v76 = df_mod
            df_mod.to_csv("team_data.csv", index=False)
            st.session_state.team_editor_ver += 1
            st.success("✅ Einstellungen erfolgreich auf Mitarbeiter übertragen!")
            st.rerun()

    with st.form("team_editor_form"):
        edited_data = st.data_editor(
            st.session_state.staff_df_v76, 
            num_rows="dynamic", 
            key=f"tabelle_mitarbeiter_v76_{st.session_state.team_editor_ver}",
            column_config={
                "ID": None,
                "Abteilung": st.column_config.SelectboxColumn("Abteilung", options=["Abteilung B", "Abteilung H", "Abteilung F"]),
                "Rolle": st.column_config.SelectboxColumn("Rolle", options=ROLE_OPTIONS),
                "Qualifikation": st.column_config.SelectboxColumn("Zusatzqualifikation", options=["Keine", "Wundmanager", "Praxisanleiter", "Palliativ"]),
                "Gesetz_Status": st.column_config.SelectboxColumn("Gesetzl. Status (Steiermark)", options=GESETZ_STATUS_OPTIONS, width="medium"),
                "Wochenstd": st.column_config.NumberColumn("Wochenstd.", min_value=1.0, max_value=60.0, default=37.0, step=0.5),
                "Prozent": st.column_config.NumberColumn("Anst. (%)", disabled=True), 
                "Max_Nacht": st.column_config.NumberColumn("Max Nacht", min_value=0, max_value=20, default=0),
                "Nur_Nacht": st.column_config.CheckboxColumn("Nur Nacht?"),
                "Spezialdienst": st.column_config.TextColumn(
                    "Erlaubte Dienste (z.B. Ohne = Standard, oder exakt: F7, MS, T8)", 
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
            st.session_state.staff_df_v76 = clean_edited
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

# --- TAB 2: DIENSTE-STUDIO INKL. LIVE-ARBEITSZEIT- & § 11 AZG PAUSENRECHNER ---
with tab_shifts:
    st.header("⏱️ 2. Dienste-Studio & Automatischer Arbeitszeit-Rechner (§ 11 AZG Pausen-Automatik)")
    st.info(
        "💡 **Intelligenter Zeit- & § 11 AZG Pausen-Rechner:** \n"
        "- **Unter / bis 6,0h Brutto:** Automatisch **`0 Min.`** Pause (keine Pflichtpause nach § 11 AZG).\n"
        "- **Über 6,0h bis unter 10,0h Brutto:** Automatisch **`30 Min.`** gesetzliche Ruhepause nach § 11 AZG.\n"
        "- **Langdienste ab 10,0h Brutto:** Automatisch **`45 Min.`** Ruhepause (du kannst den Wert bei Bedarf jederzeit im Feld anpassen)."
    )

    with st.container(border=True):
        st.subheader("🕒 Neuen Dienst mit Zeit- & § 11 AZG Pausenrechner erstellen")
        col_mode1, col_mode2 = st.columns([2, 1.5])
        with col_mode1:
            calc_mode = st.radio(
                "Berechnungs-Modus für Dienststunden:",
                ["🧮 Automatisch aus Beginn, Ende & Pause berechnen (Empfohlen)", "✍️ Netto-Stunden manuell als Zahl eingeben"],
                horizontal=True
            )
        with col_mode2:
            azg_auto_pause = st.checkbox(
                "⚖️ Gesetzliche Pause nach § 11 AZG automatisch vorschlagen (0 / 30 / 45 Min.)",
                value=True,
                help="Wenn aktiv, wird die Pause automatisch anhand der Brutto-Dauer auf 0 Min. (≤6h), 30 Min. (>6h) oder 45 Min. (≥10h Langdienst) voreingestellt."
            )

        sc1, sc2, sc3 = st.columns([1.1, 2.2, 1.8])
        with sc1:
            new_sh_code = st.text_input("1. Dienst-Kürzel:", placeholder="z. B. T8, K6, SD1").strip().upper()
        with sc2:
            new_sh_name = st.text_input("2. Name / Beschreibung:", placeholder="z. B. Kurzdienst / Zwischendienst").strip()
        with sc3:
            new_sh_type = st.selectbox("3. Dienst-Kategorie:", ["Tagdienst Pflege", "Nachtdienst", "Speisesaal / Sonder", "Leitung / Büro"])

        tc1, tc2, tc3, tc4 = st.columns([1.1, 1.1, 1.3, 2.5])
        with tc1:
            t_start = st.time_input("4. Beginn (Uhrzeit):", value=time(7, 0), step=300)
        with tc2:
            t_end = st.time_input("5. Ende (Uhrzeit):", value=time(15, 30), step=300)

        von_str = t_start.strftime("%H:%M")
        bis_str = t_end.strftime("%H:%M")
        raw_brutto_h, is_overnight = get_brutto_hours_and_overnight(von_str, bis_str)
        suggested_azg_min, azg_Explanation = get_azg_pause_suggestion(raw_brutto_h, new_sh_type)

        with tc3:
            if azg_auto_pause:
                p_min = st.number_input(
                    "6. Pause (Min. – § 11 AZG):",
                    min_value=0, max_value=180,
                    value=int(suggested_azg_min),
                    step=5,
                    key=f"p_azg_{von_str}_{bis_str}_{new_sh_type}"
                )
            else:
                p_min = st.number_input(
                    "6. Pause (Minuten manuell):",
                    min_value=0, max_value=180,
                    value=30,
                    step=5,
                    key="p_manual_fixed"
                )

        brutto_h, auto_netto_h, _ = calculate_shift_hours_from_times(von_str, bis_str, p_min)

        with tc4:
            st.caption(azg_Explanation)
            if "Automatisch" in calc_mode:
                final_new_hours = auto_netto_h
                night_badge = " 🌙 *(Über Mitternacht)*" if is_overnight else ""
                st.success(
                    f"⏱️ **Ergebnis ({von_str} – {bis_str}){night_badge}:** "
                    f"Brutto `{brutto_h:.2f} h` − Pause `{p_min} Min. ({p_min/60.0:.2f} h)` = **`{final_new_hours:.2f} Netto-Stunden`**"
                )
            else:
                final_new_hours = st.number_input(
                    "Manuelle Netto-Stunden (h):", min_value=0.25, max_value=24.0, value=float(auto_netto_h), step=0.05, format="%.2f"
                )

        st.markdown("**7. Zuweisungs-Modus & Berufsgruppen:**")
        rc0, rc1, rc2, rc3, rc4, rc5 = st.columns([1.5, 1, 1, 1, 1, 1.5])
        with rc0:
            auto_std_new = st.checkbox(
                "⚡ Standard für Alle?", value=False,
                help="Lasse dieses Häkchen AUS, damit dieser Dienst nur Personen zugewiesen wird, bei denen du ihn explizit einträgst!"
            )
        with rc1:
            allow_dgkp = st.checkbox("🩺 DGKP/WBL", value=True)
        with rc2:
            allow_pfa = st.checkbox("💉 PFA", value=True)
        with rc3:
            allow_pa = st.checkbox("🏥 PA", value=True)
        with rc4:
            allow_hh = st.checkbox("🍽️ HH", value=True)
        with rc5:
            if st.button("💾 Dienst jetzt speichern", type="primary", use_container_width=True):
                if not new_sh_code or new_sh_code in ["OFF", "..."]:
                    st.error("Bitte ein gültiges Dienst-Kürzel eingeben (z. B. T8, K6, SD1)!")
                else:
                    df_sh = st.session_state.shifts_df_v76.copy()
                    desc_label = new_sh_name if new_sh_name else f"Dienst {new_sh_code}"
                    new_entry = pd.DataFrame([{
                        "Kürzel": new_sh_code,
                        "Bezeichnung": desc_label,
                        "Von": von_str,
                        "Bis": bis_str,
                        "Pause_Min": int(p_min),
                        "Stunden": float(final_new_hours),
                        "Typ": new_sh_type,
                        "Auto_Standard": bool(auto_std_new),
                        "Erlaubt_DGKP": bool(allow_dgkp),
                        "Erlaubt_PFA": bool(allow_pfa),
                        "Erlaubt_PA": bool(allow_pa),
                        "Erlaubt_HH": bool(allow_hh)
                    }])
                    df_sh = pd.concat([df_sh, new_entry], ignore_index=True)
                    df_sh = sanitize_shifts_df(df_sh, recalc_from_time=False)
                    st.session_state.shifts_df_v76 = df_sh
                    df_sh.to_csv("shifts_data.csv", index=False)
                    st.session_state.shifts_editor_ver += 1
                    if "last_generated_df" in st.session_state:
                        st.session_state.last_generated_df = recalculate_plan_df(
                            st.session_state.last_generated_df, st.session_state.staff_df_v76, num_days
                        )
                        st.session_state.last_generated_df.to_csv(plan_autosave_path, index=False)
                        st.session_state.plan_editor_ver += 1
                    st.success(
                        f"✅ Dienst **{new_sh_code}** ({von_str}–{bis_str}, Pause {p_min} Min. ➔ **{final_new_hours:.2f}h Netto**) gespeichert!"
                    )
                    st.rerun()

    st.divider()
    st.subheader("📋 Alle Dienste im System (Inkl. Von, Bis, Pause & Netto-Stunden)")
    recalc_table_toggle = st.checkbox(
        "🔄 Beim Speichern der Tabelle die `Netto-Stunden (h)` automatisch aus `Von`, `Bis` und `Pause (Min)` neu berechnen",
        value=True
    )
    with st.form("edit_all_shifts_form"):
        edited_shifts_df = st.data_editor(
            st.session_state.shifts_df_v76,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key=f"shifts_table_editor_{st.session_state.shifts_editor_ver}",
            column_config={
                "Kürzel": st.column_config.TextColumn("Kürzel", width="small", required=True),
                "Bezeichnung": st.column_config.TextColumn("Bezeichnung", width="medium"),
                "Von": st.column_config.TextColumn("Von (HH:MM)", width="small"),
                "Bis": st.column_config.TextColumn("Bis (HH:MM)", width="small"),
                "Pause_Min": st.column_config.NumberColumn("Pause (Min)", min_value=0, max_value=180, step=5, width="small"),
                "Stunden": st.column_config.NumberColumn("Netto-Stunden (h)", min_value=0.25, max_value=24.0, step=0.05, format="%.2f"),
                "Typ": st.column_config.SelectboxColumn("Kategorie", options=["Tagdienst Pflege", "Nachtdienst", "Speisesaal / Sonder", "Leitung / Büro"], width="medium"),
                "Auto_Standard": st.column_config.CheckboxColumn("Standard für Alle?", help="Wenn AUS: Dienst wird nur geplant, wenn er bei der Person explizit eingetragen ist!"),
                "Erlaubt_DGKP": st.column_config.CheckboxColumn("DGKP/WBL"),
                "Erlaubt_PFA": st.column_config.CheckboxColumn("PFA"),
                "Erlaubt_PA": st.column_config.CheckboxColumn("PA"),
                "Erlaubt_HH": st.column_config.CheckboxColumn("HH")
            }
        )
        col_sh_btn1, col_sh_btn2 = st.columns([2, 1])
        with col_sh_btn1:
            save_table_shifts = st.form_submit_button("💾 Änderungen an der Dienste-Tabelle speichern", type="primary", use_container_width=True)
        with col_sh_btn2:
            reset_shifts_btn = st.form_submit_button("🔄 Standard-Dienste wiederherstellen", use_container_width=True)

        if save_table_shifts:
            clean_sh = sanitize_shifts_df(edited_shifts_df, recalc_from_time=recalc_table_toggle)
            st.session_state.shifts_df_v76 = clean_sh
            clean_sh.to_csv("shifts_data.csv", index=False)
            st.session_state.shifts_editor_ver += 1
            if "last_generated_df" in st.session_state:
                st.session_state.last_generated_df = recalculate_plan_df(
                    st.session_state.last_generated_df, st.session_state.staff_df_v76, num_days
                )
                st.session_state.last_generated_df.to_csv(plan_autosave_path, index=False)
                st.session_state.plan_editor_ver += 1
            st.success("✅ Dienste-Katalog aktualisiert und alle Dienstplan-Stunden neu berechnet!")
            st.rerun()

        if reset_shifts_btn:
            default_sh = get_default_shifts_df()
            st.session_state.shifts_df_v76 = default_sh
            default_sh.to_csv("shifts_data.csv", index=False)
            st.session_state.shifts_editor_ver += 1
            st.rerun()

with tab_pavo:
    st.header("🧮 3. StPAVO Steiermark – Personalberechnung nach Pflegestufen & Qualifikations-Mix")
    st.subheader("1. Bewohneranzahl nach Pflegegeldstufen (Stufe 0 bis 7) eingeben")
    edited_pavo = st.data_editor(
        st.session_state.pavo_df_v76,
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
    if not edited_pavo.equals(st.session_state.pavo_df_v76):
        st.session_state.pavo_df_v76 = edited_pavo
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

    stufen_cols = ["Stufe_0", "Stufe_1", "Stufe_2", "Stufe_3", "Stufe_4", "Stufe_5", "Stufe_6", "Stufe_7"]
    station_results = []
    total_residents = 0
    total_soll_vza = 0.0

    for _, p_row in st.session_state.pavo_df_v76.iterrows():
        abt_n = str(p_row["Abteilung"])
        bew_sum = sum(int(p_row.get(sc, 0)) for sc in stufen_cols)
        vza_sum = sum(float(p_row.get(sc, 0)) / DEFAULT_PAVO_KEYS[sc] for sc in stufen_cols)
        
        netto_tag_vza = max(1.0, vza_sum - 3.2)
        daily_netto_hours = (netto_tag_vza * 29.8) / 7.0
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

    df_team_curr = sanitize_team_df(st.session_state.staff_df_v76)
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
            f"💡 **Stations-Fokus im KI-Planer:** "
            f"**Abteilung B:** Min. `{st.session_state.target_min_b}` (Ideal 5) PA/PFA + 1 HH (`JED` Pflicht!) + 1 DGKP | "
            f"**Abteilung H:** Min. `{st.session_state.target_min_h}` PA/PFA/HH + 1 DGKP (mit WBL-Reserve bis 15:30 Mo–Fr)."
        )
    with col_apply_pavo2:
        if st.button("🔗 StPAVO-Tagesbedarf übernehmen", type="primary", use_container_width=True):
            st.session_state.target_min_b = int(empf_b)
            st.session_state.target_min_h = int(empf_h)
            st.success(f"✅ Tagesbedarf (Abt. B = {empf_b}, Abt. H = {empf_h}) übernommen!")

    st.divider()
    st.subheader("3. Prozentuale Aufteilung nach Berufsgruppen (StPAVO Qualifikations-Mix: SOLL vs. IST)")

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
            "StPAVO Status": "🟢 Erfüllt" if pct_dgkp_ist >= pct_dgkp and vza_dgkp_ist >= soll_dgkp_vza - 0.2 else "🔴 Zu wenig DGKP"
        },
        {
            "Berufsgruppe (StPAVO Steiermark)": "💉 Pflegefachassistenz (PFA)",
            "Gesetzl. Vorgabe (%)": f"Richtwert {pct_pfa:.1f} %",
            "IST-Anteil im Team (%)": f"{pct_pfa_ist:.1f} %",
            "SOLL (VZÄ)": round(soll_pfa_vza, 2),
            "IST (VZÄ)": round(vza_pfa_ist, 2),
            "Differenz (VZÄ)": round(vza_pfa_ist - soll_pfa_vza, 2),
            "StPAVO Status": "🟢 Optimal" if vza_pfa_ist >= soll_pfa_vza - 0.5 else "🟡 Durch DGKP/PA kompensiert"
        },
        {
            "Berufsgruppe (StPAVO Steiermark)": "🏥 Pflegeassistenz (PA)",
            "Gesetzl. Vorgabe (%)": f"Richtwert {pct_pa:.1f} %",
            "IST-Anteil im Team (%)": f"{pct_pa_ist:.1f} %",
            "SOLL (VZÄ)": round(soll_pa_vza, 2),
            "IST (VZÄ)": round(vza_pa_ist, 2),
            "Differenz (VZÄ)": round(vza_pa_ist - soll_pa_vza, 2),
            "StPAVO Status": "🟢 Erfüllt" if (pct_dgkp_ist + pct_pfa_ist + pct_pa_ist) >= (pct_dgkp + pct_pfa + pct_pa - 1.0) else "🔴 Pflege-Quote prüfen"
        },
        {
            "Berufsgruppe (StPAVO Steiermark)": "🍽️ Heimhilfe (HH)",
            "Gesetzl. Vorgabe (%)": f"max. {pct_hh:.1f} %",
            "IST-Anteil im Team (%)": f"{pct_hh_ist:.1f} %",
            "SOLL (VZÄ)": round(soll_hh_vza, 2),
            "IST (VZÄ)": round(vza_hh_ist, 2),
            "Differenz (VZÄ)": round(vza_hh_ist - soll_hh_vza, 2),
            "StPAVO Status": "🟢 Gesetzestreu" if pct_hh_ist <= pct_hh + 1.0 else "⚠️ Über Max.-Quote (Max. 20%)"
        }
    ])
    st.dataframe(qual_mix_df, use_container_width=True, hide_index=True)

with tab3:
    st.header("🗓️ 4. Kompakt-Kalender, Live-Urlaubs-Kontingent-Ampel & Auto-ZA-Assistent")
    current_staff = st.session_state.staff_df_v76["Name"].dropna().astype(str).str.strip().tolist()
    
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

    if "abs_matrix_v76" not in st.session_state:
        if os.path.exists(cal_autosave_path):
            try:
                with open(cal_autosave_path, "rb") as f:
                    saved_cal = read_csv_smart(f.read(), is_index_col=True)
                st.session_state.raw_uploaded_cal = saved_cal
                st.session_state.abs_matrix_v76 = sync_calendar_df(saved_cal, current_staff, day_cols)
            except Exception:
                st.session_state.abs_matrix_v76 = pd.DataFrame("", index=current_staff, columns=day_cols)
        else:
            st.session_state.abs_matrix_v76 = pd.DataFrame("", index=current_staff, columns=day_cols)
    else:
        if st.session_state.get("needs_cal_resync") and "raw_uploaded_cal" in st.session_state:
            st.session_state.abs_matrix_v76 = sync_calendar_df(st.session_state.raw_uploaded_cal, current_staff, day_cols)
            st.session_state.needs_cal_resync = False
        else:
            st.session_state.abs_matrix_v76 = sync_calendar_df(st.session_state.abs_matrix_v76, current_staff, day_cols)

    dynamic_fix_options = [
        f"📌 {row['Kürzel']} (Fix {row['Von']}–{row['Bis']} | {row['Stunden']}h)"
        for _, row in SHIFTS_DF_CURRENT.iterrows()
    ]
    entry_options = [
        "", 
        "URL (Urlaub - Fix & bezahlt)", 
        "ENT (Entlastungstag - Fix & Block-Erholung)", 
        "ZA (Zeitausgleich - Fix & baut Überstunden ab)",
        "WUN (Wunsch-Frei - Fairer KI-Richter)", 
        "SU (Sonderurlaub)", 
        "KRA (Krankenstand)", 
        "FO (Fortbildung GuKG)", 
        "MUS (Muss arbeiten)"
    ] + dynamic_fix_options + ["🗑️ LÖSCHEN (Zelle leeren)"]

    col_bak1, col_bak2, col_bak3 = st.columns([1.2, 1.2, 1.2])
    with col_bak1:
        st.download_button(
            label="📥 Kalender / Fix-Dienste als Backup speichern", 
            data=st.session_state.abs_matrix_v76.to_csv(index=True).encode('utf-8'), 
            file_name=f"Urlaubsmatrix_{mesec}_{leto}.csv", 
            mime="text/csv",
            use_container_width=True
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
                    st.session_state.abs_matrix_v76 = synced_cal
                    synced_cal.to_csv(cal_autosave_path, index=True)
                    st.session_state.last_cal_hash = cal_hash
                    st.session_state.cal_editor_ver += 1
                    st.success("✅ Kalender sofort geladen!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Fehler beim Laden des Kalenders: {e}")
    with col_bak3:
        st.session_state.max_vac_per_station = st.number_input(
            "🚦 Max. Urlaube/Abwesende pro Station (B / H):",
            min_value=1, max_value=5, value=int(st.session_state.max_vac_per_station), step=1
        )

    with st.expander("🤖 KI-Urlaubs-Kontingent-Prüfer & Automatischer ZA-/Entlastungs-Planer", expanded=False):
        q_c1, q_c2 = st.columns(2)
        with q_c1:
            st.markdown("**🔍 1. Urlaubs-Antrag vorab auf Kontingent prüfen:**")
            chk_emp = st.selectbox("Mitarbeiter für Antrag:", current_staff, key="chk_vac_emp")
            chk_d1, chk_d2 = st.slider("Gewünschter Zeitraum:", 1, num_days, (1, 7), key="chk_vac_days")
            if st.button("🚦 Prüfen, ob Urlaub im Kontingent frei ist"):
                emp_row_info = st.session_state.staff_df_v76[st.session_state.staff_df_v76["Name"] == chk_emp].iloc[0]
                e_abt = str(emp_row_info["Abteilung"])
                e_rol = str(emp_row_info["Rolle"])
                q_df_now = build_vacation_quota_summary_df(
                    st.session_state.abs_matrix_v76, st.session_state.staff_df_v76, day_cols, st.session_state.max_vac_per_station
                )
                conflict_days = []
                for d_i in range(chk_d1, chk_d2 + 1):
                    c_n = day_cols[d_i - 1]
                    if e_abt == "Abteilung B" and int(q_df_now.iloc[0][c_n]) >= st.session_state.max_vac_per_station:
                        conflict_days.append(f"{d_i}. (Abt. B voll)")
                    elif e_abt == "Abteilung H" and int(q_df_now.iloc[1][c_n]) >= st.session_state.max_vac_per_station:
                        conflict_days.append(f"{d_i}. (Abt. H voll)")
                    elif e_abt == "Abteilung F" and int(q_df_now.iloc[4][c_n]) >= 1:
                        conflict_days.append(f"{d_i}. (Abt. F Nachtpool voll)")
                    if e_rol == "Heimhelfer" and int(q_df_now.iloc[3][c_n]) >= 1:
                        conflict_days.append(f"{d_i}. (Bereits 1 HH auf Urlaub – JED-Gefahr!)")
                    if e_rol == "DGKP" and e_abt in ["Abteilung B", "Abteilung H"] and int(q_df_now.iloc[2][c_n]) >= 2:
                        conflict_days.append(f"{d_i}. (Bereits 2 DGKP abwesend)")
                if not conflict_days:
                    st.success(f"✅ **GRÜNES LICHT!** `{chk_emp}` ({e_abt}, {e_rol}) kann von **{chk_d1}. bis {chk_d2}.** problemlos auf Urlaub/ZA gehen!")
                else:
                    st.warning(f"⚠️ **Kontingent-Warnung an folgenden Tagen:** {', '.join(conflict_days)}")

        with q_c2:
            st.markdown("**⚖️ 2. Automatischer ZA-Abbau für Mitarbeiter mit hohem Plus-Saldo (`Saldo_Alt > +12h`):**")
            if st.button("⚡ Auto-ZA für Plus-Stunden an grünen Tagen eintragen", type="primary"):
                q_df_now = build_vacation_quota_summary_df(
                    st.session_state.abs_matrix_v76, st.session_state.staff_df_v76, day_cols, st.session_state.max_vac_per_station
                )
                za_added_count = 0
                for _, s_r in st.session_state.staff_df_v76.iterrows():
                    emp_n = str(s_r["Name"]).strip()
                    s_alt = float(s_r.get("Saldo_Alt", 0.0))
                    e_abt = str(s_r["Abteilung"]).strip()
                    e_rol = str(s_r["Rolle"]).strip()
                    if s_alt >= 12.0 and e_abt in ["Abteilung B", "Abteilung H"]:
                        needed_za_days = min(3, int(s_alt // 11.5))
                        given = 0
                        for d_i in range(1, num_days + 1):
                            if given >= needed_za_days:
                                break
                            c_n = day_cols[d_i - 1]
                            if st.session_state.abs_matrix_v76.at[emp_n, c_n] != "":
                                continue
                            row_idx_abt = 0 if e_abt == "Abteilung B" else 1
                            if int(q_df_now.iloc[row_idx_abt][c_n]) < st.session_state.max_vac_per_station - 1:
                                if e_rol == "Heimhelfer" and int(q_df_now.iloc[3][c_n]) >= 1:
                                    continue
                                st.session_state.abs_matrix_v76.at[emp_n, c_n] = "ZA"
                                q_df_now.at[row_idx_abt, c_n] = int(q_df_now.iloc[row_idx_abt][c_n]) + 1
                                given += 1
                                za_added_count += 1
                if za_added_count > 0:
                    st.session_state.raw_uploaded_cal = st.session_state.abs_matrix_v76.copy()
                    st.session_state.abs_matrix_v76.to_csv(cal_autosave_path, index=True)
                    st.session_state.cal_editor_ver += 1
                    st.success(f"✅ Es wurden automatisch **{za_added_count} ZA-Tage** an grünen Kontingent-Tagen eingetragen!")
                    st.rerun()
                else:
                    st.info("Aktuell hat kein Mitarbeiter auf B/H ein `Saldo_Alt` von mindestens +12,0 Stunden.")

    st.subheader("⚡ Schnelleingabe (Urlaube, Entlastungstage, ZA, Wünsche & Fix-Dienste)")
    with st.form("bulk_add_form"):
        b_col1, b_col2, b_col3, b_col4 = st.columns([2, 2, 1.8, 1])
        with b_col1: 
            selected_emps = st.multiselect("1. Mitarbeiter auswählen:", current_staff)
        with b_col2: 
            d_start, d_end = st.slider("2. Von Tag bis Tag:", 1, num_days, (1, 5))
        with b_col3: 
            selected_reason = st.selectbox("3. Urlaub, ENT, ZA, Wunsch oder Fix-Dienst:", entry_options[1:])
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
                    st.session_state.abs_matrix_v76.at[emp, target_col] = val_to_write
            st.session_state.raw_uploaded_cal = st.session_state.abs_matrix_v76.copy()
            st.session_state.abs_matrix_v76.to_csv(cal_autosave_path, index=True)
            st.session_state.cal_editor_ver += 1
            st.success("✅ Erfolgreich eingetragen & gespeichert!")
            st.rerun()

    def style_compact_cal(val, col_name):
        style = "text-align: center; font-size: 12px; "
        v = str(val).strip().upper()
        if v == "URL":
            style += "background-color: #d1ecf1; color: #0c5460; font-weight: bold; "
        elif v == "KRA":
            style += "background-color: #f8d7da; color: #721c24; font-weight: bold; "
        elif v == "ZA":
            style += "background-color: #343a40; color: white; font-weight: bold; "
        elif v in ["SU", "PFL", "FO"]:
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
        sub_cal = st.session_state.abs_matrix_v76.loc[staff_subset].copy()
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
        cleaned_sub = edited_sub_cal.copy()
        for c_col in cleaned_sub.columns:
            cleaned_sub[c_col] = cleaned_sub[c_col].map(normalize_cal_cell)
        if not cleaned_sub.equals(sub_cal):
            st.session_state.abs_matrix_v76.loc[staff_subset, day_cols] = cleaned_sub[day_cols].values
            st.session_state.raw_uploaded_cal = st.session_state.abs_matrix_v76.copy()
            st.session_state.abs_matrix_v76.to_csv(cal_autosave_path, index=True)
            st.session_state.cal_editor_ver += 1
            st.rerun()

    if "Aufgeteilt" in view_mode_cal:
        for dept_label, dept_icon in [("Abteilung B", "🔵"), ("Abteilung H", "🟢"), ("Abteilung F", "🟣")]:
            dept_emps = st.session_state.staff_df_v76[
                st.session_state.staff_df_v76["Abteilung"] == dept_label
            ]["Name"].dropna().astype(str).str.strip().tolist()
            dept_emps = [e for e in dept_emps if e in st.session_state.abs_matrix_v76.index]
            if dept_emps:
                st.markdown(f"**{dept_icon} {dept_label} ({len(dept_emps)} Mitarbeiter)**")
                render_compact_cal_block(dept_emps, dept_label.replace(" ", "_"))
    else:
        render_compact_cal_block(current_staff, "all_staff")

    st.subheader("🚦 Live-Urlaubs- & Kontingent-Ampel (Prüfung über den gesamten Monat)")
    quota_summary_df = build_vacation_quota_summary_df(
        st.session_state.abs_matrix_v76, st.session_state.staff_df_v76, day_cols, int(st.session_state.max_vac_per_station)
    )
    st.dataframe(
        style_vacation_quota_df(quota_summary_df, int(st.session_state.max_vac_per_station)),
        use_container_width=True,
        hide_index=True
    )

with tab2:
    st.header("📅 5. Automatische Dienstplangenerierung & Live-Editor")
    
    if "last_generated_df" not in st.session_state and os.path.exists(plan_autosave_path):
        try:
            loaded_plan = pd.read_csv(plan_autosave_path)
            st.session_state.last_generated_df = recalculate_plan_df(
                loaded_plan, st.session_state.staff_df_v76, num_days
            )
        except Exception:
            pass
    
    if st.button("🚀 Dienstplan neu berechnen (Gezielte Zusatzdienste | WBL Mo–Fr anwesend + Reserve-DGKP bis 15:30 | B/H/F Fokus)", type="primary", use_container_width=True):
        
        try:
            with st.spinner("⏳ KI berechnet Dienstplan (Zuerst alle regulären DGKPs – Stationsleitung nur im Notfall Mo–Fr als Reserve bis 15:30)..."):
                
                df_clean = sanitize_team_df(st.session_state.staff_df_v76)
                staff_list = df_clean.to_dict("records")
                
                st.session_state.absences_v76 = []
                st.session_state.wishes_v76 = []
                st.session_state.work_rules_v76 = []
                st.session_state.fixed_shifts_v76 = []
                
                for emp_name in current_staff:
                    emp_id_list = df_clean.loc[df_clean["Name"] == emp_name, "ID"].values
                    if len(emp_id_list) == 0: 
                        continue
                    emp_id = int(emp_id_list[0])
                    emp_role_val = str(df_clean.loc[df_clean["ID"] == emp_id, "Rolle"].values[0]).strip()
                    emp_abt_val = str(df_clean.loc[df_clean["ID"] == emp_id, "Abteilung"].values[0]).strip()
                    
                    for d in range(1, num_days + 1):
                        col_name = day_cols[d-1]
                        val = st.session_state.abs_matrix_v76.at[emp_name, col_name]
                        
                        if pd.notna(val) and str(val).strip() != "":
                            val_str = str(val).upper().replace("📌", "").strip()
                            if val_str in ["NAN", "NONE", "<NA>", "NULL", ""]: 
                                continue
                                
                            day_idx = d - 1
                            reason = ""
                            
                            matched_manual_sh = None
                            for sh_c in sorted(MANUAL_SHIFT_CODES, key=len, reverse=True):
                                if val_str == sh_c or val_str.startswith(sh_c + " "):
                                    matched_manual_sh = sh_c
                                    break
                                    
                            if matched_manual_sh is not None:
                                if emp_abt_val == "Abteilung F" and matched_manual_sh not in NIGHT_SHIFTS:
                                    continue
                                if emp_role_val in ["DGKP", "Leitung"] and matched_manual_sh == "N2":
                                    matched_manual_sh = "N1"
                                st.session_state.fixed_shifts_v76.append({
                                    "emp_id": emp_id, "emp_name": emp_name, "day": day_idx, "shift": matched_manual_sh
                                })
                                continue

                            if "URL" in val_str: reason = "URL"
                            elif "SU" in val_str: reason = "SU"
                            elif "ENT" in val_str: reason = "ENT"
                            elif "KRA" in val_str: reason = "KRA"
                            elif "ZA" in val_str: reason = "ZA"
                            elif "PFL" in val_str: reason = "PFLEGE"
                            elif "FO" in val_str: reason = "FO"
                            elif "WUN" in val_str or "FREI" in val_str: reason = "WUNSCH-FREI"
                            elif "MUS" in val_str: reason = "MUSS-ARBEITEN"
                            
                            if reason in HARD_ABSENCES:
                                st.session_state.absences_v76.append({"emp_id": emp_id, "emp_name": emp_name, "day": day_idx, "reason": reason})
                            elif reason == "WUNSCH-FREI":
                                st.session_state.wishes_v76.append({"emp_id": emp_id, "emp_name": emp_name, "day": day_idx})
                            elif reason == "MUSS-ARBEITEN":
                                st.session_state.work_rules_v76.append({"emp_id": emp_id, "emp_name": emp_name, "day": day_idx, "rule": reason})

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
                                v_last = extract_base_shift(m_rows.iloc[0][last_c])
                                v_sec = extract_base_shift(m_rows.iloc[0][sec_last_c])
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
                    abt = str(s.get("Abteilung", "Abteilung B")).strip()
                    rolle = str(s.get("Rolle", "Pflegeassistenz")).strip()

                    if abt != "Abteilung F":
                        for d in range(num_days):
                            hour_deviations.append(is_night[(s["ID"], d)] * 4500)

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

                    if rolle != "Leitung":
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
                            hour_deviations.append(single_off * 1800)

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

                for r in st.session_state.work_rules_v76:
                    if r["day"] < num_days:
                        hour_deviations.append(work[(r["emp_id"], r["day"], "OFF")] * 800000)

                fixed_Set = set()
                for fx in st.session_state.fixed_shifts_v76:
                    if fx["day"] < num_days and fx["shift"] in shifts:
                        fixed_Set.add((fx["emp_id"], fx["day"]))
                        hour_deviations.append((1 - work[(fx["emp_id"], fx["day"], fx["shift"])]) * 1800000)

                abs_Set = {(a["emp_id"], a["day"]) for a in st.session_state.absences_v76}
                wish_Set = {(w["emp_id"], w["day"]) for w in st.session_state.wishes_v76}

                dow_keys = ["MO", "DI", "MI", "DO", "FR", "SA", "SO"]
                for s in staff_list:
                    allowed_shifts = resolve_allowed_shifts_for_person(s, SHIFTS_DF_CURRENT)
                    if s["Abteilung"] != "Abteilung F":
                        for fx in st.session_state.fixed_shifts_v76:
                            if fx["emp_id"] == s["ID"] and fx["shift"] in shifts and fx["shift"] not in allowed_shifts:
                                if not (s["Rolle"] in ["DGKP", "Leitung"] and fx["shift"] == "N2"):
                                    allowed_shifts.append(fx["shift"])

                    unallowed = [sh for sh in shifts.keys() if sh not in allowed_shifts]
                    spez_str = str(s.get("Spezialdienst", "Ohne")).strip()
                    gesetz = str(s.get("Gesetz_Status", "Normal")).strip()
                    explicit_person_codes = parse_explicit_shifts(spez_str, MANUAL_SHIFT_CODES)
                    
                    for d in range(num_days):
                        dow = (d + first_day_of_month_weekday) % 7
                        is_holiday = (date(leto, mesec, d+1) in at_holidays) or (mesec == 12 and (d+1 == 24 or d+1 == 31))
                        
                        for sh in unallowed: 
                            model.Add(work[(s["ID"], d, sh)] == 0)

                        if s["Abteilung"] == "Abteilung F":
                            for sh_d in shifts.keys():
                                if sh_d not in NIGHT_SHIFTS + ["OFF"]:
                                    model.Add(work[(s["ID"], d, sh_d)] == 0)

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
                                has_muss = any(r["day"] == d and r["emp_id"] == s["ID"] for r in st.session_state.work_rules_v76)
                                if not has_muss:
                                    model.Add(work[(s["ID"], d, "OFF")] == 1)
                            else:
                                if (s["ID"], d) not in abs_Set and (s["ID"], d) not in wish_Set and bool(s.get(day_col_key, True)):
                                    hour_deviations.append(work[(s["ID"], d, "OFF")] * 300000)
                                if "WBL-P" in shifts:
                                    hour_deviations.append(work[(s["ID"], d, "WBL-P")] * 95000)
                                
                        if s["Rolle"] == "DGKP" and s["Abteilung"] != "Abteilung F" and not explicit_person_codes and (s["ID"], d) not in fixed_Set:
                            if dow >= 5 or is_holiday:
                                if "X7" in allowed_shifts and "X7" in shifts:
                                    for sh in ["X4", "X6"]:
                                        if sh in shifts:
                                            hour_deviations.append(work[(s["ID"], d, sh)] * 25000)

                    max_n_val = int(s.get("Max_Nacht", 0))
                    if s["Abteilung"] == "Abteilung F" and max_n_val == 0 and s["Rolle"] != "Leitung":
                        max_n_val = 12
                    if max_n_val > 0 and gesetz != "Mutterschutz (MSchG)":
                        over_nacht = model.NewIntVar(0, 31, f'over_n_{s["ID"]}')
                        model.Add(sum(is_night[(s["ID"], d)] for d in range(num_days)) - max_n_val <= over_nacht)
                        hour_deviations.append(over_nacht * 50000)

                for a in st.session_state.absences_v76:
                    if a["day"] < num_days: 
                        model.Add(work[(a["emp_id"], a["day"], "OFF")] == 1)
                        if a["reason"] == "ENT":
                            d_ent = a["day"]
                            if d_ent > 0 and d_ent + 1 < num_days:
                                isolated_ent = model.NewBoolVar(f'iso_ent_{a["emp_id"]}_{d_ent}')
                                model.AddMinEquality(isolated_ent, [worked_day[(a["emp_id"], d_ent - 1)], worked_day[(a["emp_id"], d_ent + 1)]])
                                hour_deviations.append(isolated_ent * 18000)

                for w in st.session_state.wishes_v76:
                    if w["day"] < num_days:
                        hour_deviations.append(worked_day[(w["emp_id"], w["day"])] * 55000)

                for s in staff_list:
                    w_std = float(s.get("Wochenstd", 37.0))
                    daily_avg = w_std / 7.0
                    standard_target = daily_avg * num_days
                    saldo_alt = float(s.get("Saldo_Alt", 0.0))
                    gesetz = str(s.get("Gesetz_Status", "Normal")).strip()
                    
                    emp_paid_abs_days = sum(
                        1 for a in st.session_state.absences_v76 
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
                    
                    if s["Abteilung"] == "Abteilung F":
                        hour_deviations.append(under_work * 80)
                    else:
                        hour_deviations.append(under_work * 260) 

                    if gesetz in ["Altersteilzeit (ATZ)", "Elternteilzeit (ETZ)", "Mutterschutz (MSchG)", "Pflegekarenz / Teilzeit"]:
                        hour_deviations.append(over_work * 300)
                    else:
                        hour_deviations.append(over_work * 12)

                day_sh = [sh for sh in DAY_CARE_SHIFTS if sh in shifts and sh not in ["WBL", "WBL-P"]]
                dgkp_reg_shifts = [sh for sh in DGKP_DAY_SHIFTS if sh in shifts and sh not in ["WBL", "WBL-P"]]
                
                o_dgkp_b_reg = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] == "DGKP"]
                o_dgkp_h_reg = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] == "DGKP"]
                o_wbl_ids = [s["ID"] for s in staff_list if s["Rolle"] == "Leitung"]
                o_dgkp_all = [s["ID"] for s in staff_list if s["Rolle"] in ["DGKP", "Leitung"]]
                
                o_pa_b = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] in ["Pflegeassistenz", "PFA"]]
                o_hh_b = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] == "Heimhelfer"]
                o_pa_hh_b = o_pa_b + o_hh_b
                
                o_pa_h = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] in ["Pflegeassistenz", "PFA"]]
                o_hh_h = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] == "Heimhelfer"]
                o_pa_hh_h = o_pa_h + o_hh_h
                
                o_hh_all = o_hh_b + o_hh_h
                o_pa_night_all = [s["ID"] for s in staff_list if s["Rolle"] in ["Pflegeassistenz", "PFA"]]
                
                b_shorts, h_shorts, jed_shorts, dg_shorts, n1_shorts, n2_shorts = {}, {}, {}, {}, {}, {}
                min_b_req = int(st.session_state.target_min_b)
                min_h_req = int(st.session_state.target_min_h)

                for d in range(num_days):
                    if "JED" in shifts and len(o_hh_all) > 0:
                        jed_total = sum(work[(e, d, "JED")] for e in o_hh_all)
                        model.Add(jed_total <= 1)
                        jed_covered = model.NewBoolVar(f'jed_cov_{d}')
                        model.Add(jed_total == 1).OnlyEnforceIf(jed_covered)
                        model.Add(jed_total == 0).OnlyEnforceIf(jed_covered.Not())
                        
                        jed_short = model.NewIntVar(0, 1, f'jed_short_{d}')
                        model.Add(jed_short == 1 - jed_covered)
                        hour_deviations.append(jed_short * 380000)
                        jed_shorts[d] = jed_short

                        for e_hh in o_hh_all:
                            for sh_care in day_sh:
                                model.Add(work[(e_hh, d, sh_care)] <= jed_covered)
                                hour_deviations.append(work[(e_hh, d, sh_care)] * 2500)
                    else:
                        jed_short = model.NewIntVar(0, 1, f'jed_short_{d}')
                        model.Add(jed_short == 0)
                        jed_shorts[d] = jed_short

                    b_care_day = sum(work[(e, d, sh)] for e in o_pa_hh_b for sh in day_sh)
                    b_short = model.NewIntVar(0, 10, f'b_short_{d}')
                    model.Add(b_care_day + b_short >= min_b_req)
                    hour_deviations.append(b_short * 95000)
                    b_shorts[d] = b_short

                    b_ideal_5 = model.NewIntVar(0, 5, f'b_ideal5_{d}')
                    model.Add(b_care_day + b_ideal_5 >= max(min_b_req, 5))
                    hour_deviations.append(b_ideal_5 * 22000)

                    h_care_day = sum(work[(e, d, sh)] for e in o_pa_hh_h for sh in day_sh)
                    h_own_short = model.NewIntVar(0, 10, f'h_own_short_{d}')
                    model.Add(h_care_day + h_own_short >= min_h_req)
                    hour_deviations.append(h_own_short * 75000)

                    house_care_tot = b_care_day + h_care_day
                    house_care_short = model.NewIntVar(0, 15, f'house_care_short_{d}')
                    model.Add(house_care_tot + house_care_short >= min_b_req + min_h_req)
                    hour_deviations.append(house_care_short * 150000)
                    h_shorts[d] = house_care_short

                    b_dgkp = sum(work[(e, d, sh)] for e in o_dgkp_b_reg for sh in dgkp_reg_shifts)
                    h_dgkp_reg = sum(work[(e, d, sh)] for e in o_dgkp_h_reg for sh in dgkp_reg_shifts)
                    wbl_reserve_active = sum(work[(e, d, "WBL-P")] for e in o_wbl_ids) if "WBL-P" in shifts else 0
                    
                    b_dg_miss = model.NewIntVar(0, 1, f'b_dg_miss_{d}')
                    model.Add(b_dgkp + b_dg_miss >= 1)
                    hour_deviations.append(b_dg_miss * 220000)
                    
                    h_dg_miss = model.NewIntVar(0, 1, f'h_dg_miss_{d}')
                    model.Add(h_dgkp_reg + wbl_reserve_active + h_dg_miss >= 1)
                    hour_deviations.append(h_dg_miss * 220000)
                    
                    dg_tot = model.NewIntVar(0, 15, f'dg_tot_{d}')
                    model.Add(dg_tot == b_dgkp + h_dgkp_reg + wbl_reserve_active)
                    dg_short = model.NewIntVar(0, 10, f'dg_short_{d}')
                    model.Add(dg_tot + dg_short >= 2)
                    hour_deviations.append(dg_short * 320000)
                    dg_shorts[d] = dg_short
                    
                    if "N2" in shifts:
                        for e_dg in o_dgkp_all:
                            model.Add(work[(e_dg, d, "N2")] == 0)
                    
                    dgkp_night_sum = sum(is_night[(e, d)] for e in o_dgkp_all)
                    model.Add(dgkp_night_sum <= 1)
                    n1_short = model.NewIntVar(0, 1, f'n1_short_{d}')
                    model.Add(dgkp_night_sum + n1_short >= 1)
                    hour_deviations.append(n1_short * 260000)
                    n1_shorts[d] = n1_short
                    
                    pa_night_sum = sum(is_night[(e, d)] for e in o_pa_night_all)
                    model.Add(pa_night_sum <= 1)
                    n2_short = model.NewIntVar(0, 1, f'n2_short_{d}')
                    model.Add(pa_night_sum + n2_short >= 1)
                    hour_deviations.append(n2_short * 260000)
                    n2_shorts[d] = n2_short

                model.Minimize(sum(hour_deviations))
                solver = cp_model.CpSolver()
                solver.parameters.max_time_in_seconds = 35.0
                solver.parameters.num_search_workers = 8
                status = solver.Solve(model)

                if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                    data = []
                    wish_set_lookup = {(w["emp_id"], w["day"]) for w in st.session_state.wishes_v76}
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
                                    for a in st.session_state.absences_v76:
                                        if a["emp_id"] == s["ID"] and a["day"] == d: 
                                            val = a["reason"]
                                    if (s["ID"], d) in wish_set_lookup:
                                        if sh == "OFF":
                                            val = "WUNSCH"
                                        else:
                                            val = f"*{sh}"
                            row[day_str] = val
                        
                        row["SOLL"] = 0.0
                        row["IST"] = 0.0
                        row["ÜBERSTD."] = 0.0
                        row["SALDO"] = 0.0
                        data.append(row)

                    df_raw_plan = pd.DataFrame(data)

                    for d in range(num_days):
                        c = f"{d+1}."
                        b_dg_indices = df_raw_plan[
                            (df_raw_plan["Abteilung"] == "Abteilung B") &
                            (df_raw_plan["Rolle"] == "DGKP") &
                            (df_raw_plan[c].apply(extract_base_shift).isin(dgkp_reg_shifts))
                        ].index.tolist()
                        h_dg_indices = df_raw_plan[
                            (df_raw_plan["Abteilung"] == "Abteilung H") &
                            (df_raw_plan["Rolle"].isin(["DGKP", "Leitung"])) &
                            (df_raw_plan[c].apply(extract_base_shift).isin(dgkp_reg_shifts + ["WBL-P"]))
                        ].index.tolist()

                        b_dg_curr = len(b_dg_indices)
                        h_dg_curr = len(h_dg_indices)

                        if h_dg_curr == 0 and len(b_dg_indices) >= 2:
                            chosen_idx = b_dg_indices[-1]
                            sh_v = extract_base_shift(df_raw_plan.at[chosen_idx, c])
                            df_raw_plan.at[chosen_idx, c] = f"{sh_v} ➔ H"
                        elif b_dg_curr == 0 and len(h_dg_indices) >= 2:
                            chosen_idx = h_dg_indices[0]
                            for idx_cand in h_dg_indices:
                                if extract_base_shift(df_raw_plan.at[idx_cand, c]) == "WBL-P":
                                    chosen_idx = idx_cand
                                    break
                            sh_v = extract_base_shift(df_raw_plan.at[chosen_idx, c])
                            df_raw_plan.at[chosen_idx, c] = f"{sh_v} ➔ B"

                        b_care_indices = df_raw_plan[
                            (df_raw_plan["Abteilung"] == "Abteilung B") &
                            (df_raw_plan["Rolle"].isin(["Pflegeassistenz", "PFA", "Heimhelfer"])) &
                            (df_raw_plan[c].apply(extract_base_shift).isin(day_sh))
                        ].index.tolist()
                        h_care_indices = df_raw_plan[
                            (df_raw_plan["Abteilung"] == "Abteilung H") &
                            (df_raw_plan["Rolle"].isin(["Pflegeassistenz", "PFA", "Heimhelfer"])) &
                            (df_raw_plan[c].apply(extract_base_shift).isin(day_sh))
                        ].index.tolist()

                        b_c_count = len(b_care_indices)
                        h_c_count = len(h_care_indices)

                        while h_c_count < min_h_req and b_c_count > min_b_req and b_care_indices:
                            helper_idx = b_care_indices.pop()
                            sh_v = extract_base_shift(df_raw_plan.at[helper_idx, c])
                            df_raw_plan.at[helper_idx, c] = f"{sh_v} ➔ H"
                            b_c_count -= 1
                            h_c_count += 1

                        while b_c_count < min_b_req and h_c_count > min_h_req and h_care_indices:
                            helper_idx = h_care_indices.pop()
                            sh_v = extract_base_shift(df_raw_plan.at[helper_idx, c])
                            df_raw_plan.at[helper_idx, c] = f"{sh_v} ➔ B"
                            h_c_count -= 1
                            b_c_count += 1

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
                        if solver.Value(h_shorts[d]) > 0:
                            for _ in range(solver.Value(h_shorts[d])): add_v_shift("⚠️ X-Oseba Pflege", "Abteilung H", "Pflegeassistenz", d, "F2")
                        if solver.Value(dg_shorts[d]) > 0:
                            for _ in range(solver.Value(dg_shorts[d])): add_v_shift("⚠️ X-Oseba DGKP", "Abteilung B", "DGKP", d, "X7")

                    if virtual_rows:
                        df_raw_plan = pd.concat([df_raw_plan, pd.DataFrame(virtual_rows)], ignore_index=True)

                    final_df = recalculate_plan_df(df_raw_plan, df_clean, num_days)
                    st.session_state.last_generated_df = final_df
                    final_df.to_csv(plan_autosave_path, index=False)
                    st.session_state.plan_editor_ver += 1
                    st.success("🎉 Dienstplan erfolgreich berechnet!")
                    st.rerun()
                else:
                    st.error("🚨 UNBEKANNTER FEHLER: Modell konnte nicht gelöst werden.")
        except Exception as e: 
            st.error(f"⚠️ KRITISCHER SYSTEMFEHLER: {e}")

    if "last_generated_df" in st.session_state:
        df_rezultat = st.session_state.last_generated_df
        
        st.info(
            "✏️ **Live-Editor & Stationsleitung-Legende:** \n"
            "- **`WBL` (Blau-Grau):** Dein regulärer Leitungsdienst Mo–Fr bis 15:30 Uhr.\n"
            "- **`WBL-P` (Orange umrandet):** Du springst Mo–Fr bis 15:30 Uhr als **Diplom-Reserve in der Pflege** ein, weil keine andere DGKP verfügbar war!\n"
            "- **`F2 ➔ H` / `⬅️ Name`:** Stationsübergreifende Aushilfe zwischen B und H."
        )
        
        def style_cells(val, col_name):
            style = ""
            if isinstance(val, str):
                base_s = extract_base_shift(val)
                if val == "...": style += "color: #b3b3b3; text-align: center; " 
                elif "🚨" in val: style += "background-color: #ffcccc; color: #cc0000; font-weight: bold; text-align: center; border: 2px solid red; " 
                elif "⚠️" in val: style += "color: #cc0000; font-weight: bold; " 
                elif base_s == "WBL-P":
                    style += "background-color: #ffe8cc; color: #994d00; font-weight: bold; border: 2px solid #ff8800; text-align: center; border-radius: 4px; "
                elif base_s == "WBL":
                    style += "background-color: #e2e8f0; color: #1e293b; font-weight: bold; text-align: center; border-radius: 4px; "
                elif val.startswith("*"):
                    style += "background-color: #fff3cd; color: #856404; font-weight: bold; border: 2px solid #ffc107; text-align: center; "
                elif "➔" in val or "⬅️" in val or "🤝" in val:
                    style += "background-color: #d4edda; color: #005c15; font-weight: bold; border: 2px solid #28a745; text-align: center; border-radius: 4px; "
                elif "Wundmanager" in val or "Praxisanleiter" in val: style += "font-weight: bold; color: #0056b3; "
                elif base_s in NIGHT_SHIFTS: style += "background-color: #1e3a8a; color: white; font-weight: bold; text-align: center; border-radius: 4px; "
                elif "KRA" in val: style += "background-color: #f8d7da; color: #721c24; font-weight: bold; text-align: center; "
                elif "URL" in val: style += "background-color: #d1ecf1; color: #0c5460; font-weight: bold; text-align: center; "
                elif "SU" in val or "PFLEGE" in val or val == "FO": style += "background-color: #ffebd6; color: #cc5500; font-weight: bold; text-align: center; border: 1px solid #ffcc99; "
                elif "ENT" in val: style += "background-color: #f3e8ff; color: #4b0082; font-weight: bold; text-align: center; border: 1px solid #d8b4fe; "
                elif "ZA" in val: style += "background-color: #333333; color: white; font-weight: bold; text-align: center; border-radius: 4px; "
                elif "WUNSCH" in val: style += "background-color: #d4edda; color: #155724; font-weight: bold; text-align: center; "
                elif base_s in SHIFTS_HUNDREDTHS: style += "color: black; font-weight: 500; text-align: center; "

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
            
            real_mask_sub = ~sub_df["Mitarbeiter"].astype(str).str.startswith("🤝 Aushilfe")
            if not edited_sub.loc[real_mask_sub.values, day_cols_only].equals(display_df.loc[real_mask_sub.values, day_cols_only]):
                full_updated = df_rezultat.copy()
                real_indices = sub_df[real_mask_sub].index
                full_updated.loc[real_indices, day_cols_only] = edited_sub.loc[real_mask_sub.values, day_cols_only].values
                recalculated_full = recalculate_plan_df(full_updated, st.session_state.staff_df_v76, num_days)
                st.session_state.last_generated_df = recalculated_full
                recalculated_full.to_csv(plan_autosave_path, index=False)
                st.session_state.plan_editor_ver += 1
                st.rerun()

            st.caption(f"📊 **Tägliche Besetzungs-Kontrolle ({dept_name}):** Grün = Gedeckt | Gelb = WBL-Reserve bis 15:30 👨‍⚕️ | Blau = Springer 🤝 | Rot = Unterbesetzt")
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
            geocon_df = geocon_df[~geocon_df["Mitarbeiter"].str.contains("FEHLT|X-Oseba|🤝 Aushilfe", na=False)]
            geocon_df = geocon_df.rename(columns={"Mitarbeiter": "Personalname"})
            drop_cols = ["ID_hidden", "Abteilung", "Rolle", "SOLL", "IST", "ÜBERSTD.", "SALDO"]
            geocon_df = geocon_df.drop(columns=[c for c in drop_cols if c in geocon_df.columns], errors="ignore")
            
            rename_map = {}
            for col in geocon_df.columns:
                if col.replace('.', '').isdigit():
                    geocon_df[col] = geocon_df[col].apply(lambda v: extract_base_shift(v) if ("➔" in str(v) or str(v).startswith("*")) else v)
                    d = int(col.replace('.', ''))
                    date_str = f"{d:02d}.{monat:02d}.{jahr}"
                    rename_map[col] = date_str
            geocon_df = geocon_df.rename(columns=rename_map)
            return geocon_df.to_csv(index=False, sep=";").encode('utf-8-sig')

        st.subheader("🔵 Dienstplan: Abteilung B (Ziel: 4–5 PA/PFA + 1 HH zuerst für JED + 1 DGKP)")
        df_b = render_editable_dept("Abteilung B", "abt_b")
        st.download_button(
            label="📥 Abt. B herunterladen", 
            data=convert_df(df_b), 
            file_name='Dienstplan_Abt_B.csv', 
            mime='text/csv'
        )
        st.divider()

        st.subheader("🟢 Dienstplan: Abteilung H (Ziel: 4 PA/PFA/HH + 1 DGKP | inkl. WBL-Reserve bis 15:30 & Aushilfe)")
        df_h = render_editable_dept("Abteilung H", "abt_h")
        st.download_button(
            label="📥 Abt. H herunterladen", 
            data=convert_df(df_h), 
            file_name='Dienstplan_Abt_H.csv', 
            mime='text/csv'
        )
        st.divider()

        st.subheader("🟣 Dienstplan: Abteilung F (Exklusiv Nachtpool N1 / N2)")
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

with tab_print:
    st.header("🖨️ 6. Geocon & Druck-Studio (Aushangplan, Lohnarten-Matrix & Monatsabschluss)")
    if "last_generated_df" in st.session_state:
        df_plan_pr = st.session_state.last_generated_df
        zuschlag_df = build_geocon_zuschlaege_df(
            df_plan_pr, st.session_state.staff_df_v76, num_days, leto, mesec, first_day_of_month_weekday, at_holidays
        )

        st.subheader("1. 🖨️ Offizieller A4-Aushangplan (Schwarzes Brett) & Einzel-Stundennachweis")
        col_pr1, col_pr2 = st.columns(2)
        with col_pr1:
            html_aushang = generate_printable_aushang_html(
                df_plan_pr, num_days, leto, mesec, first_day_of_month_weekday, at_holidays,
                st.session_state.target_min_b, st.session_state.target_min_h
            )
            st.download_button(
                label="🖨️ Druckfertigen A4-Aushangplan herunterladen (.html / PDF-Druck)",
                data=html_aushang.encode("utf-8"),
                file_name=f"Aushangplan_{MONTH_NAMES_DE[mesec-1]}_{leto}.html",
                mime="text/html",
                type="primary",
                use_container_width=True
            )
        with col_pr2:
            real_staff_list = zuschlag_df["Mitarbeiter"].tolist()
            sel_emp_sheet = st.selectbox("Mitarbeiter für Einzel-Stundennachweis wählen:", real_staff_list)
            if sel_emp_sheet:
                emp_r_plan = df_plan_pr[df_plan_pr["Mitarbeiter"] == sel_emp_sheet].iloc[0]
                emp_r_zu = zuschlag_df[zuschlag_df["Mitarbeiter"] == sel_emp_sheet].iloc[0]
                html_single = generate_employee_stundenzettel_html(
                    emp_r_plan, emp_r_zu, num_days, leto, mesec, first_day_of_month_weekday, at_holidays
                )
                st.download_button(
                    label=f"📄 Stundennachweis für {sel_emp_sheet} herunterladen (.html / PDF)",
                    data=html_single.encode("utf-8"),
                    file_name=f"Stundennachweis_{sel_emp_sheet}_{mesec}_{leto}.html",
                    mime="text/html",
                    use_container_width=True
                )

        st.divider()
        st.subheader("2. 💶 Geocon Lohnarten- & Zuschläge-Matrix (SWÖ-KV / Steiermark)")
        st.dataframe(zuschlag_df, use_container_width=True, hide_index=True)
        st.download_button(
            label="📥 Geocon Lohnverrechnungs- & Zuschläge-Matrix als CSV exportieren",
            data=zuschlag_df.to_csv(index=False, sep=";").encode("utf-8-sig"),
            file_name=f"Geocon_Lohnmatrix_{mesec}_{leto}.csv",
            mime="text/csv"
        )

        st.divider()
        st.subheader("3. 🔄 Geocon 1-Klick Monatsabschluss (Salden- & Urlaubs-Übertrag ins Folgemonat)")
        confirm_close = st.checkbox("✅ Ja, ich möchte den aktuellen Monat abschließen und Salden + Resturlaub in die Stammdaten übertragen.")
        if st.button("🔄 Monatsabschluss jetzt durchführen (Saldo & Resturlaub fortschreiben)", disabled=not confirm_close, type="primary"):
            df_team_upd = st.session_state.staff_df_v76.copy()
            for _, z_row in zuschlag_df.iterrows():
                base_n = str(z_row["Mitarbeiter"]).split(" (")[0].strip()
                mask = df_team_upd["Name"].astype(str).str.strip() == base_n
                if mask.any():
                    df_team_upd.loc[mask, "Saldo_Alt"] = float(z_row["SALDO Neu (h)"])
                    df_team_upd.loc[mask, "URL_Rest"] = float(z_row["🏝️ URL Rest Neu"])
            df_team_upd = sanitize_team_df(df_team_upd)
            st.session_state.staff_df_v76 = df_team_upd
            df_team_upd.to_csv("team_data.csv", index=False)
            st.session_state.team_editor_ver += 1
            st.success("✅ Monatsabschluss erfolgreich! Alle Salden (`Saldo_Alt`) und Resturlaube (`URL_Rest`) wurden für das Folgemonat aktualisiert.")
    else:
        st.info("Bitte berechne zuerst in Tab 5 einen Dienstplan, um das Geocon & Druck-Studio zu nutzen!")

with tab4:
    st.header("🚨 7. SOS Einspringer-Finder & 🔄 Smart-Tauschbörse")
    if "last_generated_df" in st.session_state:
        df_plan = st.session_state.last_generated_df
        staff_names = df_plan[~df_plan["Mitarbeiter"].str.contains("X-Oseba|FEHLT|⚠️|🤝 Aushilfe", na=False)]["Mitarbeiter"].tolist()
        
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
            base_out_sh = extract_base_shift(aktuelle_schicht)
            for _, r in df_plan.iterrows():
                m_name = r["Mitarbeiter"]
                m_rolle = r["Rolle"]
                m_abt = r["Abteilung"]
                m_schicht = r[tag_col]
                m_saldo = r["SALDO"]
                
                if any(k in m_name for k in ["X-Oseba", "FEHLT", "⚠️", "🤝 Aushilfe"]): 
                    continue
                if m_abt == "Abteilung F" and base_out_sh not in NIGHT_SHIFTS:
                    continue
                
                if m_name != ausfall_emp and m_schicht in ["...", "WBL"]:
                    prev_col = f"{ausfall_tag-1}."
                    had_night_before = (ausfall_tag > 1 and extract_base_shift(r.get(prev_col, "")) in NIGHT_SHIFTS)
                    if had_night_before:
                        continue
                    score = 100
                    gründe = []
                    if m_rolle == emp_role: 
                        score += 50
                        gründe.append("✅ Gleiche Rolle")
                    elif m_rolle == "Leitung" and emp_role == "DGKP":
                        score += 35
                        gründe.append("👨‍⚕️ Stationsleitung Reserve (bis 15:30)")
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
                
                df_test = recalculate_plan_df(df_test, st.session_state.staff_df_v76, num_days)
                audit_after = run_austrian_law_audit(
                    df_test, st.session_state.staff_df_v76, SHIFTS_DF_CURRENT, num_days, leto, mesec, first_day_of_month_weekday, at_holidays,
                    st.session_state.target_min_b, st.session_state.target_min_h
                )
                relevant_issues = pd.DataFrame()
                if not audit_after.empty:
                    relevant_issues = audit_after[
                        audit_after["Betroffen"].str.contains(swap_emp_a.split(" (")[0], na=False) |
                        audit_after["Betroffen"].str.contains(swap_emp_b.split(" (")[0], na=False) |
                        audit_after["Betroffen"].str.contains("Nachtdienst|Speisesaal", na=False)
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
    st.header("📉 8. Überstunden-, Fairness- & Wunsch-Erfüllungs-Radar")
    if "last_generated_df" in st.session_state:
        df_plan = st.session_state.last_generated_df
        real_df = df_plan[~df_plan["Mitarbeiter"].str.contains("X-Oseba|FEHLT|⚠️|🤝 Aushilfe", na=False)].copy()
        day_cols_only = [f"{d}." for d in range(1, num_days + 1) if f"{d}." in real_df.columns]
        
        wun_granted_total = 0
        wun_overruled_total = 0
        for _, r in real_df.iterrows():
            for c in day_cols_only:
                v_c = str(r[c]).strip().upper()
                if v_c == "WUNSCH":
                    wun_granted_total += 1
                elif v_c.startswith("*"):
                    wun_overruled_total += 1
        wun_all = wun_granted_total + wun_overruled_total
        wun_pct = (wun_granted_total / wun_all * 100.0) if wun_all > 0 else 100.0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Gesamte SOLL-Stunden", f"{real_df['SOLL'].sum():.1f} h")
        c2.metric("Gesamte IST-Stunden", f"{real_df['IST'].sum():.1f} h")
        c3.metric("Aufgebaute Überstunden", f"{real_df['ÜBERSTD.'].sum():.1f} h")
        c4.metric("🟢 Wunsch-Erfüllungsquote", f"{wun_pct:.1f} % ({wun_granted_total}/{wun_all})")
        
        radar_rows = []
        for _, r in real_df.iterrows():
            raw_vals = [str(r[c]).strip().upper() for c in day_cols_only]
            vals = [extract_base_shift(v) for v in raw_vals]
            n_count = sum(1 for v in vals if v in NIGHT_SHIFTS)
            long_12h = sum(1 for v in vals if SHIFTS_HUNDREDTHS.get(v, 0) >= 1200 and v not in NIGHT_SHIFTS)
            springer_count = sum(1 for v in raw_vals if "➔" in v or "WBL-P" in v)
            url_month = sum(1 for v in raw_vals if v == "URL")
            ent_za_month = sum(1 for v in raw_vals if v in ["ENT", "ZA"])
            wun_ok = sum(1 for v in raw_vals if v == "WUNSCH")
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
                "Springer / WBL-P": springer_count,
                "URL": url_month,
                "ENT / ZA": ent_za_month,
                "Wünsche erfüllt": wun_ok,
                "Burnout-Index": f"{load_score}%",
                "Belastungs-Status": status_ampel
            })
            
        radar_df = pd.DataFrame(radar_rows)
        st.subheader("⚖️ KI Fairness-, Urlaubs-, Wunsch- & Belastungs-Radar pro Mitarbeiter")
        st.dataframe(radar_df.sort_values(by="ÜBERSTD.", ascending=False), use_container_width=True, hide_index=True)
    else:
        st.info("Bitte berechne zuerst den Dienstplan, um die Analyse zu sehen!")

with tab6:
    st.header("🛡️ 9. Steiermark Pflege- & Arbeitsrechts-Kompendium + Live-Inspektorat")
    col_law1, col_law2 = st.columns(2)
    with col_law1:
        with st.expander("🤰 1. Mutterschutzgesetz (MSchG §§ 3–8)", expanded=True):
            st.markdown(
                "- **Absolutes Beschäftigungsverbot (§ 3 & § 5 MSchG):** 8 Wochen vor und 8 Wochen nach der Geburt (12 Wochen bei Früh-/Mehrlingsgeburt oder Kaiserschnitt).\n"
                "- **Absolutes Nachtarbeitsverbot (§ 6 MSchG):** Keine Beschäftigung zwischen **20:00 und 06:00 Uhr**.\n"
                "- **Sonn- und Feiertagsverbot (§ 7 MSchG):** An Sonn- und gesetzlichen Feiertagen besteht Beschäftigungsverbot.\n"
                "- **Verbot von Überstunden & Langdiensten (§ 8 MSchG):** Max. **9,0 Stunden** täglich und **40,0 Stunden** wöchentlich."
            )
        with st.expander("⏳ 2. Altersteilzeit (§ 27 AlVG & SWÖ-KV) & Elternteilzeit (MSchG/VKG)", expanded=True):
            st.markdown(
                "- **Altersteilzeit (ATZ - § 27 AlVG):** Reduktion der Normalarbeitszeit auf **40 % bis 60 %** (bei 37h Vollzeit: **14,8h bis 22,2h/Woche**).\n"
                "- **Mehrarbeits-Schutz in ATZ:** Die KI sperrt den Überstundenaufbau für ATZ-Mitarbeiter zum Schutz des AMS-Altersteilzeitgeldes.\n"
                "- **Elternteilzeit (ETZ - §§ 15h ff MSchG / VKG):** Vereinbarte Wochentage (`MO`–`SO`) sind verbindlich, kein Überstundenzwang."
            )
        with st.expander("🏥 3. StPBG & StPAVO Steiermark (Personalschlüssel & WBL-Reserve)", expanded=True):
            st.markdown(
                "- **StPAVO Personalschlüssel:** Stufe 0: 1:24 | Stufe 1: 1:12 | Stufe 2: 1:7,5 | Stufe 3: 1:4 | Stufe 4: 1:2,5 | Stufe 5: 1:2 | Stufe 6 & 7: 1:1,5.\n"
                "- **Stationsleitung (WBL) Reserve-Regel:** Mo–Fr regulär im Dienst **`WBL` (bis 15:30)** für Führung & Organisation; nur bei Ausfall aller regulären DGKPs springt die Leitung mit **`WBL-P` (bis 15:30)** als Diplom-Reserve in der Pflege ein.\n"
                "- **Heimhelfer-Regel:** Zuerst muss täglich der Speisesaal (`JED`) besetzt sein, bevor ein weiterer Heimhelfer in der Pflege (`F2`/`F7`) unterstützt.\n"
                "- **Nachtdienst-Vorgabe:** Hausweit **exakt 1x DGKP (`N1`) + 1x PFA/PA (`N2`)** (Abt. F deckt exklusiv die Nacht ab)."
            )

    with col_law2:
        with st.expander("📘 4. AZG, KA-AZG, ARG & SWÖ-KV (Arbeitszeit, Pausen § 11 AZG & Ruhezeiten)", expanded=True):
            st.markdown(
                "- **SWÖ-KV Vollzeit:** **37,0 Wochenstunden** Normalarbeitszeit.\n"
                "- **Gesetzliche Ruhepausen (§ 11 AZG / KA-AZG):** Bis 6,0h Brutto **`0 Min.`** | Über 6,0h Brutto **`30 Min.`** | Bei Langdiensten ab 10,0h **`45 Min.`**.\n"
                "- **Tageshöchstarbeitszeit:** Tagdienste bis **12,0h** (`X7`, `F2`), Nachtdienst **13,5h** (`N1`, `N2`).\n"
                "- **Wochenhöchstgrenze:** Kurzfristig bis maximal **50,0 Stunden** in einzelnen Wochen (Durchrechnung max. 48,0h).\n"
                "- **Erholung nach Nachtdienst:** Nach jedem Nachtdienst oder Nachtblock (optimal 2, max. 3 Nächte) folgen **zwingend 2 freie Kalendertage**."
            )
        with st.expander("🩺 5. GuKG (Kompetenzen DGKP, PFA & PA + Fortbildung)", expanded=True):
            st.markdown(
                "- **DGKP (§§ 12–16 GuKG):** Gesamtverantwortung für den Pflegeprozess, Pflegediagnostik, Planung und Evaluierung.\n"
                "- **Pflegefachassistenz (PFA - §§ 83a ff GuKG):** Eigenverantwortliche Durchführung übertragener Aufgaben in der Pflege und Diagnostik/Therapie.\n"
                "- **Pflegeassistenz (PA - § 83 GuKG):** Durchführung standardisierter Pflegemaßnahmen unter Anordnung und Aufsicht.\n"
                "- **Fortbildungspflicht (§ 63 & § 104c GuKG):** **60 Stunden** / 5 Jahre für **DGKP**; **40 Stunden** / 5 Jahre für **PFA & PA** (im Kalender mit `FO` buchbar)."
            )
        with st.expander("🌙 6. Nachtschwerarbeitsgesetz (NSchG) & Urlaubs-/Entlastungs-Regeln (UrlG)", expanded=True):
            st.markdown(
                "- **NSchG-Zusatzurlaub / Entlastungstage (`ENT`):** Ab 50 geleisteten Nachtschwerarbeits-Diensten pro Jahr gebühren **2 zusätzliche Urlaubstage** (`ENT`).\n"
                "- **Zeitausgleich (`ZA`):** Reduziert aktiv das aufgebaute Überstunden-Saldo (`Saldo_Alt`).\n"
                "- **Urlaubs-Kontingent:** Maximal **2 Mitarbeiter pro Station (B/H)** gleichzeitig."
            )

    st.divider()
    st.subheader("🕵️‍♂️ Automatischer Dienstplan-Prüfbericht (Live-Inspektorat Steiermark)")

    if "last_generated_df" in st.session_state:
        audit_df = run_austrian_law_audit(
            st.session_state.last_generated_df, 
            st.session_state.staff_df_v76, 
            SHIFTS_DF_CURRENT,
            num_days, leto, mesec, first_day_of_month_weekday, at_holidays,
            st.session_state.target_min_b, st.session_state.target_min_h
        )
        if audit_df.empty:
            st.success(
                "✅ **100% ZERTIFIZIERT & GESETZESTREU (Steiermark-Standard)!** Der aktuelle Dienstplan erfüllt alle Vorgaben: "
                "Zusatzdienste nur bei Zuweisung, WBL-Reserve bis 15:30, Abt. F exklusiv Nacht, Heimhelfer zuerst JED und StPAVO-Besetzung."
            )
        else:
            st.warning(f"⚠️ **Hinweis:** Bei der Überprüfung wurden **{len(audit_df)} Abweichungen / Hinweise** gefunden:")
            st.dataframe(audit_df, use_container_width=True, hide_index=True)
    else:
        st.info("Sobald du einen Dienstplan berechnet hast, erscheint hier automatisch das Prüfergebnis nach Steiermark- & Bundesrecht.")
