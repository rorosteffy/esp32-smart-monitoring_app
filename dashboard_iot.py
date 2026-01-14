# dashboard_iot.py
# ✅ Streamlit Cloud + Local
# ✅ MQTT stable (1 seul client + loop_start)
# ✅ Temps réel (rafraîchissement UI)
# ✅ Compatible paho-mqtt v2 (Callback API v2)
# ✅ Lit les clés: temperature, humidity, seuil, flame, flameHande, alarm, ...

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
MQTT_BROKER = "51.103.239.173"

# Streamlit Cloud ➜ WebSockets (Mosquitto listener 9001)
MQTT_WS_PORT = 9001
MQTT_WS_PATH = "/"          # si ton mosquitto est en /mqtt -> mets "/mqtt"

# Local/VM ➜ TCP (si tu veux tester en local)
MQTT_TCP_PORT = 1883

TOPIC_DATA = "capteur/data"

# ==========================
# LOGO
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
    "alarm": None,
    "alarmLocal": None,
    "muted": None,
    "motorForced": None,
    "motorSpeed": None,
    "last_update": None,
}

HISTORY = deque(maxlen=300)  # derniers points (≈ 300 rafraîchissements)


# ==========================
# MQTT CALLBACKS (paho v2)
# ==========================
def on_connect(client, userdata, flags, reason_code, properties=None):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = (reason_code == 0)

    if reason_code == 0:
        client.subscribe(TOPIC_DATA, qos=0)
        print("✅ MQTT CONNECTED, subscribed:", TOPIC_DATA)
    else:
        print("❌ MQTT connect error reason_code =", reason_code)


def on_disconnect(client, userdata, reason_code, properties=None):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = False
    print("🔌 MQTT disconnected reason_code =", reason_code)


def on_message(client, userdata, msg):
    global LAST, HISTORY
    raw = None
    try:
        raw = msg.payload.decode("utf-8", errors="ignore").strip()
        payload = json.loads(raw)
    except Exception as e:
        print("❌ JSON invalide:", e, "payload=", (raw[:200] if raw else msg.payload[:120]))
        return

    now = datetime.now()

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
# MQTT CLIENT (1 SEUL)
# ==========================
@st.cache_resource
def init_mqtt_client(use_ws: bool = True):
    """
    1 seul client MQTT par process Streamlit.
    - Streamlit Cloud: use_ws=True (WebSockets)
    - Local: tu peux mettre use_ws=False (TCP)
    """
    cid = f"st_{socket.gethostname()}_{os.getpid()}_{int(time.time())}"

    if use_ws:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=cid,
            protocol=mqtt.MQTTv311,
            transport="websockets",
        )
        # path websocket
        try:
            client.ws_set_options(path=MQTT_WS_PATH)
        except Exception:
            pass

        port = MQTT_WS_PORT
        print(f"🌐 MQTT mode: WebSockets {MQTT_BROKER}:{port} path={MQTT_WS_PATH}")

    else:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=cid,
            protocol=mqtt.MQTTv311,
            transport="tcp",
        )
        port = MQTT_TCP_PORT
        print(f"🖧 MQTT mode: TCP {MQTT_BROKER}:{port}")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    client.reconnect_delay_set(min_delay=1, max_delay=10)

    client.connect_async(MQTT_BROKER, port, keepalive=60)
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
# MAIN
# ==========================
def main():
    st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")

    # Sidebar: choix WS/TCP (par défaut WS pour Streamlit Cloud)
    st.sidebar.markdown("## ⚙️ Configuration")
    mode = st.sidebar.radio("Mode de connexion MQTT", ["WebSockets (Cloud)", "TCP (Local/VM)"], index=0)
    use_ws = (mode.startswith("WebSockets"))

    # start mqtt (1 seule fois)
    init_mqtt_client(use_ws=use_ws)

    # style
    st.markdown("""
    <style>
      .stApp {
        background: radial-gradient(circle at top left, #f5f0ff 0, #dbe2ff 35%, #c8d9ff 65%, #b8d3ff 100%);
        color: #0f172a;
      }
      h1 { font-weight: 800; }
    </style>
    """, unsafe_allow_html=True)

    # header
    col_logo, col_title = st.columns([1, 6])
    with col_logo:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=120)
        else:
            st.write("EPHEC")
    with col_title:
        st.title("Gestion Intelligente Température & Sécurité – IoT")

    # snapshot thread-safe
    with LOCK:
        last = dict(LAST)
        hist = list(HISTORY)
        connected = MQTT_CONNECTED

    # freshness
    fresh = False
    age_s = None
    if last["last_update"] is not None:
        age_s = (datetime.now() - last["last_update"]).total_seconds()
        fresh = (age_s <= 8.0)

    st.caption(f"Broker: {MQTT_BROKER} | topic: {TOPIC_DATA} | "
               f"{'WS:'+str(MQTT_WS_PORT) if use_ws else 'TCP:'+str(MQTT_TCP_PORT)}")

    if connected or fresh:
        st.success("État MQTT : ✅ Connecté (ou données reçues récemment)")
    else:
        if use_ws:
            st.error("État MQTT : 🔴 Déconnecté / aucune donnée récente → "
                     "vérifie Mosquitto WebSockets + port 9001 ouvert (Azure + UFW)")
        else:
            st.error("État MQTT : 🔴 Déconnecté / aucune donnée récente → vérifie port 1883 ouvert")

    if age_s is not None:
        st.caption(f"Dernière donnée reçue il y a ~{age_s:.1f} s")

    st.markdown("---")

    # cartes
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
        if last["alarm"] is True or last["alarm"] == 1:
            st.error("Alarme ACTIVE")
        elif last["alarm"] is False or last["alarm"] == 0:
            st.success("Alarme inactive")
        else:
            st.info("En attente…")

    st.markdown("---")

    # flamme
    f1, f2 = st.columns(2)
    with f1:
        st.subheader("🔥 IR / Flamme (Steffy)")
        fl = last["flame"]
        if fl is None:
            st.info("En attente (flame=None)…")
        else:
            try:
                fl_int = int(fl)
                if fl_int == 1:
                    st.error("🔥 Feu détecté (flame=1)")
                else:
                    st.success("✅ Pas de flamme (flame=0)")
            except Exception:
                st.warning(f"Valeur inconnue: {fl}")

    with f2:
        st.subheader("🔥 Flamme binôme (Hande)")
        fh = last["flameHande"]
        if fh is None:
            st.info("En attente (flameHande=None)…")
        else:
            try:
                fh_int = int(fh)
                if fh_int == 1:
                    st.warning("⚠️ Flamme chez la binôme (flameHande=1)")
                else:
                    st.success("✅ Pas de flamme chez la binôme (flameHande=0)")
            except Exception:
                st.warning(f"Valeur inconnue: {fh}")

    st.markdown("---")

    # graph
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

    # diagnostic
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

    # refresh UI
    st.sidebar.markdown("## 🔄 Rafraîchissement UI")
    refresh_s = st.sidebar.slider("Toutes les (secondes)", 1, 10, 2)

    time.sleep(refresh_s)
    safe_rerun()


if __name__ == "__main__":
    main()
