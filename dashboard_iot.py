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
# MQTT CONFIG (TCP)
# ==========================
MQTT_BROKER = "51.103.239.173"
MQTT_PORT = 1883
TOPIC_DATA = "capteur/data"

# ==========================
# LOGO (optionnel)
# ==========================
LOGO_FILENAME = "LOGO_EPHEC_HE.png"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, LOGO_FILENAME)

# ==========================
# QUEUE THREAD-SAFE
# ==========================
mqtt_queue = deque(maxlen=500)
mqtt_lock = threading.Lock()

# ==========================
# MQTT THREAD (une seule fois)
# ==========================
@st.cache_resource
def start_mqtt():
    state = {"connected": False}

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            state["connected"] = True
            client.subscribe(TOPIC_DATA)
            print("✅ MQTT connected -> subscribed:", TOPIC_DATA)
        else:
            state["connected"] = False
            print("❌ MQTT connect failed rc =", rc)

    def on_disconnect(client, userdata, rc, properties=None):
        state["connected"] = False
        print("🔌 MQTT disconnected rc =", rc)

    def on_message(client, userdata, msg):
        # ⚠️ NE JAMAIS toucher st.session_state ici !
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            payload["_time"] = datetime.now().isoformat(timespec="seconds")
            with mqtt_lock:
                mqtt_queue.append(payload)
        except Exception as e:
            print("⚠️ JSON invalide:", e, "payload=", msg.payload)

    client = mqtt.Client(protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    def loop():
        while True:
            try:
                client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
                client.loop_forever()
            except Exception as e:
                state["connected"] = False
                print("⚠️ MQTT loop error:", e)
                time.sleep(3)

    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return state

# ==========================
# SESSION STATE INIT (UI seulement)
# ==========================
st.session_state.setdefault("last_data", {})
st.session_state.setdefault("history", [])
st.session_state.setdefault("last_seen", None)

# ==========================
# PAGE
# ==========================
st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")

# Header
c1, c2 = st.columns([1, 6])
with c1:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=90)
    else:
        st.write("EPHEC")
with c2:
    st.title("🌡️ Gestion Intelligente Température & Sécurité – IoT")
    st.caption(f"Broker: {MQTT_BROKER} | TCP:{MQTT_PORT} | Topic: {TOPIC_DATA}")

# Start MQTT (1 fois)
mqtt_state = start_mqtt()

# ==========================
# DRAIN QUEUE -> UPDATE UI
# ==========================
new_count = 0
with mqtt_lock:
    while mqtt_queue:
        msg = mqtt_queue.popleft()
        st.session_state.last_data = msg
        st.session_state.last_seen = datetime.now()
        st.session_state.history.append(msg)
        st.session_state.history = st.session_state.history[-200:]
        new_count += 1

# ==========================
# STATUS
# ==========================
if mqtt_state["connected"]:
    st.success("✅ MQTT connecté (TCP 1883)")
else:
    st.error("🔴 MQTT déconnecté")

if st.session_state.last_seen:
    st.caption(f"Dernière donnée reçue: {st.session_state.last_seen.strftime('%H:%M:%S')} | +{new_count} msg")
else:
    st.warning("En attente de données MQTT… (vérifie que l’ESP32 publie bien sur capteur/data)")

st.divider()

data = st.session_state.last_data or {}

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
f1, f2 = st.columns(2)
flame = data.get("flame", None)
flame_h = data.get("flameHande", None)

with f1:
    st.subheader("🔥 Flamme Steffy")
    if flame == 1:
        st.error("🔥 FEU DÉTECTÉ")
    elif flame == 0:
        st.success("✅ Pas de flamme")
    else:
        st.info("En attente…")

with f2:
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
if not hist:
    st.info("Aucune donnée reçue")
else:
    df = pd.DataFrame(hist)
    df["time"] = pd.to_datetime(df.get("_time"), errors="coerce")

    def line_chart(col, title, ytitle):
        d = df.dropna(subset=["time"])
        if col not in d.columns:
            return None
        return (
            alt.Chart(d)
            .mark_line()
            .encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y(f"{col}:Q", title=ytitle),
                tooltip=["time:T", col],
            )
            .properties(height=250, title=title)
        )

    g1, g2 = st.columns(2)
    with g1:
        ch = line_chart("temperature", "Température", "°C")
        if ch: st.altair_chart(ch, use_container_width=True)
    with g2:
        ch = line_chart("humidity", "Humidité", "%")
        if ch: st.altair_chart(ch, use_container_width=True)

with st.expander("🧪 Debug JSON (dernier message)"):
    st.json(data)

cA, cB = st.columns(2)
with cA:
    if st.button("🗑️ Reset historique"):
        st.session_state.history = []
        st.success("Historique vidé.")
with cB:
    st.caption("Auto-refresh: 1s")

# ==========================
# AUTO REFRESH
# ==========================
time.sleep(1)
st.rerun()
