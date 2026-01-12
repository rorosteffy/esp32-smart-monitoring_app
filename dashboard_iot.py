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
# CONFIG MQTT
# ==========================
MQTT_BROKER = "51.103.239.173"
MQTT_PORT   = 1883

TOPIC_DATA = "capteur/data"            # ESP32 -> JSON
TOPIC_CMD  = "noeud/operateur/cmd"     # Streamlit -> commandes binôme

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

LAST = {
    "temperature": None,
    "humidity": None,
    "seuil": None,          # ✅ clé ESP32: "seuil"
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

# ==========================
# RERUN COMPATIBLE
# ==========================
def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
        return
    if hasattr(st, "experimental_rerun"):
        st.experimental_rerun()
        return
    # fallback très ancien
    st.query_params["_ts"] = str(int(time.time()))

# ==========================
# MQTT CALLBACKS (signatures v1 compatibles)
# ==========================
def on_connect(client, userdata, flags, rc):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = (rc == 0)
    if rc == 0:
        client.subscribe(TOPIC_DATA)
        print("✅ MQTT connecté, abonné à", TOPIC_DATA)
    else:
        print("❌ MQTT erreur connexion rc =", rc)

def on_disconnect(client, userdata, rc):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = False
    print("🔌 MQTT déconnecté rc =", rc)

def on_message(client, userdata, msg):
    global LAST, HISTORY
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print("JSON invalide :", e)
        return

    now = datetime.now()

    # ✅ Ton ESP32 publie: temperature, humidity, seuil, flame, flameHande, alarm...
    with LOCK:
        LAST["temperature"]  = payload.get("temperature")
        LAST["humidity"]     = payload.get("humidity")
        LAST["seuil"]        = payload.get("seuil")        # ✅ IMPORTANT
        LAST["flame"]        = payload.get("flame")
        LAST["flameHande"]   = payload.get("flameHande")
        LAST["alarm"]        = payload.get("alarm")
        LAST["alarmLocal"]   = payload.get("alarmLocal")
        LAST["muted"]        = payload.get("muted")
        LAST["motorForced"]  = payload.get("motorForced")
        LAST["motorSpeed"]   = payload.get("motorSpeed")
        LAST["last_update"]  = now

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
    # client_id stable -> évite créer 100 clients au refresh
    cid = f"streamlit_{socket.gethostname()}_{os.getpid()}"
    client = mqtt.Client(client_id=cid, protocol=mqtt.MQTTv311)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client

def mqtt_publish(cmd: str):
    client = init_mqtt_client()
    client.publish(TOPIC_CMD, cmd, qos=0, retain=False)

# ==========================
# UI helpers
# ==========================
def metric_value(v, fmt="{:.1f}"):
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        return fmt.format(v)
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

# ==========================
# MAIN
# ==========================
def main():
    st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")

    # démarre MQTT (une seule fois)
    init_mqtt_client()

    # CSS
    st.markdown("""
    <style>
      .stApp { background: radial-gradient(circle at top left, #f5f0ff 0, #dbe2ff 35%, #c8d9ff 65%, #b8d3ff 100%); }
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

    # Snapshot thread-safe
    with LOCK:
        last = dict(LAST)
        hist = list(HISTORY)
        connected = MQTT_CONNECTED

    # Data freshness (si data reçue < 6s => OK)
    fresh = False
    age_s = None
    if last["last_update"] is not None:
        age_s = (datetime.now() - last["last_update"]).total_seconds()
        fresh = (age_s <= 6.0)

    # Etat MQTT (évite le faux "déconnecté")
    if connected or fresh:
        st.success("État MQTT : ✅ Connecté (ou données reçues récemment)")
    else:
        st.error("État MQTT : 🔴 Déconnecté / aucune donnée récente")

    if age_s is not None:
        st.caption(f"Dernière donnée reçue il y a ~{age_s:.1f} s")

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
        st.metric("Seuil (°C)", "— (non reçu)" if last["seuil"] is None else f"{float(last['seuil']):.1f}")
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
        st.subheader("🔥 Flamme (Steffy)")
        if last["flame"] is None:
            st.info("En attente (flame=None)")
        elif int(last["flame"]) == 1:
            st.error("🔥 Feu détecté (flame=1)")
        else:
            st.success("✅ Aucun feu (flame=0)")

    with c6:
        st.subheader("🔥 Flamme binôme (Hande)")
        fh = last["flameHande"]
        if fh is None:
            st.info("En attente (flameHande=None)")
        elif int(fh) == 1:
            st.warning("⚠️ Flamme chez la binôme (flameHande=1)")
        else:
            st.success("✅ Pas de flamme chez la binôme (flameHande=0)")

    st.markdown("---")

    # Commandes
    st.subheader(f"🎛️ Commandes vers la binôme (topic: {TOPIC_CMD})")
    b1, b2, b3 = st.columns([1, 1, 3])
    with b1:
        if st.button("🔴 LED ROUGE ON", use_container_width=True):
            mqtt_publish(CMD_LED_ON)
            st.toast("Commande envoyée", icon="📡")
    with b2:
        if st.button("⚫ LED ROUGE OFF", use_container_width=True):
            mqtt_publish(CMD_LED_OFF)
            st.toast("Commande envoyée", icon="📡")
    with b3:
        st.info("La binôme doit écouter ce topic et exécuter LED_RED_ON / LED_RED_OFF sur son ESP32.")

    st.markdown("---")

    # Graphiques
    st.subheader("📈 Graphiques en temps réel (courbes)")
    if len(hist) == 0:
        st.info("En attente de données sur capteur/data…")
    else:
        df = pd.DataFrame(hist).dropna(subset=["time"]).tail(200)

        g1, g2 = st.columns(2)
        with g1:
            st.altair_chart(build_line_chart(df, "temperature", "Température", "Température (°C)"),
                            use_container_width=True)
        with g2:
            st.altair_chart(build_line_chart(df, "humidity", "Humidité", "Humidité (%)"),
                            use_container_width=True)

        g3, g4 = st.columns(2)
        with g3:
            st.altair_chart(build_line_chart(df, "seuil", "Seuil", "Seuil (°C)"),
                            use_container_width=True)
        with g4:
            st.altair_chart(build_line_chart(df, "flame", "Flamme", "Flamme (0/1)"),
                            use_container_width=True)

    st.markdown("---")

    # Diagnostic + CSV (sans fichier disque)
    st.subheader("🩺 Diagnostic")
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

    # Refresh UI
    refresh_s = st.sidebar.slider("Refresh UI (secondes)", 1, 10, 2)
    time.sleep(refresh_s)
    safe_rerun()

if __name__ == "__main__":
    main()
