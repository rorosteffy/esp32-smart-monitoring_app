# dashboard_iot.py
# ✅ Streamlit Cloud compatible (MQTT WebSockets)
# ✅ 1 seul client MQTT (pas de fuite)
# ✅ Données temps réel + historiques
# ✅ Garde ton style dashboard (cartes + bar charts)
# ✅ Pas d'écriture fichier obligatoire (Streamlit Cloud n'aime pas trop)

import os
import json
import time
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
MQTT_BROKER = "51.103.239.173"

# IMPORTANT:
# - Streamlit Cloud -> WebSockets (souvent 1883 bloqué)
# - Ton Mosquitto expose déjà 9001 (websockets)
MQTT_WS_PORT = 9001
MQTT_WS_PATH = "/"          # dans tes logs: path=/
MQTT_TCP_PORT = 1883        # utile en local seulement

TOPIC_DATA = "capteur/data"

# ==========================
# LOGO
# ==========================
LOGO_FILENAME = "LOGO_EPHEC_HE.png"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, LOGO_FILENAME)

# ==========================
# ETAT PARTAGE (THREAD SAFE)
# ==========================
LOCK = threading.Lock()
MQTT_CONNECTED = False

LAST = {
    "temperature": None,
    "humidity": None,
    # D'après ton code ESP32: seuil + potRaw ne sont PAS envoyés en "pot/seuilPot"
    # mais tu envoies: "seuil" (float), et pas "pot"
    "seuil": None,
    "flame": None,
    "flameHande": None,
    "alarm": None,
    "alarmLocal": None,
    "muted": None,
    "motorForced": None,
    "motorSpeed": None,
    "last_update": None,
}

HISTORY = deque(maxlen=300)   # 300 derniers points (temps réel)


# ==========================
# MQTT CALLBACKS (API v2)
# ==========================
def on_connect(client, userdata, flags, reason_code, properties=None):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = (reason_code == 0)

    if reason_code == 0:
        client.subscribe(TOPIC_DATA, qos=0)
        print("✅ MQTT connecté (WS), abonné à", TOPIC_DATA)
    else:
        print("❌ MQTT erreur connexion reason_code =", reason_code)


def on_disconnect(client, userdata, reason_code, properties=None):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = False
    print("🔌 MQTT déconnecté reason_code =", reason_code)


def on_message(client, userdata, msg):
    global LAST, HISTORY

    try:
        payload = json.loads(msg.payload.decode("utf-8", errors="ignore"))
    except Exception as e:
        print("JSON invalide :", e, "payload=", msg.payload[:80])
        return

    now = datetime.now()

    # Ton ESP32 publie: temperature, humidity, seuil, flame, flameHande, alarm, alarmLocal, muted, motorForced, motorSpeed
    with LOCK:
        LAST["temperature"] = payload.get("temperature")
        LAST["humidity"] = payload.get("humidity")
        LAST["seuil"] = payload.get("seuil")
        LAST["flame"] = payload.get("flame")
        LAST["flameHande"] = payload.get("flameHande")
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
    Un seul client MQTT par process Streamlit.
    On force WebSockets (Streamlit Cloud friendly).
    """
    cid = f"st_{socket.gethostname()}_{os.getpid()}"
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=cid,
        transport="websockets",
        protocol=mqtt.MQTTv311,
    )

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    # Options WebSocket (PATH important)
    client.ws_set_options(path=MQTT_WS_PATH)

    # Reconnect auto
    client.reconnect_delay_set(min_delay=1, max_delay=10)

    # Connexion async + loop thread
    client.connect_async(MQTT_BROKER, MQTT_WS_PORT, keepalive=60)
    client.loop_start()
    return client


# ==========================
# UI HELPERS
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


def bar_chart(df, y, title, ytitle):
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
# MAIN DASHBOARD
# ==========================
def main():
    st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")

    # Démarre MQTT (1 fois)
    init_mqtt_client()

    # CSS (comme ton style)
    st.markdown(
        """
        <style>
          .stApp {
            background: radial-gradient(circle at top left, #f5f0ff 0, #dbe2ff 35%, #c8d9ff 65%, #b8d3ff 100%);
            color: #0f172a;
          }
          h1 { font-weight: 800; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Header
    col_logo, col_title = st.columns([1, 6])
    with col_logo:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=110)
        else:
            st.write("EPHEC")
    with col_title:
        st.title("Gestion Intelligente Température & Sécurité – IoT")
        st.caption(f"Broker: {MQTT_BROKER} | transport=websockets | port={MQTT_WS_PORT} | path={MQTT_WS_PATH}")

    # Snapshot thread-safe
    with LOCK:
        last = dict(LAST)
        hist = list(HISTORY)
        connected = MQTT_CONNECTED

    # Fraîcheur data
    fresh = False
    age_s = None
    if last["last_update"] is not None:
        age_s = (datetime.now() - last["last_update"]).total_seconds()
        fresh = (age_s <= 8.0)

    # Etat
    if connected or fresh:
        st.success("État MQTT : ✅ Connecté (ou données reçues récemment)")
    else:
        st.warning("En attente de données MQTT… (vérifie que l’ESP32 publie bien sur capteur/data)")

    if age_s is not None:
        st.caption(f"Dernière donnée reçue il y a ~{age_s:.1f} s")

    st.markdown("---")

    # Cartes
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.subheader("🌡️ Température")
        st.metric("Température (°C)", metric_value(last["temperature"]))
    with c2:
        st.subheader("💧 Humidité")
        st.metric("Humidité (%)", metric_value(last["humidity"], "{:.0f}"))
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

    # Flamme
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
            st.warning("⚠️ Flamme chez la binôme (flameHande=1)")
        else:
            st.success("✅ Pas de flamme chez la binôme (flameHande=0)")

    st.markdown("---")

    # Graphiques (BARRES) comme ton dashboard
    st.subheader("📊 Graphiques en temps réel")
    if len(hist) == 0:
        st.info("En attente de données temps réel…")
    else:
        df = pd.DataFrame(hist).tail(120)

        g1, g2 = st.columns(2)
        with g1:
            st.altair_chart(bar_chart(df, "temperature", "Température (barres)", "°C"), use_container_width=True)
        with g2:
            st.altair_chart(bar_chart(df, "humidity", "Humidité (barres)", "%"), use_container_width=True)

        g3, g4 = st.columns(2)
        with g3:
            st.altair_chart(bar_chart(df, "seuil", "Seuil (barres)", "°C"), use_container_width=True)
        with g4:
            st.altair_chart(bar_chart(df, "flame", "Flamme (barres)", "0/1"), use_container_width=True)

    st.markdown("---")

    # Diagnostic
    st.subheader("🩺 Diagnostic")
    st.json(last)

    # Refresh UI
    st.sidebar.markdown("### 🔄 Rafraîchissement")
    refresh_s = st.sidebar.slider("Refresh UI (secondes)", 1, 10, 2)

    time.sleep(refresh_s)
    safe_rerun()


if __name__ == "__main__":
    main()
