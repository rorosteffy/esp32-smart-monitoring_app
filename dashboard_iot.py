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

TOPIC_DATA = "capteur/data"               # ESP32 -> JSON capteurs
TOPIC_CMD_TO_PARTNER = "noeud/operateur/cmd"  # Streamlit -> commandes binôme

# ==========================
# LOGO (optionnel)
# ==========================
LOGO_FILENAME = "LOGO_EPHEC_HE.png"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, LOGO_FILENAME)

# ==========================
# SESSION STATE INIT
# ==========================
if "mqtt_started" not in st.session_state:
    st.session_state.mqtt_started = False

if "mqtt_connected" not in st.session_state:
    st.session_state.mqtt_connected = False

if "mqtt_status" not in st.session_state:
    st.session_state.mqtt_status = "INIT"

if "last_data" not in st.session_state:
    st.session_state.last_data = {
        "temperature": None,
        "humidity": None,
        "seuil": None,          # <- on standardise en "seuil"
        "flame": None,
        "pot": None,
        "alarm": None,
        "last_update": None,
        "raw_payload": None,
    }

if "history" not in st.session_state:
    st.session_state.history = []  # list of dict: time, temperature, humidity, flame, pot, seuil

if "csv_path" not in st.session_state:
    st.session_state.csv_path = os.path.join(SCRIPT_DIR, "historique_mesures.csv")

# ==========================
# MQTT CALLBACKS
# ==========================
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        st.session_state.mqtt_connected = True
        st.session_state.mqtt_status = "✅ Connecté"
        client.subscribe(TOPIC_DATA)
        print("✅ MQTT connecté, abonné à", TOPIC_DATA)
    else:
        st.session_state.mqtt_connected = False
        st.session_state.mqtt_status = f"❌ Erreur connexion rc={rc}"
        print("❌ MQTT erreur rc=", rc)

def on_disconnect(client, userdata, rc):
    st.session_state.mqtt_connected = False
    st.session_state.mqtt_status = f"🔌 Déconnecté rc={rc}"
    print("🔌 MQTT déconnecté rc=", rc)

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print("JSON invalide:", e)
        return

    # --- Normalisation des champs (important pour ton ESP32)
    temp = payload.get("temperature")
    hum  = payload.get("humidity")

    # ✅ ton ESP32 envoie "seuil"
    # mais si un autre code envoie "seuilPot", on accepte aussi
    seuil = payload.get("seuil", payload.get("seuilPot"))

    flame = payload.get("flame")
    pot   = payload.get("pot", payload.get("potRaw"))  # au cas où
    alarm = payload.get("alarm", payload.get("alarmAll", payload.get("alarmTemp")))

    now = datetime.now()

    st.session_state.last_data = {
        "temperature": temp,
        "humidity": hum,
        "seuil": seuil,
        "flame": flame,
        "pot": pot,
        "alarm": alarm,
        "last_update": now,
        "raw_payload": payload,
    }

    st.session_state.history.append({
        "time": now,
        "temperature": temp,
        "humidity": hum,
        "seuil": seuil,
        "flame": flame,
        "pot": pot,
    })

    # garder uniquement les derniers points pour éviter surcharge
    st.session_state.history = st.session_state.history[-300:]

# ==========================
# MQTT THREAD (1 seule fois)
# ==========================
def mqtt_worker():
    client = mqtt.Client(client_id=f"streamlit_dashboard_{int(time.time())}")
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    while True:
        try:
            if not st.session_state.mqtt_connected:
                st.session_state.mqtt_status = "🔁 Connexion..."
                client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
                client.loop_start()
            time.sleep(2)
        except Exception as e:
            st.session_state.mqtt_connected = False
            st.session_state.mqtt_status = f"⚠️ Erreur MQTT: {e}"
            print("⚠️ MQTT worker error:", e)
            time.sleep(3)

def start_mqtt_once():
    if st.session_state.mqtt_started:
        return
    t = threading.Thread(target=mqtt_worker, daemon=True)
    t.start()
    st.session_state.mqtt_started = True

# ==========================
# UI
# ==========================
st.set_page_config(
    page_title="Gestion Intelligente Température & Sécurité – IoT",
    layout="wide",
)

# Auto-refresh propre (sans plugin)
st.markdown(
    "<meta http-equiv='refresh' content='2'>",
    unsafe_allow_html=True
)

# CSS background (comme tu veux)
st.markdown(
    """
    <style>
    .stApp {
        background: radial-gradient(circle at top left, #f5f0ff 0, #dbe2ff 35%, #c8d9ff 65%, #b8d3ff 100%);
        color: #0f172a;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# Start MQTT
start_mqtt_once()

# Header
col_logo, col_title = st.columns([1, 6])
with col_logo:
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, width=110)
    else:
        st.write("EPHEC")

with col_title:
    st.markdown("## Gestion Intelligente Température & Sécurité – IoT")

# MQTT status
if st.session_state.mqtt_connected:
    st.success(f"État MQTT : {st.session_state.mqtt_status}")
else:
    st.error(f"État MQTT : {st.session_state.mqtt_status}")

st.markdown("---")

d = st.session_state.last_data

# Cards
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.subheader("🌡️ Température")
    st.metric("Temp (°C)", "—" if d["temperature"] is None else f"{d['temperature']:.1f}")

with c2:
    st.subheader("💧 Humidité")
    st.metric("Hum (%)", "—" if d["humidity"] is None else f"{d['humidity']:.1f}")

with c3:
    st.subheader("📦 Seuil (ESP32)")
    st.metric("Seuil (°C)", "—" if d["seuil"] is None else f"{d['seuil']:.1f}")

with c4:
    st.subheader("🕹️ Potentiomètre")
    st.metric("POT (brut)", "—" if d["pot"] is None else f"{d['pot']}")

st.markdown("---")

# Flame + Alarm
c5, c6 = st.columns(2)
with c5:
    st.subheader("🔥 IR / Flamme")
    if d["flame"] is None:
        st.info("En attente (flame=None)")
    elif int(d["flame"]) == 1:
        st.error("🔥 Feu détecté (flame=1)")
    else:
        st.success("✅ Aucun feu (flame=0)")

with c6:
    st.subheader("🚨 État de l'alarme")
    if d["alarm"]:
        st.error("Alarme ACTIVE")
    else:
        st.success("Alarme inactive")

st.markdown("---")

# ✅ Commandes vers binôme
st.subheader(f"🎛️ Commandes vers la binôme (topic: {TOPIC_CMD_TO_PARTNER})")

cmd_col1, cmd_col2, cmd_col3 = st.columns([2, 2, 6])

# On crée un petit client MQTT publisher local (sans thread) quand on clique
def publish_cmd(command: str):
    try:
        pub = mqtt.Client(client_id=f"streamlit_pub_{int(time.time())}")
        pub.connect(MQTT_BROKER, MQTT_PORT, keepalive=30)
        pub.publish(TOPIC_CMD_TO_PARTNER, command, qos=0, retain=False)
        pub.disconnect()
        return True
    except Exception as e:
        st.error(f"Erreur publish MQTT: {e}")
        return False

with cmd_col1:
    if st.button("🔴 LED ROUGE ON"):
        ok = publish_cmd("LED_RED_ON")
        if ok:
            st.success("Commande envoyée: LED_RED_ON")

with cmd_col2:
    if st.button("⚫ LED ROUGE OFF"):
        ok = publish_cmd("LED_RED_OFF")
        if ok:
            st.success("Commande envoyée: LED_RED_OFF")

with cmd_col3:
    st.info("⚠️ Ta binôme doit écouter `noeud/operateur/cmd` et exécuter LED_RED_ON / LED_RED_OFF.")

st.markdown("---")

# ✅ Graphiques en courbes
st.subheader("📈 Graphiques en temps réel (courbes)")

hist = st.session_state.history
if len(hist) < 2:
    st.info("En attente des données…")
else:
    df = pd.DataFrame(hist).dropna(subset=["time"])
    df = df.tail(200)

    # Temp line
    line_temp = alt.Chart(df).mark_line().encode(
        x=alt.X("time:T", title="Temps"),
        y=alt.Y("temperature:Q", title="Température (°C)"),
        tooltip=["time:T", "temperature:Q"]
    ).properties(height=240, title="Température")

    # Hum line
    line_hum = alt.Chart(df).mark_line().encode(
        x=alt.X("time:T", title="Temps"),
        y=alt.Y("humidity:Q", title="Humidité (%)"),
        tooltip=["time:T", "humidity:Q"]
    ).properties(height=240, title="Humidité")

    colA, colB = st.columns(2)
    with colA:
        st.altair_chart(line_temp, use_container_width=True)
    with colB:
        st.altair_chart(line_hum, use_container_width=True)

    # Seuil + Pot line
    line_seuil = alt.Chart(df).mark_line().encode(
        x=alt.X("time:T", title="Temps"),
        y=alt.Y("seuil:Q", title="Seuil (°C)"),
        tooltip=["time:T", "seuil:Q"]
    ).properties(height=240, title="Seuil (ESP32)")

    line_pot = alt.Chart(df).mark_line().encode(
        x=alt.X("time:T", title="Temps"),
        y=alt.Y("pot:Q", title="Potentiomètre (brut)"),
        tooltip=["time:T", "pot:Q"]
    ).properties(height=240, title="Potentiomètre")

    colC, colD = st.columns(2)
    with colC:
        st.altair_chart(line_seuil, use_container_width=True)
    with colD:
        st.altair_chart(line_pot, use_container_width=True)

st.markdown("---")

# Diagnostic JSON
st.subheader("🩺 Diagnostic")
colj1, colj2 = st.columns(2)

with colj1:
    st.write("Dernier JSON reçu :")
    st.json(d["raw_payload"] if d["raw_payload"] is not None else {})

with colj2:
    st.write("Outils :")
    if st.button("🗑️ Réinitialiser l'historique"):
        st.session_state.history = []
        st.success("Historique effacé")

    # Export CSV (sans ouvrir en boucle dans le callback)
    if len(hist) > 0:
        df_all = pd.DataFrame(hist)
        csv = df_all.to_csv(index=False)
        st.download_button("💾 Télécharger CSV", data=csv, file_name="historique_mesures.csv", mime="text/csv")

if d["last_update"] is not None:
    st.caption(f"Dernière mise à jour : {d['last_update']}")
else:
    st.caption("Aucune donnée reçue pour l’instant.")
