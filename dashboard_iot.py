import streamlit as st
import paho.mqtt.client as mqtt
import json
import pandas as pd
import altair as alt
from datetime import datetime
import os

# ==========================
# CONFIG
# ==========================
MQTT_BROKER = "51.103.239.173"
MQTT_PORT = 1883
TOPIC_DATA = "capteur/data"
TOPIC_CMD  = "noeud/operateur/cmd"

LOGO_FILENAME = "LOGO_EPHEC_HE.png"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, LOGO_FILENAME)

# ==========================
# INIT SESSION STATE
# ==========================
if "mqtt_connected" not in st.session_state:
    st.session_state.mqtt_connected = False

if "last_data" not in st.session_state:
    st.session_state.last_data = {
        "temperature": None,
        "humidity": None,
        "seuil": None,
        "flame": None,
        "pot": None,
        "alarm": False,
        "last_update": None,
        "raw": None,
    }

if "history" not in st.session_state:
    st.session_state.history = []  # list of dicts

if "mqtt_started" not in st.session_state:
    st.session_state.mqtt_started = False

if "mqtt_client" not in st.session_state:
    st.session_state.mqtt_client = None


def pick(payload, *keys, default=None):
    for k in keys:
        if k in payload and payload[k] is not None:
            return payload[k]
    return default


# ==========================
# MQTT CALLBACKS
# ==========================
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        st.session_state.mqtt_connected = True
        client.subscribe(TOPIC_DATA)
        print("✅ MQTT connecté. Abonné à:", TOPIC_DATA)
    else:
        st.session_state.mqtt_connected = False
        print("❌ MQTT erreur connexion rc =", rc)


def on_disconnect(client, userdata, rc):
    st.session_state.mqtt_connected = False
    print("🔌 MQTT déconnecté rc =", rc)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print("❌ JSON invalide:", e)
        return

    ld = st.session_state.last_data
    ld["raw"] = payload
    ld["temperature"] = pick(payload, "temperature", "temp", "T")
    ld["humidity"]    = pick(payload, "humidity", "hum", "H")
    ld["seuil"]       = pick(payload, "seuil", "threshold", "setpoint")
    ld["flame"]       = pick(payload, "flame", "ir", "fire")
    ld["pot"]         = pick(payload, "pot", "adc", "potValue")
    ld["alarm"]       = bool(pick(payload, "alarm", "alarme", default=False))
    ld["last_update"] = datetime.now()

    st.session_state.history.append({
        "time": ld["last_update"],
        "temperature": ld["temperature"],
        "humidity": ld["humidity"],
        "seuil": ld["seuil"],
        "flame": ld["flame"],
        "pot": ld["pot"],
    })

    if len(st.session_state.history) > 600:
        st.session_state.history = st.session_state.history[-600:]


# ==========================
# MQTT START (ONE TIME)
# ==========================
def start_mqtt_once():
    if st.session_state.mqtt_started:
        return

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()  # ✅ thread réseau interne (stable)
        st.session_state.mqtt_client = client
        st.session_state.mqtt_started = True
    except Exception as e:
        st.session_state.mqtt_connected = False
        st.session_state.mqtt_started = False
        print("⚠️ Connexion MQTT impossible:", e)


def mqtt_publish(cmd: str) -> bool:
    client = st.session_state.mqtt_client
    if client is None or not st.session_state.mqtt_connected:
        return False
    try:
        client.publish(TOPIC_CMD, cmd)
        return True
    except Exception:
        return False


# ==========================
# UI
# ==========================
st.set_page_config(page_title="Dashboard IoT", layout="wide")

# ✅ refresh UI sans casser MQTT
# (Streamlit >= 1.18) : autorefresh officiel
st.autorefresh(interval=1000, key="refresh_1s")

start_mqtt_once()

st.markdown(
    """
    <style>
    .stApp {
        background: radial-gradient(circle at top left, #f5f0ff 0, #dbe2ff 35%, #c8d9ff 65%, #b8d3ff 100%);
        color: #0f172a;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

col_logo, col_title = st.columns([1, 6])
with col_logo:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=110)
    else:
        st.write("EPHEC")

with col_title:
    st.markdown("## Gestion Intelligente Température & Sécurité – IoT")

if st.session_state.mqtt_connected:
    st.success("État MQTT : ✅ Connecté au broker")
else:
    st.error("État MQTT : 🔴 Déconnecté du broker")

st.divider()

ld = st.session_state.last_data

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.subheader("🌡️ Température")
    st.metric("Temp (°C)", f"{float(ld['temperature']):.1f}" if ld["temperature"] is not None else "—")
with c2:
    st.subheader("💧 Humidité")
    st.metric("Hum (%)", f"{float(ld['humidity']):.1f}" if ld["humidity"] is not None else "—")
with c3:
    st.subheader("📦 Seuil (ESP32)")
    st.metric("Seuil", f"{float(ld['seuil']):.1f}" if ld["seuil"] is not None else "— (non reçu)")
with c4:
    st.subheader("🕹️ Potentiomètre")
    st.metric("POT (brut)", f"{int(float(ld['pot']))}" if ld["pot"] is not None else "—")

st.divider()

c5, c6 = st.columns(2)
with c5:
    st.subheader("🔥 IR / Flamme")
    f = ld["flame"]
    if f is None:
        st.info("En attente (flame=None)")
    elif int(float(f)) == 1:
        st.error("🔥 Feu détecté (flame=1)")
    else:
        st.success("✅ Aucun feu (flame=0)")

with c6:
    st.subheader("🚨 État de l'alarme")
    st.error("Alarme ACTIVE") if ld["alarm"] else st.success("Alarme inactive")

st.divider()

st.subheader("🎛️ Commandes vers la binôme (topic: noeud/operateur/cmd)")
b1, b2, b3 = st.columns([1, 1, 2])
with b1:
    if st.button("🔴 LED ROUGE ON", use_container_width=True):
        st.success("Envoyé ✅" if mqtt_publish("LED_RED_ON") else "Échec ❌ (MQTT non connecté)")
with b2:
    if st.button("⚫ LED ROUGE OFF", use_container_width=True):
        st.success("Envoyé ✅" if mqtt_publish("LED_RED_OFF") else "Échec ❌ (MQTT non connecté)")
with b3:
    st.info("Ta binôme doit SUBSCRIBE sur noeud/operateur/cmd et traiter LED_RED_ON / LED_RED_OFF.")

st.divider()

st.subheader("📈 Graphiques en temps réel (courbes)")
hist = st.session_state.history
if len(hist) == 0:
    st.info("En attente de données…")
else:
    df = pd.DataFrame(hist).tail(200).copy()
    for col in ["temperature", "humidity", "seuil", "flame", "pot"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    g1, g2 = st.columns(2)
    with g1:
        st.altair_chart(
            alt.Chart(df).mark_line(point=True).encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y("temperature:Q", title="Temp (°C)"),
                tooltip=["time:T", "temperature:Q"],
            ).properties(height=260, title="Température"),
            use_container_width=True
        )
    with g2:
        st.altair_chart(
            alt.Chart(df).mark_line(point=True).encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y("humidity:Q", title="Hum (%)"),
                tooltip=["time:T", "humidity:Q"],
            ).properties(height=260, title="Humidité"),
            use_container_width=True
        )

st.divider()

st.subheader("🩺 Diagnostic")
d1, d2 = st.columns([2, 1])
with d1:
    st.write("**Dernier JSON reçu :**")
    st.json(ld["raw"] if ld["raw"] is not None else {"info": "Aucun message"})
    if ld["last_update"]:
        st.caption(f"Dernière mise à jour : {ld['last_update']}")

with d2:
    if st.button("🗑️ Vider l’historique"):
        st.session_state.history = []
        st.success("Historique effacé ✅")
