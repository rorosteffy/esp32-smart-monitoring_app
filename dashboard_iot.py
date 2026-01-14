import json
import time
import threading
from datetime import datetime

import streamlit as st
import pandas as pd
import altair as alt
import paho.mqtt.client as mqtt

# ================= MQTT CONFIG =================
MQTT_BROKER = "51.103.239.173"
MQTT_PORT   = 9001                 # ✅ WebSocket (Streamlit Cloud)
MQTT_TOPIC  = "capteur/data"

# ================= GLOBAL DATA =================
lock = threading.Lock()
last_data = {
    "temperature": None,
    "humidity": None,
    "seuil": None,
    "flame": None,
    "timestamp": None
}
history = []

# ================= MQTT CALLBACKS =================
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe(MQTT_TOPIC)
        print("✅ MQTT connected")
    else:
        print("❌ MQTT connection error", rc)

def on_message(client, userdata, msg):
    global last_data, history
    try:
        payload = json.loads(msg.payload.decode())
        now = datetime.now()

        with lock:
            last_data = {
                "temperature": payload.get("temperature"),
                "humidity": payload.get("humidity"),
                "seuil": payload.get("seuil"),
                "flame": payload.get("flame"),
                "timestamp": now
            }

            history.append({
                "time": now,
                "temperature": last_data["temperature"],
                "humidity": last_data["humidity"],
                "seuil": last_data["seuil"],
                "flame": last_data["flame"]
            })

            history[:] = history[-300:]  # garde 300 points max

    except Exception as e:
        print("MQTT JSON error:", e)

# ================= MQTT INIT (ONE TIME) =================
@st.cache_resource
def start_mqtt():
    client = mqtt.Client(transport="websockets")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
    return client

# ================= UI =================
st.set_page_config("Dashboard IoT EPHEC", layout="wide")
start_mqtt()

st.title("🌡️ Dashboard IoT – Température & Sécurité")

with lock:
    data = dict(last_data)
    df = pd.DataFrame(history)

# ===== STATUS =====
if data["timestamp"]:
    age = (datetime.now() - data["timestamp"]).total_seconds()
    if age < 5:
        st.success("MQTT connecté – données temps réel")
    else:
        st.warning("MQTT connecté – données anciennes")
else:
    st.error("En attente de données MQTT…")

# ===== METRICS =====
c1, c2, c3, c4 = st.columns(4)

c1.metric("🌡️ Température (°C)", data["temperature"] or "—")
c2.metric("💧 Humidité (%)", data["humidity"] or "—")
c3.metric("📦 Seuil (°C)", data["seuil"] or "—")

if data["flame"] == 1:
    c4.error("🔥 FLAMME")
else:
    c4.success("✅ Pas de flamme")

# ===== GRAPHS =====
if not df.empty:
    st.subheader("📈 Courbes temps réel")

    def chart(y, title):
        return alt.Chart(df).mark_line(point=True).encode(
            x="time:T",
            y=alt.Y(f"{y}:Q", title=title),
            tooltip=["time:T", y]
        ).properties(height=250)

    g1, g2 = st.columns(2)
    g1.altair_chart(chart("temperature", "Température (°C)"), use_container_width=True)
    g2.altair_chart(chart("humidity", "Humidité (%)"), use_container_width=True)

    g3, g4 = st.columns(2)
    g3.altair_chart(chart("seuil", "Seuil (°C)"), use_container_width=True)
    g4.altair_chart(chart("flame", "Flamme (0/1)"), use_container_width=True)

# ===== AUTO REFRESH =====
time.sleep(2)
st.rerun()
