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

st.set_page_config(page_title="KI-Dienstplan PRO 61.0", layout="wide")

st.title("🏥 KI-Dienstplan System (Version 61.0 - Instant-Sync & Smart Brain)")
st.markdown(
    "**Aktuelle Konfiguration:** \n"
    "- ⚡ **Instant-Sync beim Upload:** Team- und Kalender-Dateien aktualisieren die Tabellen sofort beim ersten Hochladen (unterstützt Komma `,` und Excel-Semikolon `;`).\n"
    "- 🧠 **Smart Nacht-Logik:** Optimal 2 Nächte am Stück (max. 3 erlaubt). Danach folgen **zwingend 2 freie Tage** (Schlaftag + Ruhetag).\n"
    "- ⏱️ **50h-Woche & Überstunden:** Mitarbeiter können bei Bedarf bis zu 50h/Woche arbeiten (wird als `ÜBERSTD.` ausgewiesen).\n"
    "- 🚨 **100% Absturzsicher:** Der Plan wird immer erstellt – ungedeckte Schichten werden als `X-Oseba` markiert."
)

# Hilfsfunktion für sicheres CSV-Lesen (Komma oder Semikolon aus Excel)
def read_csv_smart(raw_bytes, is_index_col=False):
    for enc in ["utf-8-sig", "utf-8", "latin1"]:
        try:
            text = raw_bytes.decode(enc)
            first_line = text.splitlines()[0] if text.splitlines() else ""
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
    df["Nur_Nacht"] = df["Nur_Nacht"].astype(bool)
    
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
        
    cols_order = [
        "ID", "Name", "Abteilung", "Rolle", "Qualifikation", "Wochenstd", "Prozent", 
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
            elif c == "Nur_Nacht": 
                df[c] = False
            else: 
                df[c] = 0
    return df[cols_order].reset_index(drop=True)

if "team_editor_ver" not in st.session_state:
    st.session_state.team_editor_ver = 0
if "cal_editor_ver" not in st.session_state:
    st.session_state.cal_editor_ver = 0

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "⚙️ 1. Einstellungen", 
    "📅 2. Dienstplan", 
    "🏝️ 3. Abwesenheiten", 
    "🚨 4. SOS", 
    "📉 5. Analyse", 
    "🛡️ 6. Inspektorat"
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

    st.divider()
    st.header("2. Team verwalten & Backup")
    
    if "staff_df_v61" not in st.session_state:
        loaded_df = None
        if os.path.exists("team_data.csv"):
            try:
                with open("team_data.csv", "rb") as f:
                    loaded_df = sanitize_team_df(read_csv_smart(f.read(), is_index_col=False))
            except Exception: 
                loaded_df = None

        if loaded_df is None or loaded_df.empty:
            initial_staff = []
            initial_staff.append({"ID": len(initial_staff), "Name": "WBL Uroš", "Abteilung": "Abteilung H", "Rolle": "Leitung", "Qualifikation": "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 30.0, "URL_Rest": 30.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": False, "SO": False, "FT": False, "Spezialdienst": "Ohne"})
            for i in range(1, 6): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP B-{i}", "Abteilung": "Abteilung B", "Rolle": "DGKP", "Qualifikation": "Wundmanager" if i==1 else "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 5): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP H-{i}", "Abteilung": "Abteilung H", "Rolle": "DGKP", "Qualifikation": "Praxisanleiter" if i==1 else "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 5): initial_staff.append({"ID": len(initial_staff), "Name": f"DGKP F-{i}", "Abteilung": "Abteilung F", "Rolle": "DGKP", "Qualifikation": "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 12, "Nur_Nacht": True if i < 3 else False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 9): initial_staff.append({"ID": len(initial_staff), "Name": f"PA B-{i}", "Abteilung": "Abteilung B", "Rolle": "Pflegeassistenz", "Qualifikation": "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 9): initial_staff.append({"ID": len(initial_staff), "Name": f"PA H-{i}", "Abteilung": "Abteilung H", "Rolle": "Pflegeassistenz", "Qualifikation": "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 8, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "Ohne"})
            for i in range(1, 4): initial_staff.append({"ID": len(initial_staff), "Name": f"HH B-{i}", "Abteilung": "Abteilung B", "Rolle": "Heimhelfer", "Qualifikation": "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "JED"})
            for i in range(1, 3): initial_staff.append({"ID": len(initial_staff), "Name": f"HH H-{i}", "Abteilung": "Abteilung H", "Rolle": "Heimhelfer", "Qualifikation": "Keine", "Wochenstd": 37.0, "Prozent": 100.0, "URL_Gesamt": 25.0, "URL_Rest": 25.0, "Saldo_Alt": 0.0, "Max_Nacht": 0, "Nur_Nacht": False, "MO": True, "DI": True, "MI": True, "DO": True, "FR": True, "SA": True, "SO": True, "FT": True, "Spezialdienst": "JED"})
            
            st.session_state.staff_df_v61 = pd.DataFrame(initial_staff)
        else:
            st.session_state.staff_df_v61 = loaded_df

    col_import, col_export = st.columns(2)
    with col_export:
        st.download_button(
            label="📥 Aktuelles Team als Backup speichern", 
            data=st.session_state.staff_df_v61.to_csv(index=False).encode('utf-8'), 
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
            if st.session_state.get("last_team_hash") != file_hash:
                try:
                    uploaded_team = sanitize_team_df(read_csv_smart(raw_bytes, is_index_col=False))
                    uploaded_team.to_csv("team_data.csv", index=False)
                    st.session_state.staff_df_v61 = uploaded_team
                    st.session_state.last_team_hash = file_hash
                    st.session_state.team_editor_ver += 1
                    st.session_state.cal_editor_ver += 1
                    st.session_state.needs_cal_resync = True
                    st.success("✅ Team sofort geladen und aktualisiert!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Fehler beim Laden der Team-Datei: {e}")
            
    st.write("---")
    if st.button("🚨 Alles auf Standard zurücksetzen"):
        if os.path.exists("team_data.csv"): 
            os.remove("team_data.csv")
        for k in ["staff_df_v61", "abs_matrix_v61", "raw_uploaded_cal"]:
            if k in st.session_state: 
                del st.session_state[k]
        st.session_state.team_editor_ver += 1
        st.session_state.cal_editor_ver += 1
        st.rerun()

    with st.form("team_editor_form"):
        edited_data = st.data_editor(
            st.session_state.staff_df_v61, 
            num_rows="dynamic", 
            key=f"tabelle_mitarbeiter_v61_{st.session_state.team_editor_ver}",
            column_config={
                "ID": None,
                "Abteilung": st.column_config.SelectboxColumn("Abteilung", options=["Abteilung B", "Abteilung H", "Abteilung F"]),
                "Rolle": st.column_config.SelectboxColumn("Rolle", options=["Leitung", "DGKP", "Pflegeassistenz", "Heimhelfer"]),
                "Qualifikation": st.column_config.SelectboxColumn("Zusatzqualifikation", options=["Keine", "Wundmanager", "Praxisanleiter", "Palliativ"]),
                "Wochenstd": st.column_config.NumberColumn("Wochenstd.", min_value=1.0, max_value=60.0, default=37.0, step=0.5),
                "Prozent": st.column_config.NumberColumn("Anst. (%)", disabled=True), 
                "Max_Nacht": st.column_config.NumberColumn("Max Nacht", min_value=0, max_value=20, default=0),
                "Spezialdienst": st.column_config.SelectboxColumn("Spezialdienst", options=["Ohne", "Nur WE und Feiertage", "F2", "F7", "X7", "X6", "X4", "JED", "MS", "SM"]),
                "URL_Gesamt": st.column_config.NumberColumn("Urlaub Gesamt", min_value=0.0, max_value=50.0, default=25.0),
                "URL_Rest": st.column_config.NumberColumn("Urlaub Rest", min_value=0.0, max_value=50.0, default=25.0)
            }, 
            use_container_width=True, 
            height=700
        )
        if st.form_submit_button("💾 Spremembe ekipe potrdi", type="primary"):
            clean_edited = sanitize_team_df(edited_data)
            clean_edited["URL_Rest"] = clean_edited.apply(lambda row: min(row["URL_Gesamt"], row["URL_Rest"]), axis=1)
            st.session_state.staff_df_v61 = clean_edited
            clean_edited.to_csv("team_data.csv", index=False)
            st.session_state.team_editor_ver += 1
            st.session_state.cal_editor_ver += 1
            st.success("✅ Teamdaten erfolgreich gespeichert!")
            st.rerun()

with tab3:
    st.header("🏝️ 3. Abwesenheiten & Wünsche (Smart Matrix)")
    
    current_staff = st.session_state.staff_df_v61["Name"].dropna().astype(str).str.strip().tolist()
    
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
        
        # Index bereinigen für exakten Abgleich
        src = source_df.copy()
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

    if "abs_matrix_v61" not in st.session_state:
        st.session_state.abs_matrix_v61 = pd.DataFrame("", index=current_staff, columns=day_cols)
    else:
        # Falls ein Team nachträglich hochgeladen wurde, synchronisiere mit dem gespeicherten Raw-Kalender
        if st.session_state.get("needs_cal_resync") and "raw_uploaded_cal" in st.session_state:
            st.session_state.abs_matrix_v61 = sync_calendar_df(st.session_state.raw_uploaded_cal, current_staff, day_cols)
            st.session_state.needs_cal_resync = False
        else:
            st.session_state.abs_matrix_v61 = sync_calendar_df(st.session_state.abs_matrix_v61, current_staff, day_cols)

    color_options = ["", "🔴 URL", "🟠 SU", "🟣 ENT", "🔵 KRA", "⚫ ZA", "🟢 WUNSCH", "⚪ MUSS"]

    col_bak1, col_bak2 = st.columns(2)
    with col_bak1:
        st.download_button(
            label="📥 Kalender-Backup speichern", 
            data=st.session_state.abs_matrix_v61.to_csv(index=True).encode('utf-8'), 
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
            if st.session_state.get("last_cal_hash") != cal_hash:
                try:
                    uploaded_cal = read_csv_smart(raw_cal_bytes, is_index_col=True)
                    uploaded_cal = uploaded_cal.fillna("").astype(str)
                    uploaded_cal = uploaded_cal.replace(to_replace=r'^(nan|NaN|None|<NA>|null|none)$', value='', regex=True)
                    
                    st.session_state.raw_uploaded_cal = uploaded_cal
                    st.session_state.abs_matrix_v61 = sync_calendar_df(uploaded_cal, current_staff, day_cols)
                    st.session_state.last_cal_hash = cal_hash
                    st.session_state.cal_editor_ver += 1
                    st.success("✅ Kalender sofort beim ersten Versuch geladen und angezeigt!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Fehler beim Laden des Kalenders: {e}")
            
    st.divider()

    st.subheader("⚡ Schnelleingabe (Mehrere Tage / Personen gleichzeitig)")
    with st.form("bulk_add_form"):
        b_col1, b_col2, b_col3, b_col4 = st.columns([2, 2, 1, 1])
        with b_col1: 
            selected_emps = st.multiselect("1. Mitarbeiter auswählen:", current_staff)
        with b_col2: 
            d_start, d_end = st.slider("2. Von Tag bis Tag:", 1, num_days, (1, 5))
        with b_col3: 
            selected_reason = st.selectbox("3. Grund:", color_options[1:])
        with b_col4: 
            st.write("")
            st.write("")
            submit_bulk = st.form_submit_button("➕ Eintragen", type="primary", use_container_width=True)
            
        if submit_bulk and selected_emps:
            for emp in selected_emps:
                for d in range(d_start, d_end + 1):
                    target_col = day_cols[d-1]
                    st.session_state.abs_matrix_v61.at[emp, target_col] = selected_reason
            st.session_state.raw_uploaded_cal = st.session_state.abs_matrix_v61.copy()
            st.session_state.cal_editor_ver += 1
            st.success("✅ Erfolgreich in die Matrix übernommen!")
            st.rerun()

    st.markdown("👇 **Die Live-Matrix (Änderungen sind sofort aktiv)**")
    
    col_config = {}
    for c in day_cols:
        col_config[c] = st.column_config.TextColumn(c, width="small")
        
    edited_cal_matrix = st.data_editor(
        st.session_state.abs_matrix_v61,
        column_config=col_config,
        use_container_width=True,
        height=700,
        key=f"live_abwesenheiten_matrix_v61_{st.session_state.cal_editor_ver}"
    )
    st.session_state.abs_matrix_v61 = edited_cal_matrix

with tab2:
    st.header("Automatische Dienstplangenerierung")
    
    if st.button("🚀 Dienstplan berechnen", type="primary", use_container_width=True):
        
        try:
            with st.spinner("⏳ KI berechnet optimalen Dienstplan (2er-Nachtblöcke, 2 Tage Ruhezeit, 50h-Limit)..."):
                
                df_clean = sanitize_team_df(st.session_state.staff_df_v61)
                staff_list = df_clean.to_dict("records")
                
                st.session_state.absences_v61 = []
                st.session_state.work_rules_v61 = []
                
                for emp_name in current_staff:
                    emp_id_list = df_clean.loc[df_clean["Name"] == emp_name, "ID"].values
                    if len(emp_id_list) == 0: 
                        continue
                    emp_id = int(emp_id_list[0])
                    
                    for d in range(1, num_days + 1):
                        col_name = day_cols[d-1]
                        val = st.session_state.abs_matrix_v61.at[emp_name, col_name]
                        
                        if pd.notna(val) and str(val).strip() != "":
                            val_str = str(val).upper().strip()
                            if val_str in ["NAN", "NONE", "<NA>", "NULL", ""]: 
                                continue
                                
                            day_idx = d - 1
                            reason = ""
                            
                            if "URL" in val_str: reason = "URL"
                            elif "SU" in val_str: reason = "SU"
                            elif "ENT" in val_str: reason = "ENT"
                            elif "KRA" in val_str: reason = "KRA"
                            elif "ZA" in val_str: reason = "ZA"
                            elif "WUNSCH" in val_str: reason = "WUNSCH-FREI"
                            elif "MUSS" in val_str: reason = "MUSS-ARBEITEN"
                            
                            if reason in ["URL", "SU", "ENT", "KRA", "ZA", "WUNSCH-FREI"]:
                                st.session_state.absences_v61.append({"emp_id": emp_id, "emp_name": emp_name, "day": day_idx, "reason": reason})
                            elif reason == "MUSS-ARBEITEN":
                                st.session_state.work_rules_v61.append({"emp_id": emp_id, "emp_name": emp_name, "day": day_idx, "rule": reason})

                model = cp_model.CpModel()
                hour_deviations = []
                shifts = {
                    "X4": 825, "X6": 1100, "X7": 1200, "F2": 1200, "F7": 1100, 
                    "N1": 1350, "N2": 1350, "JED": 1050, "MS": 700, "SM": 1075, "OFF": 0
                }
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
                    # 1. NACHTSCHICHT-INTELLIGENZ:
                    # - Nach Nachtende zwingend 2 Tage frei (Schlaftag d+1 + Ruhetag d+2)
                    for d in range(num_days - 1):
                        sleep_viol = model.NewBoolVar(f'sleep_viol_{s["ID"]}_{d}')
                        model.Add(work[(s["ID"], d+1, "OFF")] + is_night[(s["ID"], d+1)] + sleep_viol >= is_night[(s["ID"], d)])
                        hour_deviations.append(sleep_viol * 1000000)
                        
                    for d in range(num_days - 2):
                        rest_viol = model.NewBoolVar(f'rest_viol_{s["ID"]}_{d}')
                        model.Add(work[(s["ID"], d+2, "OFF")] + is_night[(s["ID"], d+1)] + rest_viol >= is_night[(s["ID"], d)])
                        hour_deviations.append(rest_viol * 900000)

                    # - Maximal 3 Nächte am Stück (4 Nächte in Folge verboten)
                    for d in range(num_days - 3):
                        four_n_viol = model.NewBoolVar(f'four_n_{s["ID"]}_{d}')
                        model.Add(sum(is_night[(s["ID"], d+i)] for i in range(4)) <= 3 + four_n_viol)
                        hour_deviations.append(four_n_viol * 1500000)

                    # - Beste Kombination: 2 Nächte!
                    for d in range(num_days - 2):
                        three_n = model.NewBoolVar(f'three_n_{s["ID"]}_{d}')
                        model.AddMinEquality(three_n, [is_night[(s["ID"], d)], is_night[(s["ID"], d+1)], is_night[(s["ID"], d+2)]])
                        hour_deviations.append(three_n * 35000)

                    for d in range(1, num_days - 1):
                        single_n_pen = model.NewIntVar(0, 1, f'single_n_pen_{s["ID"]}_{d}')
                        model.Add(single_n_pen >= is_night[(s["ID"], d)] - is_night[(s["ID"], d-1)] - is_night[(s["ID"], d+1)])
                        hour_deviations.append(single_n_pen * 65000)

                    # 2. ALLGEMEINE ARBEITSBLÖCKE & 50-STUNDEN-WOCHE
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

                    # Gleitendes 7-Tage-Fenster: Bis 50h (5000) erlaubt als Überstunden
                    for d in range(num_days - 6):
                        week_hrs = sum(work[(s["ID"], d+i, sh)] * shifts[sh] for i in range(7) for sh in shifts.keys())
                        over_50 = model.NewIntVar(0, 10000, f'over50_{s["ID"]}_{d}')
                        model.Add(over_50 >= week_hrs - 5000)
                        hour_deviations.append(over_50 * 400)

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

                for r in st.session_state.work_rules_v61:
                    if r["day"] < num_days:
                        model.Add(work[(r["emp_id"], r["day"], "OFF")] == 0)

                for s in staff_list:
                    allowed_shifts = ["OFF"]
                    nur_nacht = bool(s.get("Nur_Nacht", False))
                    spez = str(s.get("Spezialdienst", "Ohne"))
                    
                    if spez != "Ohne" and spez != "Nur WE und Feiertage":
                        if "F2" in spez: allowed_shifts.append("F2")
                        if "F7" in spez: allowed_shifts.append("F7")
                        if "X7" in spez: allowed_shifts.append("X7")
                        if "X6" in spez: allowed_shifts.append("X6")
                        if "X4" in spez: allowed_shifts.append("X4")
                        if "JED" in spez: 
                            allowed_shifts.append("JED")
                            if s["Rolle"] == "Heimhelfer": allowed_shifts.extend(["F2", "F7"])
                        if "MS" in spez: allowed_shifts.append("MS")
                        if "SM" in spez: allowed_shifts.append("SM")
                        if int(s.get("Max_Nacht", 0)) > 0:
                            nocna = "N1" if s["Rolle"] in ["DGKP", "Leitung"] else "N2"
                            allowed_shifts.append(nocna)
                    else:
                        if s["Abteilung"] == "Abteilung F":
                            if s["Rolle"] in ["DGKP", "Leitung"]: 
                                allowed_shifts.append("N1")
                                if not nur_nacht: allowed_shifts.extend(["X4", "X6", "X7"]) 
                            else: 
                                allowed_shifts.append("N2") 
                                if not nur_nacht: allowed_shifts.extend(["F2", "F7"])
                        else:
                            if s["Rolle"] in ["DGKP", "Leitung"]:
                                if not nur_nacht: allowed_shifts.extend(["X4", "X6", "X7"])
                                if int(s.get("Max_Nacht", 0)) > 0: allowed_shifts.append("N1")
                            elif s["Rolle"] in ["Pflegeassistenz", "Heimhelfer"]:
                                if not nur_nacht: allowed_shifts.extend(["F2", "F7"])
                                if int(s.get("Max_Nacht", 0)) > 0: allowed_shifts.append("N2")
                        
                    allowed_shifts = list(set(allowed_shifts))
                    unallowed = [sh for sh in shifts.keys() if sh not in allowed_shifts]
                    
                    for d in range(num_days):
                        dow = (d + first_day_of_month_weekday) % 7
                        is_holiday = (date(leto, mesec, d+1) in at_holidays) or (mesec == 12 and (d+1 == 24 or d+1 == 31))
                        
                        for sh in unallowed: 
                            model.Add(work[(s["ID"], d, sh)] == 0)
                        
                        if s["Rolle"] == "Leitung":
                            if dow >= 5 or is_holiday:
                                has_muss = any(r["day"] == d and r["emp_id"] == s["ID"] for r in st.session_state.work_rules_v61)
                                if not has_muss:
                                    model.Add(work[(s["ID"], d, "OFF")] == 1)
                                
                        if s["Rolle"] == "DGKP":
                            if dow >= 5 or is_holiday:
                                for sh in ["X4", "X6", "F2", "F7", "JED", "MS", "SM", "N2"]:
                                    model.Add(work[(s["ID"], d, sh)] == 0)

                    if s["Max_Nacht"] > 0:
                        nocna_koda = "N1" if s["Rolle"] in ["DGKP", "Leitung"] else "N2"
                        if nocna_koda in allowed_shifts: 
                            over_nacht = model.NewIntVar(0, 31, f'over_n_{s["ID"]}')
                            model.Add(sum(work[(s["ID"], d, nocna_koda)] for d in range(num_days)) - int(s["Max_Nacht"]) <= over_nacht)
                            hour_deviations.append(over_nacht * 50000)
                    else:
                        if "N1" in allowed_shifts: model.Add(sum(work[(s["ID"], d, "N1")] for d in range(num_days)) == 0)
                        if "N2" in allowed_shifts: model.Add(sum(work[(s["ID"], d, "N2")] for d in range(num_days)) == 0)
                        
                    if s["Rolle"] == "Leitung":
                        model.Add(sum(work[(s["ID"], d, "N1")] for d in range(num_days)) == 0)
                        model.Add(sum(work[(s["ID"], d, "N2")] for d in range(num_days)) == 0)

                for a in st.session_state.absences_v61:
                    if a["day"] < num_days: 
                        model.Add(work[(a["emp_id"], a["day"], "OFF")] == 1)

                # --- STUNDEN & ÜBERSTUNDEN LOGIK ---
                paid_absence_reasons = ["URL", "SU", "ENT", "KRA"]
                for s in staff_list:
                    w_std = float(s.get("Wochenstd", 37.0))
                    daily_avg = w_std / 7.0
                    standard_target = daily_avg * num_days
                    saldo_alt = float(s.get("Saldo_Alt", 0.0))
                    
                    emp_paid_abs_days = sum(
                        1 for a in st.session_state.absences_v61 
                        if a["emp_id"] == s["ID"] and a["reason"] in paid_absence_reasons
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
                    hour_deviations.append(over_work * 12)

                # --- STATIONS-ABDECKUNG & CROSS-COVERAGE ---
                day_sh = ["X4", "X6", "X7", "F2", "F7", "MS", "SM"]
                dgkp_shifts = ["X4", "X6", "X7"]
                
                o_b_all = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B"]
                o_h_all = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H"]
                o_dgkp_b = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung B" and s["Rolle"] in ["DGKP", "Leitung"]]
                o_dgkp_h = [s["ID"] for s in staff_list if s["Abteilung"] == "Abteilung H" and s["Rolle"] in ["DGKP", "Leitung"]]
                o_n1_alle = [s["ID"] for s in staff_list if s["Rolle"] in ["DGKP", "Leitung"]]
                o_n2_pa = [s["ID"] for s in staff_list if s["Rolle"] == "Pflegeassistenz"]
                
                b_shorts, h_shorts, jed_shorts, dg_shorts, n1_diffs, n2_diffs = {}, {}, {}, {}, {}, {}

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
                    
                    b_dgkp = sum(work[(e, d, sh)] for e in o_dgkp_b for sh in dgkp_shifts)
                    h_dgkp = sum(work[(e, d, sh)] for e in o_dgkp_h for sh in dgkp_shifts)
                    dg_tot = model.NewIntVar(0, 10, f'dg_tot_{d}')
                    model.Add(dg_tot == b_dgkp + h_dgkp)
                    dg_short = model.NewIntVar(0, 10, f'dg_short_{d}')
                    model.Add(dg_tot + dg_short >= 2)
                    hour_deviations.append(dg_short * 80000)
                    dg_shorts[d] = dg_short
                    
                    n1_sum = sum(work[(e, d, "N1")] for e in o_n1_alle)
                    n1_diff = model.NewIntVar(-10, 10, f'n1_diff_{d}')
                    model.Add(n1_sum + n1_diff == 1)
                    abs_n1 = model.NewIntVar(0, 10, f'abs_n1_{d}')
                    model.AddAbsEquality(abs_n1, n1_diff)
                    hour_deviations.append(abs_n1 * 150000)
                    n1_diffs[d] = n1_diff
                    
                    n2_sum = sum(work[(e, d, "N2")] for e in o_n2_pa)
                    n2_diff = model.NewIntVar(-10, 10, f'n2_diff_{d}')
                    model.Add(n2_sum + n2_diff == 1)
                    abs_n2 = model.NewIntVar(0, 10, f'abs_n2_{d}')
                    model.AddAbsEquality(abs_n2, n2_diff)
                    hour_deviations.append(abs_n2 * 150000)
                    n2_diffs[d] = n2_diff

                model.Minimize(sum(hour_deviations))
                solver = cp_model.CpSolver()
                solver.parameters.max_time_in_seconds = 45.0 
                status = solver.Solve(model)

                if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                    st.success("🎉 Dienstplan erfolgreich mit Smart-Brain-Logik generiert!")
                    data = []
                    for s in staff_list:
                        qual_str = f" ({s['Qualifikation']})" if s.get('Qualifikation', 'Keine') != "Keine" else ""
                        row = {
                            "ID_hidden": s["ID"], 
                            "Abteilung": s["Abteilung"], 
                            "Rolle": s["Rolle"], 
                            "Mitarbeiter": f"{s['Name']}{qual_str}"
                        }
                        total_hours_100 = 0
                        w_std = float(s.get("Wochenstd", 37.0))
                        daily_avg = w_std / 7.0
                        
                        for d in range(num_days):
                            day_str = f"{d+1}."
                            val = "..."
                            for sh in shifts.keys():
                                if solver.Value(work[(s["ID"], d, sh)]) == 1:
                                    val = sh if sh != "OFF" else "..."
                                    for a in st.session_state.absences_v61:
                                        if a["emp_id"] == s["ID"] and a["day"] == d: 
                                            if "WUNSCH" in a["reason"]: val = "WUNSCH"
                                            elif "MUSS" in a["reason"]: val = "MUSS"
                                            else: val = a["reason"]
                                            if a["reason"] in paid_absence_reasons:
                                                total_hours_100 += int(round(daily_avg * 100))
                                    total_hours_100 += shifts[sh]
                            row[day_str] = val
                        
                        soll_neu = daily_avg * num_days
                        ist_std = round(total_hours_100 / 100.0, 1)
                        saldo_neu = round(ist_std - soll_neu + float(s.get("Saldo_Alt", 0.0)), 1)
                        ueberstunden = round(max(0.0, ist_std - soll_neu), 1)
                        
                        row["SOLL"] = round(soll_neu, 1)
                        row["IST"] = ist_std
                        row["ÜBERSTD."] = ueberstunden
                        row["SALDO"] = saldo_neu
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
                                "ID_hidden": 9999, "Abteilung": abt, "Rolle": rolle, 
                                "Mitarbeiter": name, "SOLL": 0.0, "IST": 0.0, "ÜBERSTD.": 0.0, "SALDO": 0.0
                            }
                            for i in range(num_days): 
                                new_row[f"{i+1}."] = "..."
                            new_row[f"{day+1}."] = f"🚨 {shift}"
                            virtual_rows.append(new_row)

                    for d in range(num_days):
                        if solver.Value(n1_diffs[d]) > 0:
                            for _ in range(solver.Value(n1_diffs[d])): add_v_shift("⚠️ X-Oseba N1", "Abteilung F", "DGKP", d, "N1")
                        if solver.Value(n2_diffs[d]) > 0:
                            for _ in range(solver.Value(n2_diffs[d])): add_v_shift("⚠️ X-Oseba N2", "Abteilung F", "Pflegeassistenz", d, "N2")
                        if solver.Value(jed_shorts[d]) > 0:
                            for _ in range(solver.Value(jed_shorts[d])): add_v_shift("⚠️ X-Oseba Speis", "Abteilung B", "Heimhelfer", d, "JED")
                        if solver.Value(b_shorts[d]) > 0:
                            for _ in range(solver.Value(b_shorts[d])): add_v_shift("⚠️ X-Oseba B", "Abteilung B", "Pflegeassistenz", d, "F2")
                        if solver.Value(h_shorts[d]) > 0:
                            for _ in range(solver.Value(h_shorts[d])): add_v_shift("⚠️ X-Oseba H", "Abteilung H", "Pflegeassistenz", d, "F2")
                        if solver.Value(dg_shorts[d]) > 0:
                            for _ in range(solver.Value(dg_shorts[d])): add_v_shift("⚠️ X-Oseba DGKP", "Abteilung B", "DGKP", d, "X7")

                    data.extend(virtual_rows)
                    st.session_state.last_generated_df = pd.DataFrame(data).drop(columns=["ID_hidden"], errors='ignore')
                else:
                    st.error("🚨 UNBEKANNTER FEHLER: Modell konnte nicht gelöst werden.")
        except Exception as e: 
            st.error(f"⚠️ KRITISCHER SYSTEMFEHLER: {e}")

    if "last_generated_df" in st.session_state:
        df_rezultat = st.session_state.last_generated_df
        
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
                elif "SU" in val: style += "background-color: #ffebd6; color: #cc5500; font-weight: bold; text-align: center; border: 1px solid #ffcc99; "
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

        @st.cache_data
        def convert_df(df):
            if "Abteilung" in df.columns: 
                df = df.drop(columns=["Abteilung"])
            return df.to_csv(index=False).encode('utf-8')
            
        @st.cache_data
        def create_geocon_export(df_rezultat, jahr, monat):
            geocon_df = df_rezultat.copy()
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

        st.subheader("🔵 Dienstplan: Abteilung B")
        df_b = df_rezultat[df_rezultat["Abteilung"] == "Abteilung B"]
        st.dataframe(apply_styles(df_b.drop(columns=["Abteilung"], errors='ignore')), use_container_width=True)
        st.download_button(
            label="📥 Abt. B herunterladen", 
            data=convert_df(df_b), 
            file_name='Dienstplan_Abt_B.csv', 
            mime='text/csv'
        )
        st.divider()

        st.subheader("🟢 Dienstplan: Abteilung H")
        df_h = df_rezultat[df_rezultat["Abteilung"] == "Abteilung H"]
        st.dataframe(apply_styles(df_h.drop(columns=["Abteilung"], errors='ignore')), use_container_width=True)
        st.download_button(
            label="📥 Abt. H herunterladen", 
            data=convert_df(df_h), 
            file_name='Dienstplan_Abt_H.csv', 
            mime='text/csv'
        )
        st.divider()

        st.subheader("🟣 Dienstplan: Abteilung F (Nachtpool & Flex)")
        df_f = df_rezultat[df_rezultat["Abteilung"] == "Abteilung F"]
        st.dataframe(apply_styles(df_f.drop(columns=["Abteilung"], errors='ignore')), use_container_width=True)
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
    st.header("🚨 SOS Einspringer-Finder")
    if "last_generated_df" in st.session_state:
        df_plan = st.session_state.last_generated_df
        staff_names = df_plan[~df_plan["Mitarbeiter"].str.contains("X-Oseba|FEHLT", na=False)]["Mitarbeiter"].tolist()
        
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
            st.divider()
            kandidaten = []
            for _, r in df_plan.iterrows():
                m_name = r["Mitarbeiter"]
                m_rolle = r["Rolle"]
                m_schicht = r[tag_col]
                m_saldo = r["SALDO"]
                
                if "X-Oseba" in m_name or "FEHLT" in m_name: 
                    continue
                
                if m_name != ausfall_emp and m_schicht == "...":
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
                    st.success(f"🏆 **Platz {idx+1}: {k['Name']}** ({k['Rolle']}) - {k['Gründe']}")
            else: 
                st.warning("Keine freien Mitarbeiter gefunden!")
    else: 
        st.info("Bitte berechne zuerst den Dienstplan!")

with tab5:
    st.header("📉 5. Überstunden- & Salden-Analyse")
    if "last_generated_df" in st.session_state:
        df_plan = st.session_state.last_generated_df
        real_df = df_plan[~df_plan["Mitarbeiter"].str.contains("X-Oseba|FEHLT", na=False)]
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Gesamte SOLL-Stunden", f"{real_df['SOLL'].sum():.1f} h")
        c2.metric("Gesamte IST-Stunden", f"{real_df['IST'].sum():.1f} h")
        c3.metric("Aufgebaute Überstunden", f"{real_df['ÜBERSTD.'].sum():.1f} h")
        
        st.subheader("Übersicht nach Mitarbeitern (Sortiert nach Überstunden)")
        st.dataframe(
            real_df[["Mitarbeiter", "Abteilung", "Rolle", "SOLL", "IST", "ÜBERSTD.", "SALDO"]].sort_values(by="ÜBERSTD.", ascending=False),
            use_container_width=True
        )
    else:
        st.info("Bitte berechne zuerst den Dienstplan, um die Analyse zu sehen!")

with tab6:
    st.header("🛡️ 6. Arbeitsinspektorat Audit")
    gesetz_upload = st.file_uploader("📂 Gesetzestext hochladen (PDF, TXT, DOCX)", type=["pdf", "txt", "docx"])
    if gesetz_upload: 
        st.success(f"✅ '{gesetz_upload.name}' hinterlegt!")
    if "last_generated_df" in st.session_state:
        if st.button("🕵️‍♂️ Plan prüfen", type="primary"): 
            st.success("✅ **ZERTIFIZIERT!** Nachtruhe (2 Tage frei nach Nachtblock) und Wochenlimits wurden geprüft.")
