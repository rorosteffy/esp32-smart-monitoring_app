import os, time, json, socket, threading
from datetime import datetime
from collections import deque

import streamlit as st
import pandas as pd
import altair as alt
import paho.mqtt.client as mqtt

# ---------- MQTT (WS obligatoire pour Streamlit Cloud) ----------
MQTT_BROKER  = os.getenv("MQTT_BROKER", "51.103.239.173")
MQTT_PORT    = int(os.getenv("MQTT_PORT", "9001"))
MQTT_WS_PATH = os.getenv("MQTT_WS_PATH", "/")

TOPIC_DATA = os.getenv("TOPIC_DATA", "capteur/data")
TOPIC_CMD  = os.getenv("TOPIC_CMD",  "noeud/operateur/cmd")

CMD_LED_ON  = "LED_RED_ON"
CMD_LED_OFF = "LED_RED_OFF"

# ---------- State ----------
LOCK = threading.Lock()
STATE = {
    "connected": False,
    "rc": None,
    "last_msg_at": None,
    "last_error": None,
    "last_raw": None,
    "last": {
        "temperature": None,
        "humidity": None,
        "seuil": None,
        "flame": None,
        "flameHande": None,
        "alarm": None,
    }
}
HISTORY = deque(maxlen=300)

# ---------- MQTT callbacks ----------
def on_connect(client, userdata, flags, rc):
    with LOCK:
        STATE["rc"] = rc
        STATE["connected"] = (rc == 0)
        STATE["last_error"] = None
    if rc == 0:
        client.subscribe(TOPIC_DATA, qos=0)
        print("✅ CONNECT OK subscribe", TOPIC_DATA)
    else:
        print("❌ CONNECT rc=", rc)

def on_disconnect(client, userdata, rc):
    with LOCK:
        STATE["connected"] = False
        STATE["rc"] = rc
    print("🔌 DISCONNECT rc=", rc)

def on_message(client, userdata, msg):
    raw = msg.payload.decode("utf-8", errors="ignore")
    now = datetime.now()

    with LOCK:
        STATE["last_msg_at"] = now
        STATE["last_raw"] = raw[:800]

    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return
    except Exception:
        return

    with LOCK:
        last = STATE["last"]
        last["temperature"] = payload.get("temperature")
        last["humidity"]    = payload.get("humidity")
        last["seuil"]       = payload.get("seuil")
        last["flame"]       = payload.get("flame")
        last["flameHande"]  = payload.get("flameHande")
        last["alarm"]       = payload.get("alarm")

        HISTORY.append({
            "time": now,
            "temperature": last["temperature"],
            "humidity": last["humidity"],
            "seuil": last["seuil"],
            "flame": last["flame"],
        })

# ---------- Single MQTT client ----------
@st.cache_resource
def get_mqtt():
    cid = f"st_{socket.gethostname()}_{os.getpid()}"
    c = mqtt.Client(client_id=cid, protocol=mqtt.MQTTv311, transport="websockets")
    c.ws_set_options(path=MQTT_WS_PATH)

    c.on_connect = on_connect
    c.on_disconnect = on_disconnect
    c.on_message = on_message

    c.reconnect_delay_set(1, 10)
    try:
        c.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
        c.loop_start()
    except Exception as e:
        with LOCK:
            STATE["last_error"] = str(e)
    return c

def publish(cmd: str):
    c = get_mqtt()
    try:
        c.publish(TOPIC_CMD, cmd, qos=0, retain=False)
    except Exception as e:
        with LOCK:
            STATE["last_error"] = f"publish: {e}"

# ---------- UI helpers ----------
def mv(v, fmt="{:.1f}"):
    if v is None:
        return "—"
    try:
        return fmt.format(float(v))
    except Exception:
        return str(v)

def chart(df, y, title, ytitle):
    return (
        alt.Chart(df).mark_line(point=True).encode(
            x=alt.X("time:T", title="Temps"),
            y=alt.Y(f"{y}:Q", title=ytitle),
            tooltip=["time:T", alt.Tooltip(f"{y}:Q")]
        ).properties(height=250, title=title)
    )

def rerun():
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

# ---------- App ----------
def main():
    st.set_page_config(page_title="Dashboard IoT EPHEC", layout="wide")
    get_mqtt()

    st.title("Gestion Intelligente Température & Sécurité – IoT")
    st.caption(f"Broker: {MQTT_BROKER} | transport=websockets | port={MQTT_PORT} | path={MQTT_WS_PATH}")

    with LOCK:
        s = dict(STATE)
        last = dict(STATE["last"])
        hist = list(HISTORY)

    # status
    age = None
    fresh = False
    if s["last_msg_at"] is not None:
        age = (datetime.now() - s["last_msg_at"]).total_seconds()
        fresh = age <= 10

    if s["connected"] or fresh:
        st.success(f"MQTT ✅ connecté (rc={s['rc']})")
    else:
        st.error(f"MQTT 🔴 déconnecté / pas de data (rc={s['rc']})")

    if age is not None:
        st.caption(f"Dernier message: ~{age:.1f}s")
    if s["last_error"]:
        st.warning(f"Erreur: {s['last_error']}")

    st.markdown("---")

    # metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Temp (°C)", mv(last["temperature"]))
    c2.metric("Hum (%)", mv(last["humidity"], "{:.0f}"))
    c3.metric("Seuil (°C)", mv(last["seuil"]))
    c4.metric("Alarme", "ACTIVE" if last["alarm"] else "inactive")

    st.markdown("---")

    f1, f2 = st.columns(2)
    f1.write(f"🔥 Flamme Steffy: {last['flame']}")
    f2.write(f"🔥 Flamme Hande: {last['flameHande']}")

    st.markdown("---")

    # commands
    st.subheader("🎛️ Commandes binôme")
    b1, b2, b3 = st.columns([1,1,2])
    if b1.button("🔴 LED ROUGE ON", use_container_width=True):
        publish(CMD_LED_ON)
        st.toast("Envoyé", icon="📡")
    if b2.button("⚫ LED ROUGE OFF", use_container_width=True):
        publish(CMD_LED_OFF)
        st.toast("Envoyé", icon="📡")
    if b3.button("🧪 Test MQTT (publish PING)", use_container_width=True):
        publish("PING")
        st.toast("PING envoyé", icon="🧪")

    st.markdown("---")

    # charts
    st.subheader("📈 Courbes")
    if len(hist) == 0:
        st.info("En attente de données sur capteur/data…")
    else:
        df = pd.DataFrame(hist).tail(200)
        g1, g2 = st.columns(2)
        g1.altair_chart(chart(df, "temperature", "Température", "°C"), use_container_width=True)
        g2.altair_chart(chart(df, "humidity", "Humidité", "%"), use_container_width=True)
        g3, g4 = st.columns(2)
        g3.altair_chart(chart(df, "seuil", "Seuil", "°C"), use_container_width=True)
        g4.altair_chart(chart(df, "flame", "Flamme", "0/1"), use_container_width=True)

    with st.expander("DEBUG", expanded=True):
        st.write("Dernier payload brut:")
        st.code(s["last_raw"] or "—")
        st.write("Dernier JSON interprété:")
        st.json(last)

    # refresh UI
    refresh_s = st.sidebar.slider("Refresh UI (s)", 1, 10, 2)
    time.sleep(refresh_s)
    rerun()

if __name__ == "__main__":
    main()
