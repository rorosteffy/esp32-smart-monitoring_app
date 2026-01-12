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
import socket

# ==========================
# MQTT CONFIG (par défaut)
# ==========================
DEFAULT_BROKER = "51.103.239.173"
DEFAULT_PORT = 1883
DEFAULT_TRANSPORT = "tcp"   # "tcp" ou "websockets"
DEFAULT_TOPIC_DATA = "capteur/data"
DEFAULT_TOPIC_CMD  = "noeud/operateur/cmd"

CMD_LED_ON  = "LED_RED_ON"
CMD_LED_OFF = "LED_RED_OFF"

# ==========================
# UI CONFIG
# ==========================
st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")

# ==========================
# THREAD-SAFE STATE
# ==========================
LOCK = threading.Lock()

LAST = {
    "temperature": None,
    "humidity": None,
    "seuil": None,         # clé ESP32: "seuil"
    "flame": None,
    "flameHande": None,
    "alarm": None,
    "alarmLocal": None,
    "muted": None,
    "motorForced": None,
    "motorSpeed": None,
    "last_update": None,
}

HISTORY = deque(maxlen=400)

# Etat connexion (seulement info)
MQTT_STATE = {
    "connected": False,
    "last_rc": None,
    "last_err": None,
    "last_change": None,
}

def now_ts():
    return datetime.now()

# ==========================
# MQTT CALLBACKS
# ==========================
def on_connect(client, userdata, flags, rc):
    with LOCK:
        MQTT_STATE["connected"] = (rc == 0)
        MQTT_STATE["last_rc"] = rc
        MQTT_STATE["last_err"] = None
        MQTT_STATE["last_change"] = now_ts()

    if rc == 0:
        client.subscribe(userdata["topic_data"])
        # print utile dans logs Streamlit Cloud
        print("✅ MQTT connecté, abonné à", userdata["topic_data"])
    else:
        print("❌ MQTT connexion rc =", rc)

def on_disconnect(client, userdata, rc):
    with LOCK:
        MQTT_STATE["connected"] = False
        MQTT_STATE["last_rc"] = rc
        MQTT_STATE["last_change"] = now_ts()
    print("🔌 MQTT déconnecté rc =", rc)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8", errors="ignore"))
    except Exception as e:
        print("JSON invalide:", e)
        return

    t = now_ts()

    # Ton ESP32 publie : temperature, humidity, seuil, flame, flameHande, alarm...
    with LOCK:
        LAST["temperature"] = payload.get("temperature")
        LAST["humidity"] = payload.get("humidity")
        LAST["seuil"] = payload.get("seuil")  # IMPORTANT
        LAST["flame"] = payload.get("flame")
        LAST["flameHande"] = payload.get("flameHande")
        LAST["alarm"] = payload.get("alarm")
        LAST["alarmLocal"] = payload.get("alarmLocal")
        LAST["muted"] = payload.get("muted")
        LAST["motorForced"] = payload.get("motorForced")
        LAST["motorSpeed"] = payload.get("motorSpeed")
        LAST["last_update"] = t

        HISTORY.append({
            "time": t,
            "temperature": LAST["temperature"],
            "humidity": LAST["humidity"],
            "seuil": LAST["seuil"],
            "flame": LAST["flame"],
        })

# ==========================
# MQTT INIT (1 seule fois)
# ==========================
@st.cache_resource
def mqtt_start(broker: str, port: int, transport: str, topic_data: str, topic_cmd: str):
    """
    Démarre MQTT une seule fois (cache_resource).
    Si Streamlit rerun, le client reste le même.
    """
    cid = f"streamlit_{socket.gethostname()}_{os.getpid()}"
    client = mqtt.Client(client_id=cid, protocol=mqtt.MQTTv311, userdata={
        "topic_data": topic_data,
        "topic_cmd": topic_cmd
    })

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    # websockets option (si ton broker offre 9001 par ex)
    if transport == "websockets":
        client.transport = "websockets"

    try:
        client.connect_async(broker, port, keepalive=60)
        client.loop_start()
        with LOCK:
            MQTT_STATE["last_err"] = None
            MQTT_STATE["last_change"] = now_ts()
    except Exception as e:
        with LOCK:
            MQTT_STATE["connected"] = False
            MQTT_STATE["last_err"] = str(e)
            MQTT_STATE["last_change"] = now_ts()

    return client

def mqtt_publish(client: mqtt.Client, topic_cmd: str, cmd: str):
    try:
        client.publish(topic_cmd, cmd, qos=0, retain=False)
        st.toast(f"✅ Envoyé: {cmd}", icon="📡")
    except Exception as e:
        st.error(f"Publish MQTT impossible: {e}")

# ==========================
# CHARTS
# ==========================
def line_chart(df: pd.DataFrame, y: str, title: str, ytitle: str):
    return (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("time:T", title="Temps"),
            y=alt.Y(f"{y}:Q", title=ytitle),
            tooltip=["time:T", alt.Tooltip(f"{y}:Q")]
        )
        .properties(height=260, title=title)
    )

def fmt_metric(v, fmt="{:.1f}"):
    if v is None:
        return "—"
    try:
        if isinstance(v, (int, float)):
            return fmt.format(v)
        return str(v)
    except:
        return "—"

# ==========================
# SIDEBAR CONFIG (Cloud-friendly)
# ==========================
st.sidebar.title("⚙️ Connexion MQTT (Cloud)")
broker = st.sidebar.text_input("Broker", DEFAULT_BROKER)
transport = st.sidebar.selectbox("Transport", ["tcp", "websockets"], index=0)
port = st.sidebar.number_input("Port", min_value=1, max_value=65535, value=(9001 if transport=="websockets" else DEFAULT_PORT), step=1)

topic_data = st.sidebar.text_input("Topic DATA (ESP32 →)", DEFAULT_TOPIC_DATA)
topic_cmd  = st.sidebar.text_input("Topic CMD (Streamlit →)", DEFAULT_TOPIC_CMD)

refresh_s = st.sidebar.slider("Rafraîchissement UI (secondes)", 1, 10, 2)

st.sidebar.caption("💡 Si Cloud ne reçoit rien en TCP 1883, essaie WebSockets + port 9001 (si ton broker l’a).")

# Start MQTT once
client = mqtt_start(broker, int(port), transport, topic_data, topic_cmd)

# ==========================
# HEADER
# ==========================
st.markdown("""
<style>
  .stApp { background: radial-gradient(circle at top left, #f5f0ff 0, #dbe2ff 35%, #c8d9ff 65%, #b8d3ff 100%); }
</style>
""", unsafe_allow_html=True)

st.title("Gestion Intelligente Température & Sécurité – IoT")

# Snapshot
with LOCK:
    last = dict(LAST)
    hist = list(HISTORY)
    mqtt_state = dict(MQTT_STATE)

# Freshness
fresh = False
age_s = None
if last["last_update"] is not None:
    age_s = (datetime.now() - last["last_update"]).total_seconds()
    fresh = (age_s <= 8.0)

# MQTT status (pas de faux négatif)
if mqtt_state["connected"] or fresh:
    st.success("État MQTT : ✅ Connecté (ou données reçues récemment)")
else:
    st.error("État MQTT : 🔴 Déconnecté / aucune donnée récente")

cols = st.columns(3)
with cols[0]:
    st.caption(f"rc: {mqtt_state.get('last_rc')}")
with cols[1]:
    st.caption(f"Erreur: {mqtt_state.get('last_err')}")
with cols[2]:
    if age_s is None:
        st.caption("Dernière donnée: —")
    else:
        st.caption(f"Dernière donnée: ~{age_s:.1f}s")

st.divider()

# ==========================
# METRICS
# ==========================
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.subheader("🌡️ Température")
    st.metric("Temp (°C)", fmt_metric(last["temperature"]))
with c2:
    st.subheader("💧 Humidité")
    st.metric("Hum (%)", fmt_metric(last["humidity"], "{:.0f}"))
with c3:
    st.subheader("📦 Seuil (ESP32)")
    if last["seuil"] is None:
        st.metric("Seuil (°C)", "— (non reçu)")
    else:
        st.metric("Seuil (°C)", f"{float(last['seuil']):.1f}")
with c4:
    st.subheader("🚨 Alarme")
    if last["alarm"] is True:
        st.error("Alarme ACTIVE")
    else:
        st.success("Alarme inactive")

st.divider()

# ==========================
# FLAME STATUS
# ==========================
f1, f2 = st.columns(2)
with f1:
    st.subheader("🔥 Flamme (Steffy)")
    if last["flame"] is None:
        st.info("En attente (flame=None)")
    elif int(last["flame"]) == 1:
        st.error("🔥 Feu détecté (flame=1)")
    else:
        st.success("✅ Aucun feu (flame=0)")

with f2:
    st.subheader("🔥 Flamme binôme (Hande)")
    fh = last["flameHande"]
    if fh is None:
        st.info("En attente (flameHande=None)")
    elif int(fh) == 1:
        st.warning("⚠️ Flamme chez la binôme (flameHande=1)")
    else:
        st.success("✅ Pas de flamme chez la binôme (flameHande=0)")

st.divider()

# ==========================
# COMMANDS
# ==========================
st.subheader(f"🎛️ Commandes vers la binôme (topic: `{topic_cmd}`)")
b1, b2, b3 = st.columns([1, 1, 3])
with b1:
    if st.button("🔴 LED ROUGE ON", use_container_width=True):
        mqtt_publish(client, topic_cmd, CMD_LED_ON)
with b2:
    if st.button("⚫ LED ROUGE OFF", use_container_width=True):
        mqtt_publish(client, topic_cmd, CMD_LED_OFF)
with b3:
    st.info("Ta binôme doit SUBSCRIBE à `noeud/operateur/cmd` et exécuter LED_RED_ON / LED_RED_OFF.")

st.divider()

# ==========================
# REALTIME CURVES
# ==========================
st.subheader("📈 Graphiques en temps réel (courbes)")
if len(hist) == 0:
    st.info(f"En attente de données sur `{topic_data}`…")
else:
    df = pd.DataFrame(hist).dropna(subset=["time"]).tail(200)

    g1, g2 = st.columns(2)
    with g1:
        st.altair_chart(line_chart(df, "temperature", "Température", "Température (°C)"),
                        use_container_width=True)
    with g2:
        st.altair_chart(line_chart(df, "humidity", "Humidité", "Humidité (%)"),
                        use_container_width=True)

    g3, g4 = st.columns(2)
    with g3:
        st.altair_chart(line_chart(df, "seuil", "Seuil", "Seuil (°C)"),
                        use_container_width=True)
    with g4:
        st.altair_chart(line_chart(df, "flame", "Flamme", "Flamme (0/1)"),
                        use_container_width=True)

st.divider()

# ==========================
# DIAGNOSTIC + CSV DOWNLOAD
# ==========================
d1, d2 = st.columns(2)
with d1:
    st.subheader("🩺 Dernier JSON")
    st.json(last)

with d2:
    st.subheader("📁 Outils")
    if st.button("🗑️ Effacer l'historique"):
        with LOCK:
            HISTORY.clear()
        st.success("Historique effacé")

    if len(hist) > 0:
        df_all = pd.DataFrame(hist)
        st.download_button(
            "💾 Télécharger l’historique CSV",
            data=df_all.to_csv(index=False).encode("utf-8"),
            file_name="historique_mesures.csv",
            mime="text/csv",
        )

# ==========================
# AUTO-REFRESH SANS MODULE EXTERNE
# ==========================
time.sleep(refresh_s)
st.rerun()
