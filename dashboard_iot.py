import streamlit as st
import paho.mqtt.client as mqtt
import json
import threading
import time
from datetime import datetime
from collections import deque
import pandas as pd
import altair as alt

# ==========================
# MQTT CONFIG
# ==========================
MQTT_BROKER = "51.103.239.173"
MQTT_PORT = 1883
TOPIC_DATA = "capteur/data"

# ==========================
# MQTT BRIDGE
# ==========================
class MqttBridge:
    def __init__(self):
        self.connected = False
        self.queue = deque(maxlen=500)
        self.lock = threading.Lock()

    def push(self, payload):
        with self.lock:
            self.queue.append(payload)

    def pop_all(self):
        items = []
        with self.lock:
            while self.queue:
                items.append(self.queue.popleft())
        return items

@st.cache_resource
def get_bridge():
    bridge = MqttBridge()

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            bridge.connected = True
            client.subscribe(TOPIC_DATA)

    def on_disconnect(client, userdata, rc, properties=None):
        bridge.connected = False

    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            data["_time"] = datetime.now()
            bridge.push(data)
        except:
            pass

    client = mqtt.Client(protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    def loop():
        while True:
            try:
                client.connect(MQTT_BROKER, MQTT_PORT, 60)
                client.loop_forever()
            except:
                time.sleep(3)

    threading.Thread(target=loop, daemon=True).start()
    return bridge

# ==========================
# PAGE CONFIG
# ==========================
st.set_page_config(
    page_title="Dashboard IoT EPHEC",
    layout="wide"
)

# ==========================
# 🎨 STYLE PRO ÉQUILIBRÉ
# ==========================
st.markdown("""
<style>
.stApp {
    background: linear-gradient(135deg, #dfe7f1 0%, #eef2f7 40%, #f4f6f9 100%);
    color: #1e293b;
}

h1, h2, h3 {
    color: #0f172a;
}

[data-testid="stMetric"] {
    background: rgba(255,255,255,0.85);
    border-radius: 16px;
    padding: 20px;
    box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
}

.stAlert {
    border-radius: 14px;
}

section[data-testid="stSidebar"] {
    background: #e6ecf5;
}

.block-container {
    padding-top: 2.2rem;
}

hr {
    border: none;
    height: 1px;
    background: #cbd5e1;
}
</style>
""", unsafe_allow_html=True)

# ==========================
# STATE
# ==========================
st.session_state.setdefault("history", [])
st.session_state.setdefault("last", {})
st.session_state.setdefault("last_seen", None)

bridge = get_bridge()

# ==========================
# DATA UPDATE
# ==========================
msgs = bridge.pop_all()
for m in msgs:
    st.session_state.last = m
    st.session_state.last_seen = datetime.now()
    st.session_state.history.append(m)

st.session_state.history = st.session_state.history[-200:]
data = st.session_state.last

# ==========================
# HEADER
# ==========================
st.title("🌡️ Gestion Intelligente Température & Sécurité – IoT")
st.caption(f"Broker : {MQTT_BROKER} | TCP 1883 | Topic : {TOPIC_DATA}")

if bridge.connected:
    st.success("✅ MQTT connecté (TCP 1883)")
else:
    st.error("🔴 MQTT déconnecté")

if st.session_state.last_seen:
    st.info(f"📥 Données reçues à {st.session_state.last_seen.strftime('%H:%M:%S')} (+{len(msgs)} msg)")
else:
    st.warning("⏳ En attente de données MQTT…")

st.divider()

# ==========================
# METRICS
# ==========================
m1, m2, m3, m4 = st.columns(4)
m1.metric("🌡️ Température (°C)", data.get("temperature", "—"))
m2.metric("💧 Humidité (%)", data.get("humidity", "—"))
m3.metric("📦 Seuil (°C)", data.get("seuil", data.get("seuilPot", "—")))
m4.metric("🚨 Alarme", "ACTIVE" if data.get("alarm") else "OK")

st.divider()

# ==========================
# FLAMMES
# ==========================
f1, f2 = st.columns(2)

with f1:
    st.subheader("🔥 Flamme Steffy")
    if data.get("flame") == 1:
        st.error("🔥 FEU DÉTECTÉ")
    elif data.get("flame") == 0:
        st.success("✅ Pas de flamme")
    else:
        st.info("En attente…")

with f2:
    st.subheader("🔥 Flamme Hande")
    if data.get("flameHande") == 1:
        st.error("🔥 FEU DÉTECTÉ")
    elif data.get("flameHande") == 0:
        st.success("✅ Pas de flamme")
    else:
        st.info("En attente…")

st.divider()

# ==========================
# 📈 GRAPHIQUES (COURBES)
# ==========================
st.subheader("📈 Graphiques temps réel")

if st.session_state.history:
    df = pd.DataFrame(st.session_state.history)
    df["time"] = pd.to_datetime(df["_time"])

    def line(col, title, unit):
        return (
            alt.Chart(df)
            .mark_line(
                interpolate="monotone",
                strokeWidth=3,
                color="#2563eb"
            )
            .encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y(f"{col}:Q", title=unit),
                tooltip=["time:T", col]
            )
            .properties(height=280, title=title)
        )

    g1, g2 = st.columns(2)
    g1.altair_chart(line("temperature", "Température", "°C"), use_container_width=True)
    g2.altair_chart(line("humidity", "Humidité", "%"), use_container_width=True)
else:
    st.info("Aucune donnée pour les graphiques")

# ==========================
# AUTO REFRESH
# ==========================
time.sleep(1)
st.rerun()
