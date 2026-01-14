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
st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")

# ==========================
# 🎨 THEME PRO (BLEU/ROSE) - PAS TROP SOMBRE
# ==========================
st.markdown("""
<style>
/* Background global : un peu plus sombre + bleu/rose */
.stApp{
  background: linear-gradient(135deg,
    #b9c6dd 0%,
    #cfd7ea 35%,
    #e7d2e8 70%,
    #f2eff8 100%);
  color:#0f172a;
}

/* Conteneur principal */
.block-container{
  padding-top: 2.0rem;
}

/* Titres */
h1,h2,h3{
  color:#0b1220;
}

/* Alerts (status MQTT etc.) */
.stAlert{
  border-radius: 16px;
  box-shadow: 0 10px 25px rgba(15,23,42,0.08);
}

/* Cartes custom (metrics) */
.metric-card{
  background: rgba(255,255,255,0.78);
  border: 1px solid rgba(255,255,255,0.55);
  border-radius: 18px;
  padding: 18px 18px 14px 18px;
  box-shadow: 0 14px 35px rgba(15,23,42,0.10);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  position: relative;
  overflow: hidden;
  min-height: 110px;
}

/* Bande colorée en haut de chaque carte */
.metric-card::before{
  content:"";
  position:absolute;
  top:0; left:0; right:0;
  height:7px;
  background: var(--accent, linear-gradient(90deg,#3b82f6,#ec4899));
}

/* Label + valeur */
.metric-label{
  font-size: 0.95rem;
  opacity: 0.85;
  margin-bottom: 8px;
}
.metric-value{
  font-size: 2.0rem;
  font-weight: 800;
  letter-spacing: -0.02em;
  color: var(--val, #0f172a);
}

/* Sous-texte discret */
.metric-sub{
  margin-top: 6px;
  font-size: 0.85rem;
  opacity: 0.70;
}

/* Dividers */
hr{
  border:none;
  height:1px;
  background: rgba(15,23,42,0.15);
}

/* Graph container : arrondi + léger fond */
[data-testid="stAltairChart"]{
  background: rgba(255,255,255,0.72);
  border-radius: 18px;
  padding: 10px 10px 6px 10px;
  box-shadow: 0 14px 35px rgba(15,23,42,0.09);
  border: 1px solid rgba(255,255,255,0.55);
}

/* Sidebar un peu plus douce */
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
# DATA UPDATE
# ==========================
msgs = bridge.pop_all()
for m in msgs:
    st.session_state.last = m
    st.session_state.last_seen = datetime.now()
    st.session_state.history.append(m)

st.session_state.history = st.session_state.history[-250:]
data = st.session_state.last or {}

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
# METRICS (COULEURS)
# ==========================
c1, c2, c3, c4 = st.columns(4)

temp = data.get("temperature", "—")
hum = data.get("humidity", "—")
seuil = data.get("seuil", data.get("seuilPot", "—"))
alarm = data.get("alarm", False)

with c1:
    metric_card(
        "🌡️ Température (°C)",
        f"{temp}",
        "linear-gradient(90deg,#2563eb,#22c55e)",  # bleu -> vert
        "#0b1b3a",
        "Mesure DHT11"
    )

with c2:
    metric_card(
        "💧 Humidité (%)",
        f"{hum}",
        "linear-gradient(90deg,#06b6d4,#3b82f6)",  # cyan -> bleu
        "#083344",
        "Mesure DHT11"
    )

with c3:
    metric_card(
        "📦 Seuil (°C)",
        f"{seuil}",
        "linear-gradient(90deg,#8b5cf6,#ec4899)",  # violet -> rose
        "#2e1065",
        "Consigne / Pot"
    )

with c4:
    metric_card(
        "🚨 Alarme",
        "ACTIVE" if alarm else "OK",
        "linear-gradient(90deg,#ef4444,#f59e0b)" if alarm else "linear-gradient(90deg,#22c55e,#3b82f6)",
        "#7f1d1d" if alarm else "#0f172a",
        "État global"
    )

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
# 📈 GRAPHIQUES (COURBES + STYLE PRO)
# ==========================
st.subheader("📈 Graphiques temps réel")

if st.session_state.history:
    df = pd.DataFrame(st.session_state.history)
    df["time"] = pd.to_datetime(df["_time"])

    def line(col, title, unit, color_hex):
        d = df.dropna(subset=["time"])
        if col not in d.columns:
            return None
        return (
            alt.Chart(d)
            .mark_line(interpolate="monotone", strokeWidth=3, color=color_hex)
            .encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y(f"{col}:Q", title=unit),
                tooltip=["time:T", col],
            )
            .properties(height=280, title=title)
        )

    g1, g2 = st.columns(2)
    with g1:
        ch = line("temperature", "Température", "°C", "#2563eb")  # bleu
        if ch:
            st.altair_chart(ch, use_container_width=True)

    with g2:
        ch = line("humidity", "Humidité", "%", "#ec4899")  # rose
        if ch:
            st.altair_chart(ch, use_container_width=True)
else:
    st.info("Aucune donnée pour les graphiques")

with st.expander("🧪 Debug JSON (dernier message)"):
    st.json(data)

# ==========================
# AUTO REFRESH
# ==========================
time.sleep(1)
st.rerun()
