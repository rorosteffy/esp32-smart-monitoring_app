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

# ==========================
# CONFIG MQTT
# ==========================
MQTT_BROKER = "51.103.239.173"
MQTT_PORT = 1883

TOPIC_DATA = "capteur/data"            # ESP32 -> JSON
TOPIC_CMD  = "noeud/operateur/cmd"     # Streamlit -> commandes binôme (LED)

# Commandes envoyées à la binôme (texte simple)
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

LAST = {
    "temperature": None,
    "humidity": None,
    "seuil": None,        # ✅ clé correcte venant de l’ESP32
    "flame": None,
    "flameHande": None,
    "alarm": None,
    "alarmLocal": None,
    "muted": None,
    "motorForced": None,
    "motorSpeed": None,
    "last_update": None,
}

HISTORY = deque(maxlen=300)  # garde les 300 derniers points


# ==========================
# MQTT CALLBACKS
# ==========================
def on_connect(client, userdata, flags, rc):
    with LOCK:
        st.session_state["mqtt_connected"] = (rc == 0)
    if rc == 0:
        client.subscribe(TOPIC_DATA)
        print("✅ MQTT connecté, abonné à", TOPIC_DATA)
    else:
        print("❌ MQTT connexion error rc =", rc)


def on_disconnect(client, userdata, rc):
    with LOCK:
        st.session_state["mqtt_connected"] = False
    print("🔌 MQTT déconnecté rc =", rc)


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print("JSON invalide :", e)
        return

    now = datetime.now()

    # ✅ IMPORTANT: ton ESP32 publie doc["seuil"] (pas seuilPot/tempSeuil)
    with LOCK:
        LAST["temperature"]  = payload.get("temperature")
        LAST["humidity"]     = payload.get("humidity")
        LAST["seuil"]        = payload.get("seuil")          # ✅
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
# MQTT CLIENT (créé 1 seule fois)
# ==========================
@st.cache_resource
def init_mqtt():
    client_id = f"streamlit_{int(time.time())}"
    client = mqtt.Client(client_id=client_id)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    # Connexion async + loop en thread interne
    client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()

    return client


def mqtt_publish_cmd(cmd: str):
    client = init_mqtt()
    try:
        client.publish(TOPIC_CMD, cmd, qos=0, retain=False)
        st.toast(f"✅ Commande envoyée: {cmd}", icon="📡")
    except Exception as e:
        st.error(f"Erreur publish MQTT: {e}")


# ==========================
# UI
# ==========================
def nice_metric(label, value, suffix=""):
    if value is None:
        st.metric(label, "—")
    else:
        if isinstance(value, (int, float)):
            st.metric(label, f"{value:.1f}{suffix}")
        else:
            st.metric(label, f"{value}{suffix}")


def build_charts(df: pd.DataFrame):
    # Convert time for altair
    base = alt.Chart(df).encode(x=alt.X("time:T", title="Temps"))

    temp = base.mark_line(point=True).encode(
        y=alt.Y("temperature:Q", title="Température (°C)"),
        tooltip=["time:T", "temperature:Q"]
    ).properties(height=260, title="Température")

    hum = base.mark_line(point=True).encode(
        y=alt.Y("humidity:Q", title="Humidité (%)"),
        tooltip=["time:T", "humidity:Q"]
    ).properties(height=260, title="Humidité")

    seuil = base.mark_line(point=True).encode(
        y=alt.Y("seuil:Q", title="Seuil (°C)"),
        tooltip=["time:T", "seuil:Q"]
    ).properties(height=260, title="Seuil (ESP32)")

    flame = base.mark_line(point=True).encode(
        y=alt.Y("flame:Q", title="Flamme (0/1)"),
        tooltip=["time:T", "flame:Q"]
    ).properties(height=260, title="IR / Flamme")

    c1, c2 = st.columns(2)
    with c1:
        st.altair_chart(temp, use_container_width=True)
    with c2:
        st.altair_chart(hum, use_container_width=True)

    c3, c4 = st.columns(2)
    with c3:
        st.altair_chart(seuil, use_container_width=True)
    with c4:
        st.altair_chart(flame, use_container_width=True)


def main():
    st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")

    # Init state connected flag
    if "mqtt_connected" not in st.session_state:
        st.session_state["mqtt_connected"] = False

    # ✅ démarre MQTT (1 seule fois)
    init_mqtt()

    # CSS simple
    st.markdown("""
    <style>
      .stApp { background: radial-gradient(circle at top left, #f5f0ff 0, #dbe2ff 35%, #c8d9ff 65%, #b8d3ff 100%); }
    </style>
    """, unsafe_allow_html=True)

    # Header + logo
    col_logo, col_title = st.columns([1, 6])
    with col_logo:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=120)
        else:
            st.write("EPHEC")
    with col_title:
        st.title("Gestion Intelligente Température & Sécurité – IoT")

    # Etat MQTT
    if st.session_state["mqtt_connected"]:
        st.success("État MQTT : ✅ Connecté au broker")
    else:
        st.error("État MQTT : 🔴 Déconnecté du broker")

    st.markdown("---")

    # Snapshot thread-safe
    with LOCK:
        last = dict(LAST)
        hist = list(HISTORY)

    # Cartes
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.subheader("🌡️ Température")
        nice_metric("Temp (°C)", last["temperature"])
    with c2:
        st.subheader("💧 Humidité")
        nice_metric("Hum (%)", last["humidity"])
    with c3:
        st.subheader("📦 Seuil (ESP32)")
        if last["seuil"] is None:
            st.metric("Seuil (°C)", "— (non reçu)")
        else:
            st.metric("Seuil (°C)", f"{last['seuil']:.1f}")
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
        st.subheader("🔥 IR / Flamme (Steffy)")
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
            st.warning("⚠️ Flamme détectée chez la binôme (flameHande=1)")
        else:
            st.success("✅ Pas de flamme chez la binôme (flameHande=0)")

    st.markdown("---")

    # ✅ COMMANDES BINÔME
    st.subheader(f"🎛️ Commandes vers la binôme (topic: {TOPIC_CMD})")

    b1, b2, b3 = st.columns([1, 1, 3])
    with b1:
        if st.button("🔴 LED ROUGE ON", use_container_width=True):
            mqtt_publish_cmd(CMD_LED_ON)

    with b2:
        if st.button("⚫ LED ROUGE OFF", use_container_width=True):
            mqtt_publish_cmd(CMD_LED_OFF)

    with b3:
        st.info("📌 Ta binôme doit coder son ESP32 pour écouter ce topic et exécuter LED_RED_ON / LED_RED_OFF.")

    st.markdown("---")

    # Graphiques courbes
    st.subheader("📈 Graphiques en temps réel (courbes)")
    if len(hist) == 0:
        st.info("En attente de données sur capteur/data…")
    else:
        df = pd.DataFrame(hist).dropna(subset=["time"]).tail(150)
        build_charts(df)

    st.markdown("---")

    # Diagnostic + export CSV (sans écrire fichier en boucle)
    st.subheader("🩺 Diagnostic")
    d1, d2 = st.columns(2)
    with d1:
        st.write("Dernier JSON interprété :")
        st.json(last)

    with d2:
        st.write("Outils :")
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

    if last["last_update"] is not None:
        st.caption(f"Dernière mise à jour : {last['last_update']}")
    else:
        st.caption("Aucune donnée reçue pour l’instant.")

    # ✅ RAFRAÎCHISSEMENT UI SANS CASSER MQTT
    refresh_s = st.sidebar.slider("Refresh UI (secondes)", 1, 10, 2)
    time.sleep(refresh_s)
    st.rerun()


if __name__ == "__main__":
    main()
