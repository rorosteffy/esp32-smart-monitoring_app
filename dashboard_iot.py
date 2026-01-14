// ===============================
// ESP32 - NOEUD DETECTION (STEFFY)
// Publie JSON -> capteur/data (pour Streamlit)
// Reçoit flamme Hande -> noeud/operateur/flame
// Reçoit commandes moteur -> noeud/remote
// Broker MQTT : 51.103.239.173:1883
// ===============================

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "DHT.h"

// ---------- WIFI ----------
const char* ssid     = "TON_WIFI";
const char* password = "TON_MDP";

// ---------- MQTT ----------
const char* MQTT_BROKER = "51.103.239.173";
const uint16_t MQTT_PORT = 1883;

const char* TOPIC_PUB_DATA     = "capteur/data";           // ✅ Streamlit lit ça
const char* TOPIC_SUB_FLAME_H  = "noeud/operateur/flame";  // Hande -> "0/1"
const char* TOPIC_SUB_REMOTE   = "noeud/remote";           // commandes moteur

WiFiClient espClient;
PubSubClient mqtt(espClient);

// ---------- PINS (adapte si besoin) ----------
#define PIN_DHT       14
#define DHTTYPE       DHT11

#define PIN_FLAME_DO  35    // capteur flamme DO (0/1)
#define PIN_POT       32    // pot ADC (0..4095)

#define PIN_LED_RED   15
#define PIN_LED_GREEN 2
#define PIN_BUZZER    4

// L298N
#define PIN_IN1       16
#define PIN_IN2       17
#define PIN_ENA       18    // PWM

// ---------- PWM ESP32 ----------
const int PWM_CH = 0;
const int PWM_FREQ = 20000;
const int PWM_RES = 8; // 0..255

// ---------- DHT ----------
DHT dht(PIN_DHT, DHTTYPE);

// ---------- ETAT ----------
float temperature = NAN;
float humidity = NAN;

int flameLocal = -1;     // 0/1
int flameHande = -1;     // 0/1 reçu MQTT
int alarm = 0;           // 0/1
int seuilC = 30;         // seuil en °C (pot)
int potRaw = 0;

bool motorOn = false;
int motorSpeed = 0;      // 0..255

unsigned long tLastPub = 0;
const unsigned long PUB_MS = 1000;

// ---------- OUTILS ----------
int mapPotToSeuilC(int pot) {
  // Pot 0..4095 => seuil 20..40°C (tu peux changer)
  int s = map(pot, 0, 4095, 20, 40);
  if (s < 0) s = 0;
  if (s > 60) s = 60;
  return s;
}

void setMotor(bool on, int speed) {
  motorOn = on;
  motorSpeed = constrain(speed, 0, 255);

  if (!motorOn || motorSpeed == 0) {
    digitalWrite(PIN_IN1, LOW);
    digitalWrite(PIN_IN2, LOW);
    ledcWrite(PWM_CH, 0);
    motorOn = false;
    motorSpeed = 0;
    return;
  }

  // sens fixe (avant). Si tu veux inverser, swap IN1/IN2
  digitalWrite(PIN_IN1, HIGH);
  digitalWrite(PIN_IN2, LOW);
  ledcWrite(PWM_CH, motorSpeed);
}

void setAlarm(int state) {
  alarm = (state ? 1 : 0);

  if (alarm == 1) {
    digitalWrite(PIN_LED_RED, HIGH);
    digitalWrite(PIN_LED_GREEN, LOW);
    digitalWrite(PIN_BUZZER, HIGH);
  } else {
    digitalWrite(PIN_LED_RED, LOW);
    digitalWrite(PIN_LED_GREEN, HIGH);
    digitalWrite(PIN_BUZZER, LOW);
  }
}

// ---------- MQTT CALLBACK ----------
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String msg;
  msg.reserve(length + 1);
  for (unsigned int i = 0; i < length; i++) msg += (char)payload[i];
  msg.trim();

  String t = String(topic);

  // 1) Flamme Hande : "0" ou "1"
  if (t == TOPIC_SUB_FLAME_H) {
    if (msg == "0" || msg == "1") {
      flameHande = msg.toInt();
    }
    return;
  }

  // 2) Commandes moteur : "MOTOR_OFF" ou "MOTOR_ON 120"
  if (t == TOPIC_SUB_REMOTE) {
    msg.toUpperCase();

    if (msg.startsWith("MOTOR_OFF")) {
      setMotor(false, 0);
      return;
    }

    if (msg.startsWith("MOTOR_ON")) {
      int sp = 180; // par défaut
      int idx = msg.indexOf(' ');
      if (idx > 0) {
        sp = msg.substring(idx + 1).toInt();
      }
      setMotor(true, sp);
      return;
    }

    return;
  }
}

// ---------- MQTT CONNECT ----------
void mqttConnect() {
  while (!mqtt.connected()) {
    String cid = "ESP32_DETECTION_" + String((uint32_t)ESP.getEfuseMac(), HEX);
    if (mqtt.connect(cid.c_str())) {
      mqtt.subscribe(TOPIC_SUB_FLAME_H);
      mqtt.subscribe(TOPIC_SUB_REMOTE);
    } else {
      delay(1500);
    }
  }
}

// ---------- PUBLISH JSON ----------
void publishData() {
  StaticJsonDocument<256> doc;

  // ✅ clés EXACTES attendues par ton Streamlit
  // temperature, humidity, seuil, flame, flameHande, alarm, motorSpeed, ...
  doc["temperature"] = isnan(temperature) ? nullptr : temperature;
  doc["humidity"]    = isnan(humidity) ? nullptr : humidity;

  doc["seuil"]       = seuilC;
  doc["pot"]         = potRaw;

  doc["flame"]       = flameLocal;     // 0/1
  doc["flameHande"]  = flameHande;     // 0/1 (ou -1 si pas reçu)

  doc["alarm"]       = alarm;          // 0/1
  doc["motorSpeed"]  = motorSpeed;     // 0..255
  doc["motorOn"]     = motorOn ? 1 : 0;

  doc["timestamp"]   = (long) (millis() / 1000);

  char buffer[256];
  size_t n = serializeJson(doc, buffer, sizeof(buffer));
  mqtt.publish(TOPIC_PUB_DATA, buffer, n);
}

// ---------- SETUP ----------
void setup() {
  Serial.begin(115200);

  pinMode(PIN_LED_RED, OUTPUT);
  pinMode(PIN_LED_GREEN, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);

  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);

  pinMode(PIN_FLAME_DO, INPUT); // GPIO35 = input only (ok)

  // PWM motor
  ledcSetup(PWM_CH, PWM_FREQ, PWM_RES);
  ledcAttachPin(PIN_ENA, PWM_CH);
  ledcWrite(PWM_CH, 0);

  setAlarm(0);
  setMotor(false, 0);

  dht.begin();

  // WiFi
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.println("\n✅ WiFi connecté");

  // MQTT
  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqtt.setCallback(mqttCallback);
  mqttConnect();
  Serial.println("✅ MQTT connecté");
}

// ---------- LOOP ----------
void loop() {
  if (!mqtt.connected()) mqttConnect();
  mqtt.loop();

  // lecture capteurs
  potRaw = analogRead(PIN_POT);
  seuilC = mapPotToSeuilC(potRaw);

  flameLocal = digitalRead(PIN_FLAME_DO); // 0/1

  // DHT (pas trop souvent)
  static unsigned long tDht = 0;
  if (millis() - tDht >= 2000) {
    tDht = millis();
    float h = dht.readHumidity();
    float t = dht.readTemperature();
    if (!isnan(h)) humidity = h;
    if (!isnan(t)) temperature = t;
  }

  // logique alarme (tu peux changer)
  // alarme si flamme locale OU température > seuil
  bool alarmCond = false;
  if (flameLocal == 1) alarmCond = true;
  if (!isnan(temperature) && temperature > seuilC) alarmCond = true;

  setAlarm(alarmCond ? 1 : 0);

  // publish régulier
  if (millis() - tLastPub >= PUB_MS) {
    tLastPub = millis();
    publishData();
  }
}
