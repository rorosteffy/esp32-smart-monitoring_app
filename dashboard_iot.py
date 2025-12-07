import streamlit as st
import paho.mqtt.client as mqtt
import json
import threading
import time
import pandas as pd
import altair as alt
from datetime import datetime

# ==========================
# CONFIG MQTT
# ==========================
MQTT_BROKER = "51.103.239.173"
MQTT_PORT = 1883
TOPIC_DATA = "capteur/data"   # JSON global envoyé par l’ESP32

# ==========================
# ETAT GLOBAL – 1ère initialisation uniquement
# ==========================

# Ces "if 'xxx' not in globals()" évitent que Streamlit
# réinitialise les variables à chaque rerun.
if "mqtt_client" not in globals():
    mqtt_client = None

if "mqtt_thread" not in globals():
    mqtt_thread = None

if "mqtt_started" not in globals():
    mqtt_started = False

if "mqtt_connected" not in globals():
    mqtt_connected = False

if "last_data" not in globals():
    last_data = {
        "temperature": None,
        "humidity": None,
        "tempSeuil": None,
        "humSeuil": None,
        "flame": None,
        "flameRaw": None,
        "pot": None,
        "seuilPot": None,
        "alarm": None,
        "last_update": None,
    }

if "data_history" not in globals():
    # Chaque entrée : {"time": datetime, "temperature":..., "humidity":..., "flame":..., "pot":...}
    data_history = []


# ==========================
# CALLBACKS MQTT
# ==========================

def on_connect(client, userdata, flags, rc):
    global mqtt_connected
    print("on_connect rc =", rc)
    if rc == 0:
        mqtt_connected = True
        print("✅ Connecté au broker MQTT, abonné à", TOPIC_DATA)
        client.subscribe(TOPIC_DATA)
    else:
        mqtt_connected = False
        print("❌ Erreur de connexion MQTT")


def on_disconnect(client, userdata, rc):
    global mqtt_connected
    mqtt_connected = False
    print("🔌 Déconnecté du broker MQTT (rc =", rc, ")")


def on_message(client, userdata, msg):
    """Réception des messages JSON de l’ESP32."""
    global last_data, data_history

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        print("MQTT message reçu sur", msg.topic, ":", payload)
    except Exception as e:
        print("JSON invalide :", e)
        return

    # Mise à jour du dernier état
    last_data["temperature"] = payload.get("temperature")
    last_data["humidity"] = payload.get("humidity")
    last_data["tempSeuil"] = payload.get("tempSeuil")
    last_data["humSeuil"] = payload.get("humSeuil")
    last_data["flame"] = payload.get("flame")
    last_data["flameRaw"] = payload.get("flameRaw")
    last_data["pot"] = payload.get("pot")
    last_data["seuilPot"] = payload.get("seuilPot")
    last_data["alarm"] = payload.get("alarm")
    last_data["last_update"] = datetime.now()

    # On stocke aussi dans l’historique pour les graphes
    data_history.append({
        "time": last_data["last_update"],
        "temperature": last_data["temperature"],
        "humidity": last_data["humidity"],
        "flame": last_data["flame"],
        "pot": last_data["pot"],
    })

    # (optionnel) Sauvegarde CSV automatique
    try:
        with open("historique_mesures.csv", "a", encoding="utf-8") as f:
            line = f"{last_data['last_update']};{last_data['temperature']};{last_data['humidity']};{last_data['flame']};{last_data['pot']}\n"
            f.write(line)
    except Exception as e:
        print("Erreur écriture CSV :", e)


# ==========================
# DÉMARRAGE CLIENT MQTT
# ==========================

def start_mqtt():
    """Lance le client MQTT dans un thread séparé (une seule fois)."""
    global mqtt_client, mqtt_thread, mqtt_started

    if mqtt_started:
        return  # déjà lancé

    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message

    def _mqtt_loop():
        while True:
            try:
                if not mqtt_connected:
                    print("🔁 Tentative de connexion au broker MQTT...")
                    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
                mqtt_client.loop_forever()
            except Exception as e:
                print("⚠️ Erreur dans la boucle MQTT :", e)
                time.sleep(5)  # petite pause avant de retenter

    mqtt_thread = threading.Thread(target=_mqtt_loop, daemon=True)
    mqtt_thread.start()
    mqtt_started = True


# ==========================
# UI STREAMLIT
# ==========================

def build_dashboard():
    st.set_page_config(
        page_title="Gestion Intelligente Température & Sécurité – IoT",
        layout="wide",
    )

    # --------- Bandeau titre + logo EPHEC ---------
    col_logo, col_title = st.columns([1, 5])
    with col_logo:
        # Image dans le même dossier : LOGO_EPHEC_HE.png
        st.image("LOGO_EPHEC_HE.png", width=130)
    with col_title:
        st.markdown(
            "<h1 style='margin-bottom:0.2em;'>Gestion Intelligente Température & Sécurité – IoT</h1>",
            unsafe_allow_html=True,
        )

    # --------- État MQTT ---------
    if mqtt_connected:
        st.success("État MQTT : ✅ Connecté au broker MQTT")
    else:
        st.error("État MQTT : 🔴 Déconnecté du broker MQTT")

    st.markdown("---")

    # --------- 4 cartes principales ---------
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.subheader("🌡️ Température")
        if last_data["temperature"] is not None:
            st.metric("Température (°C)", f"{last_data['temperature']:.1f}")
        else:
            st.write("—")

    with c2:
        st.subheader("💧 Humidité")
        if last_data["humidity"] is not None:
            st.metric("Humidité (%)", f"{last_data['humidity']:.1f}")
        else:
            st.write("—")

    with c3:
        st.subheader("📦 Température du seuil (ESP32)")
        if last_data["seuilPot"] is not None:
            st.metric("Seuil T (°C)", f"{last_data['seuilPot']:.1f}")
        else:
            st.write("Seuil T consigne : None °C")

    with c4:
        st.subheader("🕹️ Potentiomètre → Seuil")
        if last_data["pot"] is not None:
            st.metric("Valeur brute POT", f"{last_data['pot']}")
        else:
            st.write("Valeur brute POT : None")

    st.markdown("---")

    # --------- IR / Flamme + État alarme ---------
    c5, c6 = st.columns(2)

    with c5:
        st.subheader("🔥 IR / Flamme")
        flame = last_data["flame"]
        if flame is None:
            st.info("En attente de données (flame = None)...")
        elif flame == 1:
            st.error("🔥 Feu détecté (flame = 1)")
        else:
            st.success("✅ Aucun feu détecté (flame = 0)")

    with c6:
        st.subheader("🚨 État de l'alarme")
        if last_data["alarm"]:
            st.error("Alarme ACTIVE")
        else:
            st.success("Alarme inactive")

    st.markdown("---")

    # --------- Graphiques en temps réel ---------
    st.subheader("📊 Graphiques en temps réel")

    if len(data_history) == 0:
        st.info("En attente de données temps réel des capteurs…")
    else:
        df = pd.DataFrame(data_history)

        # Température & Humidité
        col_g1, col_g2 = st.columns(2)

        with col_g1:
            temp_chart = (
                alt.Chart(df)
                .mark_line()
                .encode(
                    x="time:T",
                    y=alt.Y("temperature:Q", title="Température (°C)"),
                    tooltip=["time:T", "temperature:Q"],
                )
                .properties(height=250, title="Température")
            )
            st.altair_chart(temp_chart, use_container_width=True)

        with col_g2:
            hum_chart = (
                alt.Chart(df)
                .mark_line()
                .encode(
                    x="time:T",
                    y=alt.Y("humidity:Q", title="Humidité (%)"),
                    tooltip=["time:T", "humidity:Q"],
                )
                .properties(height=250, title="Humidité")
            )
            st.altair_chart(hum_chart, use_container_width=True)

        # Flamme & Potentiomètre
        col_g3, col_g4 = st.columns(2)

        with col_g3:
            flame_chart = (
                alt.Chart(df)
                .mark_line(step="post")
                .encode(
                    x="time:T",
                    y=alt.Y("flame:Q", title="Flamme détectée (0/1)"),
                    tooltip=["time:T", "flame:Q"],
                )
                .properties(height=250, title="IR / Flamme")
            )
            st.altair_chart(flame_chart, use_container_width=True)

        with col_g4:
            pot_chart = (
                alt.Chart(df)
                .mark_line()
                .encode(
                    x="time:T",
                    y=alt.Y("pot:Q", title="Valeur brute POT"),
                    tooltip=["time:T", "pot:Q"],
                )
                .properties(height=250, title="Potentiomètre")
            )
            st.altair_chart(pot_chart, use_container_width=True)

    st.markdown("---")

    # --------- Zone diagnostic / JSON ---------
    st.subheader("🩺 Diagnostic du système")

    col_d1, col_d2 = st.columns(2)

    with col_d1:
        st.write("**Dernier message JSON reçu :**")
        st.json(last_data)

    with col_d2:
        st.write("**Outils :**")
        if st.button("🗑️ Réinitialiser l’historique"):
            data_history.clear()
            st.success("Historique effacé (la prochaine mesure remplira à nouveau les graphiques).")

        # Téléchargement CSV (si le fichier existe)
        try:
            with open("historique_mesures.csv", "r", encoding="utf-8") as f:
                csv_content = f.read()
            st.download_button(
                "💾 Télécharger l’historique CSV",
                data=csv_content,
                file_name="historique_mesures.csv",
                mime="text/csv",
            )
        except FileNotFoundError:
            st.info("Aucun fichier CSV encore créé (attends la première mesure).")

    # Petite info sur la dernière mise à jour
    if last_data["last_update"] is not None:
        st.caption(f"Dernière mise à jour : {last_data['last_update']}")
    else:
        st.caption("Aucune donnée reçue pour l’instant.")


# ==========================
# MAIN
# ==========================

def main():
    # On s’assure que le client MQTT tourne en arrière-plan
    start_mqtt()
    # Puis on construit le dashboard
    build_dashboard()


if __name__ == "__main__":
    main()
