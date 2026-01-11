import streamlit as st
import paho.mqtt.client as mqtt
import json
import threading
import time
from collections import deque
import pandas as pd
import altair as alt
from datetime import datetime

# ==========================
# MQTT CONFIG
# ==========================
BROKER = "51.103.239.173"
PORT = 1883

TOPIC_DATA = "capteur/data"
TOPIC_CMD  = "noeud/operateur/cmd"   # <-- topic commande (boutons)

# ==========================
# OUTILS
# ==========================
def safe_json_loads(s: str):
    try:
        return json.loads(s)
    except:
        return None

def mqtt_publish_cmd(payload: dict):
    """Publie une commande MQTT uniquement quand on clique."""
    try:
        c = mqtt.Client()
        c.connect(BROKER, PORT, 60)
        c.publish(TOPIC_CMD, json.dumps(payload))
        c.disconnect()
        return True, None
    except Exception as e:
        return False, str(e)

# ==========================
# RESSOURCE MQTT (1 seule fois)
# ==========================
@st.cache_resource
def start_mqtt_listener():
    """
    Ressource partagée : 1 client MQTT + 1 thread.
    Ne redémarre pas à chaque clic (sinon ça bug).
    """
    state = {
        "connected": False,
        "last": {},
        "history": deque(maxlen=200),  # 200 derniers points
        "lock": threading.Lock(),
    }

    client = mqtt.Client()

    def on_connect(c, userdata, flags, rc):
        with state["lock"]:
            state["connected"] = (rc == 0)
        if rc == 0:
            c.subscribe(TOPIC_DATA)

    def on_disconnect(c, userdata, rc):
        with state["lock"]:
            state["connected"] = False

    def on_message(c, userdata, msg):
        raw = msg.payload.decode("utf-8", errors="ignore")
        payload = safe_json_loads(raw)
        if not isinstance(payload, dict):
            return

        now = datetime.now()

        # mapping robuste (selon tes payloads)
        temperature = payload.get("temperature")
        humidity = payload.get("humidity", payload.get("humidite"))
        flame = payload.get("flame")
        pot = payload.get("pot")
        seuil = payload.get("seuilPot", payload.get("seuil", payload.get("tempSeuil")))

        with state["lock"]:
            state["last"] = {
                **payload,
                "temperature": temperature,
                "humidity": humidity,
                "flame": flame,
                "pot": pot,
                "seuil": seuil,
                "last_update": now.isoformat(sep=" ", timespec="seconds"),
            }
            state["history"].append({
                "time": now,
                "temperature": temperature,
                "humidity": humidity,
                "flame": flame,
                "pot": pot,
                "seuil": seuil,
            })

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    def worker():
        while True:
            try:
                client.connect(BROKER, PORT, 60)
                client.loop_forever()
            except Exception:
                with state["lock"]:
                    state["connected"] = False
                time.sleep(3)

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    return state

# ==========================
# UI
# ==========================
st.set_page_config(page_title="ESP32 Smart Monitoring", layout="wide")
state = start_mqtt_listener()

# refresh automatique (toutes les 1s)
time.sleep(1)
st.experimental_rerun()

# lire état
with state["lock"]:
    connected = state["connected"]
    last = dict(state["last"])
    hist = list(state["history"])

st.title("📡 ESP32 Smart Monitoring – Temps Réel (MQTT)")

if connected:
    st.success("MQTT : ✅ Connecté")
else:
    st.error("MQTT : 🔴 Déconnecté (reconnexion automatique...)")

st.markdown("---")

# ======= BOUTONS (commandes) =======
st.subheader("🎛️ Commandes (ESP32)")

col1, col2 = st.columns(2)

with col1:
    if st.button("🔵 LED ON"):
        ok, err = mqtt_publish_cmd({"cmd": "LED_ON"})
        if ok:
            st.success("Commande envoyée : LED_ON")
        else:
            st.error(f"Erreur MQTT: {err}")

with col2:
    if st.button("⚫ LED OFF"):
        ok, err = mqtt_publish_cmd({"cmd": "LED_OFF"})
        if ok:
            st.success("Commande envoyée : LED_OFF")
        else:
            st.error(f"Erreur MQTT: {err}")

st.markdown("---")

# ======= KPIs =======
c1, c2, c3, c4 = st.columns(4)
c1.metric("🌡️ Température", str(last.get("temperature", "—")))
c2.metric("💧 Humidité", str(last.get("humidity", "—")))
c3.metric("🎚️ Seuil", str(last.get("seuil", "—")))
c4.metric("🔥 Flamme", str(last.get("flame", "—")))

st.markdown("---")

# ======= GRAPHIQUES =======
st.subheader("📈 Graphiques (derniers points)")

if len(hist) < 2:
    st.info("En attente de données…")
else:
    df = pd.DataFrame(hist)
    df["time"] = pd.to_datetime(df["time"])

    colA, colB = st.columns(2)
    with colA:
        chart_t = alt.Chart(df).mark_line().encode(x="time:T", y="temperature:Q").properties(height=250)
        st.altair_chart(chart_t, use_container_width=True)

    with colB:
        chart_h = alt.Chart(df).mark_line().encode(x="time:T", y="humidity:Q").properties(height=250)
        st.altair_chart(chart_h, use_container_width=True)

st.markdown("---")
st.subheader("🧾 Dernier JSON reçu")
st.json(last if last else {})
