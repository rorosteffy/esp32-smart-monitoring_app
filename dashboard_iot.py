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

TOPIC_DATA = "capteur/data"      # JSON global envoyé par ESP32
# si tu as une flamme “binôme” sur un autre topic, mets-le ici sinon laisse pareil
TOPIC_HANDE = "noeud/operateur/flame"

# TCP / WebSockets (ton mosquitto.conf montre: 1883 mqtt + 9001 websockets)
MQTT_TCP_PORT = 1883
MQTT_WS_PORT  = 9001
MQTT_WS_PATH  = "/"  # souvent "/" sur mosquitto websockets

# ==========================
# LOGO
# ==========================
LOGO_FILENAME = "LOGO_EPHEC_HE.png"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(SCRIPT_DIR, LOGO_FILENAME)

# ==========================
# SESSION STATE INIT
# ==========================
def init_state():
    if "mqtt_started" not in st.session_state:
        st.session_state.mqtt_started = False

    if "mqtt_connected" not in st.session_state:
        st.session_state.mqtt_connected = False

    if "mqtt_mode" not in st.session_state:
        st.session_state.mqtt_mode = "INIT"  # TCP / WS / INIT

    if "last_error" not in st.session_state:
        st.session_state.last_error = None

    if "last_msg_ts" not in st.session_state:
        st.session_state.last_msg_ts = None

    if "last_data" not in st.session_state:
        st.session_state.last_data = {
            "temperature": None,
            "humidity": None,
            "seuil": None,
            "flame": None,
            "flameHande": None,
            "alarm": None,
            "alarmTemp": None,
            "alarmFlame": None,
            "alarmLocal": None,
            "muted": None,
            "motorForced": None,
            "motorSpeed": None,
        }

    if "history" not in st.session_state:
        st.session_state.history = []  # list of dicts

init_state()

# ==========================
# MQTT CALLBACKS (paho v1 + v2)
# ==========================
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        st.session_state.mqtt_connected = True
        st.session_state.last_error = None
        client.subscribe(TOPIC_DATA)
        # TOPIC_HANDE optionnel
        if TOPIC_HANDE:
            client.subscribe(TOPIC_HANDE)
    else:
        st.session_state.mqtt_connected = False
        st.session_state.last_error = f"Erreur connexion MQTT rc={rc}"

def on_disconnect(client, userdata, rc, properties=None):
    st.session_state.mqtt_connected = False

def safe_float(v):
    try:
        if v is None:
            return None
        return float(v)
    except:
        return None

def parse_payload_to_data(payload: dict):
    """Mappe ton JSON MQTT vers last_data."""
    d = st.session_state.last_data

    # clés vues dans ton screenshot VM:
    # {"temperature":23.6,"humidity":39,"seuil":30.9,"flame":0,"flameHande":0,"alarmTemp":false,...,"motorSpeed":255}
    d["temperature"] = safe_float(payload.get("temperature"))
    d["humidity"]    = safe_float(payload.get("humidity"))
    d["seuil"]       = safe_float(payload.get("seuil"))

    # flame / flameHande peuvent être 0/1 ou bool
    def to01(x):
        if x is None:
            return None
        if isinstance(x, bool):
            return 1 if x else 0
        try:
            return int(x)
        except:
            return None

    d["flame"]      = to01(payload.get("flame"))
    d["flameHande"] = to01(payload.get("flameHande"))

    # alarm global ou alarmTemp / alarmFlame / alarmLocal
    d["alarm"]      = payload.get("alarm")
    d["alarmTemp"]  = payload.get("alarmTemp")
    d["alarmFlame"] = payload.get("alarmFlame")
    d["alarmLocal"] = payload.get("alarmLocal")

    d["muted"]       = payload.get("muted")
    d["motorForced"] = payload.get("motorForced")
    d["motorSpeed"]  = payload.get("motorSpeed")

def on_message(client, userdata, msg):
    try:
        raw = msg.payload.decode("utf-8", errors="ignore").strip()
        # topic flame binôme peut être "0/1"
        if msg.topic == TOPIC_HANDE and raw in ("0", "1"):
            st.session_state.last_data["flameHande"] = int(raw)
            st.session_state.last_msg_ts = datetime.now()
        else:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                parse_payload_to_data(payload)
                st.session_state.last_msg_ts = datetime.now()
            else:
                return
    except Exception as e:
        st.session_state.last_error = f"JSON invalide: {e}"
        return

    # push history
    now = datetime.now()
    d = st.session_state.last_data

    st.session_state.history.append({
        "time": now,
        "temperature": d["temperature"],
        "humidity": d["humidity"],
        "seuil": d["seuil"],
        "flame": d["flame"],
        "flameHande": d["flameHande"],
    })

    # garder derniers points
    if len(st.session_state.history) > 400:
        st.session_state.history = st.session_state.history[-400:]

    # append csv
    try:
        with open("historique_mesures.csv", "a", encoding="utf-8") as f:
            f.write(f"{now.isoformat()};{d['temperature']};{d['humidity']};{d['seuil']};{d['flame']};{d['flameHande']}\n")
    except:
        pass

# ==========================
# MQTT START (thread) - AUTO TCP then WS
# ==========================
def start_mqtt_once():
    if st.session_state.mqtt_started:
        return

    st.session_state.mqtt_started = True

    def mqtt_worker():
        # on tente TCP d'abord (plus simple)
        # si ça échoue, on bascule WS
        while True:
            try:
                client = mqtt.Client()
                client.on_connect = on_connect
                client.on_disconnect = on_disconnect
                client.on_message = on_message

                # ===== TRY TCP =====
                st.session_state.mqtt_mode = f"TCP:{MQTT_TCP_PORT}"
                client.connect(MQTT_BROKER, MQTT_TCP_PORT, keepalive=60)
                client.loop_forever(retry_first_connection=True)

            except Exception as e_tcp:
                st.session_state.last_error = f"TCP KO: {e_tcp}"

                # ===== TRY WS =====
                try:
                    client = mqtt.Client(transport="websockets")
                    client.on_connect = on_connect
                    client.on_disconnect = on_disconnect
                    client.on_message = on_message

                    # important: ws_set_options pour path
                    try:
                        client.ws_set_options(path=MQTT_WS_PATH)
                    except:
                        pass

                    st.session_state.mqtt_mode = f"WS:{MQTT_WS_PORT}"
                    client.connect(MQTT_BROKER, MQTT_WS_PORT, keepalive=60)
                    client.loop_forever(retry_first_connection=True)

                except Exception as e_ws:
                    st.session_state.last_error = f"WS KO: {e_ws}"
                    st.session_state.mqtt_connected = False
                    time.sleep(3)

    t = threading.Thread(target=mqtt_worker, daemon=True)
    t.start()

# ==========================
# UI STYLE (PRO EPHEC IoT)
# ==========================
def inject_style():
    st.markdown("""
    <style>
    .stApp {
        background: linear-gradient(
            135deg,
            #f8fafc 0%,
            #eef2ff 25%,
            #e0e7ff 50%,
            #dbeafe 75%,
            #f8fafc 100%
        );
        color: #0f172a;
    }
    /* cartes */
    [data-testid="stMetric"], .stAlert, .element-container {
        background: rgba(255, 255, 255, 0.80);
        border-radius: 14px;
        padding: 12px;
        box-shadow: 0 8px 20px rgba(0,0,0,0.06);
    }
    h1, h2, h3 { color:#0f172a; font-weight:800; }
    </style>
    """, unsafe_allow_html=True)

# ==========================
# CHARTS (LIGNE)
# ==========================
def build_line_chart(df, field, title, unit=""):
    base = alt.Chart(df).encode(
        x=alt.X("time:T", title="Temps"),
        tooltip=["time:T", alt.Tooltip(field+":Q", title=title)]
    )
    line = base.mark_line().encode(
        y=alt.Y(field+":Q", title=f"{title} {unit}".strip())
    )
    pts = base.mark_circle(size=45).encode(
        y=alt.Y(field+":Q")
    )
    return (line + pts).properties(height=260, title=title)

# ==========================
# DASHBOARD
# ==========================
def dashboard():
    st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")
    inject_style()

    # header
    col_logo, col_title = st.columns([1, 6])
    with col_logo:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=120)
        else:
            st.write("EPHEC")
    with col_title:
        st.markdown("# 🌡️ Gestion Intelligente Température & Sécurité – IoT")
        st.caption(f"Broker: {MQTT_BROKER} | Mode: {st.session_state.mqtt_mode} | Topic: {TOPIC_DATA}")

    # status bars
    if st.session_state.mqtt_connected:
        st.success("✅ MQTT connecté")
    else:
        st.error("🔴 MQTT déconnecté")

    if st.session_state.last_error:
        st.warning(f"⚠️ {st.session_state.last_error}")

    # last msg
    if st.session_state.last_msg_ts:
        st.info(f"✅ Données reçues: {st.session_state.last_msg_ts.strftime('%H:%M:%S')} | +{len(st.session_state.history)} points")
    else:
        st.warning("En attente de données MQTT… (vérifie que l’ESP32 publie bien sur capteur/data)")

    st.markdown("---")

    d = st.session_state.last_data

    # metrics row
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("🌡️ Température (°C)", "—" if d["temperature"] is None else f"{d['temperature']:.1f}")
    with c2:
        st.metric("💧 Humidité (%)", "—" if d["humidity"] is None else f"{d['humidity']:.0f}")
    with c3:
        st.metric("📦 Seuil (°C)", "—" if d["seuil"] is None else f"{d['seuil']:.2f}")
    with c4:
        alarm_on = bool(d.get("alarm")) or bool(d.get("alarmTemp")) or bool(d.get("alarmFlame")) or bool(d.get("alarmLocal"))
        st.metric("🚨 Alarme", "ACTIVE" if alarm_on else "OK")

    st.markdown("---")

    # flame states
    f1, f2 = st.columns(2)
    with f1:
        st.subheader("🔥 Flamme Steffy")
        if d["flame"] is None:
            st.info("En attente…")
        elif d["flame"] == 1:
            st.error("🔥 FEU détecté")
        else:
            st.success("✅ Pas de flamme")

    with f2:
        st.subheader("🔥 Flamme Hande")
        if d["flameHande"] is None:
            st.info("En attente…")
        elif d["flameHande"] == 1:
            st.error("🔥 FEU détecté (binôme)")
        else:
            st.success("✅ Pas de flamme")

    st.markdown("---")

    st.subheader("📈 Graphiques temps réel (LIGNES)")
    if len(st.session_state.history) == 0:
        st.info("Aucune donnée reçue pour tracer les graphes.")
    else:
        df = pd.DataFrame(st.session_state.history).dropna(subset=["time"]).tail(200)

        g1, g2 = st.columns(2)
        with g1:
            st.altair_chart(build_line_chart(df, "temperature", "Température", "(°C)"), use_container_width=True)
        with g2:
            st.altair_chart(build_line_chart(df, "humidity", "Humidité", "(%)"), use_container_width=True)

        g3, g4 = st.columns(2)
        with g3:
            st.altair_chart(build_line_chart(df, "seuil", "Seuil (ESP32)", "(°C)"), use_container_width=True)
        with g4:
            # flame 0/1 line
            flame_df = df.copy()
            st.altair_chart(build_line_chart(flame_df, "flame", "Flamme Steffy (0/1)"), use_container_width=True)

    st.markdown("---")

    # tools
    st.subheader("🧰 Outils")
    cc1, cc2 = st.columns(2)

    with cc1:
        if st.button("🗑️ Réinitialiser l’historique"):
            st.session_state.history = []
            st.success("Historique effacé.")

    with cc2:
        try:
            with open("historique_mesures.csv", "r", encoding="utf-8") as f:
                csv_content = f.read()
            st.download_button("💾 Télécharger CSV", data=csv_content, file_name="historique_mesures.csv", mime="text/csv")
        except:
            st.info("CSV pas encore créé.")

    st.markdown("---")
    st.subheader("🔎 Dernier JSON (debug)")
    st.json(st.session_state.last_data)

# ==========================
# MAIN
# ==========================
start_mqtt_once()
dashboard()

# refresh propre (Streamlit Cloud OK)
time.sleep(1)
st.rerun()
