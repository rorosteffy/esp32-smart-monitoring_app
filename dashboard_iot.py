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
# OBJET PERSISTANT (queue + état + thread)
# ==========================
class MqttBridge:
    def __init__(self):
        self.connected = False
        self.queue = deque(maxlen=500)
        self.lock = threading.Lock()
        self.client = None
        self.thread = None
        self.started = False

    def push(self, payload: dict):
        with self.lock:
            self.queue.append(payload)

    def pop_all(self):
        items = []
        with self.lock:
            while self.queue:
                items.append(self.queue.popleft())
        return items


@st.cache_resource
def get_mqtt_bridge():
    bridge = MqttBridge()

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            bridge.connected = True
            client.subscribe(TOPIC_DATA)
            print("✅ MQTT connected -> subscribed:", TOPIC_DATA)
        else:
            bridge.connected = False
            print("❌ MQTT connect failed rc =", rc)

    def on_disconnect(client, userdata, rc, properties=None):
        bridge.connected = False
        print("🔌 MQTT disconnected rc =", rc)

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            payload["_time"] = datetime.now().isoformat(timespec="seconds")
            bridge.push(payload)
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
                bridge.connected = False
                print("⚠️ MQTT loop error:", e)
                time.sleep(3)

    bridge.client = client
    bridge.thread = threading.Thread(target=loop, daemon=True)
    bridge.thread.start()
    bridge.started = True
    return bridge


# ==========================
# SESSION STATE INIT (UI)
# ==========================
st.session_state.setdefault("last_data", {})
st.session_state.setdefault("history", [])
st.session_state.setdefault("last_seen", None)

# ==========================
# PAGE
# ==========================
st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")

# ==========================
# ✅ DARK GRADIENT THEME (PRO)
# ==========================
st.markdown("""
<style>
/* Background sombre dégradé */
.stApp {
    background: radial-gradient(circle at top left, #1b2b4a 0%, #0b1220 45%, #05070c 100%);
    color: #e5e7eb;
}

/* Header spacing */
.block-container { padding-top: 1.2rem; }

/* Titres */
h1, h2, h3, h4 {
    color: #f8fafc !important;
    font-weight: 800 !important;
}

/* Texte / caption */
p, li, span, label, .stCaption {
    color: #cbd5e1 !important;
}

/* Cartes / blocs (metrics, alerts, charts) */
[data-testid="stMetric"], 
[data-testid="stVerticalBlockBorderWrapper"],
.stAlert,
.element-container,
div[data-testid="stMetric"] {
    background: rgba(255,255,255,0.06) !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    border-radius: 16px !important;
    padding: 14px !important;
    box-shadow: 0 10px 26px rgba(0,0,0,0.35) !important;
}

/* Séparateurs */
hr {
    border: none;
    height: 1px;
    background: rgba(255,255,255,0.12);
}

/* Expander */
details {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 14px;
    padding: 10px;
}

/* Boutons */
.stButton > button {
    background: linear-gradient(135deg, #2563eb, #06b6d4) !important;
    color: white !important;
    border: 0 !important;
    border-radius: 12px !important;
    font-weight: 700 !important;
    padding: 10px 14px !important;
}
.stButton > button:hover {
    filter: brightness(1.08);
}

/* Input background (si tu ajoutes plus tard) */
input, textarea {
    background: rgba(255,255,255,0.06) !important;
    color: #e5e7eb !important;
}

/* Enlever fond blanc des charts altair (si besoin) */
.vega-embed, .vega-embed details, canvas {
    background: transparent !important;
}
</style>
""", unsafe_allow_html=True)

# ==========================
# HEADER
# ==========================
c1, c2 = st.columns([1, 6])
with c1:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=90)
    else:
        st.write("EPHEC")
with c2:
    st.title("🌡️ Gestion Intelligente Température & Sécurité – IoT")
    st.caption(f"Broker: {MQTT_BROKER} | TCP:{MQTT_PORT} | Topic: {TOPIC_DATA}")

bridge = get_mqtt_bridge()

# ==========================
# DRAIN QUEUE -> UPDATE UI
# ==========================
new_msgs = bridge.pop_all()
for msg in new_msgs:
    st.session_state.last_data = msg
    st.session_state.last_seen = datetime.now()
    st.session_state.history.append(msg)

st.session_state.history = st.session_state.history[-200:]
data = st.session_state.last_data or {}

# ==========================
# STATUS
# ==========================
if bridge.connected:
    st.success("✅ MQTT connecté (TCP 1883)")
else:
    st.error("🔴 MQTT déconnecté")

if st.session_state.last_seen:
    st.info(f"✅ Données reçues: {st.session_state.last_seen.strftime('%H:%M:%S')} | +{len(new_msgs)} msg")
else:
    st.warning("En attente de données MQTT… (vérifie que l’ESP32 publie bien sur capteur/data)")

st.divider()

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
# GRAPHIQUES (LIGNES)
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
            .mark_line(point=True)   # ✅ lignes + points (pas batonnet)
            .encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y(f"{col}:Q", title=ytitle),
                tooltip=["time:T", col],
            )
            .properties(height=260, title=title)
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
