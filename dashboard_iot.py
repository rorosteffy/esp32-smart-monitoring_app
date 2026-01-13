import os, time, json, socket, threading
from datetime import datetime
from collections import deque

import streamlit as st
import pandas as pd
import altair as alt
import paho.mqtt.client as mqtt

# ==========================
# MQTT CONFIG (AUTO)
# ==========================
MQTT_BROKER = os.getenv("MQTT_BROKER", "51.103.239.173")
RUNNING_ON_CLOUD = bool(os.getenv("STREAMLIT_SERVER_HEADLESS", ""))  # True sur Streamlit Cloud

# Cloud => websockets 9001 / Local => tcp 1883
MQTT_PORT = int(os.getenv("MQTT_PORT", "9001" if RUNNING_ON_CLOUD else "1883"))
MQTT_TRANSPORT = os.getenv("MQTT_TRANSPORT", "websockets" if RUNNING_ON_CLOUD else "tcp")
MQTT_WS_PATH = os.getenv("MQTT_WS_PATH", "/")

TOPIC_DATA = os.getenv("TOPIC_DATA", "capteur/data")
TOPIC_CMD  = os.getenv("TOPIC_CMD",  "noeud/operateur/cmd")

CMD_LED_ON  = "LED_RED_ON"
CMD_LED_OFF = "LED_RED_OFF"

# ==========================
# SHARED STATE
# ==========================
LOCK = threading.Lock()
MQTT_CONNECTED = False
MQTT_RC = None
MQTT_LAST_MSG_AT = None

LAST = {
    "temperature": None,
    "humidity": None,
    "seuil": None,
    "flame": None,
    "flameHande": None,
    "alarm": None,
    "last_update": None,
}
HISTORY = deque(maxlen=400)

# ==========================
# MQTT CALLBACKS
# ==========================
def on_connect(client, userdata, flags, rc):
    global MQTT_CONNECTED, MQTT_RC
    with LOCK:
        MQTT_CONNECTED = (rc == 0)
        MQTT_RC = rc

    if rc == 0:
        client.subscribe(TOPIC_DATA, qos=0)
        print("✅ MQTT connecté, subscribe", TOPIC_DATA, "| transport:", MQTT_TRANSPORT, "port:", MQTT_PORT)
    else:
        print("❌ MQTT connect rc =", rc)

def on_disconnect(client, userdata, rc):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = False
    print("🔌 MQTT déconnecté rc =", rc)

def on_message(client, userdata, msg):
    global MQTT_LAST_MSG_AT
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print("JSON invalide:", e)
        return

    now = datetime.now()
    with LOCK:
        MQTT_LAST_MSG_AT = now
        LAST["temperature"] = payload.get("temperature")
        LAST["humidity"]    = payload.get("humidity")
        LAST["seuil"]       = payload.get("seuil")
        LAST["flame"]       = payload.get("flame")
        LAST["flameHande"]  = payload.get("flameHande")
        LAST["alarm"]       = payload.get("alarm")
        LAST["last_update"] = now

        HISTORY.append({
            "time": now,
            "temperature": LAST["temperature"],
            "humidity": LAST["humidity"],
            "seuil": LAST["seuil"],
            "flame": LAST["flame"],
        })

# ==========================
# MQTT SINGLE CLIENT
# ==========================
@st.cache_resource
def init_mqtt():
    cid = f"st_{socket.gethostname()}_{os.getpid()}"

    if MQTT_TRANSPORT == "websockets":
        client = mqtt.Client(client_id=cid, protocol=mqtt.MQTTv311, transport="websockets")
        client.ws_set_options(path=MQTT_WS_PATH)
    else:
        client = mqtt.Client(client_id=cid, protocol=mqtt.MQTTv311)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    client.reconnect_delay_set(min_delay=1, max_delay=10)
    client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client

def mqtt_publish(cmd: str):
    c = init_mqtt()
    c.publish(TOPIC_CMD, cmd, qos=0, retain=False)

# ==========================
# UI HELPERS
# ==========================
def mv(v, fmt="{:.1f}"):
    if v is None:
        return "—"
    try:
        return fmt.format(float(v))
    except Exception:
        return str(v)

def chart(df, col, title, ytitle):
    return (
        alt.Chart(df)
        .mark_line(point=True)
        .encode(
            x=alt.X("time:T", title="Temps"),
            y=alt.Y(f"{col}:Q", title=ytitle),
            tooltip=["time:T", alt.Tooltip(f"{col}:Q")]
        )
        .properties(height=260, title=title)
    )

def safe_rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# ==========================
# APP
# ==========================
def main():
    st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")
    init_mqtt()

    st.title("Gestion Intelligente Température & Sécurité – IoT")

    with LOCK:
        last = dict(LAST)
        hist = list(HISTORY)
        connected = MQTT_CONNECTED
        rc = MQTT_RC
        last_msg_at = MQTT_LAST_MSG_AT

    # Freshness = data reçue dans les 10s
    fresh = False
    age_s = None
    if last_msg_at is not None:
        age_s = (datetime.now() - last_msg_at).total_seconds()
        fresh = age_s <= 10

    if connected or fresh:
        st.success(f"MQTT ✅ (transport={MQTT_TRANSPORT}, port={MQTT_PORT}) | rc={rc}")
    else:
        st.error(f"MQTT 🔴 (transport={MQTT_TRANSPORT}, port={MQTT_PORT}) | rc={rc}")

    if age_s is not None:
        st.caption(f"Dernier message MQTT: ~{age_s:.1f}s")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Temp (°C)", mv(last["temperature"]))
    c2.metric("Hum (%)", mv(last["humidity"], "{:.0f}"))
    c3.metric("Seuil (°C)", "—" if last["seuil"] is None else mv(last["seuil"]))
    c4.metric("Alarme", "ACTIVE" if last["alarm"] else "inactive")

    st.markdown("---")

    st.subheader("🔥 Flamme")
    f1, f2 = st.columns(2)
    f1.write(f"Steffy: {last['flame']}")
    f2.write(f"Hande : {last['flameHande']}")

    st.markdown("---")

    st.subheader("🎛️ Commandes binôme")
    b1, b2 = st.columns(2)
    if b1.button("🔴 LED ROUGE ON", use_container_width=True):
        mqtt_publish(CMD_LED_ON)
    if b2.button("⚫ LED ROUGE OFF", use_container_width=True):
        mqtt_publish(CMD_LED_OFF)

    st.markdown("---")

    st.subheader("📈 Courbes (temps réel)")
    if len(hist) == 0:
        st.info("En attente de données sur capteur/data…")
    else:
        df = pd.DataFrame(hist).tail(250)

        g1, g2 = st.columns(2)
        g1.altair_chart(chart(df, "temperature", "Température", "°C"), use_container_width=True)
        g2.altair_chart(chart(df, "humidity", "Humidité", "%"), use_container_width=True)

        g3, g4 = st.columns(2)
        g3.altair_chart(chart(df, "seuil", "Seuil", "°C"), use_container_width=True)
        g4.altair_chart(chart(df, "flame", "Flamme", "0/1"), use_container_width=True)

    st.sidebar.markdown("### Refresh UI")
    refresh_s = st.sidebar.slider("secondes", 1, 10, 2)
    time.sleep(refresh_s)
    safe_rerun()

if __name__ == "__main__":
    main()
