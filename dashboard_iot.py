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

TOPIC_DATA = "capteur/data"            # JSON capteurs
TOPIC_CMD  = "noeud/operateur/cmd"     # commandes vers binôme (LED)

# ==========================
# LOGO (optionnel)
# ==========================
LOGO_FILENAME = "LOGO_EPHEC_HE.png"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, LOGO_FILENAME)

# ==========================
# ETAT GLOBAL (thread-safe simple)
# ==========================
mqtt_client = None
mqtt_thread = None
mqtt_started = False
mqtt_connected = False

last_data = {
    "temperature": None,
    "humidity": None,
    "seuil": None,     # ✅ champ "seuil"
    "flame": None,
    "pot": None,
    "alarm": None,
    "last_update": None,
    "raw": None,       # JSON brut
}

data_history = []  # list of dicts: time, temperature, humidity, seuil, flame, pot


# ==========================
# OUTILS
# ==========================
def pick(payload, *keys, default=None):
    """Retourne la première valeur non None existante dans payload."""
    for k in keys:
        if k in payload and payload[k] is not None:
            return payload[k]
    return default


def mqtt_publish(text: str) -> bool:
    """Publie une commande texte vers la binôme."""
    global mqtt_client, mqtt_connected
    if mqtt_client is None or not mqtt_connected:
        return False
    try:
        mqtt_client.publish(TOPIC_CMD, text)
        return True
    except Exception:
        return False


def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    elif hasattr(st, "experimental_rerun"):
        st.experimental_rerun()


# ==========================
# CALLBACKS MQTT
# ==========================
def on_connect(client, userdata, flags, rc):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        client.subscribe(TOPIC_DATA)
        print("✅ MQTT connecté. Abonné à:", TOPIC_DATA)
    else:
        mqtt_connected = False
        print("❌ MQTT erreur connexion rc =", rc)


def on_disconnect(client, userdata, rc):
    global mqtt_connected
    mqtt_connected = False
    print("🔌 MQTT déconnecté rc =", rc)


def on_message(client, userdata, msg):
    global last_data, data_history

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print("❌ JSON invalide:", e)
        return

    # garder JSON brut
    last_data["raw"] = payload

    # mapping
    last_data["temperature"] = pick(payload, "temperature", "temp", "T")
    last_data["humidity"]    = pick(payload, "humidity", "hum", "H")
    last_data["seuil"]       = pick(payload, "seuil", "threshold", "setpoint")   # ✅
    last_data["flame"]       = pick(payload, "flame", "ir", "fire")
    last_data["pot"]         = pick(payload, "pot", "adc", "potValue")
    last_data["alarm"]       = pick(payload, "alarm", "alarme", default=False)
    last_data["last_update"] = datetime.now()

    # historiser
    data_history.append({
        "time": last_data["last_update"],
        "temperature": last_data["temperature"],
        "humidity": last_data["humidity"],
        "seuil": last_data["seuil"],
        "flame": last_data["flame"],
        "pot": last_data["pot"],
    })

    # limiter l'historique
    if len(data_history) > 600:
        data_history[:] = data_history[-600:]


# ==========================
# MQTT THREAD (reconnexion robuste)
# ==========================
def start_mqtt():
    global mqtt_client, mqtt_thread, mqtt_started, mqtt_connected

    if mqtt_started:
        return

    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message

    def _loop():
        global mqtt_connected
        while True:
            try:
                # tentative de connexion si pas connecté
                if not mqtt_connected:
                    print("🔁 Tentative connexion MQTT...")
                    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
                # boucle réseau (bloque jusqu'à déconnexion)
                mqtt_client.loop_forever()
            except Exception as e:
                print("⚠️ Boucle MQTT erreur:", e)
                mqtt_connected = False
                time.sleep(3)

    mqtt_thread = threading.Thread(target=_loop, daemon=True)
    mqtt_thread.start()
    mqtt_started = True


# ==========================
# UI STREAMLIT
# ==========================
def build_dashboard():
    st.set_page_config(page_title="Dashboard IoT", layout="wide")

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

    # Etat MQTT
    if mqtt_connected:
        st.success("État MQTT : ✅ Connecté au broker")
    else:
        st.error("État MQTT : 🔴 Déconnecté du broker")

    st.divider()

    # Cartes
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.subheader("🌡️ Température")
        t = last_data["temperature"]
        st.metric("Temp (°C)", f"{float(t):.1f}" if t is not None else "—")

    with c2:
        st.subheader("💧 Humidité")
        h = last_data["humidity"]
        st.metric("Hum (%)", f"{float(h):.1f}" if h is not None else "—")

    with c3:
        st.subheader("📦 Seuil (ESP32)")
        s = last_data["seuil"]
        st.metric("Seuil", f"{float(s):.1f}" if s is not None else "— (non reçu)")

    with c4:
        st.subheader("🕹️ Potentiomètre")
        p = last_data["pot"]
        # pot peut être float ou int
        st.metric("POT (brut)", f"{int(float(p))}" if p is not None else "—")

    st.divider()

    # Flamme / Alarme
    c5, c6 = st.columns(2)

    with c5:
        st.subheader("🔥 IR / Flamme")
        f = last_data["flame"]
        if f is None:
            st.info("En attente (flame=None)")
        elif int(float(f)) == 1:
            st.error("🔥 Feu détecté (flame=1)")
        else:
            st.success("✅ Aucun feu (flame=0)")

    with c6:
        st.subheader("🚨 État de l'alarme")
        if bool(last_data["alarm"]):
            st.error("Alarme ACTIVE")
        else:
            st.success("Alarme inactive")

    st.divider()

    # Commandes binôme
    st.subheader("🎛️ Commandes vers la binôme (topic: noeud/operateur/cmd)")
    b1, b2, b3 = st.columns([1, 1, 2])

    with b1:
        if st.button("🔴 LED ROUGE ON", use_container_width=True):
            ok = mqtt_publish("LED_RED_ON")
            st.success("Commande envoyée ✅" if ok else "Échec envoi ❌ (MQTT non connecté)")

    with b2:
        if st.button("⚫ LED ROUGE OFF", use_container_width=True):
            ok = mqtt_publish("LED_RED_OFF")
            st.success("Commande envoyée ✅" if ok else "Échec envoi ❌ (MQTT non connecté)")

    with b3:
        st.info("Ta binôme doit SUBSCRIBE sur noeud/operateur/cmd et traiter LED_RED_ON / LED_RED_OFF.")

    st.divider()

    # Graphiques (courbes)
    st.subheader("📈 Graphiques en temps réel (courbes)")

    if len(data_history) == 0:
        st.info("En attente de données…")
    else:
        df = pd.DataFrame(data_history).tail(200).copy()

        # convertir en numérique (ignore les None)
        for col in ["temperature", "humidity", "seuil", "flame", "pot"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        g1, g2 = st.columns(2)
        with g1:
            chart_t = (
                alt.Chart(df)
                .mark_line(point=True)
                .encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("temperature:Q", title="Temp (°C)"),
                    tooltip=["time:T", "temperature:Q"],
                )
                .properties(height=260, title="Température")
            )
            st.altair_chart(chart_t, use_container_width=True)

        with g2:
            chart_h = (
                alt.Chart(df)
                .mark_line(point=True)
                .encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("humidity:Q", title="Hum (%)"),
                    tooltip=["time:T", "humidity:Q"],
                )
                .properties(height=260, title="Humidité")
            )
            st.altair_chart(chart_h, use_container_width=True)

        g3, g4 = st.columns(2)
        with g3:
            chart_s = (
                alt.Chart(df)
                .mark_line(point=True)
                .encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("seuil:Q", title="Seuil"),
                    tooltip=["time:T", "seuil:Q"],
                )
                .properties(height=260, title="Seuil")
            )
            st.altair_chart(chart_s, use_container_width=True)

        with g4:
            chart_f = (
                alt.Chart(df)
                .mark_line(point=True)
                .encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("flame:Q", title="Flamme (0/1)"),
                    tooltip=["time:T", "flame:Q"],
                )
                .properties(height=260, title="IR / Flamme")
            )
            st.altair_chart(chart_f, use_container_width=True)

    st.divider()

    # Diagnostic + outils
    st.subheader("🩺 Diagnostic du système")
    d1, d2 = st.columns([2, 1])

    with d1:
        st.write("**Dernier JSON reçu (brut) :**")
        st.json(last_data["raw"] if last_data["raw"] is not None else {"info": "Aucun message reçu"})

        st.write("**Dernier état interprété :**")
        st.json({k: v for k, v in last_data.items() if k != "raw"})

        if last_data["last_update"] is not None:
            st.caption(f"Dernière mise à jour : {last_data['last_update']}")

    with d2:
        st.write("**Outils :**")
        if st.button("🗑️ Vider l’historique"):
            data_history.clear()
            st.success("Historique effacé ✅")

        st.write("**Topic data :**")
        st.code(TOPIC_DATA)
        st.write("**Topic cmd :**")
        st.code(TOPIC_CMD)


# ==========================
# MAIN
# ==========================
def main():
    start_mqtt()
    build_dashboard()
    time.sleep(1)
    safe_rerun()


if __name__ == "__main__":
    main()
