import streamlit as st
import paho.mqtt.client as mqtt
import json
import threading
import time
import pandas as pd
import altair as alt

# ---------------- MQTT CONFIG ----------------
MQTT_BROKER = "51.103.239.173"   # IP de ton broker (VM)
MQTT_PORT = 1883
TOPIC_DATA = "capteur/data"      # même topic que sur l’ESP32

# ---------------- VARIABLES GLOBALES ----------------
mqtt_connected = False
mqtt_started = False

# Dernières valeurs reçues
last_data = {
    "temperature": None,
    "humidity": None,
    "tempSeuil": None,
    "humSeuil": None,
    "flame": None,
    "alarm": None,
    "pot": None,          # valeur venant de "marmite" ou "pot"
    "last_update": None,
}

# Historique pour les graphes
history = {
    "time": [],
    "temperature": [],
    "humidity": [],
    "tempSeuil": [],
    "humSeuil": [],
    "pot": [],
}

lock = threading.Lock()

# ---------------- MQTT CALLBACKS ----------------
def on_connect(client, userdata, flags, rc):
    global mqtt_connected
    print("on_connect rc =", rc)
    if rc == 0:
        mqtt_connected = True
        client.subscribe(TOPIC_DATA)
        print("✅ Connecté au broker MQTT, abonné à", TOPIC_DATA)
    else:
        mqtt_connected = False
        print("❌ Échec connexion MQTT, code rc =", rc)


def on_message(client, userdata, msg):
    global last_data, history
    try:
        payload_str = msg.payload.decode("utf-8")
        print("MQTT message reçu sur", msg.topic, ":", payload_str)
        data = json.loads(payload_str)

        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        t_str = time.strftime("%H:%M:%S")

        # --- Mapping marmite -> pot ---
        pot_value = None
        if "pot" in data:
            pot_value = data["pot"]
        elif "marmite" in data:
            pot_value = data["marmite"]

        with lock:
            # Met à jour les dernières valeurs simples
            for k in ("temperature", "humidity", "tempSeuil",
                      "humSeuil", "flame", "alarm"):
                if k in data:
                    last_data[k] = data[k]

            # Valeur du potentiomètre
            if pot_value is not None:
                last_data["pot"] = pot_value

            last_data["last_update"] = now_str

            # Historique pour les graphes
            history["time"].append(t_str)
            history["temperature"].append(data.get("temperature"))
            history["humidity"].append(data.get("humidity"))
            history["tempSeuil"].append(data.get("tempSeuil"))
            history["humSeuil"].append(data.get("humSeuil"))
            history["pot"].append(pot_value)

    except Exception as e:
        print("Erreur MQTT :", e)


# ---------------- MQTT THREAD ----------------
def mqtt_thread():
    client = mqtt.Client(client_id="STREAMLIT_DASHBOARD")
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        print("Connexion au broker MQTT…")
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        client.loop_forever()
    except Exception as e:
        print("Erreur de connexion MQTT :", e)


# Lancer le thread MQTT une seule fois
if not mqtt_started:
    th = threading.Thread(target=mqtt_thread, daemon=True)
    th.start()
    mqtt_started = True

# ---------------- STREAMLIT UI ----------------
st.set_page_config(
    page_title="Gestion Intelligente Température & Sécurité – IoT",
    layout="wide"
)

# ---- Thème pastel clair ----
st.markdown(
    """
    <style>
    body, .stApp {
        background: linear-gradient(135deg, #fdfbfb 0%, #ebedee 50%, #ffe6f7 100%);
        font-family: "Segoe UI", sans-serif;
    }
    .metric-card {
        background: #ffffff;
        padding: 16px 20px;
        border-radius: 18px;
        box-shadow: 0 10px 24px rgba(0,0,0,0.06);
        border: 1px solid rgba(255,255,255,0.8);
    }
    .section-title {
        font-size: 20px;
        font-weight: 600;
        margin-top: 12px;
        margin-bottom: 8px;
        color: #444;
    }
    .json-card {
        background: #ffffff;
        padding: 12px 16px;
        border-radius: 14px;
        box-shadow: 0 6px 18px rgba(0,0,0,0.05);
    }
    .status-pill {
        display: inline-flex;
        align-items: center;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 13px;
        font-weight: 500;
        background: #ffecec;
        color: #d64545;
    }
    .status-pill.ok {
        background: #e3ffe9;
        color: #118a38;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Copie locale des données pour l’UI
with lock:
    data = last_data.copy()
    hist = {k: list(v) for k, v in history.items()}

# --------- ENTÊTE ----------
st.markdown(
    """
    <h1 style='text-align: center; color: #4A4A4A; font-size: 40px;'>
        Gestion Intelligente Température & Sécurité – IoT
    </h1>
    """,
    unsafe_allow_html=True,
)

mqtt_status_html = (
    '<span class="status-pill ok">🟢 Connecté au broker MQTT</span>'
    if mqtt_connected
    else '<span class="status-pill">🔴 Déconnecté du broker MQTT</span>'
)
st.markdown(f"État MQTT : {mqtt_status_html}", unsafe_allow_html=True)

st.markdown("---")

# --------- CARTES PRINCIPALES ----------
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.subheader("🌡️ Température")
    st.metric("Température (°C)", data["temperature"])
    st.markdown("</div>", unsafe_allow_html=True)

with c2:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.subheader("💧 Humidité")
    st.metric("Humidité (%)", data["humidity"])
    st.markdown("</div>", unsafe_allow_html=True)

with c3:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.subheader("🧊 Température du seuil (ESP32)")
    st.write(f"Seuil T consigne : **{data['tempSeuil']} °C**")
    st.write(f"Seuil H consigne : **{data['humSeuil']} %**")
    st.markdown("</div>", unsafe_allow_html=True)

with c4:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.subheader("🎚️ Potentiomètre → Seuil")
    st.write(f"Valeur brute POT : **{data['pot']}**")
    st.markdown("</div>", unsafe_allow_html=True)

st.markdown("---")

# --------- IR & ALARME ----------
col_ir, col_alarm = st.columns(2)

with col_ir:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.subheader("🔥 IR / Flamme")
    if data["flame"] == 1:
        st.markdown("**🟥 Flamme détectée !**")
    else:
        st.markdown("**🟩 Aucun feu détecté (flame = 0)**")
    st.markdown("</div>", unsafe_allow_html=True)

with col_alarm:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.subheader("🚨 État de l'alarme")
    if data["alarm"]:
        st.markdown("**🚨 ALARME ACTIVE**")
    else:
        st.markdown("**🟢 Alarme inactive**")
    st.markdown("</div>", unsafe_allow_html=True)

# --------- GRAPHIQUES ----------
st.markdown("---")
st.markdown('<div class="section-title">📈 Graphiques en temps réel</div>', unsafe_allow_html=True)

# On construit un DataFrame même si on n'a qu'un point
df = pd.DataFrame({
    "time": hist["time"],
    "Température": hist["temperature"],
    "Seuil_T": hist["tempSeuil"],
    "Humidité": hist["humidity"],
    "Seuil_H": hist["humSeuil"],
    "Potentiomètre": hist["pot"],
}).dropna(how="all")

if df.empty:
    # Aucun message reçu → on affiche juste une info
    st.info("En attente de données temps réel du capteur…")
else:
    col_g1, col_g2 = st.columns(2)

    # ----- Température vs Seuil -----
    with col_g1:
        st.markdown("**🌡️ Température vs Seuil**")
        base_temp = alt.Chart(df).encode(x="time")

        ligne_temp = base_temp.mark_line().encode(
            y=alt.Y("Température", title="Température (°C)")
        )
        points_temp = base_temp.mark_circle(size=60).encode(
            y="Température"
        )

        ligne_seuil_t = base_temp.mark_line(color="red").encode(
            y=alt.Y("Seuil_T", title="Seuil T (°C)")
        )
        points_seuil_t = base_temp.mark_circle(size=60, color="red").encode(
            y="Seuil_T"
        )

        st.altair_chart(ligne_temp + points_temp + ligne_seuil_t + points_seuil_t,
                        use_container_width=True)

    # ----- Humidité vs Seuil -----
    with col_g2:
        st.markdown("**💧 Humidité vs Seuil**")
        base_hum = alt.Chart(df).encode(x="time")

        ligne_hum = base_hum.mark_line().encode(
            y=alt.Y("Humidité", title="Humidité (%)")
        )
        points_hum = base_hum.mark_circle(size=60).encode(
            y="Humidité"
        )

        ligne_seuil_h = base_hum.mark_line(color="red").encode(
            y=alt.Y("Seuil_H", title="Seuil H (%)")
        )
        points_seuil_h = base_hum.mark_circle(size=60, color="red").encode(
            y="Seuil_H"
        )

        st.altair_chart(ligne_hum + points_hum + ligne_seuil_h + points_seuil_h,
                        use_container_width=True)

# --------- JSON BRUT (avec clé 'potentiometre') ----------
st.markdown("---")
st.markdown('<div class="section-title">📝 Dernier message JSON reçu</div>', unsafe_allow_html=True)
st.markdown('<div class="json-card">', unsafe_allow_html=True)

# Préparation des données pour l'affichage
display_data = data.copy()

# On enlève éventuellement une ancienne clé
if "potentiometre" in display_data:
    display_data.pop("potentiometre")

# On ajoute une clé lisible "potentiometre"
display_data["potentiometre"] = display_data.get("pot")

st.json(display_data)
st.markdown("</div>", unsafe_allow_html=True)

if data["last_update"]:
    st.caption(f"Dernière mise à jour : {data['last_update']}")
else:
    st.caption("En attente de données…")
