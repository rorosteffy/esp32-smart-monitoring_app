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

    # ✅ paho v1 ET v2 compatible
    def on_connect(client, userdata, flags, rc, properties=None):
        bridge.connected = (rc == 0)
        if rc == 0:
            client.subscribe(TOPIC_DATA)

    def on_disconnect(client, userdata, rc, properties=None):
        bridge.connected = False

    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode("utf-8"))
            data["_time"] = datetime.now()  # datetime direct
            bridge.push(data)
        except:
            pass

    client = mqtt.Client(protocol=mqtt.MQTTv311)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=5)

    def loop():
        while True:
            try:
                client.connect(MQTT_BROKER, MQTT_PORT, 60)
                client.loop_forever()
            except:
                bridge.connected = False
                time.sleep(2)

    threading.Thread(target=loop, daemon=True).start()
    return bridge

# ==========================
# PAGE CONFIG
# ==========================
st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")

# ==========================
# 🎨 THEME PRO BLEU/ROSE (un peu sombre)
# ==========================
st.markdown("""
<style>
.stApp{
  background: linear-gradient(135deg,
    #93a8c6 0%,
    #a7b7d6 30%,
    #c7b0d8 65%,
    #e7e2f2 100%);
  color:#0f172a;
}
.block-container{ padding-top: 1.8rem; }
h1,h2,h3{ color:#0b1220; }

.metric-card{
  background: rgba(255,255,255,0.78);
  border: 1px solid rgba(255,255,255,0.55);
  border-radius: 18px;
  padding: 16px 16px 12px 16px;
  box-shadow: 0 14px 35px rgba(15,23,42,0.12);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  position: relative;
  overflow: hidden;
  min-height: 105px;
}
.metric-card::before{
  content:"";
  position:absolute;
  top:0; left:0; right:0;
  height:7px;
  background: var(--accent, linear-gradient(90deg,#3b82f6,#ec4899));
}
.metric-label{ font-size: 0.95rem; opacity: 0.85; margin-bottom: 6px; }
.metric-value{ font-size: 2.0rem; font-weight: 850; letter-spacing: -0.02em; color: var(--val, #0f172a); }
.metric-sub{ margin-top: 6px; font-size: 0.85rem; opacity: 0.70; }

[data-testid="stAltairChart"]{
  background: rgba(255,255,255,0.72);
  border-radius: 18px;
  padding: 10px 10px 6px 10px;
  box-shadow: 0 14px 35px rgba(15,23,42,0.11);
  border: 1px solid rgba(255,255,255,0.55);
}
section[data-testid="stSidebar"]{
  background: rgba(255,255,255,0.55);
  backdrop-filter: blur(12px);
}
</style>
""", unsafe_allow_html=True)

def metric_card(label, value, accent_css, value_color, sub=""):
    st.markdown(
        f"""
        <div class="metric-card" style="--accent:{accent_css}; --val:{value_color};">
          <div class="metric-label">{label}</div>
          <div class="metric-value">{value}</div>
          <div class="metric-sub">{sub}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ==========================
# STATE
# ==========================
st.session_state.setdefault("history", [])
st.session_state.setdefault("last", {})
st.session_state.setdefault("last_seen", None)

bridge = get_bridge()

# ==========================
# UPDATE DATA
# ==========================
msgs = bridge.pop_all()
for m in msgs:
    st.session_state.last = m
    st.session_state.last_seen = datetime.now()
    st.session_state.history.append(m)

st.session_state.history = st.session_state.history[-250:]
data = st.session_state.last or {}

# ==========================
# HEADER + STATUS
# ==========================
st.title("🌡️ Gestion Intelligente Température & Sécurité – IoT")
st.caption(f"Broker : {MQTT_BROKER} | Port : {MQTT_PORT} | Topic : {TOPIC_DATA}")

if bridge.connected:
    st.success("✅ MQTT connecté (TCP 1883)")
else:
    st.error("🔴 MQTT déconnecté")

if st.session_state.last_seen:
    st.info(f"📥 Dernière donnée: {st.session_state.last_seen.strftime('%H:%M:%S')} (+{len(msgs)} msg)")
else:
    st.warning("⏳ En attente de données MQTT… (vérifie l’ESP32 publie capteur/data)")

st.divider()

# ==========================
# METRICS
# ==========================
c1, c2, c3, c4 = st.columns(4)

temp = data.get("temperature", "—")
hum = data.get("humidity", "—")
seuil = data.get("seuil", data.get("seuilPot", "—"))
alarm = bool(data.get("alarm", False))

with c1:
    metric_card("🌡️ Température (°C)", f"{temp}",
                "linear-gradient(90deg,#2563eb,#22c55e)", "#0b1b3a", "Mesure DHT11")
with c2:
    metric_card("💧 Humidité (%)", f"{hum}",
                "linear-gradient(90deg,#06b6d4,#3b82f6)", "#083344", "Mesure DHT11")
with c3:
    metric_card("📦 Seuil (°C)", f"{seuil}",
                "linear-gradient(90deg,#8b5cf6,#ec4899)", "#2e1065", "Consigne / Pot")
with c4:
    metric_card("🚨 Alarme", "ACTIVE" if alarm else "OK",
                "linear-gradient(90deg,#ef4444,#f59e0b)" if alarm else "linear-gradient(90deg,#22c55e,#3b82f6)",
                "#7f1d1d" if alarm else "#0f172a",
                "État global")

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
# 📈 GRAPHIQUES (COURBES + STEP)
# ==========================
st.subheader("📈 Graphiques temps réel (courbes)")

hist = st.session_state.history
if not hist:
    st.info("Aucune donnée pour les graphiques.")
else:
    df = pd.DataFrame(hist)
    df["time"] = pd.to_datetime(df["_time"], errors="coerce")
    df = df.dropna(subset=["time"]).tail(250)

    def line_chart(col, title, unit, color_hex):
        if col not in df.columns:
            return None
        return (
            alt.Chart(df)
            .mark_line(interpolate="monotone", strokeWidth=3, color=color_hex)
            .encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y(f"{col}:Q", title=unit),
                tooltip=["time:T", alt.Tooltip(f"{col}:Q")]
            )
            .properties(height=280, title=title)
        )

    def step_chart(col, title, unit, color_hex):
        if col not in df.columns:
            return None
        return (
            alt.Chart(df)
            .mark_line(interpolate="step-after", strokeWidth=4, color=color_hex)
            .encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y(f"{col}:Q", title=unit, scale=alt.Scale(domain=[-0.05, 1.05])),
                tooltip=["time:T", alt.Tooltip(f"{col}:Q")]
            )
            .properties(height=280, title=title)
        )

    g1, g2 = st.columns(2)
    with g1:
        ch = line_chart("temperature", "Température", "°C", "#2563eb")
        if ch: st.altair_chart(ch, use_container_width=True)
    with g2:
        ch = line_chart("humidity", "Humidité", "%", "#ec4899")
        if ch: st.altair_chart(ch, use_container_width=True)

    g3, g4 = st.columns(2)
    with g3:
        ch = line_chart("seuil", "Seuil (si présent)", "°C", "#7c3aed")
        if ch: st.altair_chart(ch, use_container_width=True)
        else:
            st.info("Pas de colonne 'seuil' dans l’historique (OK si tu envoies seuilPot).")
    with g4:
        ch = step_chart("flame", "IR / Flamme (0/1) - STEP", "0/1", "#f97316")
        if ch: st.altair_chart(ch, use_container_width=True)

with st.expander("🧪 Debug JSON (dernier message)"):
    st.json(data)

# ==========================
# AUTO REFRESH
# ==========================
time.sleep(1)
st.rerun()
