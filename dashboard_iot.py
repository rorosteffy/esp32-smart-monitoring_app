import json
import time
import socket
import threading
from datetime import datetime

import streamlit as st
import paho.mqtt.client as mqtt

# =========================
# CONFIG MQTT
# =========================
MQTT_BROKER = "51.103.239.173"
MQTT_WS_PORT = 9001
MQTT_WS_PATH = "/"
TOPIC_DATA = "ims/dashboard"

# =========================
# ETAT GLOBAL
# =========================
LOCK = threading.Lock()
MQTT_CONNECTED = False
LAST_UPDATE = None

DATA = {
    "ims10_ready": 1,
    "ims6_control_ok": 1,
    "ims7_run": 1,
    "pieces_produites": 1285,
    "pieces_rejetees": 47,
    "piece_prete": 1,
    "controle_ok": 1,
    "etat_robot": "En Attente",
    "defaut_capteur": 0,
    "station_bloquee": 0,
    "erreur_communication": 0
}

# =========================
# MQTT
# =========================
def on_connect(client, userdata, flags, rc, properties=None):
    global MQTT_CONNECTED
    MQTT_CONNECTED = (rc == 0)
    if rc == 0:
        client.subscribe(TOPIC_DATA)

def on_disconnect(client, userdata, rc, properties=None):
    global MQTT_CONNECTED
    MQTT_CONNECTED = False

def on_message(client, userdata, msg):
    global LAST_UPDATE
    try:
        payload = json.loads(msg.payload.decode())
        with LOCK:
            for k in DATA:
                if k in payload:
                    DATA[k] = payload[k]
            LAST_UPDATE = datetime.now()
    except:
        pass

@st.cache_resource
def init_mqtt():
    client = mqtt.Client(transport="websockets")
    client.ws_set_options(path=MQTT_WS_PATH)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect_async(MQTT_BROKER, MQTT_WS_PORT)
    client.loop_start()
    return client

# =========================
# UI STYLE
# =========================
st.set_page_config(layout="wide")

st.markdown("""
<style>

/* ===== FOND ===== */
.stApp {
    background: linear-gradient(180deg, #8fa2b8 0%, #6f8298 100%);
    color: #102030;
}

/* ===== CONTAINER ===== */
.block-container {
    max-width: 1400px;
    padding-top: 0.5rem;
}

/* ===== TITRE ===== */
.main-title {
    text-align:center;
    font-size:2.6rem;
    font-weight:900;
    margin-bottom:20px;
    color:#0b1f38;
}

/* ===== CARTES ===== */
.card {
    background:white;
    padding:18px;
    border-radius:12px;
    box-shadow:0 6px 15px rgba(0,0,0,0.2);
}

/* ===== STATUS ===== */
.status {
    background:#16a34a;
    color:white;
    padding:18px;
    border-radius:10px;
    font-weight:800;
    text-align:center;
    font-size:20px;
}

/* ===== BOUTONS ===== */
div[data-testid="stButton"] button {
    height:90px;
    border-radius:18px;
    font-size:24px;
    font-weight:900;
    color:white;
}

/* START */
button[kind="secondary"]:nth-of-type(1) {
    background:#22c55e;
}

/* STOP */
button[kind="secondary"]:nth-of-type(2) {
    background:#ef4444;
}

/* RESET */
button[kind="secondary"]:nth-of-type(3) {
    background:#64748b;
}

</style>
""", unsafe_allow_html=True)

# =========================
# APP
# =========================
init_mqtt()

st.markdown('<div class="main-title">🏭 Dashboard IMS - Supervision Production</div>', unsafe_allow_html=True)

if MQTT_CONNECTED:
    st.success("MQTT connecté")
else:
    st.error("Perte de communication MQTT")

# =========================
# LAYOUT
# =========================
left, right = st.columns([1,2])

with left:
    st.subheader("⚙️ Statut des Stations")

    st.markdown('<div class="status">✅ IMS10 READY</div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown('<div class="status">🧪 IMS6 CONTROL OK</div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown('<div class="status">▶️ IMS7 RUN</div>', unsafe_allow_html=True)

    st.subheader("🚨 Alarmes")
    st.markdown('<div class="card">⚠️ Défaut Capteur</div>', unsafe_allow_html=True)
    st.markdown('<div class="card">⛔ Station Bloquée</div>', unsafe_allow_html=True)
    st.markdown('<div class="card">📶 Erreur Communication</div>', unsafe_allow_html=True)

with right:
    st.subheader("📦 Flux de Production")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown(f"""
        <div class="card" style="background:#16a34a;color:white;text-align:center;">
        ⚙️ Pièces Produites<br><br>
        <h1>{DATA["pieces_produites"]}</h1>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown(f"""
        <div class="card" style="background:#dc2626;color:white;text-align:center;">
        ⚠️ Pièces Rejetées<br><br>
        <h1>{DATA["pieces_rejetees"]}</h1>
        </div>
        """, unsafe_allow_html=True)

    st.subheader("🧩 Variables Clés")

    v1, v2, v3 = st.columns(3)
    v1.success("✅ Pièce prête")
    v2.success("✅ Contrôle OK")
    v3.info(f"🤖 {DATA['etat_robot']}")

# =========================
# BOUTONS
# =========================
st.markdown("<br>", unsafe_allow_html=True)

b1, b2, b3 = st.columns(3)

with b1:
    st.button("🟢 START")

with b2:
    st.button("🔴 STOP")

with b3:
    st.button("♻️ RESET")

# =========================
# REFRESH
# =========================
time.sleep(2)
st.rerun()
