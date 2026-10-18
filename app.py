with st.form("team_editor_form"):
        edited_data = st.data_editor(
            st.session_state.staff_df_v31, num_rows="dynamic", key="tabelle_mitarbeiter_v31",
            column_config={
                "ID": None,
                "Abteilung": st.column_config.SelectboxColumn("Abteilung", options=["Abteilung B", "Abteilung H", "Abteilung F"]),
                "Rolle": st.column_config.SelectboxColumn("Rolle", options=["Leitung", "DGKP", "Pflegeassistenz", "Heimhelfer"]),
                "Qualifikation": st.column_config.SelectboxColumn("Zusatzqualifikation", options=["Keine", "Wundmanager", "Praxisanleiter", "Palliativ"]),
                "Wochenstd": st.column_config.NumberColumn("Wochenstd.", min_value=1.0, max_value=60.0, default=37.0, step=0.5),
                "Prozent": st.column_config.NumberColumn("Anst. (%)", disabled=True), 
                "Spezialdienst": st.column_config.SelectboxColumn("Spezialdienst", options=["Ohne", "Nur WE und Feiertage", "F2", "F7", "X7", "X6", "X4", "JED", "MS", "SM"]),
                "URL_Gesamt": st.column_config.NumberColumn("Urlaub Gesamt", min_value=0.0, max_value=50.0, default=25.0),
                "URL_Rest": st.column_config.NumberColumn("Urlaub Rest", min_value=0.0, max_value=50.0, default=25.0)
            }, use_container_width=True, height=500
        )
        if st.form_submit_button("💾 Spremembe ekipe potrdi", type="primary"):
            # VAROVALKA: Prazna polja (None) pretvorimo nazaj v številke preden računamo
            edited_data["Wochenstd"] = pd.to_numeric(edited_data["Wochenstd"], errors='coerce').fillna(37.0)
            edited_data["Prozent"] = (edited_data["Wochenstd"] / 37.0) * 100
            edited_data["Prozent"] = edited_data["Prozent"].round(1)
            
            edited_data["URL_Gesamt"] = pd.to_numeric(edited_data["URL_Gesamt"], errors='coerce').fillna(25.0)
            edited_data["URL_Rest"] = pd.to_numeric(edited_data["URL_Rest"], errors='coerce').fillna(25.0)
            
            # Sedaj lahko varno izračuna minimum, ker ni več praznih polj
            edited_data["URL_Rest"] = edited_data.apply(lambda row: min(row["URL_Gesamt"], row["URL_Rest"]), axis=1)
            
            st.session_state.staff_df_v31 = edited_data
            edited_data.to_csv("team_data.csv", index=False)
            st.success("✅ Teamdaten erfolgreich gespeichert!")
            st.rerun()
