import json
import time
import socket
import threading
from datetime import datetime

import streamlit as st
import paho.mqtt.client as mqtt

# =========================
# CONFIG MQTT
# =========================
MQTT_BROKER = "51.103.239.173"
MQTT_WS_PORT = 9001
MQTT_WS_PATH = "/"
TOPIC_DATA = "ims/dashboard"

TOPIC_CMD_START = "ims/cmd/start"
TOPIC_CMD_STOP = "ims/cmd/stop"
TOPIC_CMD_RESET = "ims/cmd/reset"

# =========================
# ETAT GLOBAL
# =========================
LOCK = threading.Lock()
MQTT_CONNECTED = False
LAST_UPDATE = None
MQTT_CLIENT = None

DATA = {
    "ims10_ready": 1,
    "ims6_control_ok": 1,
    "ims6_control_nok": 0,
    "ims7_run": 1,
    "pieces_produites": 1285,
    "pieces_rejetees": 47,
    "piece_prete": 1,
    "controle_ok": 1,
    "etat_robot": "En Attente",
    "defaut_capteur": 0,
    "station_bloquee": 0,
    "erreur_communication": 0
}

# =========================
# MQTT CALLBACKS
# =========================
def on_connect(client, userdata, flags, reason_code, properties=None):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = (reason_code == 0)

    if reason_code == 0:
        client.subscribe(TOPIC_DATA)
        print("MQTT CONNECTED")
    else:
        print("MQTT CONNECT ERROR:", reason_code)


def on_disconnect(client, userdata, reason_code, properties=None):
    global MQTT_CONNECTED
    with LOCK:
        MQTT_CONNECTED = False
    print("MQTT DISCONNECTED")


def on_message(client, userdata, msg):
    global LAST_UPDATE
    try:
        payload = json.loads(msg.payload.decode("utf-8", errors="ignore"))
        with LOCK:
            for k in DATA.keys():
                if k in payload:
                    DATA[k] = payload[k]
            LAST_UPDATE = datetime.now()
    except Exception as e:
        print("JSON invalide:", e)


@st.cache_resource
def init_mqtt():
    global MQTT_CLIENT

    cid = f"streamlit_{socket.gethostname()}"
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=cid,
        protocol=mqtt.MQTTv311,
        transport="websockets",
    )

    client.ws_set_options(path=MQTT_WS_PATH)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    client.connect_async(MQTT_BROKER, MQTT_WS_PORT, keepalive=60)
    client.loop_start()

    MQTT_CLIENT = client
    return client


# =========================
# MQTT HELPERS
# =========================
def publish_command(topic, payload):
    global MQTT_CLIENT
    try:
        if MQTT_CLIENT is None:
            return False

        result = MQTT_CLIENT.publish(topic, payload)
        return result.rc == mqtt.MQTT_ERR_SUCCESS
    except Exception as e:
        print("Erreur publish:", e)
        return False


# =========================
# UI HELPERS
# =========================
def big_status(text, bg="#16a34a"):
    return f"""
    <div style="
        background:{bg};
        border-radius:18px;
        padding:24px 18px;
        text-align:center;
        color:white;
        font-size:24px;
        font-weight:800;
        box-shadow:0 8px 18px rgba(0,0,0,0.16);
        border:1px solid rgba(255,255,255,0.12);
        min-height:84px;
        display:flex;
        align-items:center;
        justify-content:center;
    ">
        {text}
    </div>
    """


def dual_status(left_text, ok_active=True):
    ok_color = "#22c55e" if ok_active else "#7890a8"
    nok_color = "#dc2626" if not ok_active else "#8b1e1e"

    return f"""
    <div style="
        background:#18a84b;
        border-radius:34px;
        padding:15px 18px;
        display:flex;
        align-items:center;
        justify-content:space-between;
        color:white;
        font-weight:800;
        font-size:20px;
        box-shadow:0 8px 18px rgba(0,0,0,0.16);
        border:1px solid rgba(255,255,255,0.12);
    ">
        <span>{left_text}</span>
        <div style="display:flex; gap:10px;">
            <span style="
                background:{ok_color};
                padding:8px 18px;
                border-radius:11px;
                font-size:18px;
            ">OK</span>
            <span style="
                background:{nok_color};
                padding:8px 18px;
                border-radius:11px;
                font-size:18px;
            ">NOK</span>
        </div>
    </div>
    """


def value_card(title, value, header_color, body_color):
    st.markdown(
        f"""
        <div style="
            border-radius:18px;
            overflow:hidden;
            box-shadow:0 8px 18px rgba(0,0,0,0.16);
            border:1px solid rgba(255,255,255,0.12);
        ">
            <div style="
                background:{header_color};
                color:white;
                padding:18px 20px;
                font-size:20px;
                font-weight:700;
            ">
                {title}
            </div>
            <div style="
                background:{body_color};
                color:white;
                padding:38px 24px;
                text-align:center;
                font-size:60px;
                font-weight:800;
            ">
                {value}
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def small_indicator(text, active=True, color_active="#16a34a", color_inactive="#97a9bc"):
    bg = color_active if active else color_inactive
    txt = "white" if active else "#102030"

    st.markdown(
        f"""
        <div style="
            background:{bg};
            color:{txt};
            border-radius:14px;
            padding:18px;
            font-size:18px;
            font-weight:700;
            text-align:center;
            min-height:74px;
            display:flex;
            align-items:center;
            justify-content:center;
            border:1px solid rgba(255,255,255,0.12);
            box-shadow:0 5px 12px rgba(0,0,0,0.10);
        ">
            {text}
        </div>
        """,
        unsafe_allow_html=True
    )


def alarm_row(icon, text, active=False):
    if active:
        bg = "#fff1d6"
        border = "#f59e0b"
        txt = "#7c2d12"
    else:
        bg = "#eef3f8"
        border = "#cbd5e1"
        txt = "#1f2937"

    st.markdown(
        f"""
        <div style="
            background:{bg};
            border:1px solid {border};
            border-radius:14px;
            padding:16px 18px;
            color:{txt};
            font-size:18px;
            font-weight:700;
            margin-bottom:12px;
            box-shadow:0 3px 8px rgba(0,0,0,0.07);
        ">
            {icon} &nbsp; {text}
        </div>
        """,
        unsafe_allow_html=True
    )


# =========================
# APP
# =========================
def main():
    st.set_page_config(page_title="Dashboard IMS", layout="wide")
    init_mqtt()

    st.markdown("""
    <style>
    .stApp {
        background: linear-gradient(180deg, #b4c0ce 0%, #a1b0c0 100%);
        color: #102030;
    }

    .block-container {
        max-width: 1420px;
        padding-top: 0.45rem;
        padding-bottom: 1rem;
    }

    h1, h2, h3 {
        color: #0f223a !important;
        font-weight: 800 !important;
        margin-bottom: 0.45rem !important;
    }

    .main-title {
        width: 100%;
        text-align: center;
        font-size: 2.75rem;
        font-weight: 900;
        color: #0b1f38;
        margin-top: 0.15rem;
        margin-bottom: 1rem;
        line-height: 1.15;
    }

    div[data-testid="stButton"] button {
        width: 100%;
        height: 102px;
        border-radius: 22px;
        font-size: 28px;
        font-weight: 900;
        border: none;
        color: white !important;
        box-shadow: 0 12px 22px rgba(0,0,0,0.20);
        transition: 0.2s ease;
        margin-top: 0;
    }

    div[data-testid="stButton"] button:hover {
        transform: scale(1.02);
        opacity: 0.97;
    }

    div[data-testid="stButton"] button:focus {
        outline: none !important;
        box-shadow: 0 0 0 3px rgba(59,130,246,0.30);
    }

    div[data-testid="stAlert"] {
        border-radius: 14px;
    }

    /* Couleurs boutons de commande */
    .start-btn button {
        background: linear-gradient(180deg, #22c55e 0%, #16a34a 100%) !important;
    }

    .stop-btn button {
        background: linear-gradient(180deg, #ef4444 0%, #dc2626 100%) !important;
    }

    .reset-btn button {
        background: linear-gradient(180deg, #94a3b8 0%, #64748b 100%) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    with LOCK:
        d = dict(DATA)
        connected = MQTT_CONNECTED
        last_update = LAST_UPDATE

    st.markdown(
        '<div class="main-title">🏭 Dashboard IMS - Supervision Production</div>',
        unsafe_allow_html=True
    )

    if connected:
        st.success("🟢 Système connecté en temps réel")
    else:
        st.error("🔴 Perte de communication MQTT")

    if last_update:
        age_s = (datetime.now() - last_update).total_seconds()
        st.caption(f"🕒 Dernière mise à jour : {last_update.strftime('%H:%M:%S')} | ⏱️ Âge donnée : {age_s:.1f} s")
    else:
        st.caption("📭 Aucune donnée reçue pour le moment")

    left, right = st.columns([1.03, 1.67], gap="large")

    with left:
        st.markdown("<h2 style='text-align:center;'>📡 Statut des Stations</h2>", unsafe_allow_html=True)

        st.markdown(
            big_status(
                "✅ IMS10 READY" if d["ims10_ready"] else "⏳ IMS10 BUSY",
                "#16a34a" if d["ims10_ready"] else "#dc2626"
            ),
            unsafe_allow_html=True
        )

        st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

        st.markdown(
            dual_status("🧪 IMS6 CONTROL", ok_active=bool(d["ims6_control_ok"])),
            unsafe_allow_html=True
        )

        st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

        ims7_text = "▶️ IMS7 RUN" if d["ims7_run"] else "⏹️ IMS7 STOP"
        ims7_color = "#16a34a" if d["ims7_run"] else "#dc2626"
        st.markdown(big_status(ims7_text, ims7_color), unsafe_allow_html=True)

        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        st.markdown("<h2 style='text-align:center;'>🚨 Alarmes</h2>", unsafe_allow_html=True)

        alarm_row("⚠️", "Défaut Capteur", active=bool(d["defaut_capteur"]))
        alarm_row("⛔", "Station Bloquée", active=bool(d["station_bloquee"]))
        alarm_row("📶", "Erreur Communication", active=bool(d["erreur_communication"]))

    with right:
        st.markdown("<h2 style='text-align:center;'>📦 Flux de Production</h2>", unsafe_allow_html=True)

        p1, p2 = st.columns(2, gap="medium")
        with p1:
            value_card("⚙️ Pièces Produites", d["pieces_produites"], "#16a34a", "#166534")
        with p2:
            value_card("⚠️ Pièces Rejetées", d["pieces_rejetees"], "#ef4444", "#b91c1c")

        st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)
        st.markdown("<h2 style='text-align:center;'>🧩 Variables Clés</h2>", unsafe_allow_html=True)

        v1, v2, v3 = st.columns(3, gap="medium")
        with v1:
            small_indicator(
                "✅ Signal: Pièce Prête" if d["piece_prete"] else "⬜ Signal: Pas prête",
                active=bool(d["piece_prete"]),
                color_active="#16a34a",
                color_inactive="#cbd5e1"
            )
        with v2:
            small_indicator(
                "✅ Contrôle: OK" if d["controle_ok"] else "❌ Contrôle: NOK",
                active=bool(d["controle_ok"]),
                color_active="#16a34a",
                color_inactive="#cbd5e1"
            )
        with v3:
            small_indicator(
                f"🤖 État Robot: {d['etat_robot']}",
                active=True,
                color_active="#2563eb"
            )

    st.markdown("<div style='height:42px;'></div>", unsafe_allow_html=True)

    # UNE SEULE LIGNE DE COMMANDES
    pad_left, b1, b2, b3, pad_right = st.columns([0.45, 1, 1, 1, 0.45], gap="large")

    with b1:
        st.markdown('<div class="start-btn">', unsafe_allow_html=True)
        if st.button("🟢 START", key="start_btn"):
            ok = publish_command(TOPIC_CMD_START, "1")
            if ok:
                st.success("✅ START envoyé")
            else:
                st.error("❌ Erreur START")
        st.markdown('</div>', unsafe_allow_html=True)

    with b2:
        st.markdown('<div class="stop-btn">', unsafe_allow_html=True)
        if st.button("🔴 STOP", key="stop_btn"):
            ok = publish_command(TOPIC_CMD_STOP, "1")
            if ok:
                st.warning("🛑 STOP envoyé")
            else:
                st.error("❌ Erreur STOP")
        st.markdown('</div>', unsafe_allow_html=True)

    with b3:
        st.markdown('<div class="reset-btn">', unsafe_allow_html=True)
        if st.button("♻️ RESET", key="reset_btn"):
            ok = publish_command(TOPIC_CMD_RESET, "1")
            if ok:
                st.info("🔄 RESET envoyé")
            else:
                st.error("❌ Erreur RESET")
        st.markdown('</div>', unsafe_allow_html=True)

    time.sleep(2)
    st.rerun()


if __name__ == "__main__":
    main()final corrige ca stp code complet գործ
