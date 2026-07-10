/*
 * ResQHub — вузол «розумна розетка» (ESP32 + ACS712 + реле).
 * Демо «висмикни вилку»: датчик струму бачить наявність живлення на об'єкті,
 * вузол шле реальну телеметрію на той самий /api/telemetry, що й симулятор.
 *
 * ──────────────── ПІДКЛЮЧЕННЯ ────────────────
 *  ACS712  VCC → 5V (VIN)!!    GND → GND      OUT → GPIO33   ← ADC1 (працює з WiFi)
 *     ⚠ VCC саме 5V, НЕ 3V3: на 3.3V сенсор поза спеком і «мовчить»
 *       (виглядає як мертвий пін). GPIO33 — це ADC1, тому WiFi йому не заважає.
 *  Реле    VCC → 5V           GND → GND      IN  → GPIO26   (керує лампою)
 *  ESP32 живиться від USB або павербанка.
 *
 *  ⚠ ESP32: ADC2-піни (0/2/4/12-15/25/26/27) НЕ читаються, коли увімкнено
 *    Wi-Fi. ACS712 має бути на ADC1: GPIO 32/33/34/35/36/39. GPIO34 = only-input.
 *  ⚠ Реле НЕ можна вішати на 34-39 (вони input-only). Бери 25/26/27/32/33.
 *  ⚠ Для малої лампи вихід ACS712 коливається біля 2.5В (< 3.3В) — безпечно.
 *    Для потужнішого навантаження додай дільник 2:1 на OUT → ADC.
 *
 * Бібліотеки: стандартні для ESP32 core (WiFi, HTTPClient, WiFiClientSecure).
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>

// ─────────────── КОНФІГ (заповни своє) ───────────────
const char* WIFI_SSID = "ТВІЙ_WIFI";       // напр. хотспот телефона
const char* WIFI_PASS = "ПАРОЛЬ";

// Для живого демо НАДІЙНІШЕ слати на локальний ноут (http, без інтернету):
//   const char* BACKEND = "http://192.168.1.50:8000";   // IP ноута зі стеком
// Або на прод (https):
const char* BACKEND   = "https://resqhub.systems";

// Об'єкт, який «оживляє» цей вузол. За замовч. — ЗОШ №3 (без генератора).
const char* OBJECT_ID = "a7014620-8a24-4883-8706-95656bcbe62e";

// ─────────────── ПІНИ ───────────────
const int PIN_ACS712 = 33;   // ADC1 — сигнал ACS712 OUT (працює з увімкненим WiFi)
const int PIN_RELAY  = 26;   // керування лампою (HIGH = увімкнено)
const bool RELAY_ACTIVE_HIGH = true;  // деякі модулі інвертовані — переключи, якщо навпаки

// ─────────────── ACS712 ───────────────
// Чутливість (В на Ампер): 5A=0.185, 20A=0.100, 30A=0.066. У тебе 5A.
const float ACS712_V_PER_A = 0.185f;
// Поріг струму (А), вище якого вважаємо «живлення є». Для малої лампи ~0.03.
const float CURRENT_THRESHOLD_A = 0.05f;

// ─────────────── Демо-фізика батареї ───────────────
// Локально імітуємо запас батареї, щоб об'єкт ВИДИМО деградував при блекауті,
// як і симульовані об'єкти. Темп підібраний під живе демо (~60с до нуля).
const float DRAIN_PER_CYCLE  = 4.0f;   // %/цикл коли живлення нема
const float CHARGE_PER_CYCLE = 8.0f;   // %/цикл коли живлення є
const int   OCCUPANCY        = 120;    // людей в укритті (для реалістичності)

const unsigned long CYCLE_MS = 3000;   // період телеметрії

// ─────────────── Стан ───────────────
float batteryPct = 100.0f;

// Читає AC-RMS струм з ACS712 за ~200мс (авто-центрування біля середнього).
float readCurrentA() {
  const int   N = 400;
  double sum = 0, sumsq = 0;
  for (int i = 0; i < N; i++) {
    int raw = analogRead(PIN_ACS712);   // 0..4095 ≈ 0..3.3В
    sum   += raw;
    sumsq += (double)raw * raw;
    delayMicroseconds(400);             // ~ покриває кілька періодів 50Гц
  }
  double mean = sum / N;
  double var  = sumsq / N - mean * mean;
  double rmsCounts = var > 0 ? sqrt(var) : 0;
  double rmsVolts  = rmsCounts * (3.3 / 4095.0);
  return (float)(rmsVolts / ACS712_V_PER_A);
}

void setRelay(bool on) {
  digitalWrite(PIN_RELAY, (on == RELAY_ACTIVE_HIGH) ? HIGH : LOW);
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi");
  int tries = 0;
  while (WiFi.status() != WL_CONNECTED && tries++ < 40) {
    delay(500);
    Serial.print(".");
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? " OK" : " FAIL");
  if (WiFi.status() == WL_CONNECTED) Serial.println(WiFi.localIP());
}

void postTelemetry(bool powerOn, float battery) {
  if (WiFi.status() != WL_CONNECTED) { connectWiFi(); return; }

  String url = String(BACKEND) + "/api/telemetry";
  float estHours = battery / 100.0f * 2.0f;   // маленький запас → швидко критично

  String body = String("{") +
    "\"object_id\":\"" + OBJECT_ID + "\"," +
    "\"power_on\":" + (powerOn ? "true" : "false") + "," +
    "\"battery_pct\":" + String(battery, 1) + "," +
    "\"battery_est_hours\":" + String(estHours, 2) + "," +
    "\"occupancy\":" + String(OCCUPANCY) + "," +
    "\"co2_ppm\":650,\"temp_c\":21.0,\"internet_on\":true,\"generator_on\":false" +
    "}";

  HTTPClient http;
  int code;
  if (url.startsWith("https")) {
    WiFiClientSecure client;
    client.setInsecure();               // демо: не перевіряємо cert
    http.begin(client, url);
    http.addHeader("Content-Type", "application/json");
    code = http.POST(body);
  } else {
    WiFiClient client;
    http.begin(client, url);
    http.addHeader("Content-Type", "application/json");
    code = http.POST(body);
  }
  Serial.printf("POST %d  power_on=%d  bat=%.0f%%\n", code, powerOn, battery);
  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(PIN_RELAY, OUTPUT);
  setRelay(true);                        // лампа увімкнена (живлення «є»)
  analogReadResolution(12);              // 0..4095
  analogSetPinAttenuation(PIN_ACS712, ADC_11db);  // діапазон ~0..3.3В
  connectWiFi();
}

void loop() {
  unsigned long t0 = millis();

  float amps = readCurrentA();
  bool powerOn = amps > CURRENT_THRESHOLD_A;

  // Демо-батарея: нема струму → розряд, є струм → заряд.
  if (powerOn) batteryPct = min(100.0f, batteryPct + CHARGE_PER_CYCLE);
  else         batteryPct = max(0.0f,   batteryPct - DRAIN_PER_CYCLE);

  Serial.printf("I=%.3fA  ", amps);
  postTelemetry(powerOn, batteryPct);

  unsigned long dt = millis() - t0;
  if (dt < CYCLE_MS) delay(CYCLE_MS - dt);
}
