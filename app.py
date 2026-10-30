import calendar
from datetime import date
import hashlib
import io
import os
import re
import holidays
import numpy as np
from ortools.sat.python import cp_model
import pandas as pd
import streamlit as st

st.set_page_config(page_title="KI-Dienstplan PRO 74.0", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 74.0 - Targeted-Shifts & WBL-Reserve 15:30)")
st.markdown(
    "**System-Architektur (Gezielte Schicht-Zuweisung, Freie Stunden-wahl & WBL-Reserve bis 15:30):** \n"
    "- 🎯 **Kein ungewolltes Verteilen neuer Dienste:** Neue Dienste im *Dienste-Studio (Tab 2)* werden **nur noch jenen Mitarbeitern zugeteilt**, bei denen du das Kürzel explizit unter `Erlaubte Dienste` (Tab 1) oder als Fix-Dienst (Tab 4) einträgst!\n"
    "- ⏱️ **Beliebige Dienste & freie Stundenanzahl:** Jede erdenkliche Stundenanzahl (z. B. `6.5`, `7.4`, `8.0`, `8.25` oder direkt `S1(6.5)` in der Zelle) wird sofort exakt berechnet.\n"
    "- 👨‍⚕️ **Stationsleitung (WBL) als Mo–Fr Reserve bis 15:30:** Die KI plant zuerst alle regulären DGKPs ein. Nur wenn Mo–Fr auf B oder H keine DGKP verfügbar ist, springt die Stationsleitung mit Dienst **`L15` (bis 15:30 Uhr)** als Reserve ein."
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
        {"Kürzel": "X7", "Bezeichnung": "DGKP Langdienst", "Uhrzeit": "07:00-19:30", "Stunden": 12.0, "Typ": "Tagdienst Pflege", "Auto_Alle": True, "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "X6", "Bezeichnung": "DGKP Tagdienst", "Uhrzeit": "07:00-18:30", "Stunden": 11.0, "Typ": "Tagdienst Pflege", "Auto_Alle": True, "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "X4", "Bezeichnung": "DGKP Kurzdienst", "Uhrzeit": "07:00-15:30", "Stunden": 8.25, "Typ": "Tagdienst Pflege", "Auto_Alle": True, "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "L15", "Bezeichnung": "WBL / Leitung Reserve bis 15:30", "Uhrzeit": "07:00-15:30", "Stunden": 8.0, "Typ": "Leitung / Reserve (bis 15:30)", "Auto_Alle": False, "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "WBL", "Bezeichnung": "WBL Büro / Leitung Mo-Fr bis 15:30", "Uhrzeit": "07:00-15:30", "Stunden": 7.4, "Typ": "Leitung / Reserve (bis 15:30)", "Auto_Alle": False, "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "F2", "Bezeichnung": "PFA/PA/HH Langdienst", "Uhrzeit": "07:00-19:30", "Stunden": 12.0, "Typ": "Tagdienst Pflege", "Auto_Alle": True, "Erlaubt_DGKP": False, "Erlaubt_PFA": True, "Erlaubt_PA": True, "Erlaubt_HH": True},
        {"Kürzel": "F7", "Bezeichnung": "PFA/PA/HH Tagdienst", "Uhrzeit": "07:00-18:30", "Stunden": 11.0, "Typ": "Tagdienst Pflege", "Auto_Alle": True, "Erlaubt_DGKP": False, "Erlaubt_PFA": True, "Erlaubt_PA": True, "Erlaubt_HH": True},
        {"Kürzel": "N1", "Bezeichnung": "Nachtdienst DGKP", "Uhrzeit": "19:00-08:30", "Stunden": 13.5, "Typ": "Nachtdienst", "Auto_Alle": True, "Erlaubt_DGKP": True, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": False},
        {"Kürzel": "N2", "Bezeichnung": "Nachtdienst PFA/PA", "Uhrzeit": "19:00-08:30", "Stunden": 13.5, "Typ": "Nachtdienst", "Auto_Alle": True, "Erlaubt_DGKP": False, "Erlaubt_PFA": True, "Erlaubt_PA": True, "Erlaubt_HH": False},
        {"Kürzel": "JED", "Bezeichnung": "Speisesaal Dienst", "Uhrzeit": "07:00-18:00", "Stunden": 10.5, "Typ": "Speisesaal / Sonder", "Auto_Alle": True, "Erlaubt_DGKP": False, "Erlaubt_PFA": False, "Erlaubt_PA": False, "Erlaubt_HH": True},
        {"Kürzel": "SM", "Bezeichnung": "Mitteldienst SM (Nur bei Zuweisung)", "Uhrzeit": "07:00-18:15", "Stunden": 10.75, "Typ": "Tagdienst Pflege", "Auto_Alle": False, "Erlaubt_DGKP": False, "Erlaubt_PFA": True, "Erlaubt_PA": True, "Erlaubt_HH": True},
        {"Kürzel": "MS", "Bezeichnung": "Kurzdienst MS (Nur bei Zuweisung)", "Uhrzeit": "07:00-14:30", "Stunden": 7.0, "Typ": "Tagdienst Pflege", "Auto_Alle": False, "Erlaubt_DGKP": False, "Erlaubt_PFA": True, "Erlaubt_PA": True, "Erlaubt_HH": True},
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
    
    # Stelle sicher, dass L15 und WBL für die Stationsleitung immer vorhanden sind
    existing_codes = set(df["Kürzel"].tolist())
    defaults = get_default_shifts_df()
    for req_code in ["L15", "WBL"]:
        if req_code not in existing_codes:
            df = pd.concat([df, defaults[defaults["Kürzel"] == req_code]], ignore_index=True)

    if "Bezeichnung" not in df.columns:
        df["Bezeichnung"] = "Dienst"
    df["Bezeichnung"] = df["Bezeichnung"].fillna("Dienst").astype(str).str.strip()

    if "Uhrzeit" not in df.columns:
        df["Uhrzeit"] = "07:00-15:30"
    df["Uhrzeit"] = df["Uhrzeit"].fillna("07:00-15:30").astype(str).str.strip()
    
    if "Stunden" not in df.columns:
        df["Stunden"] = 8.0
    df["Stunden"] = pd.to_numeric(df["Stunden"], errors="coerce").fillna(8.0).clip(lower=0.25, upper=24.0).round(2)
    
    valid_types = ["Tagdienst Pflege", "Leitung / Reserve (bis 15:30)", "Nachtdienst", "Speisesaal / Sonder"]
    if "Typ" not in df.columns:
        df["Typ"] = "Tagdienst Pflege"
    df["Typ"] = df["Typ"].fillna("Tagdienst Pflege").astype(str).str.strip()
    df.loc[~df["Typ"].isin(valid_types), "Typ"] = "Tagdienst Pflege"
    df.loc[df["Kürzel"].isin(["L15", "WBL"]), "Typ"] = "Leitung / Reserve (bis 15:30)"
    
    if "Auto_Alle" not in df.columns:
        # Nur die klassischen Kernschichten sind standardmäßig für alle aktiv!
        core_auto = {"X7", "X6", "X4", "F2", "F7", "N1", "N2", "JED"}
        df["Auto_Alle"] = df["Kürzel"].isin(core_auto)
    else:
        df["Auto_Alle"] = df["Auto_Alle"].apply(lambda x: False if str(x).strip().lower() in ["false", "0", "no", "nein", "falsch"] else True)

    if "Erlaubt_PA" in df.columns and "Erlaubt_PFA" not in df.columns:
        df["Erlaubt_PFA"] = df["Erlaubt_PA"]
        
    for b_col, def_val in [("Erlaubt_DGKP", True), ("Erlaubt_PFA", True), ("Erlaubt_PA", True), ("Erlaubt_HH", False)]:
        if b_col not in df.columns:
            df[b_col] = def_val
        else:
            df[b_col] = df[b_col].apply(lambda x: False if str(x).strip().lower() in ["false", "0", "no", "nein", "falsch"] else True)
            
    cols = ["Kürzel", "Bezeichnung", "Uhrzeit", "Stunden", "Typ", "Auto_Alle", "Erlaubt_DGKP", "Erlaubt_PFA", "Erlaubt_PA", "Erlaubt_HH"]
    return df[cols].reset_index(drop=True)

if "shifts_df_v74" not in st.session_state:
    if os.path.exists("shifts_data.csv"):
        try:
            with open("shifts_data.csv", "rb") as f:
                st.session_state.shifts_df_v74 = sanitize_shifts_df(read_csv_smart(f.read(), is_index_col=False))
        except Exception:
            st.session_state.shifts_df_v74 = get_default_shifts_df()
    else:
        st.session_state.shifts_df_v74 = get_default_shifts_df()

SHIFTS_DF_CURRENT = sanitize_shifts_df(st.session_state.shifts_df_v74)
SHIFTS_HUNDREDTHS = {
    row["Kürzel"]: int(round(float(row["Stunden"]) * 100)) 
    for _, row in SHIFTS_DF_CURRENT.iterrows()
}
SHIFTS_HUNDREDTHS["OFF"] = 0

SHIFT_LABELS = {
    row["Kürzel"]: f"{row['Kürzel']} ({row['Stunden']}h | {row['Uhrzeit']} – {row['Bezeichnung']})" 
    for _, row in SHIFTS_DF_CURRENT.iterrows()
}
DAY_CARE_SHIFTS = SHIFTS_DF_CURRENT[
    SHIFTS_DF_CURRENT["Typ"].isin(["Tagdienst Pflege", "Leitung / Reserve (bis 15:30)"]) &
    (SHIFTS_DF_CURRENT["Kürzel"] != "WBL")
]["Kürzel"].tolist()

NIGHT_SHIFTS = SHIFTS_DF_CURRENT[SHIFTS_DF_CURRENT["Typ"] == "Nachtdienst"]["Kürzel"].tolist()
if not NIGHT_SHIFTS:
    NIGHT_SHIFTS = ["N1", "N2"]

DGKP_DAY_SHIFTS = SHIFTS_DF_CURRENT[
    (SHIFTS_DF_CURRENT["Typ"].isin(["Tagdienst Pflege", "Leitung / Reserve (bis 15:30)"])) &
    (SHIFTS_DF_CURRENT["Erlaubt_DGKP"] == True) &
    (SHIFTS_DF_CURRENT["Kürzel"] != "WBL")
]["Kürzel"].tolist()

PA_PFA_DAY_SHIFTS = SHIFTS_DF_CURRENT[
    (SHIFTS_DF_CURRENT["Typ"] == "Tagdienst Pflege") &
    ((SHIFTS_DF_CURRENT["Erlaubt_PA"] == True) | (SHIFTS_DF_CURRENT["Erlaubt_PFA"] == True))
]["Kürzel"].tolist()
MANUAL_SHIFT_CODES = SHIFTS_DF_CURRENT["Kürzel"].tolist()

def parse_inline_shift_and_hours(val_str):
    """
    Erkennt auch direkt eingetippte Dienste mit Stunden in Klammern wie 'T1(6.5)' oder 'S2(7,5)'.
    Gibt (bereinigtes_kürzel, stunden_100stel_oder_None) zurück.
    """
    s = str(val_str).strip().upper()
    m = re.match(r"^([A-Z0-9_-]+)\s*\(\s*([0-9]+(?:[.,][0-9]+)?)\s*H?\s*\)(.*)$", s)
    if m:
        code_part = m.group(1).strip()
        hrs_val = float(m.group(2).replace(",", "."))
        rest_part = m.group(3).strip()
        full_display = f"{code_part} {rest_part}".strip() if rest_part else code_part
        return code_part, int(round(hrs_val * 100)), full_display
    return None, None, s

def extract_base_shift(val_str):
    """Extrahiert das reine Schichtkürzel aus Zellen wie 'F2 ➔ H', '*F2', 'L15 ➔ B', 'T1(6.5)' oder '🚨 F2'."""
    s = str(val_str).strip().upper()
    if s.startswith("⬅️"):
        return "AUSHILFE_INFO"
    s = s.replace("🚨", "").replace("📌", "").replace("*", "").strip()
    if "➔" in s:
        s = s.split("➔")[0].strip()
    elif "->" in s:
        s = s.split("->")[0].strip()
    inl_code, _, _ = parse_inline_shift_and_hours(s)
    if inl_code:
        return inl_code
    return s

def get_shift_hundredths_smart(raw_cell_str):
    """Ermittelt die exakte Stundenanzahl (in 100stel) für jedes bekannte ODER inline definierte Kürzel wie 'K1(6.5)'."""
    s = str(raw_cell_str).strip().upper()
    if s.startswith("⬅️"):
        return 0
    s_clean = s.replace("🚨", "").replace("📌", "").replace("*", "").strip()
    if "➔" in s_clean:
        s_clean = s_clean.split("➔")[0].strip()
    elif "->" in s_clean:
        s_clean = s_clean.split("->")[0].strip()
    inl_code, inl_h100, _ = parse_inline_shift_and_hours(s_clean)
    if inl_h100 is not None:
        return inl_h100
    return SHIFTS_HUNDREDTHS.get(s_clean, 0)

def get_default_pavo_df():
    return pd.DataFrame([
        {"Abteilung": "Abteilung B", "Stufe_0": 0, "Stufe_1": 2, "Stufe_2": 4, "Stufe_3": 6, "Stufe_4": 6, "Stufe_5": 4, "Stufe_6": 2, "Stufe_7": 0},
        {"Abteilung": "Abteilung H", "Stufe_0": 0, "Stufe_1": 1, "Stufe_2": 4, "Stufe_3": 7, "Stufe_4": 6, "Stufe_5": 4, "Stufe_6": 1, "Stufe_7": 1},
    ])

if "pavo_df_v74" not in st.session_state:
    if os.path.exists("pavo_data.csv"):
        try:
            st.session_state.pavo_df_v74 = pd.read_csv("pavo_data.csv")
        except Exception:
            st.session_state.pavo_df_v74 = get_default_pavo_df()
    else:
        st.session_state.pavo_df_v74 = get_default_pavo_df()

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
    """
    NEUE GEZIELTE SCHICHT-ZUWEISUNG (Version 74.0):
    1. Wenn bei einer Person unter 'Erlaubte Dienste' (Spezialdienst) konkrete Dienst-Kürzel eingetragen sind
       (z. B. 'T6', 'MS, F7', 'L15', 'X4'), bekommt diese Person EXAKT diese eingetragenen Dienste!
       (Keine Einschränkung durch Rollen-Filter – jeder individuell zugewiesene Dienst wird 100% erlaubt!).
    2. Wenn bei einer Person 'Ohne' steht, bekommt sie NUR die Standard-Dienste mit 'Auto_Alle == True'
       (also DGKP: X7, X6, X4 | PFA/PA: F2, F7 | HH: JED + F2, F7).
       Neu erstellte Spezialdienste im Dienste-Studio (Auto_Alle == False) werden NICHT an alle verteilt!
    3. Rolle 'Leitung' (WBL Uroš): Arbeitet Mo–Fr bis 15:30 Uhr ('L15' als Pflege-Reserve & 'WBL' als Büro/Leitung).
    4. Abteilung F: Arbeitet exklusiv Nachtdienste (N1 / N2).
    """
    allowed_shifts = ["OFF"]
    nur_nacht = bool(s.get("Nur_Nacht", False))
    spez = str(s.get("Spezialdienst", "Ohne")).upper().strip()
    rolle = str(s.get("Rolle", "Pflegeassistenz")).strip()
    abt = str(s.get("Abteilung", "Abteilung B")).strip()
    gesetz = str(s.get("Gesetz_Status", "Normal")).strip()
    max_n = int(s.get("Max_Nacht", 0))

    all_defined_codes = shifts_df["Kürzel"].tolist()
    day_df = shifts_df[shifts_df["Typ"] != "Nachtdienst"]
    night_df = shifts_df[shifts_df["Typ"] == "Nachtdienst"]
    auto_day_df = day_df[day_df["Auto_Alle"] == True]

    # --- 1. STATIONSLEITUNG (LEITUNG / WBL) ---
    if rolle == "Leitung":
        # WBL arbeitet bis 15:30 (L15 als DGKP-Reserve in der Pflege, WBL als Leitungs-/Bürodienst)
        # Falls der User im Feld Spezialdienst eigene Kürzel für Leitung eingetragen hat, diese ebenfalls erlauben:
        explicit_wbl = []
        if spez not in ["OHNE", "NUR WE UND FEIERTAGE", ""]:
            tokens = [t.strip() for t in re.split(r"[,;\s]+", spez) if t.strip()]
            for code in all_defined_codes:
                if code in tokens and code not in NIGHT_SHIFTS:
                    explicit_wbl.append(code)
        if explicit_wbl:
            allowed_shifts.extend(explicit_wbl)
        for w_sh in ["L15", "WBL"]:
            if w_sh in all_defined_codes:
                allowed_shifts.append(w_sh)
        return list(set(allowed_shifts))

    # --- 2. ABTEILUNG F: EXKLUSIV NACHTDIENSTE ---
    if abt == "Abteilung F":
        if gesetz == "Mutterschutz (MSchG)":
            return ["OFF"]
        if rolle == "DGKP":
            dg_nights = night_df[night_df["Erlaubt_DGKP"] == True]["Kürzel"].tolist()
            allowed_shifts.extend(dg_nights if dg_nights else ["N1"])
        elif rolle in ["PFA", "Pflegeassistenz"]:
            role_col = "Erlaubt_PFA" if rolle == "PFA" else "Erlaubt_PA"
            pa_nights = night_df[night_df[role_col] == True]["Kürzel"].tolist()
            allowed_shifts.extend(pa_nights if pa_nights else ["N2"])
        return list(set(allowed_shifts))

    # --- 3. PRÜFE EXPLIZITE ZUWEISUNG IM FELD 'SPEZIALDIENST' (Erlaubte Dienste) ---
    explicit_codes = []
    if spez not in ["OHNE", "NUR WE UND FEIERTAGE", ""]:
        tokens = [t.strip() for t in re.split(r"[,;\s]+", spez) if t.strip()]
        for sh_c in all_defined_codes:
            if sh_c in tokens:
                explicit_codes.append(sh_c)

    # --- 4. MUTTERSCHUTZ (MSchG) ---
    if gesetz == "Mutterschutz (MSchG)":
        if explicit_codes:
            short_exp = [c for c in explicit_codes if c not in NIGHT_SHIFTS and SHIFTS_HUNDREDTHS.get(c, 0) <= 950]
            if short_exp:
                return list(set(["OFF"] + short_exp))
        if rolle == "DGKP":
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

    # --- 5. WENN EXPLIZITE DIENSTE BEI DIESER PERSON EINGETRAGEN SIND ---
    if explicit_codes:
        exp_day = [c for c in explicit_codes if c not in NIGHT_SHIFTS]
        exp_night = [c for c in explicit_codes if c in NIGHT_SHIFTS]
        if not nur_nacht and exp_day:
            allowed_shifts.extend(exp_day)
            # Spezielle Heimhelfer-Regel: Wenn beim Standard-Heimhelfer 'JED' steht, darf er zuerst JED machen
            # und (sobald JED besetzt ist) mit F2/F7 in der Pflege helfen
            if spez == "JED" and rolle == "Heimhelfer":
                for c_help in ["F2", "F7"]:
                    if c_help in all_defined_codes:
                        allowed_shifts.append(c_help)
        if exp_night:
            if rolle == "DGKP":
                allowed_shifts.extend([c for c in exp_night if c != "N2"])
            else:
                allowed_shifts.extend([c for c in exp_night if c != "N1"])
        elif max_n > 0 or nur_nacht:
            if rolle == "DGKP":
                allowed_shifts.append("N1")
            elif rolle in ["PFA", "Pflegeassistenz"]:
                allowed_shifts.append("N2")
        return list(set(allowed_shifts))

    # --- 6. STANDARD-ZUWEISUNG ('Ohne'): NUR KERN-DIENSTE MIT Auto_Alle == True! ---
    if rolle in ["Pflegeassistenz", "PFA"]:
        role_col = "Erlaubt_PFA" if rolle == "PFA" else "Erlaubt_PA"
        pa_std_day = auto_day_df[auto_day_df[role_col] == True]["Kürzel"].tolist()
        if not pa_std_day:
            pa_std_day = [c for c in ["F2", "F7"] if c in all_defined_codes]
        if not nur_nacht:
            allowed_shifts.extend(pa_std_day)
        if max_n > 0 or nur_nacht:
            pa_nights = night_df[(night_df[role_col] == True) & (night_df["Auto_Alle"] == True)]["Kürzel"].tolist()
            allowed_shifts.extend(pa_nights if pa_nights else ["N2"])
        return list(set(allowed_shifts))

    if rolle == "Heimhelfer":
        if not nur_nacht:
            hh_std_day = auto_day_df[auto_day_df["Erlaubt_HH"] == True]["Kürzel"].tolist()
            if not hh_std_day:
                hh_std_day = [c for c in ["JED", "F2", "F7"] if c in all_defined_codes]
            allowed_shifts.extend(hh_std_day)
        return list(set(allowed_shifts))

    if rolle == "DGKP":
        if not nur_nacht:
            dg_std_day = auto_day_df[
                (auto_day_df["Erlaubt_DGKP"] == True) &
                (~auto_day_df["Kürzel"].isin(["L15", "WBL"]))
            ]["Kürzel"].tolist()
            if not dg_std_day:
                dg_std_day = [c for c in ["X4", "X6", "X7"] if c in all_defined_codes]
            allowed_shifts.extend(dg_std_day)
        if max_n > 0 or nur_nacht:
            dg_nights = night_df[(night_df["Erlaubt_DGKP"] == True) & (night_df["Auto_Alle"] == True)]["Kürzel"].tolist()
            allowed_shifts.extend(dg_nights if dg_nights else ["N1"])

    return list(set(allowed_shifts))

def normalize_cal_cell(val):
    """Wandelt lange Kalender-Einträge in kompakte Kürzel um (erlaubt auch jedes eigene Dienstkürzel und Inline-Stunden wie 'T1(6.5)')."""
    if pd.isna(val):
        return ""
    s = str(val).strip().upper()
    if s in ["", "NAN", "NONE", "<NA>", "NULL", "..."]:
        return ""
    s_clean = s.replace("📌", "").replace("🔴", "").replace("🟠", "").replace("🟣", "").replace("🔵", "").replace("⚫", "").replace("🟢", "").replace("⚪", "").strip()
    inl_c, inl_h, inl_full = parse_inline_shift_and_hours(s_clean)
    if inl_c and inl_h is not None:
        return f"{inl_c}({inl_h/100.0:g})"
    for sh_c in MANUAL_SHIFT_CODES:
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
    return s_clean[:10]

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

                if rol in ["DGKP", "Leitung"] and abt in ["Abteilung B", "Abteilung H"]:
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
    """
    Berechnet SOLL, IST, ÜBERSTD. und SALDO für alle Zeilen neu (unterstützt alle Dienste aus dem
    Dienste-Studio sowie direkt eingetippte Dienste mit Stunden wie 'T1(6.5)').
    """
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
            
            sh_h100 = get_shift_hundredths_smart(clean_v)
            sh_check = extract_base_shift(clean_v)
            if sh_h100 > 0:
                total_hours_100 += sh_h100
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
            "Mitarbeiter": "🤝 Aushilfe von Abt. H / WBL",
            "SOLL": 0.0, "IST": 0.0, "ÜBERSTD.": 0.0, "SALDO": 0.0
        }
        for c in day_cols_plan:
            row_b_help[c] = " | ".join(aushilfe_for_b[c]) if aushilfe_for_b[c] else "..."
        extra_aushilfe_rows.append(row_b_help)

    if any(len(v) > 0 for v in aushilfe_for_h.values()):
        row_h_help = {
            "Abteilung": "Abteilung H",
            "Rolle": "Springer",
            "Mitarbeiter": "🤝 Aushilfe von Abt. B / WBL",
            "SOLL": 0.0, "IST": 0.0, "ÜBERSTD.": 0.0, "SALDO": 0.0
        }
        for c in day_cols_plan:
            row_h_help[c] = " | ".join(aushilfe_for_h[c]) if aushilfe_for_h[c] else "..."
        extra_aushilfe_rows.append(row_h_help)

    if extra_aushilfe_rows:
        df_cleaned = pd.concat([df_cleaned, pd.DataFrame(extra_aushilfe_rows)], ignore_index=True)

    return df_cleaned

def build_coverage_summary_df(full_df, dept_name, num_days, min_b=4, min_h=4):
    """
    Erstellt die Kontrollzeilen unter den Tabellen:
    - Berücksichtigt Springer ('➔ H' / '➔ B') und WBL-Reserve ('L15').
    - Hinweis: Der reine Büro-Dienst 'WBL' zählt NICHT als Pflege-DGKP am Bett,
      während 'L15' (WBL-Reserve bis 15:30) als DGKP-Abdeckung in der Pflege zählt!
    """
    day_cols_only = [f"{d}." for d in range(1, num_days + 1)]
    real_full = full_df[~full_df["Mitarbeiter"].astype(str).str.contains("X-Oseba|FEHLT|⚠️|🤝 Aushilfe", na=False)]

    summary_rows = []

    if dept_name in ["Abteilung B", "Abteilung H"]:
        target_Code = "B" if dept_name == "Abteilung B" else "H"
        other_Code = "H" if dept_name == "Abteilung B" else "B"
        min_pa_target = min_b if dept_name == "Abteilung B" else min_h

        row_dgkp = {"Kontroll-Kategorie": "🩺 DGKP Tag (Min. 1 | inkl. WBL-Reserve L15)"}
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
                sh_h100 = get_shift_hundredths_smart(raw_cell)

                if sh_h100 == 0 or base_sh in ["OFF", "WBL"] + NIGHT_SHIFTS:
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

                if emp_role in ["DGKP", "Leitung"]:
                    dgkp_present += 1
                    if emp_role == "Leitung" or base_sh == "L15":
                        wbl_reserve_used = True
                else:
                    pa_present += 1
                    if is_incoming_springer:
                        springer_in_count += 1

            if wbl_reserve_used:
                row_dgkp[c] = f"{dgkp_present} (👨‍⚕️ L15)"
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
            has_special = False
            if isinstance(val, (int, float, np.integer)):
                num_val = int(val)
            elif isinstance(val, str):
                if "🤝" in val or "Springer" in val or "L15" in val:
                    has_special = True
                first_part = val.split(" ")[0].strip()
                if first_part.isdigit():
                    num_val = int(first_part)

            if num_val is None:
                styles.append("text-align: center;")
                continue

            if "Min. " in kat:
                if num_val < min_needed:
                    styles.append("background-color: #f8d7da; color: #721c24; font-weight: bold; text-align: center; border: 1px solid #f5c6cb;")
                elif has_special:
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
            sh_dur = get_shift_hundredths_smart(raw_v)
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
            elif sh_dur > 0:
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
    .sh-springer {{ background-color: #d4edda !important; color: #005c15 !important; font-weight: bold; border: 1.5px solid #28a745; }}
    .sh-wbl {{ background-color: #e0f2fe !important; color: #0369a1 !important; font-weight: bold; }}
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
<div class="meta">Steiermark StPAVO & KA-AZG/SWÖ-KV zertifiziert | Legende: <strong>X7/X6/X4</strong> = DGKP Tag | <strong>L15</strong> = WBL-Reserve bis 15:30 | <strong>F2/F7</strong> = PFA/PA Tag | <strong>JED</strong> = Speisesaal | <strong>N1/N2</strong> = Nacht | <strong>➔ H / ➔ B</strong> = Aushilfe</div>
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
                base_s = extract_base_shift(val)
                dow = (d - 1 + first_day_weekday) % 7
                is_hol = (date(leto, mesec, d) in at_holidays) or (mesec == 12 and d in [24, 31])
                cell_cls = "hol-col" if is_hol else ("we-col" if dow >= 5 else "")

                if base_s in NIGHT_SHIFTS:
                    cell_cls = "sh-night"
                elif "➔" in val or "⬅️" in val:
                    cell_cls = "sh-springer"
                elif base_s in ["L15", "WBL"]:
                    cell_cls = "sh-wbl"
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
        hrs = get_shift_hundredths_smart(raw_v) / 100.0
        dow = (d - 1 + first_day_weekday) % 7
        is_hol = (date(leto, mesec, d) in at_holidays) or (mesec == 12 and d in [24, 31])
        bg = "#fff0f0" if is_hol else ("#f2f2f7" if dow >= 5 else "#ffffff")
        bemerkung = "Feiertag" if is_hol else ("Wochenende" if dow >= 5 else "")
        if "➔" in raw_v:
            bemerkung += f" | Aushilfe ({raw_v})"
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
    <thead><tr><th>Datum</th><th>Wochentag</th><th>Dienst / Abwesenheit</th><th>Gewertete Arbeitszeit</th><th>Bemerkung / Station</th></tr></thead>
    <tbody>{''.join(rows_html)}</tbody>
</table>
<div class="sig">
    <div>Datum, Unterschrift Mitarbeiter/in ({emp_name})</div>
    <div>Unterschrift WBL / Stationsleitung</div>
</div>
</body></html>"""

def run_austrian_law_audit(df_plan, staff_df, shifts_df, num_days, leto, mesec, first_day_weekday, at_holidays, min_b=4, min_h=4):
    """Prüft den Dienstplan nach Steiermark- & Österreich-Recht."""
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
            hrs_100 = sum(get_shift_hundredths_smart(row[day_cols_only[d+i]]) for i in range(7))
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
    "⏱️ 2. Dienste-Studio",
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
    st.header("2. Team, Rollen (inkl. WBL-Reserve & PFA), Gesetzlicher Status & Erlaubte Dienste")
    
    if "staff_df_v74" not in st.session_state:
        loaded_df = None
        if os.path.exists("team_data.csv"):
            try:
                with open("team_data.csv", "rb") as f:
                    loaded_df = sanitize_team_df(read_csv_smart(f.read(), is_index_col=False))
            except Exception: 
                loaded_df = None

        if loaded_df is None or loaded_df.empty:
            initial_staff = []
            initial_staff.append({"ID": len(initial_staff), "Name": "WBL Uroš", "Abteilung": "Abteilung H", "Rolle": "Leitung", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 30.0, "URL_Rest": 30.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": False, "SO": False, "FT": False, "Spezialdienst": "L15"})
            for i in range(1, 6): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP B-{i}", "Abteilung": "Abteilung B", "Rolle": "DGKP", "Qualifikation": "Wundmanager" if i==1 else "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 5): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP H-{i}", "Abteilung": "Abteilung H", "Rolle": "DGKP", "Qualifikation": "Praxisanleiter" if i==1 else "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 5): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP F-{i}", "Abteilung": "Abteilung F", "Rolle": "DGKP", "Qualifikation": "Keine", "Gesetz_Status": "Nachtschwerarbeit (NSchG)", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 12, "Nur_Nacht": True, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 3): initial_staff.append({"ID": len(initial_staff), "Name": f"PFA B-{i}", "Abteilung": "Abteilung B", "Rolle": "PFA", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 3): initial_staff.append({"ID": len(initial_staff), "Name": f"PFA H-{i}", "Abteilung": "Abteilung H", "Rolle": "PFA", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 7): initial_staff.append({"ID": len(initial_staff), "Name": f"PA B-{i}", "Abteilung": "Abteilung B", "Rolle": "Pflegeassistenz", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 7): initial_staff.append({"ID": len(initial_staff), "Name": f"PA H-{i}", "Abteilung": "Abteilung H", "Rolle": "Pflegeassistenz", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 4): initial_staff.append({"ID": len(initial_staff), "Name": f"HH B-{i}", "Abteilung": "Abteilung B", "Rolle": "Heimhelfer", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "JED"})
            for i in range(1, 3): initial_staff.append({"ID": len(initial_staff), "Name": f"HH H-{i}", "Abteilung": "Abteilung H", "Rolle": "Heimhelfer", "Qualifikation": "Keine", "Gesetz_Status": "Normal", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "JED"})
            
            st.session_state.staff_df_v74 = pd.DataFrame(initial_staff)
        else:
            st.session_state.staff_df_v74 = loaded_df

    col_import, col_export = st.columns(2)
    with col_export:
        st.download_button(
            label="📥 Aktuelles Team als Backup speichern", 
            data=st.session_state.staff_df_v74.to_csv(index=False).encode('utf-8'), 
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
                    st.session_state.staff_df_v74 = uploaded_team
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
        for k in ["staff_df_v74", "shifts_df_v74", "pavo_df_v74", "abs_matrix_v74", "raw_uploaded_cal", "last_generated_df"]:
            if k in st.session_state: 
                del st.session_state[k]
        st.session_state.team_editor_ver += 1
        st.session_state.shifts_editor_ver += 1
        st.session_state.cal_editor_ver += 1
        st.session_state.plan_editor_ver += 1
        st.rerun()

    st.subheader("🎛️ Individueller Dienst-, Stunden- & Schutzstatus-Konfigurator")
    st.caption(
        "Wähle hier für einzelne Mitarbeiter gezielt aus, **welche Dienste (auch eigene Spezialdienste aus Tab 2!)** sie arbeiten sollen. "
        "Wenn du einem Mitarbeiter hier z. B. nur `T6` oder `F7, MS` zuweist, plant die KI für diese Person **ausschließlich** diese Dienste!"
    )
    current_staff_tab1 = st.session_state.staff_df_v74["Name"].dropna().astype(str).str.strip().tolist()
    with st.form("custom_shift_builder_form"):
        cb1, cb2, cb3, cb4, cb5 = st.columns([1.8, 2.2, 1.3, 1.3, 0.9])
        with cb1:
            sel_staff_custom = st.multiselect("1. Mitarbeiter:", current_staff_tab1)
        with cb2:
            sel_shifts_custom = st.multiselect(
                "2. Exakt erlaubte Schichten:",
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
            df_mod = st.session_state.staff_df_v74.copy()
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
            st.session_state.staff_df_v74 = df_mod
            df_mod.to_csv("team_data.csv", index=False)
            st.session_state.team_editor_ver += 1
            st.success("✅ Einstellungen erfolgreich auf Mitarbeiter übertragen!")
            st.rerun()

    with st.form("team_editor_form"):
        edited_data = st.data_editor(
            st.session_state.staff_df_v74, 
            num_rows="dynamic", 
            key=f"tabelle_mitarbeiter_v74_{st.session_state.team_editor_ver}",
            column_config={
                "ID": None,
                "Abteilung": st.column_config.SelectboxColumn("Abteilung", options=["Abteilung B", "Abteilung H", "Abteilung F"]),
                "Rolle": st.column_config.SelectboxColumn("Rolle", options=ROLE_OPTIONS),
                "Qualifikation": st.column_config.SelectboxColumn("Zusatzqualifikation", options=["Keine", "Wundmanager", "Praxisanleiter", "Palliativ"]),
                "Gesetz_Status": st.column_config.SelectboxColumn("Gesetzl. Status (Steiermark)", options=GESETZ_STATUS_OPTIONS, width="medium"),
                "Wochenstd": st.column_config.NumberColumn("Wochenstd.", min_value=1.0, max_value=60.0, default=37.0, step=0.25),
                "Prozent": st.column_config.NumberColumn("Anst. (%)", disabled=True), 
                "Max_Nacht": st.column_config.NumberColumn("Max Nacht", min_value=0, max_value=20, default=0),
                "Nur_Nacht": st.column_config.CheckboxColumn("Nur Nacht? (Abt. F ist automatisch 100% Nacht)"),
                "Spezialdienst": st.column_config.TextColumn(
                    "Erlaubte Dienste (z.B. Ohne, L15, F2, F7, T6)", 
                    width="medium",
                    help="'Ohne' = Standard-Dienste. Wenn du hier eigene Kürzel (z. B. 'T6' oder 'F7, MS') eintippst, bekommt NUR diese Person genau diese Dienste!"
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
            st.session_state.staff_df_v74 = clean_edited
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
    st.header("⏱️ 2. Dienste-Studio (Beliebige Dienste & exakte Stunden festlegen)")
    st.info(
        "🎯 **Wichtige Neuerung (`Standard für Alle?`):** \n"
        "- Wenn du einen neuen Dienst anlegst, ist das Häkchen **`Automatisch für alle Mitarbeiter planen`** standardmäßig **AUS (`False`)**!\n"
        "- Das bedeutet: Die KI teilt diesen neuen Dienst **NICHT automatisch jedem zu**, sondern **nur jenen Personen**, bei denen du das Dienst-Kürzel in Tab 1 unter `Erlaubte Dienste` (oder in Tab 4 als Fix-Dienst) einträgst!"
    )
    with st.container(border=True):
        st.subheader("➕ Neuen Dienst mit beliebiger Stundenzahl erstellen (oder bestehenden anpassen)")
        with st.form("quick_create_shift_form"):
            sc1, sc2, sc3, sc4, sc5 = st.columns([1.1, 2.0, 1.3, 1.2, 1.8])
            with sc1:
                new_sh_code = st.text_input("1. Dienst-Kürzel:", placeholder="z. B. L15, T6, F3").strip().upper()
            with sc2:
                new_sh_name = st.text_input("2. Name / Beschreibung:", placeholder="z. B. Dienst bis 15:30").strip()
            with sc3:
                new_sh_time = st.text_input("3. Uhrzeit (Von-Bis):", value="07:00-15:30").strip()
            with sc4:
                new_sh_hours = st.number_input("4. Netto-Stunden (h):", min_value=0.25, max_value=24.0, value=8.0, step=0.05, format="%.2f")
            with sc5:
                new_sh_type = st.selectbox("5. Dienst-Kategorie:", ["Tagdienst Pflege", "Leitung / Reserve (bis 15:30)", "Speisesaal / Sonder", "Nachtdienst"])

            st.markdown("**6. Zuweisungs-Modus & Berufsgruppen:**")
            rc0, rc1, rc2, rc3, rc4, rc5 = st.columns([1.8, 1, 0.8, 0.8, 0.8, 1.3])
            with rc0:
                auto_all_flag = st.checkbox("🔓 Automatisch für ALLE planen?", value=False, help="Lasse dieses Häkchen AUS, damit der Dienst nur Personen zugeteilt wird, bei denen du ihn explizit einträgst!")
            with rc1:
                allow_dgkp = st.checkbox("🩺 DGKP/WBL", value=True)
            with rc2:
                allow_pfa = st.checkbox("💉 PFA", value=True)
            with rc3:
                allow_pa = st.checkbox("🏥 PA", value=True)
            with rc4:
                allow_hh = st.checkbox("🍽️ HH", value=False)
            with rc5:
                save_new_shift_btn = st.form_submit_button("💾 Dienst speichern", type="primary", use_container_width=True)

            if save_new_shift_btn:
                if not new_sh_code or new_sh_code in ["OFF", "..."]:
                    st.error("Bitte ein gültiges Dienst-Kürzel eingeben!")
                else:
                    df_sh = st.session_state.shifts_df_v74.copy()
                    new_entry = pd.DataFrame([{
                        "Kürzel": new_sh_code,
                        "Bezeichnung": new_sh_name if new_sh_name else f"Dienst {new_sh_code}",
                        "Uhrzeit": new_sh_time if new_sh_time else "07:00-15:30",
                        "Stunden": float(new_sh_hours),
                        "Typ": new_sh_type,
                        "Auto_Alle": bool(auto_all_flag),
                        "Erlaubt_DGKP": bool(allow_dgkp),
                        "Erlaubt_PFA": bool(allow_pfa),
                        "Erlaubt_PA": bool(allow_pa),
                        "Erlaubt_HH": bool(allow_hh)
                    }])
                    df_sh = pd.concat([df_sh, new_entry], ignore_index=True)
                    df_sh = sanitize_shifts_df(df_sh)
                    st.session_state.shifts_df_v74 = df_sh
                    df_sh.to_csv("shifts_data.csv", index=False)
                    st.session_state.shifts_editor_ver += 1
                    if "last_generated_df" in st.session_state:
                        st.session_state.last_generated_df = recalculate_plan_df(
                            st.session_state.last_generated_df, st.session_state.staff_df_v74, num_days
                        )
                        st.session_state.last_generated_df.to_csv(plan_autosave_path, index=False)
                        st.session_state.plan_editor_ver += 1
                    st.success(f"✅ Dienst **{new_sh_code}** ({new_sh_hours:.2f}h, {new_sh_time}) gespeichert!")
                    st.rerun()

    st.divider()
    st.subheader("📋 Alle aktiven Dienste im System (Jede Stundenzahl direkt editierbar)")
    with st.form("edit_all_shifts_form"):
        edited_shifts_df = st.data_editor(
            st.session_state.shifts_df_v74,
            num_rows="dynamic",
            use_container_width=True,
            hide_index=True,
            key=f"shifts_table_editor_{st.session_state.shifts_editor_ver}",
            column_config={
                "Kürzel": st.column_config.TextColumn("Dienst-Kürzel", width="small", required=True),
                "Bezeichnung": st.column_config.TextColumn("Bezeichnung / Name", width="medium"),
                "Uhrzeit": st.column_config.TextColumn("Uhrzeit (Von-Bis)", width="small"),
                "Stunden": st.column_config.NumberColumn("Stunden (h)", min_value=0.25, max_value=24.0, step=0.05, format="%.2f"),
                "Typ": st.column_config.SelectboxColumn("Kategorie", options=["Tagdienst Pflege", "Leitung / Reserve (bis 15:30)", "Nachtdienst", "Speisesaal / Sonder"], width="medium"),
                "Auto_Alle": st.column_config.CheckboxColumn("Standard für Alle?", help="Wenn AUS: Dienst wird nur geplant, wenn er beim Mitarbeiter unter 'Erlaubte Dienste' oder als Fix-Dienst steht."),
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
            clean_sh = sanitize_shifts_df(edited_shifts_df)
            st.session_state.shifts_df_v74 = clean_sh
            clean_sh.to_csv("shifts_data.csv", index=False)
            st.session_state.shifts_editor_ver += 1
            if "last_generated_df" in st.session_state:
                st.session_state.last_generated_df = recalculate_plan_df(
                    st.session_state.last_generated_df, st.session_state.staff_df_v74, num_days
                )
                st.session_state.last_generated_df.to_csv(plan_autosave_path, index=False)
                st.session_state.plan_editor_ver += 1
            st.success("✅ Dienste-Katalog aktualisiert!")
            st.rerun()

        if reset_shifts_btn:
            default_sh = get_default_shifts_df()
            st.session_state.shifts_df_v74 = default_sh
            default_sh.to_csv("shifts_data.csv", index=False)
            st.session_state.shifts_editor_ver += 1
            st.rerun()

with tab_pavo:
    st.header("🧮 3. StPAVO Steiermark – Personalberechnung nach Pflegestufen & Qualifikations-Mix")
    st.subheader("1. Bewohneranzahl nach Pflegegeldstufen (Stufe 0 bis 7) eingeben")
    edited_pavo = st.data_editor(
        st.session_state.pavo_df_v74,
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
    if not edited_pavo.equals(st.session_state.pavo_df_v74):
        st.session_state.pavo_df_v74 = edited_pavo
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

    for _, p_row in st.session_state.pavo_df_v74.iterrows():
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

    df_team_curr = sanitize_team_df(st.session_state.staff_df_v74)
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
            f"**Abteilung H:** Min. `{st.session_state.target_min_h}` PA/PFA/HH + 1 DGKP | **WBL:** Mo–Fr Reserve bis 15:30 (`L15`)."
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
    current_staff = st.session_state.staff_df_v74["Name"].dropna().astype(str).str.strip().tolist()
    
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

    if "abs_matrix_v74" not in st.session_state:
        if os.path.exists(cal_autosave_path):
            try:
                with open(cal_autosave_path, "rb") as f:
                    saved_cal = read_csv_smart(f.read(), is_index_col=True)
                st.session_state.raw_uploaded_cal = saved_cal
                st.session_state.abs_matrix_v74 = sync_calendar_df(saved_cal, current_staff, day_cols)
            except Exception:
                st.session_state.abs_matrix_v74 = pd.DataFrame("", index=current_staff, columns=day_cols)
        else:
            st.session_state.abs_matrix_v74 = pd.DataFrame("", index=current_staff, columns=day_cols)
    else:
        if st.session_state.get("needs_cal_resync") and "raw_uploaded_cal" in st.session_state:
            st.session_state.abs_matrix_v74 = sync_calendar_df(st.session_state.raw_uploaded_cal, current_staff, day_cols)
            st.session_state.needs_cal_resync = False
        else:
            st.session_state.abs_matrix_v74 = sync_calendar_df(st.session_state.abs_matrix_v74, current_staff, day_cols)

    dynamic_fix_options = [
        f"📌 {row['Kürzel']} (Fix {row['Stunden']}h | {row['Uhrzeit']} – {row['Bezeichnung']})"
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
            data=st.session_state.abs_matrix_v74.to_csv(index=True).encode('utf-8'), 
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
                    st.session_state.abs_matrix_v74 = synced_cal
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
                emp_row_info = st.session_state.staff_df_v74[st.session_state.staff_df_v74["Name"] == chk_emp].iloc[0]
                e_abt = str(emp_row_info["Abteilung"])
                e_rol = str(emp_row_info["Rolle"])
                q_df_now = build_vacation_quota_summary_df(
                    st.session_state.abs_matrix_v74, st.session_state.staff_df_v74, day_cols, st.session_state.max_vac_per_station
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
                    if e_rol in ["DGKP", "Leitung"] and e_abt in ["Abteilung B", "Abteilung H"] and int(q_df_now.iloc[2][c_n]) >= 2:
                        conflict_days.append(f"{d_i}. (Bereits 2 DGKP abwesend)")
                if not conflict_days:
                    st.success(f"✅ **GRÜNES LICHT!** `{chk_emp}` ({e_abt}, {e_rol}) kann von **{chk_d1}. bis {chk_d2}.** problemlos auf Urlaub/ZA gehen!")
                else:
                    st.warning(f"⚠️ **Kontingent-Warnung an folgenden Tagen:** {', '.join(conflict_days)}")

        with q_c2:
            st.markdown("**⚖️ 2. Automatischer ZA-Abbau für Mitarbeiter mit hohem Plus-Saldo (`Saldo_Alt > +12h`):**")
            if st.button("⚡ Auto-ZA für Plus-Stunden an grünen Tagen eintragen", type="primary"):
                q_df_now = build_vacation_quota_summary_df(
                    st.session_state.abs_matrix_v74, st.session_state.staff_df_v74, day_cols, st.session_state.max_vac_per_station
                )
                za_added_count = 0
                for _, s_r in st.session_state.staff_df_v74.iterrows():
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
                            if st.session_state.abs_matrix_v74.at[emp_n, c_n] != "":
                                continue
                            row_idx_abt = 0 if e_abt == "Abteilung B" else 1
                            if int(q_df_now.iloc[row_idx_abt][c_n]) < st.session_state.max_vac_per_station - 1:
                                if e_rol == "Heimhelfer" and int(q_df_now.iloc[3][c_n]) >= 1:
                                    continue
                                st.session_state.abs_matrix_v74.at[emp_n, c_n] = "ZA"
                                q_df_now.at[row_idx_abt, c_n] = int(q_df_now.iloc[row_idx_abt][c_n]) + 1
                                given += 1
                                za_added_count += 1
                if za_added_count > 0:
                    st.session_state.raw_uploaded_cal = st.session_state.abs_matrix_v74.copy()
                    st.session_state.abs_matrix_v74.to_csv(cal_autosave_path, index=True)
                    st.session_state.cal_editor_ver += 1
                    st.success(f"✅ Es wurden automatisch **{za_added_count} ZA-Tage** an grünen Kontingent-Tagen eingetragen!")
                    st.rerun()
                else:
                    st.info("Aktuell hat kein Mitarbeiter auf B/H ein `Saldo_Alt` von mindestens +12,0 Stunden.")

    st.subheader("⚡ Schnelleingabe (Urlaube, Entlastungstage, ZA, Wünsche & beliebige Fix-Dienste)")
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
                    st.session_state.abs_matrix_v74.at[emp, target_col] = val_to_write
            st.session_state.raw_uploaded_cal = st.session_state.abs_matrix_v74.copy()
            st.session_state.
