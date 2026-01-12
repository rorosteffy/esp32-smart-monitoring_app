import streamlit as st
import paho.mqtt.client as mqtt
import json
import threading
import time
from datetime import datetime
from collections import deque
import pandas as pd
import altair as alt

# ===================== MQTT CONFIG =====================
MQTT_BROKER = "51.103.239.173"
MQTT_PORT   = 1883
TOPIC_DATA  = "capteur/data"
TOPIC_CMD   = "noeud/operateur/cmd"

CMD_LED_ON  = "LED_RED_ON"
CMD_LED_OFF = "LED_RED_OFF"

# ===================== GLOBAL STATE =====================
LOCK = threading.Lock()

DATA = {
    "temperature": None,
    "humidity": None,
    "seuil": None,
    "flame": None,
    "alarm": None,
    "last_update": None
}

HISTORY = deque(maxlen=200)
MQTT_OK = False

# ===================== MQTT CALLBACKS =====================
def on_connect(client, userdata, flags, rc):
    global MQTT_OK
    MQTT_OK = (rc == 0)
    if rc == 0:
        client.subscribe(TOPIC_DATA)
        print("✅ MQTT connecté")
    else:
        print("❌ MQTT erreur rc =", rc)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except:
        return

    now = datetime.now()

    with LOCK:
        DATA["temperature"] = payload.get("temperature")
        DATA["humidity"]    = payload.get("humidity")
        DATA["seuil"]       = payload.get("seuil")
        DATA["flame"]       = payload.get("flame")
        DATA["alarm"]       = payload.get("alarm")
        DATA["last_update"] = now

        HISTORY.append({
            "time": now,
            "temperature": DATA["temperature"],
            "humidity": DATA["humidity"],
            "seuil": DATA["seuil"]
        })

# ===================== MQTT CLIENT (1 FOIS) =====================
@st.cache_resource
def start_mqtt():
    client = mqtt.Client(protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(MQTT_BROKER, MQTT_PORT, 60)
    client.loop_start()
    return client

mqtt_client = start_mqtt()

# ===================== UI =====================
st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")
st.title("Gestion Intelligente Température & Sécurité – IoT")

# -------- MQTT STATUS --------
with LOCK:
    last_time = DATA["last_update"]

if last_time and (datetime.now() - last_time).total_seconds() < 6:
    st.success("🟢 MQTT connecté – données en temps réel")
else:
    st.error("🔴 MQTT connecté mais aucune donnée récente")

# -------- METRICS --------
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.metric("🌡️ Température (°C)", DATA["temperature"] or "—")

with c2:
    st.metric("💧 Humidité (%)", DATA["humidity"] or "—")

with c3:
    st.metric("📦 Seuil (°C)", DATA["seuil"] or "—")

with c4:
    if DATA["alarm"]:
        st.error("🚨 Alarme ACTIVE")
    else:
        st.success("✅ Alarme inactive")

# -------- FLAME --------
st.subheader("🔥 Flamme")
if DATA["flame"] is None:
    st.info("En attente de données…")
elif int(DATA["flame"]) == 1:
    st.error("🔥 Feu détecté")
else:
    st.success("Aucun feu")

# -------- COMMANDES --------
st.subheader("🎛️ Commandes binôme")

b1, b2 = st.columns(2)
if b1.button("🔴 LED ROUGE ON"):
    mqtt_client.publish(TOPIC_CMD, CMD_LED_ON)

if b2.button("⚫ LED ROUGE OFF"):
    mqtt_client.publish(TOPIC_CMD, CMD_LED_OFF)

# -------- CHART --------
st.subheader("📈 Température & Humidité (temps réel)")

if len(HISTORY) > 2:
    df = pd.DataFrame(HISTORY)

    chart = alt.Chart(df).mark_line().encode(
        x="time:T",
        y="temperature:Q",
        tooltip=["time:T", "temperature:Q"]
    )

    st.altair_chart(chart, use_container_width=True)
else:
    st.info("Pas encore assez de données")

# -------- AUTO REFRESH (SAFE) --------
time.sleep(2)
st.rerun()
