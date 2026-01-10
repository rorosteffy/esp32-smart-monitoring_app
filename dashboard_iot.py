import streamlit as st
import paho.mqtt.client as mqtt
import json
import threading
import time
import pandas as pd
import altair as alt
from datetime import datetime
import os

# ==========================
# CONFIG MQTT
# ==========================
MQTT_BROKER = "51.103.239.173"
MQTT_PORT = 1883

TOPIC_DATA = "capteur/data"            # ESP32 publie ici (JSON)
TOPIC_CMD  = "noeud/operateur/cmd"     # commandes vers binôme (texte)

REFRESH_MS = 1000  # rafraîchissement UI en ms

# ==========================
# LOGO (optionnel)
# ==========================
LOGO_FILENAME = "LOGO_EPHEC_HE.png"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, LOGO_FILENAME)

# ==========================
# SESSION STATE INIT
# ==========================
def init_state():
    if "mqtt_connected" not in st.session_state:
        st.session_state.mqtt_connected = False

    if "last_data" not in st.session_state:
        st.session_state.last_data = {
            "temperature": None,
            "humidity": None,
            "seuil": None,      # on affichera "seuil" (ou "seuilPot")
            "tempSeuil": None,
            "humSeuil": None,
            "seuilPot": None,
            "flame": None,
            "flameRaw": None,
            "pot": None,
            "alarm": False,
            "last_update": None,
            "raw": None,
        }

    if "history" not in st.session_state:
        st.session_state.history = []

    if "mqtt_started" not in st.session_state:
        st.session_state.mqtt_started = False

init_state()

# ==========================
# HELPERS
# ==========================
def pick(payload, *keys, default=None):
    """Retourne la 1ère clé existante et non None."""
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

    # champs possibles (ton ESP32 peut envoyer différents noms)
    ld["temperature"] = pick(payload, "temperature", "temp", "T")
    ld["humidity"]    = pick(payload, "humidity", "hum", "H")

    # seuil : on accepte seuilPot OU seuil
    ld["seuilPot"]    = pick(payload, "seuilPot")
    ld["seuil"]       = pick(payload, "seuil", "threshold", "setpoint", default=ld["seuilPot"])

    ld["tempSeuil"]   = pick(payload, "tempSeuil")
    ld["humSeuil"]    = pick(payload, "humSeuil")

    ld["flame"]       = pick(payload, "flame", "ir", "fire")
    ld["flameRaw"]    = pick(payload, "flameRaw")
    ld["pot"]         = pick(payload, "pot", "adc", "potValue")
    ld["alarm"]       = bool(pick(payload, "alarm", "alarme", default=False))
    ld["last_update"] = datetime.now()

    # historiser pour graphes
    st.session_state.history.append({
        "time": ld["last_update"],
        "temperature": ld["temperature"],
        "humidity": ld["humidity"],
        "seuil": ld["seuil"],
        "flame": ld["flame"],
        "pot": ld["pot"],
    })

    # limiter taille
    if len(st.session_state.history) > 800:
        st.session_state.history = st.session_state.history[-800:]

# ==========================
# MQTT START (ONE TIME)
# ==========================
@st.cache_resource(show_spinner=False)
def get_mqtt_client():
    """
    Créé UNE SEULE instance MQTT par serveur Streamlit (évite reconnexion infinie).
    """
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    def loop_thread():
        while True:
            try:
                print("🔁 Tentative connexion MQTT...")
                client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
                client.loop_forever()   # bloque jusqu'à déconnexion
            except Exception as e:
                st.session_state.mqtt_connected = False
                print("⚠️ MQTT erreur, retry:", e)
                time.sleep(3)

    t = threading.Thread(target=loop_thread, daemon=True)
    t.start()
    return client

def mqtt_publish(cmd_text: str) -> bool:
    client = get_mqtt_client()
    if not st.session_state.mqtt_connected:
        return False
    try:
        client.publish(TOPIC_CMD, cmd_text)
        return True
    except Exception:
        return False

# ==========================
# UI
# ==========================
st.set_page_config(page_title="Gestion Intelligente Température & Sécurité – IoT", layout="wide")
st.autorefresh(interval=REFRESH_MS, key="refresh_ui")

# démarre MQTT (1 seule fois)
_ = get_mqtt_client()

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

col_logo, col_title = st.columns([1, 6])
with col_logo:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=120)
    else:
        st.write("EPHEC")

with col_title:
    st.markdown("# Gestion Intelligente Température & Sécurité – IoT")

if st.session_state.mqtt_connected:
    st.success("État MQTT : ✅ Connecté")
else:
    st.error("État MQTT : 🔴 Déconnecté (si sur streamlit.app: port 1883 peut être bloqué)")

st.divider()

ld = st.session_state.last_data

# --------- 4 cartes ---------
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.subheader("🌡️ Température")
    st.metric("Temp (°C)", f"{float(ld['temperature']):.1f}" if ld["temperature"] is not None else "—")

with c2:
    st.subheader("💧 Humidité")
    st.metric("Hum (%)", f"{float(ld['humidity']):.1f}" if ld["humidity"] is not None else "—")

with c3:
    st.subheader("📦 Seuil (ESP32)")
    s = ld["seuil"]
    st.metric("Seuil", f"{float(s):.1f}" if s is not None else "— (non reçu)")

with c4:
    st.subheader("🕹️ Potentiomètre")
    p = ld["pot"]
    st.metric("POT (brut)", f"{int(float(p))}" if p is not None else "—")

st.divider()

# --------- Flamme / Alarme ---------
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
    if bool(ld["alarm"]):
        st.error("Alarme ACTIVE")
    else:
        st.success("Alarme inactive")

st.divider()

# --------- Commandes binôme ---------
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

# --------- Graphiques (courbes) ---------
st.subheader("📈 Graphiques en temps réel (courbes)")

hist = st.session_state.history
if len(hist) == 0:
    st.info("En attente de données…")
else:
    df = pd.DataFrame(hist).tail(250).copy()
    for col in ["temperature", "humidity", "seuil", "flame", "pot"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    g1, g2 = st.columns(2)
    with g1:
        st.altair_chart(
            alt.Chart(df).mark_line(point=True).encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y("temperature:Q", title="Température (°C)"),
                tooltip=["time:T", "temperature:Q"]
            ).properties(height=260, title="Température"),
            use_container_width=True
        )

    with g2:
        st.altair_chart(
            alt.Chart(df).mark_line(point=True).encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y("humidity:Q", title="Humidité (%)"),
                tooltip=["time:T", "humidity:Q"]
            ).properties(height=260, title="Humidité"),
            use_container_width=True
        )

    g3, g4 = st.columns(2)
    with g3:
        st.altair_chart(
            alt.Chart(df).mark_line(point=True).encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y("seuil:Q", title="Seuil"),
                tooltip=["time:T", "seuil:Q"]
            ).properties(height=260, title="Seuil"),
            use_container_width=True
        )

    with g4:
        st.altair_chart(
            alt.Chart(df).mark_line(point=True).encode(
                x=alt.X("time:T", title="Temps"),
                y=alt.Y("flame:Q", title="Flamme (0/1)"),
                tooltip=["time:T", "flame:Q"]
            ).properties(height=260, title="IR / Flamme"),
            use_container_width=True
        )

st.divider()

# --------- Diagnostic ---------
st.subheader("🩺 Diagnostic")

d1, d2 = st.columns([2, 1])
with d1:
    st.write("**Dernier JSON reçu :**")
    st.json(ld["raw"] if ld["raw"] is not None else {"info": "Aucun message reçu"})
    if ld["last_update"] is not None:
        st.caption(f"Dernière mise à jour : {ld['last_update']}")

with d2:
    if st.button("🗑️ Vider l’historique"):
        st.session_state.history = []
        st.success("Historique effacé ✅")
