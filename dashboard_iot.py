# dashboard_iot.py
# ✅ Streamlit Cloud (WebSockets) + Local (TCP) fallback
# ✅ 1 seul client MQTT (stable)
# ✅ Lit les BONNES clés JSON de ton ESP32 (seuil, flameHande, alarm...)
# ✅ Graph temps réel + UI propre

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
# CONFIG MQTT
# ==========================
MQTT_BROKER = os.getenv("MQTT_BROKER", "51.103.239.173")

# Streamlit Cloud => websockets (9001)
MQTT_WS_PORT = int(os.getenv("MQTT_WS_PORT", "9001"))
MQTT_WS_PATH = os.getenv("MQTT_WS_PATH", "/")  # si besoin: "/mqtt"

# Local => TCP classique (1883)
MQTT_TCP_PORT = int(os.getenv("MQTT_TCP_PORT", "1883"))

TOPIC_DATA = "capteur/data"

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

LAST = {
    "temperature": None,
    "humidity": None,
    "seuil": None,
    "flame": None,
    "flameHande": None,
    "alarmTemp": None,
    "alarmFlame": None,
    "alarm": None,
    "alarmLocal": None,
    "muted": None,
    "motorForced": None,
    "motorSpeed": None,
    "last_update": None,
}

HISTORY = deque(maxlen=400)

# ==========================
# MQTT CALLBACKS
# ==========================
def on_connect(client, userdata, flags, rc, properties=None):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = (rc == 0)

    if rc == 0:
        client.subscribe(TOPIC_DATA, qos=0)
        print("✅ MQTT connecté, abonné à", TOPIC_DATA)
    else:
        print("❌ MQTT erreur rc =", rc)

def on_disconnect(client, userdata, rc, properties=None):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = False
    print("🔌 MQTT déconnecté rc =", rc)

def on_message(client, userdata, msg):
    global LAST, HISTORY
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print("JSON invalide:", e)
        return

    now = datetime.now()

    # ✅ correspond EXACTEMENT à ton JSON ESP32 vu dans mosquitto_sub
    with LOCK:
        LAST["temperature"] = payload.get("temperature")
        LAST["humidity"] = payload.get("humidity")
        LAST["seuil"] = payload.get("seuil")
        LAST["flame"] = payload.get("flame")
        LAST["flameHande"] = payload.get("flameHande")
        LAST["alarmTemp"] = payload.get("alarmTemp")
        LAST["alarmFlame"] = payload.get("alarmFlame")
        LAST["alarm"] = payload.get("alarm")
        LAST["alarmLocal"] = payload.get("alarmLocal")
        LAST["muted"] = payload.get("muted")
        LAST["motorForced"] = payload.get("motorForced")
        LAST["motorSpeed"] = payload.get("motorSpeed")
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
    """
    Streamlit => 1 seul client par process.
    D'abord WebSockets (Cloud), si échec -> fallback TCP (local).
    """
    cid = f"st_{socket.gethostname()}_{os.getpid()}"
    client = mqtt.Client(
        client_id=cid,
        protocol=mqtt.MQTTv311,
        transport="websockets"
    )

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    # options websockets
    try:
        client.ws_set_options(path=MQTT_WS_PATH)
    except Exception:
        pass

    client.reconnect_delay_set(min_delay=1, max_delay=10)

    # 1) tentative websockets
    try:
        print(f"➡️ Try WS {MQTT_BROKER}:{MQTT_WS_PORT} path={MQTT_WS_PATH}")
        client.connect_async(MQTT_BROKER, MQTT_WS_PORT, keepalive=60)
        client.loop_start()
        return client
    except Exception as e:
        print("WS fail:", e)

    # 2) fallback TCP
    client = mqtt.Client(client_id=cid, protocol=mqtt.MQTTv311, transport="tcp")
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    print(f"➡️ Fallback TCP {MQTT_BROKER}:{MQTT_TCP_PORT}")
    client.connect_async(MQTT_BROKER, MQTT_TCP_PORT, keepalive=60)
    client.loop_start()
    return client

# ==========================
# UI helpers
# ==========================
def metric_value(v, fmt="{:.1f}"):
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        try:
            return fmt.format(float(v))
        except Exception:
            return str(v)
    return str(v)

def build_bar(df: pd.DataFrame, y: str, title: str, ytitle: str):
    return (
        alt.Chart(df)
        .mark_bar()
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

    # démarre MQTT
    init_mqtt_client()

    st.markdown("""
    <style>
      .stApp {
        background: radial-gradient(circle at top left, #f5f0ff 0, #dbe2ff 35%, #c8d9ff 65%, #b8d3ff 100%);
      }
      h1 { font-weight: 800; }
    </style>
    """, unsafe_allow_html=True)

    col_logo, col_title = st.columns([1, 6])
    with col_logo:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=120)
        else:
            st.write("EPHEC")
    with col_title:
        st.title("Gestion Intelligente Température & Sécurité – IoT")
        st.caption(f"Broker: {MQTT_BROKER} | WS:{MQTT_WS_PORT}{MQTT_WS_PATH} | TCP:{MQTT_TCP_PORT}")

    with LOCK:
        last = dict(LAST)
        hist = list(HISTORY)
        connected = MQTT_CONNECTED

    fresh = False
    age_s = None
    if last["last_update"] is not None:
        age_s = (datetime.now() - last["last_update"]).total_seconds()
        fresh = (age_s <= 8.0)

    if connected or fresh:
        st.success("État MQTT : ✅ Connecté / données récentes")
    else:
        st.error("En attente de données MQTT… (Cloud: vérifie WebSockets port 9001 ouvert)")

    if age_s is not None:
        st.caption(f"Dernière donnée reçue il y a ~{age_s:.1f} s")

    st.markdown("---")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.subheader("🌡️ Température")
        st.metric("Temp (°C)", metric_value(last["temperature"]))
    with c2:
        st.subheader("💧 Humidité")
        st.metric("Hum (%)", metric_value(last["humidity"], "{:.0f}"))
    with c3:
        st.subheader("📦 Seuil (ESP32)")
        st.metric("Seuil (°C)", metric_value(last["seuil"]))
    with c4:
        st.subheader("🚨 Alarme")
        if last["alarm"] is True:
            st.error("Alarme ACTIVE")
        else:
            st.success("Alarme inactive")

    st.markdown("---")

    c5, c6 = st.columns(2)
    with c5:
        st.subheader("🔥 IR / Flamme (Steffy)")
        f = last["flame"]
        if f is None:
            st.info("En attente (flame=None)…")
        elif int(f) == 1:
            st.error("🔥 Feu détecté (flame=1)")
        else:
            st.success("✅ Pas de flamme (flame=0)")

    with c6:
        st.subheader("🔥 Flamme binôme (Hande)")
        fh = last["flameHande"]
        if fh is None:
            st.info("En attente (flameHande=None)…")
        elif int(fh) == 1:
            st.warning("⚠️ Flamme chez la binôme")
        else:
            st.success("✅ Pas de flamme chez la binôme")

    st.markdown("---")

    st.subheader("📊 Graphiques en temps réel (barres)")
    if len(hist) == 0:
        st.info("En attente de données sur capteur/data…")
    else:
        df = pd.DataFrame(hist).tail(120)

        g1, g2 = st.columns(2)
        with g1:
            st.altair_chart(build_bar(df, "temperature", "Température", "°C"), use_container_width=True)
        with g2:
            st.altair_chart(build_bar(df, "humidity", "Humidité", "%"), use_container_width=True)

        g3, g4 = st.columns(2)
        with g3:
            st.altair_chart(build_bar(df, "seuil", "Seuil", "°C"), use_container_width=True)
        with g4:
            st.altair_chart(build_bar(df, "flame", "Flamme", "0/1"), use_container_width=True)

    st.markdown("---")
    st.subheader("🩺 Diagnostic")
    st.json(last)

    st.sidebar.markdown("### 🔄 Rafraîchissement")
    refresh_s = st.sidebar.slider("Refresh UI (secondes)", 1, 10, 2)

    time.sleep(refresh_s)
    safe_rerun()

if __name__ == "__main__":
    main()
