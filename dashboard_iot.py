import streamlit as st
import paho.mqtt.client as mqtt
import json
import threading
import time
from datetime import datetime
from collections import deque
import pandas as pd
import altair as alt
import os

# ==========================
# CONFIG MQTT
# ==========================
MQTT_BROKER = "51.103.239.173"
MQTT_WS_PORT = 9001
MQTT_TOPIC = "capteur/data"
MQTT_WS_PATH = "/"   # souvent "/" avec mosquitto websockets

# ==========================
# LOGO (optionnel)
# ==========================
LOGO_FILENAME = "LOGO_EPHEC_HE.png"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, LOGO_FILENAME)

# ==========================
# FILE THREAD-SAFE (queue)
# ==========================
mqtt_queue = deque(maxlen=500)   # messages reçus (thread -> UI)
mqtt_lock = threading.Lock()

# ==========================
# MQTT THREAD (cache_resource => 1 instance)
# ==========================
@st.cache_resource
def start_mqtt_thread():
    state = {"connected": False}

    # callbacks compatibles paho v1/v2
    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            state["connected"] = True
            client.subscribe(MQTT_TOPIC)
            print("✅ MQTT connected")
        else:
            state["connected"] = False
            print("❌ MQTT connect rc =", rc)

    def on_disconnect(client, userdata, rc, properties=None):
        state["connected"] = False
        print("🔌 MQTT disconnected rc =", rc)

    def on_message(client, userdata, msg):
        # IMPORTANT: ne JAMAIS toucher st.session_state ici
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            payload["_time"] = datetime.now().isoformat(timespec="seconds")
            with mqtt_lock:
                mqtt_queue.append(payload)
        except Exception as e:
            print("Erreur JSON:", e)

    client = mqtt.Client(transport="websockets", protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    # Options WS (path)
    try:
        client.ws_set_options(path=MQTT_WS_PATH)
    except Exception:
        pass

    def loop():
        while True:
            try:
                client.connect(MQTT_BROKER, MQTT_WS_PORT, keepalive=60)
                client.loop_forever()
            except Exception as e:
                state["connected"] = False
                print("⚠️ MQTT loop error:", e)
                time.sleep(3)

    t = threading.Thread(target=loop, daemon=True)
    t.start()

    return state

# ==========================
# SESSION STATE INIT
# ==========================
st.session_state.setdefault("last_data", {})
st.session_state.setdefault("history", [])  # UI history
st.session_state.setdefault("last_seen", None)

# ==========================
# UI
# ==========================
st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")

# header + logo
c_logo, c_title = st.columns([1, 6])
with c_logo:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=90)
    else:
        st.write("EPHEC")
with c_title:
    st.title("🌡️ Gestion Intelligente Température & Sécurité – IoT")
    st.caption(f"Broker: {MQTT_BROKER} | WebSockets:{MQTT_WS_PORT} | Topic: {MQTT_TOPIC}")

# start mqtt once
mqtt_state = start_mqtt_thread()

# ==========================
# DRAIN QUEUE -> UPDATE UI STATE
# ==========================
new_messages = 0
with mqtt_lock:
    while mqtt_queue:
        payload = mqtt_queue.popleft()
        st.session_state.last_data = payload
        st.session_state.last_seen = datetime.now()
        st.session_state.history.append(payload)
        st.session_state.history = st.session_state.history[-200:]  # keep last 200
        new_messages += 1

# ==========================
# MQTT STATUS
# ==========================
if mqtt_state["connected"]:
    st.success("✅ MQTT connecté (WebSockets)")
else:
    st.error("🔴 MQTT déconnecté (vérifie port 9001 / WS / firewall)")

if st.session_state.last_seen:
    st.caption(f"Dernière donnée reçue: {st.session_state.last_seen.strftime('%H:%M:%S')}  |  +{new_messages} msg")
else:
    st.warning("En attente de données MQTT… (vérifie que l’ESP32 publie bien sur capteur/data)")

st.divider()

data = st.session_state.last_data

# ==========================
# METRICS
# ==========================
m1, m2, m3, m4 = st.columns(4)
m1.metric("🌡️ Température (°C)", data.get("temperature", "—"))
m2.metric("💧 Humidité (%)", data.get("humidity", "—"))
m3.metric("📦 Seuil (°C)", data.get("seuil", data.get("seuilPot", "—")))
alarm = data.get("alarm", False)
m4.metric("🚨 Alarme", "ACTIVE" if alarm else "OK")

st.divider()

# ==========================
# FLAMME
# ==========================
c5, c6 = st.columns(2)
flame = data.get("flame", None)
flame_h = data.get("flameHande", None)

with c5:
    st.subheader("🔥 Flamme Steffy")
    if flame == 1:
        st.error("🔥 FEU DÉTECTÉ")
    elif flame == 0:
        st.success("✅ Pas de flamme")
    else:
        st.info("En attente…")

with c6:
    st.subheader("🔥 Flamme Hande")
    if flame_h == 1:
        st.error("🔥 FEU DÉTECTÉ")
    elif flame_h == 0:
        st.success("✅ Pas de flamme")
    else:
        st.info("En attente…")

st.divider()

# ==========================
# GRAPHIQUES
# ==========================
st.subheader("📊 Graphiques temps réel")
hist = st.session_state.history

if len(hist) == 0:
    st.info("Aucune donnée reçue")
else:
    df = pd.DataFrame(hist)

    # convert time
    df["time"] = pd.to_datetime(df["_time"], errors="coerce")

    def line_chart(df, col, title, ytitle):
        base = (
            alt.Chart(df.dropna(subset=["time"]))
            .mark_line()
            .encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y(f"{col}:Q", title=ytitle),
                tooltip=["time:T", col]
            )
            .properties(height=250, title=title)
        )
        return base

    g1, g2 = st.columns(2)
    with g1:
        if "temperature" in df.columns:
            st.altair_chart(line_chart(df, "temperature", "Température", "°C"), use_container_width=True)
    with g2:
        if "humidity" in df.columns:
            st.altair_chart(line_chart(df, "humidity", "Humidité", "%"), use_container_width=True)

# ==========================
# OUTILS
# ==========================
with st.expander("🧪 Debug JSON (dernier message)"):
    st.json(data if data else {})

colA, colB = st.columns(2)
with colA:
    if st.button("🗑️ Reset historique"):
        st.session_state.history = []
        st.success("Historique vidé.")
with colB:
    st.caption("Auto-refresh: 1s")

# ==========================
# AUTO REFRESH (1s)
# ==========================
time.sleep(1)
st.rerun()
