/**
 * TrashSorter — Arduino Slave Firmware
 * ======================================
 * Nhận lệnh từ Raspberry Pi qua UART JSON, điều khiển:
 *   - 2 Servo (SG90) để gạt rác vào các ngăn
 *   - 2 IR Sensor (FC-51) phát hiện vật thể đi qua
 *   - Băng chuyền (continous rotation servo hoặc DC motor)
 *
 * Kết nối:
 *   RX (Arduino) ← TX (Raspberry Pi GPIO14)
 *   TX (Arduino) → RX (Raspberry Pi GPIO15)
 *   GND chung
 *
 * Servo:
 *   Servo 1 (Pin 9)  : Kim Loại (gạt trái)
 *   Servo 2 (Pin 10) : Nhựa (gạt trái) / Giấy (gạt phải)
 *
 * IR Sensors (interrupt):
 *   IR1 (Pin 2) : Trước Servo 1
 *   IR2 (Pin 3) : Trước Servo 2
 *
 * Băng chuyền:
 *   Motor PWM (Pin 5) : điều khiển tốc độ băng chuyền
 */

#include <Servo.h>
#include <ArduinoJson.h>

// ── Pin Definitions ─────────────────────────────────────────────────────────
const int SERVO1_PIN     = 9;   // Servo 1: Kim Loại
const int SERVO2_PIN     = 10;  // Servo 2: Nhựa + Giấy
const int IR1_PIN        = 2;   // IR Sensor 1 (interrupt)
const int IR2_PIN        = 3;   // IR Sensor 2 (interrupt)
const int CONVEYOR_PWM   = 5;   // Băng chuyền PWM
const int LED_STATUS     = 13;  // LED trạng thái (built-in)

// ── Servo Angles ────────────────────────────────────────────────────────────
const int SERVO1_NEUTRAL   = 90;
const int SERVO1_LEFT      = 45;   // Kim Loại → trái
const int SERVO1_RIGHT     = 135;  // Reject → phải

const int SERVO2_NEUTRAL   = 90;
const int SERVO2_LEFT      = 50;   // Nhựa → trái
const int SERVO2_RIGHT     = 130;  // Giấy → phải

const int HOLD_MS          = 500;  // Thời gian giữ servo trước khi trả về neutral

// ── Objects ─────────────────────────────────────────────────────────────────
Servo servo1, servo2;

// ── IR Sensor State ─────────────────────────────────────────────────────────
volatile bool ir1_triggered = false;
volatile bool ir2_triggered = false;
volatile unsigned long ir1_time = 0;
volatile unsigned long ir2_time = 0;
unsigned long last_debounce_ir1 = 0;
unsigned long last_debounce_ir2 = 0;
const unsigned long DEBOUNCE_MS = 20;

// ── System State ────────────────────────────────────────────────────────────
unsigned long uptime_start = 0;
bool conveyor_running = true;
String last_error = "";

// ── Setup ───────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  // Servos
  servo1.attach(SERVO1_PIN);
  servo2.attach(SERVO2_PIN);
  servo1.write(SERVO1_NEUTRAL);
  servo2.write(SERVO2_NEUTRAL);

  // IR Sensors (interrupt)
  pinMode(IR1_PIN, INPUT_PULLUP);
  pinMode(IR2_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(IR1_PIN), ir1_isr, FALLING);
  attachInterrupt(digitalPinToInterrupt(IR2_PIN), ir2_isr, FALLING);

  // Conveyor
  pinMode(CONVEYOR_PWM, OUTPUT);
  analogWrite(CONVEYOR_PWM, 180);  // ~70% speed

  // Status LED
  pinMode(LED_STATUS, OUTPUT);
  digitalWrite(LED_STATUS, HIGH);

  uptime_start = millis();

  // Hello message
  StaticJsonDocument<128> doc;
  doc["ack"] = "READY";
  doc["firmware"] = "TrashSorter v1.0";
  doc["uptime_s"] = 0;
  serializeJson(doc, Serial);
  Serial.println();
}

// ── Loop ────────────────────────────────────────────────────────────────────
void loop() {
  // ── Process incoming commands ──────────────────────────────────────────
  if (Serial.available()) {
    String raw = Serial.readStringUntil('\n');
    raw.trim();
    if (raw.length() > 0) {
      processCommand(raw);
    }
  }

  // ── Check IR triggers ──────────────────────────────────────────────────
  if (ir1_triggered) {
    unsigned long now = millis();
    if ((now - last_debounce_ir1) > DEBOUNCE_MS) {
      sendIRTrigger(1, ir1_time);
      last_debounce_ir1 = now;
    }
    ir1_triggered = false;
  }

  if (ir2_triggered) {
    unsigned long now = millis();
    if ((now - last_debounce_ir2) > DEBOUNCE_MS) {
      sendIRTrigger(2, ir2_time);
      last_debounce_ir2 = now;
    }
    ir2_triggered = false;
  }

  // ── Heartbeat LED ──────────────────────────────────────────────────────
  static unsigned long last_blink = 0;
  if (millis() - last_blink > 1000) {
    digitalWrite(LED_STATUS, !digitalRead(LED_STATUS));
    last_blink = millis();
  }
}

// ── IR Interrupt Handlers ──────────────────────────────────────────────────
void ir1_isr() {
  ir1_triggered = true;
  ir1_time = micros();
}

void ir2_isr() {
  ir2_triggered = true;
  ir2_time = micros();
}

// ── Send IR Trigger ────────────────────────────────────────────────────────
void sendIRTrigger(int sensor, unsigned long ts_us) {
  StaticJsonDocument<128> doc;
  doc["ack"] = "IR_TRIGGER";
  doc["sensor"] = sensor;
  doc["ts"] = ts_us;
  serializeJson(doc, Serial);
  Serial.println();
}

// ── Command Processor ───────────────────────────────────────────────────────
void processCommand(String raw) {
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, raw);

  if (err) {
    sendError("JSON parse error: " + String(err.c_str()));
    return;
  }

  String cmd = doc["cmd"] | "";

  if (cmd == "SORT") {
    int servo_id   = doc["servo"] | 0;
    String dir     = doc["dir"] | "left";

    doSort(servo_id, dir);

  } else if (cmd == "PING") {
    StaticJsonDocument<128> resp;
    resp["ack"] = "PONG";
    resp["uptime_s"] = (millis() - uptime_start) / 1000;
    serializeJson(resp, Serial);
    Serial.println();

  } else if (cmd == "RESET") {
    servo1.write(SERVO1_NEUTRAL);
    servo2.write(SERVO2_NEUTRAL);
    conveyor_running = true;
    analogWrite(CONVEYOR_PWM, 180);
    last_error = "";
    StaticJsonDocument<64> resp;
    resp["ack"] = "RESET_DONE";
    serializeJson(resp, Serial);
    Serial.println();

  } else if (cmd == "STATUS") {
    StaticJsonDocument<256> resp;
    resp["ack"] = "STATUS";
    resp["uptime_s"] = (millis() - uptime_start) / 1000;
    resp["conveyor"] = conveyor_running ? "ON" : "OFF";
    resp["servo1_angle"] = servo1.read();
    resp["servo2_angle"] = servo2.read();
    resp["error"] = last_error;
    serializeJson(resp, Serial);
    Serial.println();

  } else if (cmd == "CONVEYOR") {
    String state = doc["state"] | "ON";
    if (state == "ON") {
      analogWrite(CONVEYOR_PWM, 180);
      conveyor_running = true;
    } else {
      analogWrite(CONVEYOR_PWM, 0);
      conveyor_running = false;
    }
    StaticJsonDocument<64> resp;
    resp["ack"] = "CONVEYOR_" + state;
    serializeJson(resp, Serial);
    Serial.println();

  } else {
    sendError("Unknown command: " + cmd);
  }
}

// ── Servo Dispatch ──────────────────────────────────────────────────────────
void doSort(int servo_id, String direction) {
  unsigned long start_ms = millis();
  Servo* s = nullptr;
  int neutral = 0, angle = 0;

  if (servo_id == 1) {
    s = &servo1;
    neutral = SERVO1_NEUTRAL;
    angle = (direction == "left") ? SERVO1_LEFT : SERVO1_RIGHT;
  } else if (servo_id == 2) {
    s = &servo2;
    neutral = SERVO2_NEUTRAL;
    angle = (direction == "left") ? SERVO2_LEFT : SERVO2_RIGHT;
  } else {
    sendError("Invalid servo: " + String(servo_id));
    return;
  }

  // Gạt
  s->write(angle);
  delay(HOLD_MS);

  // Trả về neutral
  s->write(neutral);

  unsigned long elapsed = millis() - start_ms;

  // Ack
  StaticJsonDocument<128> resp;
  resp["ack"] = "SORT_DONE";
  resp["servo"] = servo_id;
  resp["dir"] = direction;
  resp["ms"] = elapsed;
  serializeJson(resp, Serial);
  Serial.println();
}

// ── Error Reporter ──────────────────────────────────────────────────────────
void sendError(String msg) {
  last_error = msg;
  StaticJsonDocument<256> doc;
  doc["ack"] = "ERROR";
  doc["msg"] = msg;
  serializeJson(doc, Serial);
  Serial.println();
}