# dashboard_iot.py
# ✅ Streamlit Cloud + Local
# ✅ MQTT WebSockets (9001) => OK sur Streamlit Cloud
# ✅ 1 seul client MQTT (cache_resource)
# ✅ Données temps réel + courbes
# ✅ Boutons LED ON/OFF -> noeud/operateur/cmd

import os
import time
import json
import socket
import threading
from datetime import datetime
from collections import deque

import streamlit as st
import pandas as pd
import altair as alt
import paho.mqtt.client as mqtt

# ==========================
# CONFIG MQTT (FORCE WEBSOCKETS)
# ==========================
MQTT_BROKER = os.getenv("MQTT_BROKER", "51.103.239.173")
MQTT_PORT = int(os.getenv("MQTT_PORT", "9001"))          # ✅ WebSocket port
MQTT_WS_PATH = os.getenv("MQTT_WS_PATH", "/")            # mosquitto websockets default "/"
MQTT_TRANSPORT = "websockets"                            # ✅ force

TOPIC_DATA = os.getenv("TOPIC_DATA", "capteur/data")
TOPIC_CMD  = os.getenv("TOPIC_CMD",  "noeud/operateur/cmd")

CMD_LED_ON  = "LED_RED_ON"
CMD_LED_OFF = "LED_RED_OFF"

# ==========================
# LOGO (optionnel)
# ==========================
LOGO_FILENAME = "LOGO_EPHEC_HE.png"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, LOGO_FILENAME)

# ==========================
# ETAT PARTAGE (thread-safe)
# ==========================
LOCK = threading.Lock()
MQTT_CONNECTED = False
MQTT_RC = None
MQTT_LAST_LOG = ""
MQTT_LAST_MSG_AT = None

LAST = {
    "temperature": None,
    "humidity": None,
    "seuil": None,
    "flame": None,
    "flameHande": None,
    "alarm": None,
    "last_update": None,
}

HISTORY = deque(maxlen=500)

# ==========================
# MQTT CALLBACKS
# ==========================
def on_log(client, userdata, level, buf):
    global MQTT_LAST_LOG
    with LOCK:
        MQTT_LAST_LOG = buf

def on_connect(client, userdata, flags, rc):
    global MQTT_CONNECTED, MQTT_RC
    with LOCK:
        MQTT_CONNECTED = (rc == 0)
        MQTT_RC = rc

    if rc == 0:
        client.subscribe(TOPIC_DATA, qos=0)
        print(f"✅ MQTT connecté (WS), abonné à {TOPIC_DATA} | {MQTT_BROKER}:{MQTT_PORT}{MQTT_WS_PATH}")
    else:
        print("❌ MQTT erreur connexion rc =", rc)

def on_disconnect(client, userdata, rc):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = False
    print("🔌 MQTT déconnecté rc =", rc)

def on_message(client, userdata, msg):
    global MQTT_LAST_MSG_AT
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print("JSON invalide :", e, "payload=", msg.payload[:120])
        return

    now = datetime.now()
    with LOCK:
        MQTT_LAST_MSG_AT = now
        LAST["temperature"] = payload.get("temperature")
        LAST["humidity"]    = payload.get("humidity")
        LAST["seuil"]       = payload.get("seuil")
        LAST["flame"]       = payload.get("flame")
        LAST["flameHande"]  = payload.get("flameHande")
        LAST["alarm"]       = payload.get("alarm")
        LAST["last_update"] = now

        HISTORY.append({
            "time": now,
            "temperature": LAST["temperature"],
            "humidity": LAST["humidity"],
            "seuil": LAST["seuil"],
            "flame": LAST["flame"],
        })

# ==========================
# MQTT CLIENT (1 seule fois)
# ==========================
@st.cache_resource
def init_mqtt_client():
    cid = f"streamlit_{socket.gethostname()}_{os.getpid()}"

    client = mqtt.Client(
        client_id=cid,
        protocol=mqtt.MQTTv311,
        transport="websockets"  # ✅ essentiel pour Streamlit Cloud
    )
    client.ws_set_options(path=MQTT_WS_PATH)

    client.on_log = on_log
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    client.reconnect_delay_set(min_delay=1, max_delay=10)
    client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client

def mqtt_publish(cmd: str):
    c = init_mqtt_client()
    try:
        c.publish(TOPIC_CMD, cmd, qos=0, retain=False)
    except Exception as e:
        st.error(f"Erreur publish MQTT: {e}")

# ==========================
# UI helpers
# ==========================
def metric_value(v, fmt="{:.1f}"):
    if v is None:
        return "—"
    try:
        return fmt.format(float(v))
    except Exception:
        return str(v)

def build_line_chart(df: pd.DataFrame, y: str, title: str, ytitle: str):
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

def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# ==========================
# MAIN
# ==========================
def main():
    st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")
    init_mqtt_client()

    # CSS
    st.markdown("""
    <style>
      .stApp {
        background: radial-gradient(circle at top left, #f5f0ff 0, #dbe2ff 35%, #c8d9ff 65%, #b8d3ff 100%);
      }
      h1 { font-weight: 800; }
    </style>
    """, unsafe_allow_html=True)

    # Header
    col_logo, col_title = st.columns([1, 6])
    with col_logo:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=120)
        else:
            st.write("EPHEC")
    with col_title:
        st.title("Gestion Intelligente Température & Sécurité – IoT")
        st.caption(f"Broker: {MQTT_BROKER} | transport=websockets | port={MQTT_PORT} | path={MQTT_WS_PATH}")

    with LOCK:
        last = dict(LAST)
        hist = list(HISTORY)
        connected = MQTT_CONNECTED
        rc = MQTT_RC
        last_log = MQTT_LAST_LOG
        last_msg_at = MQTT_LAST_MSG_AT

    # Freshness
    fresh = False
    age_s = None
    if last_msg_at is not None:
        age_s = (datetime.now() - last_msg_at).total_seconds()
        fresh = age_s <= 10

    if connected or fresh:
        st.success(f"MQTT ✅ Connecté (ou data récente) | rc={rc}")
    else:
        st.error(f"MQTT 🔴 Déconnecté / aucune donnée récente | rc={rc}")

    if age_s is not None:
        st.caption(f"Dernier message MQTT: ~{age_s:.1f} s")
    st.caption(f"Dernier log MQTT: {last_log}")

    st.markdown("---")

    # Cartes
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.subheader("🌡️ Température")
        st.metric("Temp (°C)", metric_value(last["temperature"]))
    with c2:
        st.subheader("💧 Humidité")
        st.metric("Hum (%)", metric_value(last["humidity"], "{:.0f}"))
    with c3:
        st.subheader("📦 Seuil (ESP32)")
        st.metric("Seuil (°C)", "—" if last["seuil"] is None else metric_value(last["seuil"]))
    with c4:
        st.subheader("🚨 Alarme")
        st.error("Alarme ACTIVE") if last["alarm"] else st.success("Alarme inactive")

    st.markdown("---")

    # Flamme
    f1, f2 = st.columns(2)
    with f1:
        st.subheader("🔥 Flamme (Steffy)")
        st.write("Valeur:", last["flame"])
    with f2:
        st.subheader("🔥 Flamme binôme (Hande)")
        st.write("Valeur:", last["flameHande"])

    st.markdown("---")

    # Commandes
    st.subheader(f"🎛️ Commandes vers la binôme (topic: {TOPIC_CMD})")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("🔴 LED ROUGE ON", use_container_width=True):
            mqtt_publish(CMD_LED_ON)
            st.toast("Commande envoyée", icon="📡")
    with b2:
        if st.button("⚫ LED ROUGE OFF", use_container_width=True):
            mqtt_publish(CMD_LED_OFF)
            st.toast("Commande envoyée", icon="📡")

    st.markdown("---")

    # Graphiques
    st.subheader("📈 Courbes (temps réel)")
    if len(hist) == 0:
        st.info("En attente de données sur capteur/data…")
    else:
        df = pd.DataFrame(hist).dropna(subset=["time"]).tail(250)

        g1, g2 = st.columns(2)
        with g1:
            st.altair_chart(build_line_chart(df, "temperature", "Température", "Température (°C)"),
                            use_container_width=True)
        with g2:
            st.altair_chart(build_line_chart(df, "humidity", "Humidité", "Humidité (%)"),
                            use_container_width=True)

        g3, g4 = st.columns(2)
        with g3:
            st.altair_chart(build_line_chart(df, "seuil", "Seuil (ESP32)", "Seuil (°C)"),
                            use_container_width=True)
        with g4:
            st.altair_chart(build_line_chart(df, "flame", "Flamme", "Flamme (0/1)"),
                            use_container_width=True)

    st.markdown("---")

    # Debug JSON
    with st.expander("🩺 Dernier JSON reçu", expanded=False):
        st.json(last)

    # Refresh UI
    st.sidebar.markdown("### 🔄 Rafraîchissement UI")
    refresh_s = st.sidebar.slider("Secondes", 1, 10, 2)
    time.sleep(refresh_s)
    safe_rerun()

if __name__ == "__main__":
    main()
