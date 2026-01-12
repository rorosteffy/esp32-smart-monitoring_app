import streamlit as st
import paho.mqtt.client as mqtt
import json
import time
import pandas as pd
import altair as alt
from datetime import datetime
import os

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
# INIT SESSION_STATE
# ==========================
if "mqtt_client" not in st.session_state:
    st.session_state.mqtt_client = None

if "mqtt_connected" not in st.session_state:
    st.session_state.mqtt_connected = False

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
    st.session_state.data_history = []


# ==========================
# CALLBACKS MQTT
# ==========================

def on_connect(client, userdata, flags, rc):
    print("on_connect rc =", rc)
    if rc == 0:
        st.session_state.mqtt_connected = True
        print("✅ Connecté au broker MQTT, abonné à", TOPIC_DATA)
        client.subscribe(TOPIC_DATA)
    else:
        st.session_state.mqtt_connected = False
        print("❌ Erreur de connexion MQTT")


def on_disconnect(client, userdata, rc):
    st.session_state.mqtt_connected = False
    print("🔌 Déconnecté du broker MQTT (rc =", rc, ")")


def on_message(client, userdata, msg):
    """Réception des messages JSON de l’ESP32."""
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        print("MQTT message reçu sur", msg.topic, ":", payload)
    except Exception as e:
        print("JSON invalide :", e)
        return

    d = st.session_state.last_data

    # Mise à jour du dernier état
    d["temperature"] = payload.get("temperature")
    d["humidity"]    = payload.get("humidity")
    d["tempSeuil"]   = payload.get("tempSeuil")
    d["humSeuil"]    = payload.get("humSeuil")
    d["flame"]       = payload.get("flame")
    d["flameRaw"]    = payload.get("flameRaw")
    d["pot"]         = payload.get("pot")
    d["seuilPot"]    = payload.get("seuilPot")
    d["alarm"]       = payload.get("alarm")
    d["last_update"] = datetime.now()

    # Historique pour les graphes
    st.session_state.data_history.append({
        "time": d["last_update"],
        "temperature": d["temperature"],
        "humidity": d["humidity"],
        "flame": d["flame"],
        "pot": d["pot"],
    })

    # Sauvegarde CSV automatique (optionnel)
    try:
        with open("historique_mesures.csv", "a", encoding="utf-8") as f:
            line = (
                f"{d['last_update']};"
                f"{d['temperature']};"
                f"{d['humidity']};"
                f"{d['flame']};"
                f"{d['pot']}\n"
            )
            f.write(line)
    except Exception as e:
        print("Erreur écriture CSV :", e)


# ==========================
# DÉMARRAGE CLIENT MQTT
# ==========================

def ensure_mqtt_client():
    """Crée et démarre le client MQTT UNE SEULE FOIS."""
    if st.session_state.mqtt_client is not None:
        return

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    try:
        print("🔁 Tentative de connexion au broker MQTT...")
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()  # thread réseau interne à paho
    except Exception as e:
        print("⚠️ Erreur de connexion MQTT :", e)

    st.session_state.mqtt_client = client


# ==========================
# UI STREAMLIT
# ==========================

def build_dashboard():
    st.set_page_config(
        page_title="Gestion Intelligente Température & Sécurité – IoT",
        layout="wide",
    )

    # --------- CSS ---------
    st.markdown(
        """
        <style>
        .stApp {
            background: radial-gradient(circle at top left, #f5f0ff 0, #dbe2ff 35%, #c8d9ff 65%, #b8d3ff 100%);
            color: #0f172a;
        }
        h1 {
            color: #0f172a;
            font-weight: 800;
        }
        h2, h3 {
            color: #111827;
            font-weight: 700;
        }
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
    if st.session_state.mqtt_connected:
        st.success("État MQTT : ✅ Connecté au broker MQTT")
    else:
        st.error("État MQTT : 🔴 Déconnecté du broker MQTT")

    st.markdown("---")

    d = st.session_state.last_data

    # --------- 4 cartes principales ---------
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.subheader("🌡️ Température")
        if d["temperature"] is not None:
            st.metric("Température (°C)", f"{d['temperature']:.1f}")
        else:
            st.write("—")

    with c2:
        st.subheader("💧 Humidité")
        if d["humidity"] is not None:
            st.metric("Humidité (%)", f"{d['humidity']:.1f}")
        else:
            st.write("—")

    with c3:
        st.subheader("📦 Température du seuil (ESP32)")
        if d["seuilPot"] is not None:
            st.metric("Seuil T (°C)", f"{d['seuilPot']:.1f}")
        else:
            st.write("Seuil T consigne : Aucun °C")

    with c4:
        st.subheader("🕹️ Potentiomètre → Seuil")
        if d["pot"] is not None:
            st.metric("Valeur brute POT", f"{d['pot']}")
        else:
            st.write("Valeur brute POT : Aucun")

    st.markdown("---")

    # --------- IR / Flamme + État alarme ---------
    c5, c6 = st.columns(2)

    with c5:
        st.subheader("🔥 IR / Flamme")
        flame = d["flame"]
        if flame is None:
            st.info("En attente de données (flame = None)...")
        elif flame == 1:
            st.error("🔥 Feu détecté (flame = 1)")
        else:
            st.success("✅ Aucun feu détecté (flame = 0)")

    with c6:
        st.subheader("🚨 État de l'alarme")
        if d["alarm"]:
            st.error("Alarme ACTIVE")
        else:
            st.success("Alarme inactive")

    st.markdown("---")

    # --------- Graphiques en temps réel (barres/tiges) ---------
    st.subheader("📊 Graphiques en temps réel")

    hist = st.session_state.data_history

    if len(hist) == 0:
        st.info("En attente de données temps réel des capteurs…")
    else:
        df = pd.DataFrame(hist).tail(100)  # 100 derniers points

        col_g1, col_g2 = st.columns(2)

        # Température (barres)
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

        # Humidité (barres)
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

        # Flamme (barres)
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

        # Potentiomètre (barres)
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
        st.json(d)

    with col_d2:
        st.write("**Outils :**")
        if st.button("🗑️ Réinitialiser l’historique"):
            st.session_state.data_history.clear()
            st.success("Historique effacé (la prochaine mesure remplira à nouveau les graphiques).")

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

    if d["last_update"] is not None:
        st.caption(f"Dernière mise à jour : {d['last_update']}")
    else:
        st.caption("Aucune donnée reçue pour l’instant.")


# ==========================
# MAIN
# ==========================

def main():
    ensure_mqtt_client()
    build_dashboard()

    # Rafraîchissement automatique toutes les 1 s
    time.sleep(1)
    st.experimental_rerun()


if __name__ == "__main__":
    main()
