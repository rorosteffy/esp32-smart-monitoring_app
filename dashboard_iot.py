# ---------------------------------------------------------
# DASHBOARD STREAMLIT — MQTT temps réel + historique + CSV
# (Connexion MQTT persistante dans un thread + auto-refresh)
# ---------------------------------------------------------

import streamlit as st
from streamlit_autorefresh import st_autorefresh

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
TOPIC_DATA = "capteur/data"  # JSON global envoyé par l’ESP32

# ==========================
# LOGO (optionnel)
# ==========================
LOGO_FILENAME = "LOGO_EPHEC_HE.png"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, LOGO_FILENAME)

# ==========================
# FICHIER CSV
# ==========================
CSV_FILE = "historique_mesures.csv"

# ==========================
# ETAT GLOBAL (thread-safe)
# ==========================
LOCK = threading.Lock()

mqtt_client = None
mqtt_thread = None
mqtt_started = False
mqtt_connected = False

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
    "alarmTemp": None,
    "alarmFlame": None,
    "alarmLocal": None,
    "muted": None,
    "motorForced": None,
    "motorSpeed": None,
    "last_update": None,
}

data_history = []  # list de dicts: {"time":..., "temperature":..., ...}

# =========================================================
# OUTILS
# =========================================================
def _to_float(x):
    try:
        if x is None:
            return None
        return float(x)
    except:
        return None

def _to_int(x):
    try:
        if x is None:
            return None
        return int(x)
    except:
        return None

def ensure_csv_header():
    """Ajoute l'en-tête CSV si le fichier n'existe pas ou est vide."""
    if (not os.path.exists(CSV_FILE)) or os.path.getsize(CSV_FILE) == 0:
        with open(CSV_FILE, "w", encoding="utf-8") as f:
            f.write("time;temperature;humidity;flame;pot\n")

# =========================================================
# CALLBACKS MQTT
# =========================================================
def on_connect(client, userdata, flags, rc):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        print("✅ MQTT connecté, subscribe:", TOPIC_DATA)
        client.subscribe(TOPIC_DATA)
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
        raw = msg.payload.decode("utf-8", errors="ignore")
        payload = json.loads(raw)
        print("MQTT reçu:", payload)
    except Exception as e:
        print("⚠️ JSON invalide :", e)
        return

    now = datetime.now()

    # ----- mapping robuste (car tes payloads changent parfois de noms) -----
    # exemples vus: "humidity" ou "humidite"
    humidity = payload.get("humidity", payload.get("humidite"))
    # seuil: "seuil" ou "seuilPot" ou "tempSeuil"
    seuil = payload.get("seuilPot", payload.get("seuil", payload.get("tempSeuil")))
    # alarm: "alarm" ou alarmTemp/alarmFlame
    alarm = payload.get("alarm")
    alarmTemp = payload.get("alarmTemp")
    alarmFlame = payload.get("alarmFlame")

    with LOCK:
        last_data["temperature"] = _to_float(payload.get("temperature"))
        last_data["humidity"] = _to_float(humidity)

        last_data["tempSeuil"] = _to_float(payload.get("tempSeuil"))
        last_data["humSeuil"] = _to_float(payload.get("humSeuil"))

        last_data["flame"] = _to_int(payload.get("flame"))
        last_data["flameRaw"] = _to_int(payload.get("flameRaw"))

        last_data["pot"] = _to_int(payload.get("pot"))
        last_data["seuilPot"] = _to_float(seuil)

        last_data["alarm"] = bool(alarm) if alarm is not None else None
        last_data["alarmTemp"] = bool(alarmTemp) if alarmTemp is not None else None
        last_data["alarmFlame"] = bool(alarmFlame) if alarmFlame is not None else None

        last_data["alarmLocal"] = payload.get("alarmLocal")
        last_data["muted"] = payload.get("muted")
        last_data["motorForced"] = payload.get("motorForced")
        last_data["motorSpeed"] = payload.get("motorSpeed")

        last_data["last_update"] = now

        # Historique (pour graphes)
        data_history.append({
            "time": now,
            "temperature": last_data["temperature"],
            "humidity": last_data["humidity"],
            "flame": last_data["flame"],
            "pot": last_data["pot"],
        })

        # Limiter historique (ex: 300 points)
        if len(data_history) > 300:
            data_history[:] = data_history[-300:]

    # CSV
    try:
        ensure_csv_header()
        with open(CSV_FILE, "a", encoding="utf-8") as f:
            f.write(
                f"{now.isoformat(sep=' ')};"
                f"{last_data['temperature']};"
                f"{last_data['humidity']};"
                f"{last_data['flame']};"
                f"{last_data['pot']}\n"
            )
    except Exception as e:
        print("⚠️ Erreur écriture CSV :", e)

# =========================================================
# DÉMARRAGE MQTT (thread)
# =========================================================
def start_mqtt_once():
    """Démarre MQTT une seule fois (thread daemon)."""
    global mqtt_client, mqtt_thread, mqtt_started

    if mqtt_started:
        return

    mqtt_client = mqtt.Client()
    mqtt_client.on_connect = on_connect
    mqtt_client.on_disconnect = on_disconnect
    mqtt_client.on_message = on_message

    def _worker():
        # boucle de reconnexion
        while True:
            try:
                if not mqtt_connected:
                    print("🔁 Connexion MQTT…")
                    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
                    mqtt_client.loop_start()
                time.sleep(2)
            except Exception as e:
                print("⚠️ MQTT worker error:", e)
                try:
                    mqtt_client.loop_stop()
                except:
                    pass
                time.sleep(5)

    mqtt_thread = threading.Thread(target=_worker, daemon=True)
    mqtt_thread.start()
    mqtt_started = True

# =========================================================
# UI / DASHBOARD
# =========================================================
def build_dashboard():
    st.set_page_config(
        page_title="Gestion Intelligente Température & Sécurité – IoT",
        layout="wide",
    )

    # Refresh propre toutes les 1 seconde (sans st.rerun infini)
    st_autorefresh(interval=1000, key="refresh")

    # --------- CSS ---------
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

    # --------- Bandeau titre + logo ---------
    col_logo, col_title = st.columns([1, 6])

    with col_logo:
        try:
            if os.path.exists(LOGO_PATH):
                st.image(LOGO_PATH, width=120)
            elif os.path.exists(LOGO_FILENAME):
                st.image(LOGO_FILENAME, width=120)
            else:
                st.write("**EPHEC**")
        except:
            st.write("**EPHEC**")

    with col_title:
        st.markdown(
            "<h1 style='margin-bottom:0.2em;'>Gestion Intelligente Température & Sécurité – IoT</h1>",
            unsafe_allow_html=True,
        )
        st.caption(f"Broker MQTT: {MQTT_BROKER}:{MQTT_PORT} — Topic: {TOPIC_DATA}")

    # --------- Etat MQTT ---------
    if mqtt_connected:
        st.success("État MQTT : ✅ Connecté")
    else:
        st.error("État MQTT : 🔴 Déconnecté (reconnexion automatique en cours…)")

    st.markdown("---")

    # Copie safe du dernier état
    with LOCK:
        d = dict(last_data)
        hist_copy = list(data_history)

    # --------- Cartes principales ---------
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.subheader("🌡️ Température")
        if d["temperature"] is not None:
            st.metric("Température (°C)", f"{d['temperature']:.1f}")
        else:
            st.write("—")

    with c2:
        st.subheader("💧 Humidité")
        if d["humidity"] is not None:
            st.metric("Humidité (%)", f"{d['humidity']:.1f}")
        else:
            st.write("—")

    with c3:
        st.subheader("🎚️ Seuil (ESP32)")
        if d["seuilPot"] is not None:
            st.metric("Seuil (°C)", f"{d['seuilPot']:.1f}")
        elif d["tempSeuil"] is not None:
            st.metric("tempSeuil (°C)", f"{d['tempSeuil']:.1f}")
        else:
            st.write("—")

    with c4:
        st.subheader("🕹️ Potentiomètre")
        if d["pot"] is not None:
            st.metric("POT (brut)", f"{d['pot']}")
        else:
            st.write("—")

    st.markdown("---")

    # --------- Flamme + Alarmes ---------
    c5, c6 = st.columns(2)

    with c5:
        st.subheader("🔥 Flamme (IR)")
        flame = d["flame"]
        if flame is None:
            st.info("En attente de données…")
        elif int(flame) == 1:
            st.error("🔥 Feu détecté (flame = 1)")
        else:
            st.success("✅ Aucun feu détecté (flame = 0)")

    with c6:
        st.subheader("🚨 Alarmes")
        # Si "alarm" existe -> priorité
        if d["alarm"] is True:
            st.error("ALARME GÉNÉRALE : ACTIVE")
        elif d["alarm"] is False:
            st.success("Alarme générale : inactive")
        else:
            st.write("Alarme générale : —")

        # détails
        colA, colB = st.columns(2)
        with colA:
            st.write("alarmTemp:", d["alarmTemp"])
        with colB:
            st.write("alarmFlame:", d["alarmFlame"])

    st.markdown("---")

    # --------- Graphiques ---------
    st.subheader("📊 Graphiques (100 derniers points)")

    if len(hist_copy) == 0:
        st.info("En attente de données temps réel des capteurs…")
    else:
        df = pd.DataFrame(hist_copy).tail(100)

        # Eviter bugs si time n’est pas datetime
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"])

        col_g1, col_g2 = st.columns(2)

        with col_g1:
            temp_chart = (
                alt.Chart(df)
                .mark_line()
                .encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("temperature:Q", title="Température (°C)"),
                    tooltip=["time:T", "temperature:Q"],
                )
                .properties(height=260, title="Température (ligne)")
            )
            st.altair_chart(temp_chart, use_container_width=True)

        with col_g2:
            hum_chart = (
                alt.Chart(df)
                .mark_line()
                .encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("humidity:Q", title="Humidité (%)"),
                    tooltip=["time:T", "humidity:Q"],
                )
                .properties(height=260, title="Humidité (ligne)")
            )
            st.altair_chart(hum_chart, use_container_width=True)

        col_g3, col_g4 = st.columns(2)

        with col_g3:
            flame_chart = (
                alt.Chart(df)
                .mark_step()
                .encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("flame:Q", title="Flamme (0/1)"),
                    tooltip=["time:T", "flame:Q"],
                )
                .properties(height=260, title="Flamme (step)")
            )
            st.altair_chart(flame_chart, use_container_width=True)

        with col_g4:
            pot_chart = (
                alt.Chart(df)
                .mark_line()
                .encode(
                    x=alt.X("time:T", title="Temps"),
                    y=alt.Y("pot:Q", title="POT (brut)"),
                    tooltip=["time:T", "pot:Q"],
                )
                .properties(height=260, title="Potentiomètre (ligne)")
            )
            st.altair_chart(pot_chart, use_container_width=True)

    st.markdown("---")

    # --------- Diagnostic + outils ---------
    st.subheader("🩺 Diagnostic / Données JSON")

    col_d1, col_d2 = st.columns(2)

    with col_d1:
        st.write("**Dernier état reçu :**")
        st.json(d)

        if d["last_update"] is not None:
            st.caption(f"Dernière mise à jour : {d['last_update']}")
        else:
            st.caption("Aucune donnée reçue pour l’instant.")

    with col_d2:
        st.write("**Outils :**")

        if st.button("🗑️ Réinitialiser l’historique"):
            with LOCK:
                data_history.clear()
            st.success("Historique effacé.")

        # Téléchargement CSV
        if os.path.exists(CSV_FILE):
            try:
                with open(CSV_FILE, "r", encoding="utf-8") as f:
                    csv_content = f.read()
                st.download_button(
                    "💾 Télécharger l’historique CSV",
                    data=csv_content,
                    file_name="historique_mesures.csv",
                    mime="text/csv",
                )
            except Exception as e:
                st.warning(f"Impossible de lire le CSV: {e}")
        else:
            st.info("Aucun fichier CSV encore créé (attends la première mesure).")

# =========================================================
# MAIN
# =========================================================
def main():
    start_mqtt_once()
    build_dashboard()

if __name__ == "__main__":
    main()
