/**
 * TrashSorter — Arduino Servo Firmware (SAFE)
 * ==============================================
 * Servo an toàn: thả lỏng (detach) khi idle.
 * Chỉ attach khi cần gạt. Tốc độ chậm 15ms/độ.
 * 
 * Tính năng:
 *   - SORT: gạt rác với tham số từ RPi
 *   - CALIBRATE: test góc (attach → move → hold 1s → detach)
 *   - SET_CONFIG: lưu cấu hình góc vào EEPROM (giả lập = RAM)
 *   - PING, STATUS: heartbeat + debug
 * 
 * Protocol: JSON one-liner + '\n' @ 115200 baud
 * 
 * Lệnh mẫu:
 *   {"cmd":"SORT","servo":1,"dir":"fire"}
 *   {"cmd":"CALIBRATE","servo":1,"angle":90}
 *   {"cmd":"SET_CONFIG","servo":1,"home":0,"sweep":90}
 *   {"cmd":"PING"}
 *   {"cmd":"STATUS"}
 */

#include <Servo.h>
#include <ArduinoJson.h>

// ── Pin ────────────────────────────────────────────────────────────────────
#define PIN_SERVO1      9
#define PIN_SERVO2      10
#define PIN_IR1         2
#define PIN_IR2         3
#define PIN_LED         13

// ── Timing ─────────────────────────────────────────────────────────────────
#define SPEED_MS_PER_DEG 15     // 15ms cho mỗi độ (an toàn, không cháy)
#define HOLD_AFTER_MS    500    // giữ sau khi tới góc
#define DEBOUNCE_MS      20

// ── Servo state ────────────────────────────────────────────────────────────
Servo servo1, servo2;

// Cấu hình góc (có thể SET_CONFIG từ RPi)
struct ServoConfig {
  int home;   // góc nghỉ
  int sweep;  // góc gạt
};
ServoConfig cfg1 = {0, 90};
ServoConfig cfg2 = {0, 90};

// Trạng thái non-blocking
enum Phase { IDLE, MOVING, HOLDING, RETURNING };
Phase phase1 = IDLE, phase2 = IDLE;
int   angle1 = 0, angle2 = 0;
int   target1 = 0, target2 = 0;
unsigned long nextStep1 = 0, nextStep2 = 0;
unsigned long holdEnd1 = 0, holdEnd2 = 0;
bool  servo1Attached = false, servo2Attached = false;

// ── IR state ───────────────────────────────────────────────────────────────
volatile bool ir1_pending = false;
volatile bool ir2_pending = false;
unsigned long last_ir1 = 0, last_ir2 = 0;
unsigned long boot_ms = 0;

// ── Serial buffer ──────────────────────────────────────────────────────────
char   serial_buf[256];
uint8_t buf_idx = 0;

// ── Setup ──────────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  while (!Serial) delay(10);

  pinMode(PIN_IR1, INPUT_PULLUP);
  pinMode(PIN_IR2, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_IR1), isr_ir1, FALLING);
  attachInterrupt(digitalPinToInterrupt(PIN_IR2), isr_ir2, FALLING);

  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);

  boot_ms = millis();

  // Servo KHÔNG attach ở setup — thả lỏng hoàn toàn
  StaticJsonDocument<64> doc;
  doc["boot"]     = "ok";
  doc["firmware"] = "TrashSorter-SAFE-v4.0";
  serializeJson(doc, Serial);
  Serial.println();
}

// ── ISRs ───────────────────────────────────────────────────────────────────
void isr_ir1() { ir1_pending = true; }
void isr_ir2() { ir2_pending = true; }

// ── Loop ───────────────────────────────────────────────────────────────────
void loop() {
  uint32_t now = millis();

  // ── Servo 1 state machine ─────────────────────────────────────────────
  if (servo1Attached) {
    if (phase1 == MOVING && now >= nextStep1) {
      if (angle1 < target1) { angle1++; servo1.write(angle1); }
      else if (angle1 > target1) { angle1--; servo1.write(angle1); }
      else { phase1 = HOLDING; holdEnd1 = now + HOLD_AFTER_MS; }
      nextStep1 = now + SPEED_MS_PER_DEG;
    }
    else if (phase1 == HOLDING && now >= holdEnd1) {
      // Trở về home
      target1 = cfg1.home;
      phase1 = RETURNING;
    }
    else if (phase1 == RETURNING && now >= nextStep1) {
      if (angle1 < target1) { angle1++; servo1.write(angle1); }
      else if (angle1 > target1) { angle1--; servo1.write(angle1); }
      else {
        // Về tới home → detach, thả lỏng!
        servo1.detach();
        servo1Attached = false;
        phase1 = IDLE;
        digitalWrite(PIN_LED, (servo2Attached) ? HIGH : LOW);
      }
      nextStep1 = now + SPEED_MS_PER_DEG;
    }
  }

  // ── Servo 2 state machine ─────────────────────────────────────────────
  if (servo2Attached) {
    if (phase2 == MOVING && now >= nextStep2) {
      if (angle2 < target2) { angle2++; servo2.write(angle2); }
      else if (angle2 > target2) { angle2--; servo2.write(angle2); }
      else { phase2 = HOLDING; holdEnd2 = now + HOLD_AFTER_MS; }
      nextStep2 = now + SPEED_MS_PER_DEG;
    }
    else if (phase2 == HOLDING && now >= holdEnd2) {
      target2 = cfg2.home;
      phase2 = RETURNING;
    }
    else if (phase2 == RETURNING && now >= nextStep2) {
      if (angle2 < target2) { angle2++; servo2.write(angle2); }
      else if (angle2 > target2) { angle2--; servo2.write(angle2); }
      else {
        servo2.detach();
        servo2Attached = false;
        phase2 = IDLE;
        digitalWrite(PIN_LED, (servo1Attached) ? HIGH : LOW);
      }
      nextStep2 = now + SPEED_MS_PER_DEG;
    }
  }

  // ── IR sensors ────────────────────────────────────────────────────────
  if (ir1_pending && (now - last_ir1) >= DEBOUNCE_MS) {
    noInterrupts(); ir1_pending = false; interrupts();
    if (digitalRead(PIN_IR1) == LOW && (now - boot_ms) > 1000) {
      last_ir1 = now;
      StaticJsonDocument<64> doc;
      doc["ack"] = "IR_TRIGGER"; doc["sensor"] = 1; doc["ts"] = now;
      serializeJson(doc, Serial); Serial.println();
    }
  }
  if (ir2_pending && (now - last_ir2) >= DEBOUNCE_MS) {
    noInterrupts(); ir2_pending = false; interrupts();
    if (digitalRead(PIN_IR2) == LOW && (now - boot_ms) > 1000) {
      last_ir2 = now;
      StaticJsonDocument<64> doc;
      doc["ack"] = "IR_TRIGGER"; doc["sensor"] = 2; doc["ts"] = now;
      serializeJson(doc, Serial); Serial.println();
    }
  }

  // ── Serial commands ───────────────────────────────────────────────────
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (buf_idx > 0) { serial_buf[buf_idx] = '\0'; process(serial_buf); buf_idx = 0; }
    } else if (buf_idx < sizeof(serial_buf) - 1) {
      serial_buf[buf_idx++] = c;
    }
  }
}

// ── Command processor ──────────────────────────────────────────────────────
void process(const char* raw) {
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, raw);
  if (err) { sendError("json_parse"); return; }

  const char* cmd = doc["cmd"] | "";

  if (strcmp(cmd, "SORT") == 0) {
    int id = doc["servo"] | 1;
    fireServo(id);

  } else if (strcmp(cmd, "CALIBRATE") == 0) {
    int id    = doc["servo"] | 1;
    int angle = doc["angle"] | 0;
    calibrateServo(id, angle);

  } else if (strcmp(cmd, "SET_CONFIG") == 0) {
    int id    = doc["servo"] | 1;
    int home  = doc["home"] | -1;
    int sweep = doc["sweep"] | -1;
    if (id == 1) {
      if (home  >= 0) cfg1.home  = home;
      if (sweep >= 0) cfg1.sweep = sweep;
    } else {
      if (home  >= 0) cfg2.home  = home;
      if (sweep >= 0) cfg2.sweep = sweep;
    }
    StaticJsonDocument<128> resp;
    resp["ack"] = "CONFIG_OK";
    resp["servo"] = id;
    resp["home"]  = (id==1) ? cfg1.home  : cfg2.home;
    resp["sweep"] = (id==1) ? cfg1.sweep : cfg2.sweep;
    serializeJson(resp, Serial); Serial.println();

  } else if (strcmp(cmd, "PING") == 0) {
    StaticJsonDocument<64> resp;
    resp["ack"] = "PONG";
    resp["uptime_s"] = (millis() - boot_ms) / 1000;
    serializeJson(resp, Serial); Serial.println();

  } else if (strcmp(cmd, "STATUS") == 0) {
    StaticJsonDocument<256> resp;
    resp["ack"] = "STATUS";
    resp["servo1_attached"] = servo1Attached;
    resp["servo2_attached"] = servo2Attached;
    resp["servo1_phase"] = (int)phase1;
    resp["servo2_phase"] = (int)phase2;
    resp["servo1_angle"] = angle1;
    resp["servo2_angle"] = angle2;
    resp["cfg1_home"]  = cfg1.home;
    resp["cfg1_sweep"] = cfg1.sweep;
    resp["cfg2_home"]  = cfg2.home;
    resp["cfg2_sweep"] = cfg2.sweep;
    resp["uptime_s"] = (millis() - boot_ms) / 1000;
    serializeJson(resp, Serial); Serial.println();

  } else {
    sendError("unknown_cmd");
  }
}

// ── Servo actions ──────────────────────────────────────────────────────────

void fireServo(int id) {
  ServoConfig& cfg = (id == 1) ? cfg1 : cfg2;
  Servo& srv = (id == 1) ? servo1 : servo2;
  bool& attached = (id == 1) ? servo1Attached : servo2Attached;
  Phase& phase = (id == 1) ? phase1 : phase2;
  int& angle = (id == 1) ? angle1 : angle2;
  int& target = (id == 1) ? target1 : target2;
  unsigned long& next = (id == 1) ? nextStep1 : nextStep2;

  // Attach nếu chưa
  if (!attached) {
    srv.attach((id == 1) ? PIN_SERVO1 : PIN_SERVO2);
    attached = true;
    angle = cfg.home;
    srv.write(angle);
    delay(50); // chờ servo ổn định
  }

  target = cfg.sweep;
  phase = MOVING;
  next = millis() + SPEED_MS_PER_DEG;
  digitalWrite(PIN_LED, HIGH);

  // Ack
  StaticJsonDocument<128> resp;
  resp["ack"] = "SORT_START";
  resp["servo"] = id;
  resp["from"] = cfg.home;
  resp["to"] = cfg.sweep;
  serializeJson(resp, Serial); Serial.println();
}

void calibrateServo(int id, int testAngle) {
  Servo& srv = (id == 1) ? servo1 : servo2;
  bool& attached = (id == 1) ? servo1Attached : servo2Attached;

  // Attach tạm thời
  srv.attach((id == 1) ? PIN_SERVO1 : PIN_SERVO2);
  attached = true;

  // Di chuyển từ từ đến góc test
  int startAngle = (id == 1) ? angle1 : angle2;
  int step = (testAngle > startAngle) ? 1 : -1;
  for (int a = startAngle; a != testAngle; a += step) {
    srv.write(a);
    delay(SPEED_MS_PER_DEG);
  }
  srv.write(testAngle);
  delay(1000); // giữ 1 giây để người dùng quan sát

  // Detach — thả lỏng!
  srv.detach();
  attached = false;
  if (id == 1) { phase1 = IDLE; angle1 = testAngle; }
  else         { phase2 = IDLE; angle2 = testAngle; }
  digitalWrite(PIN_LED, LOW);

  StaticJsonDocument<64> resp;
  resp["ack"] = "CALIBRATE_DONE";
  resp["servo"] = id;
  resp["angle"] = testAngle;
  serializeJson(resp, Serial); Serial.println();
}

void sendError(const char* msg) {
  StaticJsonDocument<64> doc;
  doc["ack"] = "ERROR"; doc["msg"] = msg;
  serializeJson(doc, Serial); Serial.println();
}