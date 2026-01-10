import streamlit as st
import paho.mqtt.client as mqtt
import json
import threading
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

TOPIC_DATA = "capteur/data"           # JSON envoyé par ESP32 (capteurs)
TOPIC_CMD  = "noeud/operateur/cmd"    # commandes vers ta binôme (LED etc.)

# ==========================
# LOGO (optionnel)
# ==========================
LOGO_FILENAME = "LOGO_EPHEC_HE.png"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, LOGO_FILENAME)

# ==========================
# ETAT GLOBAL
# ==========================
mqtt_client = None
mqtt_thread = None
mqtt_started = False
mqtt_connected = False

last_data = {
    "temperature": None,
    "humidity": None,
    "seuil": None,        # ✅ ton seuil est ici
    "flame": None,
    "pot": None,
    "alarm": None,
    "last_update": None,
}

data_history = []  # list of dicts: time, temperature, humidity, flame, pot, seuil


# ==========================
# OUTILS
# ==========================
def pick(payload, *keys, default=None):
    """Prend la première clé existante et non None dans payload."""
    for k in keys:
        if k in payload and payload[k] is not None:
            return payload[k]
    return default


def mqtt_publish(text: str) -> bool:
    """Publie une commande texte sur TOPIC_CMD."""
    global mqtt_client
    if mqtt_client is None:
        return False
    try:
        mqtt_client.publish(TOPIC_CMD, text)
        return True
    except Exception:
        return False


def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()


# ==========================
# CALLBACKS MQTT
# ==========================
def on_connect(client, userdata, flags, rc):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        client.subscribe(TOPIC_DATA)
        print("✅ MQTT connecté & abonné à", TOPIC_DATA)
    else:
        mqtt_connected = False
        print("❌ MQTT erreur connexion rc =", rc)


def on_disconnect(client, userdata, rc):
    global mqtt_connected
    mqtt_connected = False
    print("🔌 MQTT déconnecté rc =", rc)


def on_message(client, userdata, msg):
    global last_data, data_history
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print("❌ JSON invalide:", e)
        return

    # ✅ MAP DES CHAMPS (avec ton "seuil")
    last_data["temperature"] = pick(payload, "temperature", "temp", "T")
    last_data["humidity"]    = pick(payload, "humidity", "hum", "H")
    last_data["seuil"]       = pick(payload, "seuil", "threshold", "setpoint")  # ✅
    last_data["flame"]       = pick(payload, "flame", "ir", "fire")
    last_data["pot"]         = pick(payload, "pot", "potValue", "adc")
    last_data["alarm"]       = pick(payload, "alarm", "alarme", default=False)
    last_data["last_update"] = datetime.now()

    data_history.append({
        "time": last_data["last_update"],
        "temperature": last_data["temperature"],
        "humidity": last_data["humidity"],
        "seuil": last_data["seuil"],
        "flame": last_data["flame"],
        "pot": last_data["pot"],
    })

    # option : garder l'historique limité
    if len(data_history) > 500:
        data_history = data_history[-500:]


# ==========================
# DÉMARRAGE MQTT (THREAD)
# ==========================
def start_mqtt():
    global mqtt_client, mqtt_thread, mqtt_started, mqtt_connected

    if mqtt_started:
        return

    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message

    def _loop():
        while True:
            try:
                if not mqtt_connected:
                    print("🔁 Connexion MQTT...")
                    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
                mqtt_client.loop_forever()
            except Exception as e:
                print("⚠️ Boucle MQTT erreur:", e)
                mqtt_connected = False
                time.sleep(3)

    mqtt_thread = threading.Thread(target=_loop, daemon=True)
    mqtt_thread.start()
    mqtt_started = True


# ==========================
# UI
# ==========================
def build_dashboard():
    st.set_page_config(
        page_title="Dashboard IoT - Température & Sécurité",
        layout="wide",
    )

    # CSS léger
    st.markdown(
        """
        <style>
        .stApp {
            background: radial-gradient(circle at top left, #f5f0ff 0, #dbe2ff 35%, #c8d9ff 65%, #b8d3ff 100%);
            color: #0f172a;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # Titre + logo
    col_logo, col_title = st.columns([1, 5])
    with col_logo:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=120)
        else:
            st.write("EPHEC")
    with col_title:
        st.markdown("## Gestion Intelligente Température & Sécurité – IoT")

    # Etat MQTT
    if mqtt_connected:
        st.success("État MQTT : ✅ Connecté au broker")
    else:
        st.error("État MQTT : 🔴 Déconnecté du broker")

    st.divider()

    # Cartes principales
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.subheader("🌡️ Température")
        if last_data["temperature"] is not None:
            st.metric("Temp (°C)", f"{float(last_data['temperature']):.1f}")
        else:
            st.write("—")

    with c2:
        st.subheader("💧 Humidité")
        if last_data["humidity"] is not None:
            st.metric("Hum (%)", f"{float(last_data['humidity']):.1f}")
        else:
            st.write("—")

    with c3:
        st.subheader("📦 Seuil (ESP32)")
        if last_data["seuil"] is not None:
            st.metric("Seuil", f"{float(last_data['seuil']):.1f}")
        else:
            st.write("Seuil : — (non reçu)")

    with c4:
        st.subheader("🕹️ Potentiomètre")
        if last_data["pot"] is not None:
            st.metric("POT (brut)", f"{int(last_data['pot'])}")
        else:
            st.write("—")

    st.divider()

    # Flamme + Alarme
    c5, c6 = st.columns(2)

    with c5:
        st.subheader("🔥 IR / Flamme")
        flame = last_data["flame"]
        if flame is None:
            st.info("En attente (flame=None)")
        elif int(flame) == 1:
            st.error("🔥 Feu détecté (flame=1)")
        else:
            st.success("✅ Aucun feu (flame=0)")

    with c6:
        st.subheader("🚨 État de l'alarme")
        if bool(last_data["alarm"]):
            st.error("Alarme ACTIVE")
        else:
            st.success("Alarme inactive")

    st.divider()

    # ✅ BOUTONS COMMANDE BINÔME (LED ROUGE)
    st.subheader("🎛️ Commandes vers la binôme (topic: noeud/operateur/cmd)")
    b1, b2, b3 = st.columns([1, 1, 2])

    with b1:
        if st.button("🔴 LED ROUGE ON", use_container_width=True):
            ok = mqtt_publish("LED_RED_ON")
            st.success("Commande envoyée ✅" if ok else "Échec envoi ❌")

    with b2:
        if st.button("⚫ LED ROUGE OFF", use_container_width=True):
            ok = mqtt_publish("LED_RED_OFF")
            st.success("Commande envoyée ✅" if ok else "Échec envoi ❌")

    with b3:
        st.info("⚠️ Ta binôme doit coder son ESP32 pour écouter ce topic et exécuter LED_RED_ON / LED_RED_OFF.")

    st.divider()

    # ✅ Graphiques en courbes (pas barres)
    st.subheader("📈 Graphiques en temps réel (courbes)")

    if len(data_history) == 0:
        st.info("En attente de données…")
        return

    df = pd.DataFrame(data_history).dropna(subset=["time"]).tail(200)

    # convertir en numeric si possible
    for col in ["temperature", "humidity", "seuil", "flame", "pot"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    g1, g2 = st.columns(2)

    with g1:
        chart_temp = (
            alt.Chart(df)
            .mark_line(point=True)
            .encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y("temperature:Q", title="Temp (°C)"),
                tooltip=["time:T", "temperature:Q"],
            )
            .properties(height=260, title="Température")
        )
        st.altair_chart(chart_temp, use_container_width=True)

    with g2:
        chart_hum = (
            alt.Chart(df)
            .mark_line(point=True)
            .encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y("humidity:Q", title="Humidité (%)"),
                tooltip=["time:T", "humidity:Q"],
            )
            .properties(height=260, title="Humidité")
        )
        st.altair_chart(chart_hum, use_container_width=True)

    g3, g4 = st.columns(2)

    with g3:
        chart_seuil = (
            alt.Chart(df)
            .mark_line(point=True)
            .encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y("seuil:Q", title="Seuil"),
                tooltip=["time:T", "seuil:Q"],
            )
            .properties(height=260, title="Seuil")
        )
        st.altair_chart(chart_seuil, use_container_width=True)

    with g4:
        chart_flame = (
            alt.Chart(df)
            .mark_line(point=True)
            .encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y("flame:Q", title="Flamme (0/1)"),
                tooltip=["time:T", "flame:Q"],
            )
            .properties(height=260, title="IR / Flamme")
        )
        st.altair_chart(chart_flame, use_container_width=True)

    st.divider()

    # Diagnostic
    st.subheader("🩺 Diagnostic")
    st.write("Dernier message reçu :")
    st.json(last_data)

    if last_data["last_update"] is not None:
        st.caption(f"Dernière mise à jour : {last_data['last_update']}")


def main():
    start_mqtt()
    build_dashboard()
    time.sleep(1)
    safe_rerun()


if __name__ == "__main__":
    main()
