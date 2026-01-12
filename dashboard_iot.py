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

MQTT_BROKER = "51.103.239.173"
MQTT_PORT   = 1883
TOPIC_DATA  = "capteur/data"
TOPIC_CMD   = "noeud/operateur/cmd"

CMD_LED_ON  = "LED_RED_ON"
CMD_LED_OFF = "LED_RED_OFF"

LOCK = threading.Lock()
MQTT_CONNECTED = False

LAST = {
    "temperature": None,
    "humidity": None,
    "seuil": None,
    "flame": None,
    "flameHande": None,
    "alarm": None,
    "last_update": None,
}

HISTORY = deque(maxlen=400)

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
        # DEBUG utile:
        # print("✅ RECU capteur/data :", payload)
    except Exception as e:
        print("JSON invalide :", e)
        return

    now = datetime.now()
    with LOCK:
        LAST["temperature"] = payload.get("temperature")
        LAST["humidity"]    = payload.get("humidity")
        LAST["seuil"]       = payload.get("seuil")  # ton ESP32 publie "seuil"
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

@st.cache_resource
def init_mqtt_client():
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

def metric(v, fmt="{:.1f}"):
    if v is None:
        return "—"
    if isinstance(v, (int, float)):
        return fmt.format(v)
    return str(v)

def chart(df, y, title, ytitle):
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

def main():
    st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")
    init_mqtt_client()

    with LOCK:
        last = dict(LAST)
        hist = list(HISTORY)
        connected = MQTT_CONNECTED

    fresh = False
    age_s = None
    if last["last_update"]:
        age_s = (datetime.now() - last["last_update"]).total_seconds()
        fresh = age_s <= 6

    st.title("Gestion Intelligente Température & Sécurité – IoT")

    if connected or fresh:
        st.success("État MQTT : ✅ Connecté (ou données reçues récemment)")
    else:
        st.error("État MQTT : 🔴 Déconnecté / aucune donnée récente")

    if age_s is not None:
        st.caption(f"Dernière donnée reçue il y a ~{age_s:.1f} s")

    st.markdown("---")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.subheader("🌡️ Température")
        st.metric("Temp (°C)", metric(last["temperature"]))
    with c2:
        st.subheader("💧 Humidité")
        st.metric("Hum (%)", metric(last["humidity"], "{:.0f}"))
    with c3:
        st.subheader("📦 Seuil (ESP32)")
        st.metric("Seuil (°C)", metric(last["seuil"]))
    with c4:
        st.subheader("🚨 Alarme")
        st.write("ACTIVE" if last["alarm"] else "inactive")

    st.markdown("---")
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
    st.subheader("📈 Graphiques en temps réel (courbes)")
    if not hist:
        st.info("En attente de données sur capteur/data…")
    else:
        df = pd.DataFrame(hist).dropna(subset=["time"]).tail(200)
        g1, g2 = st.columns(2)
        with g1:
            st.altair_chart(chart(df, "temperature", "Température", "°C"), use_container_width=True)
        with g2:
            st.altair_chart(chart(df, "humidity", "Humidité", "%"), use_container_width=True)
        g3, g4 = st.columns(2)
        with g3:
            st.altair_chart(chart(df, "seuil", "Seuil", "°C"), use_container_width=True)
        with g4:
            st.altair_chart(chart(df, "flame", "Flamme", "0/1"), use_container_width=True)

    st.markdown("---")
    st.subheader("🩺 Diagnostic")
    st.json(last)

    # Refresh manuel (stable)
    if st.button("🔄 Actualiser l'UI"):
        st.rerun()

if __name__ == "__main__":
    main()
