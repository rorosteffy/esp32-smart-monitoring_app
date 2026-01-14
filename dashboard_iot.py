# dashboard_iot.py
# ✅ Streamlit Cloud compatible
# ✅ MQTT via WebSockets (port 9001) -> OK sur Streamlit Cloud
# ✅ 1 seul client MQTT (pas de fuite)
# ✅ Données temps réel + ton dashboard (cartes + barres + diagnostic)
# ✅ Map keys ESP32 (seuil/potRaw/...) <-> keys dashboard

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
# CONFIG MQTT (STREAMLIT CLOUD)
# ==========================
MQTT_BROKER = "51.103.239.173"

# ⚠️ IMPORTANT :
# - Streamlit Cloud -> TCP 1883 souvent bloqué
# - Utilise WebSockets sur 9001 (Mosquitto websockets)
MQTT_WS_PORT = 9001
MQTT_WS_PATH = "/"          # chez toi dans Mosquitto : path=/
TOPIC_DATA = "capteur/data" # JSON envoyé par ESP32

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
    "seuil": None,       # ✅ clé ESP32 (ton code C++ publie "seuil")
    "pot": None,         # potRaw/pot -> on map
    "flame": None,
    "flameRaw": None,
    "alarm": None,
    "last_update": None,
}

HISTORY = deque(maxlen=300)  # 300 derniers points (suffisant + léger)

# ==========================
# MQTT CALLBACKS
# ==========================
def on_connect(client, userdata, flags, rc, properties=None):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = (rc == 0)

    if rc == 0:
        client.subscribe(TOPIC_DATA, qos=0)
        print("✅ MQTT WS connecté, abonné à", TOPIC_DATA)
    else:
        print("❌ MQTT connexion erreur rc =", rc)

def on_disconnect(client, userdata, rc, properties=None):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = False
    print("🔌 MQTT déconnecté rc =", rc)

def _get(payload: dict, *keys):
    """Retourne la première clé existante (pour compat ESP32)."""
    for k in keys:
        if k in payload and payload.get(k) is not None:
            return payload.get(k)
    return None

def on_message(client, userdata, msg):
    global LAST, HISTORY
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print("JSON invalide:", e, "payload=", msg.payload[:120])
        return

    now = datetime.now()

    # ✅ Mapping compatible avec TON ESP32 + ton ancien dashboard
    temp = _get(payload, "temperature", "temp")
    hum  = _get(payload, "humidity", "hum")
    seuil = _get(payload, "seuil", "seuilPot", "tempSeuil")
    pot = _get(payload, "potRaw", "pot", "potentiometer")
    flame = _get(payload, "flame", "flameLocal")
    flameRaw = _get(payload, "flameRaw", "flameAO")
    alarm = _get(payload, "alarm", "alarmAll")

    with LOCK:
        LAST["temperature"] = temp
        LAST["humidity"] = hum
        LAST["seuil"] = seuil
        LAST["pot"] = pot
        LAST["flame"] = flame
        LAST["flameRaw"] = flameRaw
        LAST["alarm"] = alarm
        LAST["last_update"] = now

        HISTORY.append({
            "time": now,
            "temperature": temp,
            "humidity": hum,
            "seuil": seuil,
            "pot": pot,
            "flame": flame,
        })

# ==========================
# MQTT CLIENT (1 seule fois)
# ==========================
@st.cache_resource
def init_mqtt_client():
    """
    1 seul client MQTT par process Streamlit.
    WebSockets = OK sur Streamlit Cloud.
    """
    cid = f"st_{socket.gethostname()}_{os.getpid()}"
    client = mqtt.Client(
        client_id=cid,
        protocol=mqtt.MQTTv311,
        transport="websockets"     # ✅ IMPORTANT
    )

    # Path websockets (sinon certains brokers refusent)
    client.ws_set_options(path=MQTT_WS_PATH)

    # callbacks
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    # auto-reconnect (propre)
    client.reconnect_delay_set(min_delay=1, max_delay=10)

    # connect async + loop_start => non bloquant
    client.connect_async(MQTT_BROKER, MQTT_WS_PORT, keepalive=60)
    client.loop_start()

    return client

# ==========================
# UI HELPERS
# ==========================
def metric_value(v, fmt="{:.1f}"):
    if v is None:
        return "—"
    try:
        if isinstance(v, (int, float)):
            return fmt.format(float(v))
        return str(v)
    except Exception:
        return str(v)

def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# ==========================
# DASHBOARD UI (TON STYLE)
# ==========================
def build_dashboard():
    st.set_page_config(
        page_title="Gestion Intelligente Température & Sécurité – IoT",
        layout="wide",
    )

    # démarre MQTT
    init_mqtt_client()

    # CSS
    st.markdown(
        """
        <style>
        .stApp {
            background: radial-gradient(circle at top left, #f5f0ff 0, #dbe2ff 35%, #c8d9ff 65%, #b8d3ff 100%);
            color: #0f172a;
        }
        h1 { color: #0f172a; font-weight: 800; }
        h2, h3 { color: #111827; font-weight: 700; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Header
    col_logo, col_title = st.columns([1, 5])
    with col_logo:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=130)
        else:
            st.markdown("**EPHEC**")
    with col_title:
        st.markdown(
            "<h1 style='margin-bottom:0.2em;'>Gestion Intelligente Température & Sécurité – IoT</h1>",
            unsafe_allow_html=True,
        )
        st.caption(f"Broker: {MQTT_BROKER} | transport=websockets | port={MQTT_WS_PORT} | path={MQTT_WS_PATH}")

    # snapshot thread-safe
    with LOCK:
        last = dict(LAST)
        hist = list(HISTORY)
        connected = MQTT_CONNECTED

    # “freshness” (si data < 8s => OK même si rc n’est pas encore affiché)
    fresh = False
    age_s = None
    if last["last_update"] is not None:
        age_s = (datetime.now() - last["last_update"]).total_seconds()
        fresh = age_s <= 8

    if connected or fresh:
        st.success("État MQTT : ✅ Connecté / données reçues")
    else:
        st.warning("En attente de données MQTT… (vérifie que l’ESP32 publie bien sur capteur/data)")

    if age_s is not None:
        st.caption(f"Dernière donnée reçue il y a ~{age_s:.1f} s")

    st.markdown("---")

    # 4 cartes
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
        st.subheader("🕹️ Potentiomètre")
        st.metric("Valeur brute POT", "—" if last["pot"] is None else str(last["pot"]))

    st.markdown("---")

    # Flamme + alarme
    c5, c6 = st.columns(2)
    with c5:
        st.subheader("🔥 IR / Flamme")
        flame = last["flame"]
        if flame is None:
            st.info("En attente (flame=None)…")
        elif int(flame) == 1:
            st.error("🔥 Feu détecté (flame=1)")
        else:
            st.success("✅ Aucun feu détecté (flame=0)")

    with c6:
        st.subheader("🚨 État de l'alarme")
        if last["alarm"] is True or str(last["alarm"]) == "1":
            st.error("Alarme ACTIVE")
        else:
            st.success("Alarme inactive")

    st.markdown("---")

    # Graphiques en BARRES (comme toi)
    st.subheader("📊 Graphiques en temps réel")

    if len(hist) == 0:
        st.info("En attente de données temps réel des capteurs…")
    else:
        df = pd.DataFrame(hist).tail(120)

        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.altair_chart(
                alt.Chart(df).mark_bar().encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("temperature:Q", title="Température (°C)"),
                    tooltip=["time:T", "temperature:Q"],
                ).properties(height=260, title="Température (barres)"),
                use_container_width=True
            )

        with col_g2:
            st.altair_chart(
                alt.Chart(df).mark_bar().encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("humidity:Q", title="Humidité (%)"),
                    tooltip=["time:T", "humidity:Q"],
                ).properties(height=260, title="Humidité (barres)"),
                use_container_width=True
            )

        col_g3, col_g4 = st.columns(2)
        with col_g3:
            st.altair_chart(
                alt.Chart(df).mark_bar().encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("flame:Q", title="Flamme (0/1)"),
                    tooltip=["time:T", "flame:Q"],
                ).properties(height=260, title="IR / Flamme (barres)"),
                use_container_width=True
            )

        with col_g4:
            st.altair_chart(
                alt.Chart(df).mark_bar().encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("pot:Q", title="Valeur brute POT"),
                    tooltip=["time:T", "pot:Q"],
                ).properties(height=260, title="Potentiomètre (barres)"),
                use_container_width=True
            )

    st.markdown("---")

    # Diagnostic
    st.subheader("🩺 Diagnostic du système")
    col_d1, col_d2 = st.columns(2)

    with col_d1:
        st.write("**Dernier message JSON reçu :**")
        st.json(last)

    with col_d2:
        if st.button("🗑️ Réinitialiser l’historique"):
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

    # refresh UI sans casser MQTT
    st.sidebar.markdown("### 🔄 Rafraîchissement")
    refresh_s = st.sidebar.slider("Refresh UI (secondes)", 1, 10, 2)
    time.sleep(refresh_s)
    safe_rerun()

def main():
    build_dashboard()

if __name__ == "__main__":
    main()
