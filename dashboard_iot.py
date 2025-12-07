import streamlit as st
import paho.mqtt.client as mqtt
import json
import time
import pandas as pd
import altair as alt
from datetime import datetime
import os
from streamlit_autorefresh import st_autorefresh

# ==========================
# CONFIG MQTT
# ==========================
MQTT_BROKER = "51.103.239.173"
MQTT_PORT = 1883
TOPIC_DATA = "capteur/data"   # JSON global envoyé par l’ESP32

# ==========================
# FICHIER LOGO
# ==========================
LOGO_FILENAME = "LOGO_EPHEC_HE.png"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, LOGO_FILENAME)

# ==========================
# INITIALISATION SESSION_STATE
# ==========================

if "last_data" not in st.session_state:
    st.session_state.last_data = {
        "temperature": None,
        "humidity": None,
        "tempSeuil": None,
        "humSeuil": None,
        "flame": None,
        "flameRaw": None,
        "pot": None,
        "seuilPot": None,
        "alarm": None,
        "last_update": None,
    }

if "data_history" not in st.session_state:
    # Chaque entrée : {"time": datetime, "temperature":..., "humidity":..., "flame":..., "pot":...}
    st.session_state.data_history = []


# ==========================
# FONCTION : POLLING MQTT (CLOUD FRIENDLY)
# ==========================

def poll_mqtt():
    """
    Se connecte au broker, écoute brièvement, et retourne :
    - le dernier message reçu (texte JSON) ou None
    - un booléen indiquant si la connexion MQTT a réussi.
    Pas de thread, pas de boucle infinie → compatible Streamlit Cloud.
    """
    client = mqtt.Client()
    messages = []
    connected = False

    def _on_connect(client, userdata, flags, rc):
        nonlocal connected
        print("poll_mqtt on_connect rc =", rc)
        if rc == 0:
            connected = True

    def _on_message(client, userdata, msg):
        try:
            messages.append(msg.payload.decode())
        except Exception:
            pass

    client.on_connect = _on_connect
    client.on_message = _on_message

    try:
        rc = client.connect(MQTT_BROKER, MQTT_PORT, 60)
        if rc == 0:
            connected = True
        client.subscribe(TOPIC_DATA)
        client.loop_start()
        time.sleep(1.0)  # on laisse 1 s pour recevoir au moins 1 message
        client.loop_stop()
        client.disconnect()
    except Exception as e:
        print("Erreur MQTT (poll) :", e)
        return None, False

    last_msg = messages[-1] if messages else None
    return last_msg, connected


# ==========================
# MISE À JOUR DES DONNÉES À PARTIR DU JSON
# ==========================

def update_from_payload(payload_dict):
    """
    Met à jour st.session_state.last_data et data_history
    à partir d'un dict Python (payload JSON décodé).
    """
    last_data = st.session_state.last_data
    data_history = st.session_state.data_history

    last_data["temperature"] = payload_dict.get("temperature")
    last_data["humidity"] = payload_dict.get("humidity")
    last_data["tempSeuil"] = payload_dict.get("tempSeuil")
    last_data["humSeuil"] = payload_dict.get("humSeuil")
    last_data["flame"] = payload_dict.get("flame")
    last_data["flameRaw"] = payload_dict.get("flameRaw")
    last_data["pot"] = payload_dict.get("pot")
    last_data["seuilPot"] = payload_dict.get("seuilPot")
    last_data["alarm"] = payload_dict.get("alarm")
    last_data["last_update"] = datetime.now()

    # Historique pour les graphes
    data_history.append({
        "time": last_data["last_update"],
        "temperature": last_data["temperature"],
        "humidity": last_data["humidity"],
        "flame": last_data["flame"],
        "pot": last_data["pot"],
    })

    # Sauvegarde CSV automatique (optionnel)
    try:
        with open("historique_mesures.csv", "a", encoding="utf-8") as f:
            line = (
                f"{last_data['last_update']};"
                f"{last_data['temperature']};"
                f"{last_data['humidity']};"
                f"{last_data['flame']};"
                f"{last_data['pot']}\n"
            )
            f.write(line)
    except Exception as e:
        print("Erreur écriture CSV :", e)


# ==========================
# UI STREAMLIT
# ==========================

def build_dashboard(mqtt_ok: bool):
    last_data = st.session_state.last_data
    data_history = st.session_state.data_history

    st.set_page_config(
        page_title="Gestion Intelligente Température & Sécurité – IoT",
        layout="wide",
    )

    # Auto-refresh toutes les 2 secondes
    st_autorefresh(interval=2000, key="mqtt_refresh")

    # --------- CSS : fond, cartes, logo clignotant ---------
    st.markdown(
        """
        <style>
        /* Fond global plus clair */
        .stApp {
            background: radial-gradient(circle at top left, #f5f0ff 0, #dbe2ff 35%, #c8d9ff 65%, #b8d3ff 100%);
            color: #0f172a;
        }

        /* Cartes / blocs Streamlit */
        .stAlert, .stMetric, .st-emotion-cache-16idsys, .st-emotion-cache-1r6slb0 {
            border-radius: 12px !important;
            padding: 0.75rem 1.25rem !important;
        }

        /* Bandeau MQTT */
        .st-emotion-cache-1avcm0n {
            border-radius: 14px !important;
        }

        /* Titre principal */
        h1 {
            color: #0f172a;
            font-weight: 800;
        }

        /* Sous-titres */
        h2, h3 {
            color: #111827;
            font-weight: 700;
        }

        /* Logo EPHEC clignotant léger */
        .ephec-logo {
            animation: pulse-logo 2s infinite;
        }

        @keyframes pulse-logo {
            0%   { opacity: 0.35; transform: translateY(0px); }
            50%  { opacity: 1.0;  transform: translateY(-2px); }
            100% { opacity: 0.35; transform: translateY(0px); }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # --------- Bandeau titre + logo EPHEC ---------
    col_logo, col_title = st.columns([1, 5])

    with col_logo:
        try:
            if os.path.exists(LOGO_PATH):
                st.image(LOGO_PATH, width=130, caption=None, output_format="PNG")
            else:
                st.image(LOGO_FILENAME, width=130, caption=None, output_format="PNG")
            st.markdown("<div class='ephec-logo'></div>", unsafe_allow_html=True)
        except Exception:
            st.markdown("**EPHEC**")

    with col_title:
        st.markdown(
            "<h1 style='margin-bottom:0.2em;'>Gestion Intelligente Température & Sécurité – IoT</h1>",
            unsafe_allow_html=True,
        )

    # --------- État MQTT ---------
    if mqtt_ok:
        st.success("État MQTT : ✅ Connecté au broker MQTT")
    else:
        st.error("État MQTT : 🔴 Déconnecté du broker MQTT")

    st.markdown("---")

    # --------- 4 cartes principales ---------
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.subheader("🌡️ Température")
        if last_data["temperature"] is not None:
            st.metric("Température (°C)", f"{last_data['temperature']:.1f}")
        else:
            st.write("—")

    with c2:
        st.subheader("💧 Humidité")
        if last_data["humidity"] is not None:
            st.metric("Humidité (%)", f"{last_data['humidity']:.1f}")
        else:
            st.write("—")

    with c3:
        st.subheader("📦 Température du seuil (ESP32)")
        if last_data["seuilPot"] is not None:
            st.metric("Seuil T (°C)", f"{last_data['seuilPot']:.1f}")
        else:
            st.write("Seuil T consigne : Aucun °C")

    with c4:
        st.subheader("🕹️ Potentiomètre → Seuil")
        if last_data["pot"] is not None:
            st.metric("Valeur brute POT", f"{last_data['pot']}")
        else:
            st.write("Valeur brute POT : Aucun")

    st.markdown("---")

    # --------- IR / Flamme + État alarme ---------
    c5, c6 = st.columns(2)

    with c5:
        st.subheader("🔥 IR / Flamme")
        flame = last_data["flame"]
        if flame is None:
            st.info("En attente de données (flame = None)...")
        elif flame == 1:
            st.error("🔥 Feu détecté (flame = 1)")
        else:
            st.success("✅ Aucun feu détecté (flame = 0)")

    with c6:
        st.subheader("🚨 État de l'alarme")
        if last_data["alarm"]:
            st.error("Alarme ACTIVE")
        else:
            st.success("Alarme inactive")

    st.markdown("---")

    # --------- Graphiques en temps réel (barres) ---------
    st.subheader("📊 Graphiques en temps réel")

    if len(data_history) == 0:
        st.info("En attente de données temps réel des capteurs…")
    else:
        df = pd.DataFrame(data_history)

        # On limite aux 100 derniers points pour que les barres restent lisibles
        df = df.tail(100)

        col_g1, col_g2 = st.columns(2)

        # Température
        with col_g1:
            temp_chart = (
                alt.Chart(df)
                .mark_bar()
                .encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("temperature:Q", title="Température (°C)"),
                    tooltip=["time:T", "temperature:Q"],
                )
                .properties(height=260, title="Température (barres)")
            )
            st.altair_chart(temp_chart, use_container_width=True)

        # Humidité
        with col_g2:
            hum_chart = (
                alt.Chart(df)
                .mark_bar()
                .encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("humidity:Q", title="Humidité (%)"),
                    tooltip=["time:T", "humidity:Q"],
                )
                .properties(height=260, title="Humidité (barres)")
            )
            st.altair_chart(hum_chart, use_container_width=True)

        col_g3, col_g4 = st.columns(2)

        # Flamme
        with col_g3:
            flame_chart = (
                alt.Chart(df)
                .mark_bar()
                .encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("flame:Q", title="Flamme détectée (0/1)"),
                    tooltip=["time:T", "flame:Q"],
                )
                .properties(height=260, title="IR / Flamme (barres)")
            )
            st.altair_chart(flame_chart, use_container_width=True)

        # Potentiomètre
        with col_g4:
            pot_chart = (
                alt.Chart(df)
                .mark_bar()
                .encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("pot:Q", title="Valeur brute POT"),
                    tooltip=["time:T", "pot:Q"],
                )
                .properties(height=260, title="Potentiomètre (barres)")
            )
            st.altair_chart(pot_chart, use_container_width=True)

    st.markdown("---")

    # --------- Zone diagnostic / JSON ---------
    st.subheader("🩺 Diagnostic du système")

    col_d1, col_d2 = st.columns(2)

    with col_d1:
        st.write("**Dernier message JSON reçu :**")
        st.json(last_data)

    with col_d2:
        st.write("**Outils :**")
        if st.button("🗑️ Réinitialiser l’historique"):
            st.session_state.data_history.clear()
            st.success("Historique effacé (la prochaine mesure remplira à nouveau les graphiques).")

        # Téléchargement CSV (si le fichier existe)
        try:
            with open("historique_mesures.csv", "r", encoding="utf-8") as f:
                csv_content = f.read()
            st.download_button(
                "💾 Télécharger l’historique CSV",
                data=csv_content,
                file_name="historique_mesures.csv",
                mime="text/csv",
            )
        except FileNotFoundError:
            st.info("Aucun fichier CSV encore créé (attends la première mesure).")

    if last_data["last_update"] is not None:
        st.caption(f"Dernière mise à jour : {last_data['last_update']}")
    else:
        st.caption("Aucune donnée reçue pour l’instant.")


# ==========================
# MAIN
# ==========================

def main():
    # 1. Un petit poll MQTT à chaque refresh
    raw, connected = poll_mqtt()
    mqtt_ok = connected

    if raw:
        try:
            payload = json.loads(raw)
            print("MQTT message reçu :", payload)
            update_from_payload(payload)
        except Exception as e:
            print("Erreur JSON :", e)

    # 2. Affichage du dashboard
    build_dashboard(mqtt_ok)


if __name__ == "__main__":
    main()
