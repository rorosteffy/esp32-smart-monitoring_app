# dashboard_iot.py
# ✅ Streamlit Cloud + Local
# ✅ MQTT stable (1 seul client, loop_start)
# ✅ Temps réel (rafraîchissement UI)
# ✅ Compatible paho-mqtt v1/v2 (properties=None)
# ✅ Lit les clés ESP32: temperature, humidity, seuil, flame, flameHande, alarm, ...

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
# CONFIG
# ==========================
MQTT_BROKER = "51.103.239.173"

# Streamlit Cloud ➜ WebSocket
MQTT_WS_PORT = 9001
MQTT_WS_PATH = "/"          # souvent "/" (ou "/mqtt" selon config mosquitto)

# Local/VM ➜ TCP
MQTT_TCP_PORT = 1883

TOPIC_DATA = "capteur/data"

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
    "alarm": None,
    "alarmLocal": None,
    "muted": None,
    "motorForced": None,
    "motorSpeed": None,
    "last_update": None,
}

HISTORY = deque(maxlen=300)   # 300 derniers points


# ==========================
# MQTT CALLBACKS (paho v1/v2)
# ==========================
def on_connect(client, userdata, flags, rc, properties=None):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = (rc == 0)

    if rc == 0:
        client.subscribe(TOPIC_DATA, qos=0)
        print("✅ MQTT CONNECTED, subscribed:", TOPIC_DATA)
    else:
        print("❌ MQTT connect error rc =", rc)


def on_disconnect(client, userdata, rc, properties=None):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = False
    print("🔌 MQTT disconnected rc =", rc)


def on_message(client, userdata, msg):
    global LAST, HISTORY
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print("❌ JSON invalide:", e, "payload=", msg.payload[:120])
        return

    now = datetime.now()

    # ⚠️ Ton ESP32 publie : temperature, humidity, seuil, flame, flameHande, alarm, ...
    with LOCK:
        LAST["temperature"] = payload.get("temperature")
        LAST["humidity"] = payload.get("humidity")
        LAST["seuil"] = payload.get("seuil")
        LAST["flame"] = payload.get("flame")
        LAST["flameHande"] = payload.get("flameHande")  # ton JSON VM montre flameHande
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
# MQTT CLIENT (1 SEUL)
# ==========================
@st.cache_resource
def init_mqtt_client():
    """
    1 seul client MQTT par process Streamlit.
    - En Cloud: WebSockets (port 9001)
    - En local: si tu veux TCP, tu peux switcher dans la sidebar
    """
    # ID unique
    cid = f"st_{socket.gethostname()}_{os.getpid()}"

    # On crée le client en WebSocket (Cloud-friendly)
    client = mqtt.Client(
        client_id=cid,
        protocol=mqtt.MQTTv311,
        transport="websockets"
    )

    # Optionnel : path websocket
    try:
        client.ws_set_options(path=MQTT_WS_PATH)
    except Exception:
        pass

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    client.reconnect_delay_set(min_delay=1, max_delay=10)

    # Connexion async + loop thread interne
    client.connect_async(MQTT_BROKER, MQTT_WS_PORT, keepalive=60)
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


def bar_chart(df: pd.DataFrame, y: str, title: str, ytitle: str):
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
# MAIN APP
# ==========================
def main():
    st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")

    # démarre MQTT (1 seule fois)
    init_mqtt_client()

    # --- CSS ---
    st.markdown("""
    <style>
      .stApp {
        background: radial-gradient(circle at top left, #f5f0ff 0, #dbe2ff 35%, #c8d9ff 65%, #b8d3ff 100%);
        color: #0f172a;
      }
      h1 { font-weight: 800; }
    </style>
    """, unsafe_allow_html=True)

    # --- Header ---
    col_logo, col_title = st.columns([1, 6])
    with col_logo:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=120)
        else:
            st.write("EPHEC")
    with col_title:
        st.title("Gestion Intelligente Température & Sécurité – IoT")

    # Snapshot thread-safe
    with LOCK:
        last = dict(LAST)
        hist = list(HISTORY)
        connected = MQTT_CONNECTED

    # Data freshness
    fresh = False
    age_s = None
    if last["last_update"] is not None:
        age_s = (datetime.now() - last["last_update"]).total_seconds()
        fresh = (age_s <= 8.0)

    # Statut
    st.caption(f"Broker: {MQTT_BROKER} | WS:{MQTT_WS_PORT} | topic:{TOPIC_DATA}")
    if connected or fresh:
        st.success("État MQTT : ✅ Connecté (ou données reçues récemment)")
    else:
        st.error("État MQTT : 🔴 Déconnecté / aucune donnée récente (vérifie WS port 9001 ouvert)")

    if age_s is not None:
        st.caption(f"Dernière donnée reçue il y a ~{age_s:.1f} s")

    st.markdown("---")

    # --- Cartes principales ---
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
        elif last["alarm"] is False:
            st.success("Alarme inactive")
        else:
            st.info("En attente…")

    st.markdown("---")

    # --- Flamme ---
    f1, f2 = st.columns(2)
    with f1:
        st.subheader("🔥 IR / Flamme (Steffy)")
        fl = last["flame"]
        if fl is None:
            st.info("En attente (flame=None)…")
        elif int(fl) == 1:
            st.error("🔥 Feu détecté (flame=1)")
        else:
            st.success("✅ Pas de flamme (flame=0)")

    with f2:
        st.subheader("🔥 Flamme binôme (Hande)")
        fh = last["flameHande"]
        if fh is None:
            st.info("En attente (flameHande=None)…")
        elif int(fh) == 1:
            st.warning("⚠️ Flamme chez la binôme (flameHande=1)")
        else:
            st.success("✅ Pas de flamme chez la binôme (flameHande=0)")

    st.markdown("---")

    # --- Graphiques temps réel (barres comme tu veux) ---
    st.subheader("📊 Graphiques en temps réel (barres)")

    if len(hist) == 0:
        st.info("En attente de données MQTT… (vérifie que l’ESP32 publie bien sur capteur/data)")
    else:
        df = pd.DataFrame(hist).tail(120)

        g1, g2 = st.columns(2)
        with g1:
            st.altair_chart(bar_chart(df, "temperature", "Température", "°C"), use_container_width=True)
        with g2:
            st.altair_chart(bar_chart(df, "humidity", "Humidité", "%"), use_container_width=True)

        g3, g4 = st.columns(2)
        with g3:
            st.altair_chart(bar_chart(df, "seuil", "Seuil (ESP32)", "°C"), use_container_width=True)
        with g4:
            st.altair_chart(bar_chart(df, "flame", "Flamme", "0/1"), use_container_width=True)

    st.markdown("---")

    # --- Diagnostic ---
    st.subheader("🩺 Diagnostic du système")
    d1, d2 = st.columns(2)
    with d1:
        st.write("Dernier JSON interprété :")
        st.json(last)

    with d2:
        if st.button("🗑️ Effacer l'historique"):
            with LOCK:
                HISTORY.clear()
            st.success("Historique effacé.")

        if len(hist) > 0:
            df_all = pd.DataFrame(hist)
            csv_data = df_all.to_csv(index=False).encode("utf-8")
            st.download_button(
                "💾 Télécharger l’historique CSV",
                data=csv_data,
                file_name="historique_mesures.csv",
                mime="text/csv",
            )

    # --- Refresh ---
    st.sidebar.markdown("### 🔄 Rafraîchissement UI")
    refresh_s = st.sidebar.slider("Toutes les (secondes)", 1, 10, 2)

    time.sleep(refresh_s)
    safe_rerun()


if __name__ == "__main__":
    main()
