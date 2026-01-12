import streamlit as st
from streamlit_autorefresh import st_autorefresh
import paho.mqtt.client as mqtt
import json
import threading
from datetime import datetime
from collections import deque
import pandas as pd
import altair as alt
import os
from uuid import uuid4

# ==========================
# CONFIG MQTT
# ==========================
MQTT_BROKER = "51.103.239.173"
MQTT_PORT   = 1883

TOPIC_DATA = "capteur/data"            # ESP32 -> JSON
TOPIC_CMD  = "noeud/operateur/cmd"     # Streamlit -> commandes binôme

CMD_LED_ON  = "LED_RED_ON"
CMD_LED_OFF = "LED_RED_OFF"

# ==========================
# LOGO (optionnel)
# ==========================
LOGO_FILENAME = "LOGO_EPHEC_HE.png"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, LOGO_FILENAME)

# ==========================
# ETAT GLOBAL THREAD-SAFE
# ==========================
LOCK = threading.Lock()

LAST = {
    "temperature": None,
    "humidity": None,
    "seuil": None,          # clé ESP32 = "seuil"
    "flame": None,
    "flameHande": None,
    "alarm": None,
    "last_update": None,
}

HISTORY = deque(maxlen=400)

# ==========================
# MQTT CALLBACKS
# ==========================
def on_connect(client, userdata, flags, rc):
    # IMPORTANT : ne touche pas session_state ici
    if rc == 0:
        client.subscribe(TOPIC_DATA)
        print("✅ MQTT connecté, abonné à", TOPIC_DATA)
    else:
        print("❌ MQTT erreur connexion rc =", rc)

def on_disconnect(client, userdata, rc):
    print("🔌 MQTT déconnecté rc =", rc)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print("JSON invalide :", e)
        return

    now = datetime.now()
    with LOCK:
        LAST["temperature"] = payload.get("temperature")
        LAST["humidity"]    = payload.get("humidity")
        LAST["seuil"]       = payload.get("seuil")          # ✅
        LAST["flame"]       = payload.get("flame")
        LAST["flameHande"]  = payload.get("flameHande")
        LAST["alarm"]       = payload.get("alarm")
        LAST["last_update"] = now

        HISTORY.append({
            "time": now,
            "temperature": LAST["temperature"],
            "humidity": LAST["humidity"],
            "seuil": LAST["seuil"],
            "flame": LAST["flame"],
        })

# ==========================
# MQTT CLIENT (1 seule fois / session)
# ==========================
def get_mqtt_client():
    if "mqtt_client" not in st.session_state:
        cid = f"streamlit_{uuid4().hex}"  # ✅ unique => plus de conflit
        client = mqtt.Client(client_id=cid, protocol=mqtt.MQTTv311)

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message

        # Reconnexion automatique douce
        client.reconnect_delay_set(min_delay=1, max_delay=20)

        client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()

        st.session_state["mqtt_client"] = client

    return st.session_state["mqtt_client"]

def mqtt_publish(cmd: str):
    client = get_mqtt_client()
    client.publish(TOPIC_CMD, cmd, qos=0, retain=False)

# ==========================
# UI helpers
# ==========================
def metric_value(v, fmt="{:.1f}"):
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        return fmt.format(v)
    return str(v)

def line_chart(df: pd.DataFrame, y: str, title: str, ytitle: str):
    return (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("time:T", title="Temps"),
            y=alt.Y(f"{y}:Q", title=ytitle),
            tooltip=["time:T", alt.Tooltip(f"{y}:Q")]
        )
        .properties(height=260, title=title)
    )

# ==========================
# MAIN
# ==========================
def main():
    st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")

    # démarre MQTT (stable)
    get_mqtt_client()

    # ✅ Auto-refresh UI sans casser MQTT
    st_autorefresh(interval=1500, key="ui_refresh")  # 1.5s

    # Header
    col_logo, col_title = st.columns([1, 6])
    with col_logo:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=110)
        else:
            st.write("EPHEC")
    with col_title:
        st.title("Gestion Intelligente Température & Sécurité – IoT")

    # snapshot
    with LOCK:
        last = dict(LAST)
        hist = list(HISTORY)

    # statut "connecté" basé sur données récentes
    fresh = False
    age_s = None
    if last["last_update"] is not None:
        age_s = (datetime.now() - last["last_update"]).total_seconds()
        fresh = age_s <= 6.0

    if fresh:
        st.success("État MQTT : ✅ Données reçues (OK)")
    else:
        st.error("État MQTT : 🔴 Déconnecté / aucune donnée récente")

    if age_s is not None:
        st.caption(f"Dernière donnée reçue il y a ~{age_s:.1f} s")

    st.markdown("---")

    # Cartes
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.subheader("🌡️ Température")
        st.metric("Temp (°C)", metric_value(last["temperature"]))
    with c2:
        st.subheader("💧 Humidité")
        st.metric("Hum (%)", metric_value(last["humidity"], "{:.0f}"))
    with c3:
        st.subheader("📦 Seuil (ESP32)")
        st.metric("Seuil (°C)", metric_value(last["seuil"]))
    with c4:
        st.subheader("🚨 Alarme")
        st.write("ACTIVE" if last["alarm"] else "inactive")

    st.markdown("---")

    # Commandes
    st.subheader(f"🎛️ Commandes vers la binôme (topic: {TOPIC_CMD})")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("🔴 LED ROUGE ON", use_container_width=True):
            mqtt_publish(CMD_LED_ON)
            st.toast("Commande envoyée", icon="📡")
    with b2:
        if st.button("⚫ LED ROUGE OFF", use_container_width=True):
            mqtt_publish(CMD_LED_OFF)
            st.toast("Commande envoyée", icon="📡")

    st.markdown("---")

    # Courbes
    st.subheader("📈 Graphiques en temps réel (courbes)")
    if len(hist) == 0:
        st.info("En attente de données sur capteur/data…")
    else:
        df = pd.DataFrame(hist).dropna(subset=["time"]).tail(200)

        g1, g2 = st.columns(2)
        with g1:
            st.altair_chart(line_chart(df, "temperature", "Température", "°C"), use_container_width=True)
        with g2:
            st.altair_chart(line_chart(df, "humidity", "Humidité", "%"), use_container_width=True)

        g3, g4 = st.columns(2)
        with g3:
            st.altair_chart(line_chart(df, "seuil", "Seuil", "°C"), use_container_width=True)
        with g4:
            st.altair_chart(line_chart(df, "flame", "Flamme", "0/1"), use_container_width=True)

    st.markdown("---")
    st.subheader("🩺 Diagnostic")
    st.json(last)

if __name__ == "__main__":
    main()
