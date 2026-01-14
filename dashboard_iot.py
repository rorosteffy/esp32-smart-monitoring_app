import streamlit as st
import paho.mqtt.client as mqtt
import json
import threading
import time
from datetime import datetime
import pandas as pd
import altair as alt

# =========================================================
# CONFIG MQTT (VM MOSQUITTO)
# =========================================================
MQTT_BROKER = "51.103.239.173"
MQTT_PORT = 9001                  # WebSockets
MQTT_TOPIC = "capteur/data"

# =========================================================
# SESSION STATE
# =========================================================
if "mqtt_connected" not in st.session_state:
    st.session_state.mqtt_connected = False

if "last_data" not in st.session_state:
    st.session_state.last_data = {}

if "history" not in st.session_state:
    st.session_state.history = []

if "mqtt_started" not in st.session_state:
    st.session_state.mqtt_started = False

# =========================================================
# MQTT CALLBACKS (COMPATIBLE PAHO v1 + v2)
# =========================================================
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        st.session_state.mqtt_connected = True
        client.subscribe(MQTT_TOPIC)
        print("✅ MQTT connecté")
    else:
        print("❌ MQTT erreur rc =", rc)

def on_disconnect(client, userdata, rc, properties=None):
    st.session_state.mqtt_connected = False
    print("🔌 MQTT déconnecté")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        payload["time"] = datetime.now()
        st.session_state.last_data = payload
        st.session_state.history.append(payload)
        st.session_state.history = st.session_state.history[-200:]
    except Exception as e:
        print("Erreur JSON :", e)

# =========================================================
# START MQTT (THREAD UNIQUE)
# =========================================================
def start_mqtt():
    if st.session_state.mqtt_started:
        return

    client = mqtt.Client(
        transport="websockets",
        protocol=mqtt.MQTTv311
    )

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

    def loop():
        client.loop_forever()

    threading.Thread(target=loop, daemon=True).start()
    st.session_state.mqtt_started = True

# =========================================================
# UI STREAMLIT
# =========================================================
st.set_page_config(
    page_title="Dashboard IoT EPHEC",
    layout="wide"
)

st.title("🌡️ Gestion Intelligente Température & Sécurité – IoT")
st.caption(f"Broker: {MQTT_BROKER} | WebSockets:9001 | Topic: {MQTT_TOPIC}")

start_mqtt()

# ---------------------------------------------------------
# MQTT STATUS
# ---------------------------------------------------------
if st.session_state.mqtt_connected:
    st.success("MQTT connecté")
else:
    st.error("MQTT déconnecté – vérifie port 9001")

st.divider()

# ---------------------------------------------------------
# METRICS
# ---------------------------------------------------------
data = st.session_state.last_data

c1, c2, c3, c4 = st.columns(4)

c1.metric("🌡️ Température (°C)", data.get("temperature", "—"))
c2.metric("💧 Humidité (%)", data.get("humidity", "—"))
c3.metric("📦 Seuil (°C)", data.get("seuil", "—"))

alarm = data.get("alarm", False)
c4.metric("🚨 Alarme", "ACTIVE" if alarm else "OK")

# ---------------------------------------------------------
# FLAME STATUS
# ---------------------------------------------------------
c5, c6 = st.columns(2)

flame = data.get("flame")
flame_hande = data.get("flameHande")

with c5:
    st.subheader("🔥 Flamme Steffy")
    if flame == 1:
        st.error("🔥 FEU DÉTECTÉ")
    elif flame == 0:
        st.success("Pas de feu")
    else:
        st.info("En attente…")

with c6:
    st.subheader("🔥 Flamme Hande")
    if flame_hande == 1:
        st.error("🔥 FEU DÉTECTÉ")
    elif flame_hande == 0:
        st.success("Pas de feu")
    else:
        st.info("En attente…")

# ---------------------------------------------------------
# REAL-TIME CHARTS
# ---------------------------------------------------------
st.divider()
st.subheader("📊 Graphiques temps réel")

if len(st.session_state.history) > 0:
    df = pd.DataFrame(st.session_state.history)

    temp_chart = (
        alt.Chart(df)
        .mark_line()
        .encode(
            x="time:T",
            y="temperature:Q"
        )
        .properties(height=250, title="Température")
    )

    hum_chart = (
        alt.Chart(df)
        .mark_line()
        .encode(
            x="time:T",
            y="humidity:Q"
        )
        .properties(height=250, title="Humidité")
    )

    st.altair_chart(temp_chart, use_container_width=True)
    st.altair_chart(hum_chart, use_container_width=True)
else:
    st.info("Aucune donnée reçue")

# ---------------------------------------------------------
# AUTO REFRESH
# ---------------------------------------------------------
time.sleep(1)
st.rerun()
