# dashboard_iot.py
# Streamlit Cloud + Local
# MQTT WebSockets (9001) pour Streamlit Cloud
# Compatible paho-mqtt v2 (Callback API v2)
# Ecoute capteur/data (JSON) et affiche en temps réel

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

# Streamlit Cloud -> WebSockets
MQTT_WS_PORT = 9001
MQTT_WS_PATH = "/"          # si ton mosquitto est en /mqtt -> mets "/mqtt"

# Local/VM -> TCP (optionnel)
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
    "motorOn": None,
    "timestamp": None,
    "last_update": None,
}

HISTORY = deque(maxlen=300)  # derniers points


# ==========================
# MQTT CALLBACKS (paho v2)
# ==========================
def on_connect(client, userdata, flags, reason_code, properties=None):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = (reason_code == 0)

    if reason_code == 0:
        client.subscribe(TOPIC_DATA, qos=0)
        print("MQTT CONNECTED - subscribed:", TOPIC_DATA)
    else:
        print("MQTT connect error reason_code =", reason_code)


def on_disconnect(client, userdata, reason_code, properties=None):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = False
    print("MQTT disconnected reason_code =", reason_code)


def on_message(client, userdata, msg):
    global LAST, HISTORY

    try:
        raw = msg.payload.decode("utf-8", errors="ignore").strip()
        payload = json.loads(raw)
    except Exception as e:
        print("JSON invalide:", e)
        return

    now = datetime.now()

    # On accepte aussi des clés alternatives si jamais
    temp = payload.get("temperature", payload.get("temp"))
    hum = payload.get("humidity", payload.get("hum"))
    seuil = payload.get("seuil", payload.get("threshold"))
    flame = payload.get("flame", payload.get("ir"))
    flame_h = payload.get("flameHande", payload.get("flame_hande"))
    alarm = payload.get("alarm", payload.get("alarme"))
    motor_speed = payload.get("motorSpeed", payload.get("speed"))
    motor_on = payload.get("motorOn", payload.get("motor"))

    with LOCK:
        LAST["temperature"] = temp
        LAST["humidity"] = hum
        LAST["seuil"] = seuil
        LAST["flame"] = flame
        LAST["flameHande"] = flame_h
        LAST["alarm"] = alarm
        LAST["alarmLocal"] = payload.get("alarmLocal")
        LAST["muted"] = payload.get("muted")
        LAST["motorForced"] = payload.get("motorForced")
        LAST["motorSpeed"] = motor_speed
        LAST["motorOn"] = motor_on
        LAST["timestamp"] = payload.get("timestamp")
        LAST["last_update"] = now

        HISTORY.append({
            "time": now,
            "temperature": temp,
            "humidity": hum,
            "seuil": seuil,
            "flame": flame if flame is not None else 0,
        })


# ==========================
# MQTT CLIENT (1 SEUL)
# ==========================
@st.cache_resource
def init_mqtt_client(use_ws: bool = True):
    cid = f"st_{socket.gethostname()}_{os.getpid()}"

    if use_ws:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=cid,
            protocol=mqtt.MQTTv311,
            transport="websockets",
        )
        try:
            client.ws_set_options(path=MQTT_WS_PATH)
        except Exception:
            pass
        port = MQTT_WS_PORT
        print(f"MQTT WS -> {MQTT_BROKER}:{port} path={MQTT_WS_PATH}")
    else:
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=cid,
            protocol=mqtt.MQTTv311,
            transport="tcp",
        )
        port = MQTT_TCP_PORT
        print(f"MQTT TCP -> {MQTT_BROKER}:{port}")

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


def as_int01(v):
    try:
        return int(v)
    except Exception:
        return None


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

    # Sidebar: mode WS/TCP
    st.sidebar.markdown("## Configuration")
    mode = st.sidebar.radio("Connexion MQTT", ["WebSockets (Cloud)", "TCP (Local/VM)"], index=0)
    use_ws = mode.startswith("WebSockets")

    # démarre MQTT (1 seule fois)
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

    # snapshot
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

    st.caption(
        f"Broker: {MQTT_BROKER} | topic: {TOPIC_DATA} | "
        f"{'WebSockets:'+str(MQTT_WS_PORT) if use_ws else 'TCP:'+str(MQTT_TCP_PORT)}"
    )

    if connected or fresh:
        st.success("MQTT connecté (WebSockets)" if use_ws else "MQTT connecté (TCP)")
        if len(hist) == 0:
            st.warning("En attente de données MQTT... (vérifie que l'ESP32 publie sur capteur/data)")
    else:
        st.error("MQTT déconnecté / aucune donnée récente (vérifie ports + Mosquitto)")

    st.markdown("---")

    # cartes
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.subheader("Température (°C)")
        st.metric("Temp", metric_value(last["temperature"]))
    with c2:
        st.subheader("Humidité (%)")
        st.metric("Hum", metric_value(last["humidity"], "{:.0f}"))
    with c3:
        st.subheader("Seuil (°C)")
        st.metric("Seuil", metric_value(last["seuil"]))
    with c4:
        st.subheader("Alarme")
        a = last["alarm"]
        ai = as_int01(a)
        if a is True or ai == 1:
            st.error("ACTIVE")
        elif a is False or ai == 0:
            st.success("OK")
        else:
            st.info("En attente...")

    st.markdown("---")

    # flamme
    f1, f2 = st.columns(2)
    with f1:
        st.subheader("Flamme Steffy")
        fl = as_int01(last["flame"])
        if fl is None:
            st.info("En attente...")
        elif fl == 1:
            st.error("Feu détecté (1)")
        else:
            st.success("Pas de flamme (0)")

    with f2:
        st.subheader("Flamme Hande")
        fh = as_int01(last["flameHande"])
        if fh is None:
            st.info("En attente...")
        elif fh == 1:
            st.warning("Flamme chez la binôme (1)")
        else:
            st.success("Pas de flamme (0)")

    st.markdown("---")

    # graphiques
    st.subheader("Graphiques temps réel")
    if len(hist) == 0:
        st.info("Aucune donnée reçue")
    else:
        df = pd.DataFrame(hist).tail(120)

        g1, g2 = st.columns(2)
        with g1:
            st.altair_chart(bar_chart(df, "temperature", "Température", "°C"), use_container_width=True)
        with g2:
            st.altair_chart(bar_chart(df, "humidity", "Humidité", "%"), use_container_width=True)

        g3, g4 = st.columns(2)
        with g3:
            st.altair_chart(bar_chart(df, "seuil", "Seuil", "°C"), use_container_width=True)
        with g4:
            st.altair_chart(bar_chart(df, "flame", "Flamme", "0/1"), use_container_width=True)

    st.markdown("---")

    # diagnostic + export
    st.subheader("Diagnostic")
    d1, d2 = st.columns(2)
    with d1:
        st.write("Dernier JSON interprété :")
        st.json(last)

    with d2:
        if st.button("Effacer l'historique"):
            with LOCK:
                HISTORY.clear()
            st.success("Historique effacé.")

        if len(hist) > 0:
            df_all = pd.DataFrame(hist)
            csv_data = df_all.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Télécharger CSV",
                data=csv_data,
                file_name="historique_mesures.csv",
                mime="text/csv",
            )

    # refresh
    st.sidebar.markdown("## Rafraîchissement UI")
    refresh_s = st.sidebar.slider("Toutes les (secondes)", 1, 10, 2)
    time.sleep(refresh_s)
    safe_rerun()


if __name__ == "__main__":
    main()
