// =====================================================================
// Lite 用户配置区：只修改本区参数
// 警告：仓库内数值仅用于编译验证，不是设备实测值。完成泵流量和 pH 标定后，
// 必须填写真实参数，并把 LITE_CONFIGURED 改为 true，才能启动泵和测量。
// 接线：ORP 模块接 D2/D3，启动按钮接 D4，碱泵接 D13，酸泵接 D12，水泵接 D11，
// OLED 的 SDA/SCL 接 A4/A5。继电器为高电平启动。
// 操作：配置有效后，待机时按 D4 启动 VFA/ALK 测量；完成后再按 D4 返回待机。
// =====================================================================
const bool LITE_CONFIGURED = false;

// 三路泵流速，单位 mL/s。
const float CFG_BASE_PUMP_FLOW_ML_S = 1.0f;
const float CFG_ACID_PUMP_FLOW_ML_S = 1.0f;
const float CFG_WATER_PUMP_FLOW_ML_S = 1.0f;

// pH = ORP_mV * slope + intercept。
const float CFG_PH_SLOPE_PH_PER_MV = 0.005f;
const float CFG_PH_INTERCEPT_PH = 4.0f;

// VFA/ALK 基础参数。
const float CFG_ACID_CONCENTRATION_MOL_L = 0.1f;
const float CFG_SAMPLE_VOLUME_ML = 50.0f;
const float CFG_KV = 1.0f;
const float CFG_KA = 1.0f;

// 普通滴定参数。
const float CFG_TARGET_PH = 5.0f;
const float CFG_TRIGGER_PH = 3.7f;
const float CFG_TOLERANCE_PH = 0.2f;
const float CFG_MIX_SECONDS = 5.0f;
const uint8_t CFG_TITRATION_DIRECTION = 0;  // 0=加碱，1=加酸
const uint8_t CFG_MAX_ORDINARY_DOSES = 20;

// VFA/ALK 两阶段流程参数。
const float CFG_VFA_MIN_START_PH = 5.5f;
const float CFG_VFA_STAGE1_PH = 5.1f;
const float CFG_VFA_STAGE2_PH = 3.5f;
const float CFG_VFA_STABILITY_PH = 0.10f;
const uint16_t CFG_VFA_OBSERVE_SECONDS = 10;
const uint16_t CFG_VFA_TIMEOUT_SECONDS = 1000;
const float CFG_VFA_BLANK_ML = 0.25f;
const float CFG_VFA_NEGATIVE_TOL_MMOL = 0.05f;
// =====================================================================

#include <SoftwareSerial.h>
#include <Wire.h>
#include <avr/pgmspace.h>
#include <string.h>
#include <stdlib.h>

// 引脚
#define PUMP_BASE  13
#define PUMP_ACID  12
#define PUMP_WATER 11
#define BTN_PIN    4

// OLED 显示
#define OLED_ADDR 0x3C
#define OLED_XOFF 2
#define CHAR_W    6
#define OLED_COLS 20

static const uint8_t PROGMEM font5x7[] = {
  0x00,0x00,0x00,0x00,0x00, 0x00,0x00,0x5F,0x00,0x00,
  0x00,0x07,0x00,0x07,0x00, 0x14,0x7F,0x14,0x7F,0x14,
  0x24,0x2A,0x7F,0x2A,0x12, 0x23,0x13,0x08,0x64,0x62,
  0x36,0x49,0x55,0x22,0x50, 0x00,0x05,0x03,0x00,0x00,
  0x00,0x1C,0x22,0x41,0x00, 0x00,0x41,0x22,0x1C,0x00,
  0x08,0x2A,0x1C,0x2A,0x08, 0x08,0x08,0x3E,0x08,0x08,
  0x00,0x50,0x30,0x00,0x00, 0x08,0x08,0x08,0x08,0x08,
  0x00,0x60,0x60,0x00,0x00, 0x20,0x10,0x08,0x04,0x02,
  0x3E,0x51,0x49,0x45,0x3E, 0x00,0x42,0x7F,0x40,0x00,
  0x42,0x61,0x51,0x49,0x46, 0x21,0x41,0x45,0x4B,0x31,
  0x18,0x14,0x12,0x7F,0x10, 0x27,0x45,0x45,0x45,0x39,
  0x3C,0x4A,0x49,0x49,0x30, 0x01,0x71,0x09,0x05,0x03,
  0x36,0x49,0x49,0x49,0x36, 0x06,0x49,0x49,0x29,0x1E,
  0x00,0x36,0x36,0x00,0x00, 0x00,0x56,0x36,0x00,0x00,
  0x08,0x14,0x22,0x41,0x00, 0x14,0x14,0x14,0x14,0x14,
  0x41,0x22,0x14,0x08,0x00, 0x02,0x01,0x51,0x09,0x06,
  0x32,0x49,0x79,0x41,0x3E, 0x7E,0x11,0x11,0x11,0x7E,
  0x7F,0x49,0x49,0x49,0x36, 0x3E,0x41,0x41,0x41,0x22,
  0x7F,0x41,0x41,0x22,0x1C, 0x7F,0x49,0x49,0x49,0x41,
  0x7F,0x09,0x09,0x01,0x01, 0x3E,0x41,0x41,0x51,0x32,
  0x7F,0x08,0x08,0x08,0x7F, 0x00,0x41,0x7F,0x41,0x00,
  0x20,0x40,0x41,0x3F,0x01, 0x7F,0x08,0x14,0x22,0x41,
  0x7F,0x40,0x40,0x40,0x40, 0x7F,0x02,0x04,0x02,0x7F,
  0x7F,0x04,0x08,0x10,0x7F, 0x3E,0x41,0x41,0x41,0x3E,
  0x7F,0x09,0x09,0x09,0x06, 0x3E,0x41,0x51,0x21,0x5E,
  0x7F,0x09,0x19,0x29,0x46, 0x46,0x49,0x49,0x49,0x31,
  0x01,0x01,0x7F,0x01,0x01, 0x3F,0x40,0x40,0x40,0x3F,
  0x1F,0x20,0x40,0x20,0x1F, 0x7F,0x20,0x18,0x20,0x7F,
  0x63,0x14,0x08,0x14,0x63, 0x03,0x04,0x78,0x04,0x03,
  0x61,0x51,0x49,0x45,0x43, 0x00,0x00,0x7F,0x41,0x41,
  0x02,0x04,0x08,0x10,0x20, 0x41,0x41,0x7F,0x00,0x00,
  0x04,0x02,0x01,0x02,0x04, 0x40,0x40,0x40,0x40,0x40,
  0x00,0x01,0x02,0x04,0x00, 0x20,0x54,0x54,0x54,0x78,
  0x7F,0x48,0x44,0x44,0x38, 0x38,0x44,0x44,0x44,0x20,
  0x38,0x44,0x44,0x48,0x7F, 0x38,0x54,0x54,0x54,0x18,
  0x08,0x7E,0x09,0x01,0x02, 0x08,0x14,0x54,0x54,0x3C,
  0x7F,0x08,0x04,0x04,0x78, 0x00,0x44,0x7D,0x40,0x00,
  0x20,0x40,0x44,0x3D,0x00, 0x00,0x7F,0x10,0x28,0x44,
  0x00,0x41,0x7F,0x40,0x00, 0x7C,0x04,0x18,0x04,0x78,
  0x7C,0x08,0x04,0x04,0x78, 0x38,0x44,0x44,0x44,0x38,
  0x7C,0x14,0x14,0x14,0x08, 0x08,0x14,0x14,0x18,0x7C,
  0x7C,0x08,0x04,0x04,0x08, 0x48,0x54,0x54,0x54,0x20,
  0x04,0x3F,0x44,0x40,0x20, 0x3C,0x40,0x40,0x20,0x7C,
  0x1C,0x20,0x40,0x20,0x1C, 0x3C,0x40,0x30,0x40,0x3C,
  0x44,0x28,0x10,0x28,0x44, 0x0C,0x50,0x50,0x50,0x3C,
  0x44,0x64,0x54,0x4C,0x44, 0x00,0x08,0x36,0x41,0x00,
  0x00,0x00,0x7F,0x00,0x00, 0x00,0x41,0x36,0x08,0x00,
  0x08,0x04,0x08,0x10,0x08,
};

static void ol_cmd(uint8_t c) { Wire.beginTransmission(OLED_ADDR); Wire.write(0x00); Wire.write(c); Wire.endTransmission(); }
static void ol_cmd2(uint8_t c, uint8_t d) { Wire.beginTransmission(OLED_ADDR); Wire.write(0x00); Wire.write(c); Wire.write(d); Wire.endTransmission(); }
static void ol_setPos(uint8_t col, uint8_t page) {
  col += OLED_XOFF;
  Wire.beginTransmission(OLED_ADDR); Wire.write(0x00);
  Wire.write(0xB0|(page&7)); Wire.write(0x00|(col&0xF)); Wire.write(0x10|((col>>4)&0xF)); Wire.endTransmission();
}
static void ol_init() {
  ol_cmd(0xAE); ol_cmd2(0xD5,0x80); ol_cmd2(0xA8,0x3F); ol_cmd2(0xD3,0x00);
  ol_cmd(0x40); ol_cmd2(0x8D,0x14); ol_cmd2(0x20,0x02); ol_cmd(0xA1); ol_cmd(0xC8);
  ol_cmd2(0xDA,0x12); ol_cmd2(0x81,0xCF); ol_cmd2(0xD9,0xF1); ol_cmd2(0xDB,0x40);
  ol_cmd(0xA4); ol_cmd(0xA6); ol_cmd(0xAF);
}
static void ol_clear() {
  uint8_t z[16]; memset(z,0,16);
  for(uint8_t p=0;p<8;p++){ ol_setPos(0,p); for(uint8_t b=0;b<8;b++){ Wire.beginTransmission(OLED_ADDR); Wire.write(0x40); Wire.write(z,16); Wire.endTransmission(); } }
}
static void ol_writeChar(uint8_t x, uint8_t page, char c) {
  if(c<32||c>90) c='?';
  uint8_t col=x*CHAR_W;
  uint16_t idx=((uint8_t)c-32)*5;
  ol_setPos(col,page);
  uint8_t g[6]; for(uint8_t i=0;i<5;i++) g[i]=pgm_read_byte(&font5x7[idx+i]); g[5]=0;
  Wire.beginTransmission(OLED_ADDR); Wire.write(0x40); Wire.write(g,6); Wire.endTransmission();
}
static uint8_t _cx,_cy;
static void ol_cursor(uint8_t c,uint8_t r){ _cx=c<OLED_COLS?c:OLED_COLS-1; _cy=r&7; }
static void ol_print(const char*s){ while(*s){ ol_writeChar(_cx,_cy,*s); _cx++; if(_cx>=OLED_COLS){_cx=0;_cy++;}_cy&=7; s++; } }
static void ol_print_P(PGM_P s){ char c; while((c=pgm_read_byte(s++))){ ol_writeChar(_cx,_cy,c); _cx++; if(_cx>=OLED_COLS){_cx=0;_cy++;}_cy&=7; } }
static void ol_printF(float v,uint8_t d){ char b[12]; dtostrf(v,0,d,b); ol_print(b); }
static void ol_printI(int32_t v){ char b[12]; ltoa(v,b,10); ol_print(b); }
#define OL(text_literal) ol_print_P(PSTR(text_literal))

struct EEData {
  float vol_b, vol_a, vol_w;
  float flow_b, flow_a, flow_w;
  float acid_N, sample_ml;
  float target_ph, trigger_ph, tolerance, mix_wait;
  float ph_k, ph_b;
  uint8_t titr_dir;
};
EEData ee;

struct EEExtData {
  uint8_t result_valid;
  float kv;
  float ka;
  float vfa_raw;
  float alk_raw;
};
EEExtData eeExt;

bool g_configReady=false;
const char* g_configError="NOT CONFIGURED";

bool configFloatInRange(float value, float minValue, float maxValue){
  return isfinite(value) && value>=minValue && value<=maxValue;
}

void setConfigError(const char* field){
  if(g_configReady) g_configError=field;
  g_configReady=false;
}

void loadConfig(){
  memset(&ee,0,sizeof(ee));
  memset(&eeExt,0,sizeof(eeExt));
  ee.flow_b=CFG_BASE_PUMP_FLOW_ML_S;
  ee.flow_a=CFG_ACID_PUMP_FLOW_ML_S;
  ee.flow_w=CFG_WATER_PUMP_FLOW_ML_S;
  ee.acid_N=CFG_ACID_CONCENTRATION_MOL_L;
  ee.sample_ml=CFG_SAMPLE_VOLUME_ML;
  ee.target_ph=CFG_TARGET_PH;
  ee.trigger_ph=CFG_TRIGGER_PH;
  ee.tolerance=CFG_TOLERANCE_PH;
  ee.mix_wait=CFG_MIX_SECONDS;
  ee.ph_k=CFG_PH_SLOPE_PH_PER_MV;
  ee.ph_b=CFG_PH_INTERCEPT_PH;
  ee.titr_dir=CFG_TITRATION_DIRECTION;
  eeExt.kv=CFG_KV;
  eeExt.ka=CFG_KA;

  g_configReady=true;
  g_configError="OK";
  if(!LITE_CONFIGURED) setConfigError("NOT CONFIGURED");
  else if(!configFloatInRange(ee.flow_b,0.001f,100.0f)) setConfigError("BASE FLOW");
  else if(!configFloatInRange(ee.flow_a,0.001f,100.0f)) setConfigError("ACID FLOW");
  else if(!configFloatInRange(ee.flow_w,0.001f,100.0f)) setConfigError("WATER FLOW");
  else if(!configFloatInRange(ee.ph_k,-1.0f,1.0f) || ee.ph_k==0.0f) setConfigError("PH SLOPE");
  else if(!configFloatInRange(ee.ph_b,-14.0f,28.0f)) setConfigError("PH INTERCEPT");
  else if(!configFloatInRange(ee.acid_N,0.001f,10.0f)) setConfigError("ACID MOL/L");
  else if(!configFloatInRange(ee.sample_ml,0.1f,10000.0f)) setConfigError("SAMPLE ML");
  else if(!configFloatInRange(ee.target_ph,0.0f,14.0f)) setConfigError("TARGET PH");
  else if(!configFloatInRange(ee.trigger_ph,0.0f,14.0f)) setConfigError("TRIGGER PH");
  else if(!configFloatInRange(ee.tolerance,0.001f,5.0f)) setConfigError("TOLERANCE");
  else if(!configFloatInRange(ee.mix_wait,0.5f,120.0f)) setConfigError("MIX SECONDS");
  else if(ee.titr_dir>1) setConfigError("DIRECTION");
  else if(!configFloatInRange(eeExt.kv,0.2f,5.0f)) setConfigError("KV");
  else if(!configFloatInRange(eeExt.ka,0.2f,5.0f)) setConfigError("KA");
  else if(!configFloatInRange(CFG_VFA_MIN_START_PH,0.0f,14.0f)) setConfigError("VFA START PH");
  else if(!configFloatInRange(CFG_VFA_STAGE1_PH,0.0f,14.0f)) setConfigError("VFA STAGE1 PH");
  else if(!configFloatInRange(CFG_VFA_STAGE2_PH,0.0f,14.0f)) setConfigError("VFA STAGE2 PH");
  else if(!(CFG_VFA_MIN_START_PH>CFG_VFA_STAGE1_PH && CFG_VFA_STAGE1_PH>CFG_VFA_STAGE2_PH)) setConfigError("VFA PH ORDER");
  else if(!configFloatInRange(CFG_VFA_STABILITY_PH,0.001f,2.0f)) setConfigError("VFA STABILITY");
  else if(CFG_VFA_OBSERVE_SECONDS<1 || CFG_VFA_OBSERVE_SECONDS>120) setConfigError("VFA OBSERVE");
  else if(CFG_VFA_TIMEOUT_SECONDS<60 || CFG_VFA_TIMEOUT_SECONDS>3600) setConfigError("VFA TIMEOUT");
  else if(!configFloatInRange(CFG_VFA_BLANK_ML,0.0f,100.0f)) setConfigError("VFA BLANK");
  else if(!configFloatInRange(CFG_VFA_NEGATIVE_TOL_MMOL,0.0f,10.0f)) setConfigError("VFA NEG TOL");
  else if(CFG_MAX_ORDINARY_DOSES<1 || CFG_MAX_ORDINARY_DOSES>100) setConfigError("MAX DOSES");
}

void eeSave(){}
void eeExtSave(){}
void resultRecalcAndPersist();
void resultClearAndPersist();
void resultReport();
void stopAllPumpsRaw();
void runTitrTick();
float resultVfa(){ return eeExt.result_valid ? eeExt.vfa_raw * eeExt.kv : 0; }
float resultAlk(){ return eeExt.result_valid ? eeExt.alk_raw * eeExt.ka : 0; }

unsigned char const ORP_TIMER=10, ORP_RX_TIMEOUT=50, ORP_ADDR=0xFE;
typedef struct { unsigned char flag,orpstatus,ntcstatus; unsigned int orpADC,tempADC; int orpValue,orpValue_temp; float tempValue; } ORPTypeDef;
ORPTypeDef ORP;
float curPH=7, curORP=0;
bool phFilterPrimed=false;

// Pump runtime state
bool pumpB=false,pumpA=false,pumpW=false;
unsigned long pumpBst=0,pumpAst=0,pumpWst=0;
bool pumpVolumeDirty=false;

const uint8_t PUMP_CH_BASE=1, PUMP_CH_ACID=2, PUMP_CH_WATER=3;
// 按键
unsigned long _btnChk=0; int _btnLast=HIGH;

// ORP 软件串口
SoftwareSerial DL(2,3);
bool anyPumpRunning(){
  return pumpB || pumpA || pumpW;
}
void pumpStateReport(){
  Serial.print(F("PUMP:"));
  Serial.print(pumpB?1:0);
  Serial.print(',');
  Serial.print(pumpA?1:0);
  Serial.print(',');
  Serial.println(pumpW?1:0);
}
float* pumpFlowRef(uint8_t pump){
  if(pump==PUMP_CH_ACID) return &ee.flow_a;
  if(pump==PUMP_CH_WATER) return &ee.flow_w;
  return &ee.flow_b;
}
float* pumpVolRef(uint8_t pump){
  if(pump==PUMP_CH_ACID) return &ee.vol_a;
  if(pump==PUMP_CH_WATER) return &ee.vol_w;
  return &ee.vol_b;
}
unsigned long* pumpStartRef(uint8_t pump){
  if(pump==PUMP_CH_ACID) return &pumpAst;
  if(pump==PUMP_CH_WATER) return &pumpWst;
  return &pumpBst;
}
bool* pumpFlagRef(uint8_t pump){
  if(pump==PUMP_CH_ACID) return &pumpA;
  if(pump==PUMP_CH_WATER) return &pumpW;
  return &pumpB;
}
void setPumpState(uint8_t pump, bool on){
  uint8_t pin = PUMP_BASE;
  bool *flag = pumpFlagRef(pump);
  unsigned long *startMs = pumpStartRef(pump);
  if(pump==PUMP_CH_ACID) pin=PUMP_ACID;
  else if(pump==PUMP_CH_WATER) pin=PUMP_WATER;
  if(on){
    digitalWrite(pin,HIGH);
    if(!*flag) *startMs=millis();
    *flag=true;
  } else {
    digitalWrite(pin,LOW);
    *startMs=0;
    *flag=false;
  }
}
bool stopPumpCounted(uint8_t pump){
  bool *flag = pumpFlagRef(pump);
  unsigned long *startMs = pumpStartRef(pump);
  bool changed=false;
  if(*flag && *startMs>0){
    *pumpVolRef(pump) += (*pumpFlowRef(pump)) * (millis()-*startMs) / 1000.0;
    pumpVolumeDirty=true;
    changed=true;
  }
  setPumpState(pump,false);
  return changed;
}
void stopAllPumpsCounted(bool persist){
  stopPumpCounted(PUMP_CH_BASE);
  stopPumpCounted(PUMP_CH_ACID);
  stopPumpCounted(PUMP_CH_WATER);
  if(persist && pumpVolumeDirty){
    eeSave();
    pumpVolumeDirty=false;
  }
  pumpStateReport();
}
void stopAllPumpsRaw(){
  setPumpState(PUMP_CH_BASE,false);
  setPumpState(PUMP_CH_ACID,false);
  setPumpState(PUMP_CH_WATER,false);
  pumpStateReport();
}

// 自动状态机
enum RunState { RS_IDLE, RS_TITR, RS_MIX, RS_VFA, RS_DONE };
RunState rstate=RS_IDLE;
unsigned long rs_timer=0;     // 泵运行或混合等待的截止时刻
unsigned long rs_phaseStart=0;
int rs_doseCount=0;           // 本轮滴加次数，用于防止无限循环
bool rs_isBase=true;          // true=加碱，false=加酸
float rs_initPH=0;
bool rs_doneIsVfa=false;

// VFA sub-state
enum VFASt { V_IDLE, V_OBSERVE, V_S1_DOSE, V_S1_MIX, V_S2_DOSE, V_S2_MIX, V_DONE };
VFASt vst=V_IDLE;
float vf_initPH, vf_acidB4, vf_acid51, vf_acid35;
float vf_obsSum=0, vf_obsMin=0, vf_obsMax=0, vf_stage1_ml=0, vf_stage2_ml=0;
uint8_t vf_obsCount=0;
unsigned long vf_pauseEnd, vf_phaseStart, vf_doneUntil, vf_noticeUntil=0;
unsigned long vf_totalStart=0;
char vf_notice[18]="";
const unsigned long VFA_TOTAL_TIMEOUT_MS = (unsigned long)CFG_VFA_TIMEOUT_SECONDS * 1000UL;

// 显示缓存
float dsp_V1=0, dsp_V2=0, dsp_vfa=0, dsp_alk=0;
char dsp_state[16]="IDLE";

// 根据 pH 差值选择单次泵运行时间
float getPumpDurToTarget(float gap, float endGap){
  if(gap>1.0) return 5;
  else if(gap>0.5) return 2;
  else if(gap>endGap) return 1;
  else return 0;
}
float getPumpDur(float gap){
  return getPumpDurToTarget(gap, ee.tolerance);
}

void resultRecalcAndPersist(){
  eeExtSave();
}

void resultClearAndPersist(){
  eeExt.result_valid=0;
  eeExt.vfa_raw=0;
  eeExt.alk_raw=0;
  eeExtSave();
}

void resultReport(){
  if(!eeExt.result_valid) return;
  Serial.print(F("PH0:")); Serial.print(vf_initPH,2);
  Serial.print(F(",V1:")); Serial.print(vf_stage1_ml,3);
  Serial.print(F(",V2:")); Serial.print(vf_stage2_ml,3);
  Serial.print(F(",VFA:")); Serial.print(resultVfa(),3);
  Serial.print(F(",ALK:")); Serial.println(resultAlk(),3);
}

void setVfaNotice(const char* msg){
  strncpy(vf_notice,msg,sizeof(vf_notice)-1);
  vf_notice[sizeof(vf_notice)-1]=0;
  vf_noticeUntil=millis()+5000;
}

void reportConfigError(){
  Serial.print(F("CONFIG ERROR:"));
  Serial.println(g_configError);
}

bool ensureConfigReady(){
  if(g_configReady) return true;
  if(anyPumpRunning()) stopAllPumpsRaw();
  reportConfigError();
  return false;
}

// 停止所有泵并结算体积
void stopAllPumps(){
  stopAllPumpsCounted(true);
}
void stopAllPumpsUnsaved(){
  stopAllPumpsCounted(false);
}

const float VFA_BLANK_ML = CFG_VFA_BLANK_ML;
const float VFA_RESULT_NEG_TOL_MMOL = CFG_VFA_NEGATIVE_TOL_MMOL;

void vfaTraceReport(float stage1Ml, float stage2Ml, float totalMl){
  Serial.print(F("VFA:TRACE PH0:")); Serial.print(vf_initPH,2);
  Serial.print(F(",A1:")); Serial.print(stage1Ml,3);
  Serial.print(F(",A2:")); Serial.print(stage2Ml,3);
  Serial.print(F(",TOTAL:")); Serial.print(totalMl,3);
  Serial.print(F(",FN:")); Serial.print(ee.acid_N,6);
  Serial.print(F(",FS:")); Serial.print(ee.sample_ml,3);
  Serial.print(F(",BLANK:")); Serial.println(VFA_BLANK_ML,3);
}

void vfaCalcError(const char* reason){
  eeExt.result_valid=0;
  eeExt.vfa_raw=0;
  eeExt.alk_raw=0;
  eeExtSave();
  Serial.print(F("VFA:CALC_ERROR "));
  Serial.println(reason);
}

bool vfaSolveRaw(float initPH, float stage1Ml, float totalMl, float acidN, float sampleMl, float blankMl, float* outVfaRaw, float* outAlkRaw){
  if(!isfinite(initPH) || !isfinite(stage1Ml) || !isfinite(totalMl) || !isfinite(acidN) || !isfinite(sampleMl) || !isfinite(blankMl)) return false;
  if(sampleMl<=0 || acidN<=0 || stage1Ml<0 || totalMl<stage1Ml || blankMl<0) return false;
  float K1=6.6e-7f, K2=2.4e-5f;
  float H1=pow(10,-initPH), H2=pow(10,-CFG_VFA_STAGE1_PH), H3=pow(10,-CFG_VFA_STAGE2_PH);
  float V1_ml=stage1Ml, V2_ml=totalMl-blankMl;
  if(V2_ml<0) return false;
  float C1=V1_ml*acidN/sampleMl, C2=V2_ml*acidN/sampleMl;
  float AA1=(H2-H1)/(K2+H2),AA2=(H3-H1)/(K2+H3),BB1=(H2-H1)/(K1+H2),BB2=(H3-H1)/(K1+H3);
  float den=BB1*AA2-BB2*AA1;
  if(!isfinite(den) || fabs(den)<1e-20f) return false;
  float VAd=(C2*BB1-C1*BB2)/den, HCO3=(C1*AA2-C2*AA1)/den;
  float VAt=VAd*(H1+K2)/K2;
  float vfaRaw=VAt*1000.0f;
  float alkRaw=HCO3*1000.0f;
  if(!isfinite(vfaRaw) || !isfinite(alkRaw)) return false;
  if(vfaRaw<0){
    if(vfaRaw>-VFA_RESULT_NEG_TOL_MMOL) vfaRaw=0;
    else return false;
  }
  if(alkRaw<0){
    if(alkRaw>-VFA_RESULT_NEG_TOL_MMOL) alkRaw=0;
    else return false;
  }
  *outVfaRaw=vfaRaw;
  *outAlkRaw=alkRaw;
  return true;
}

bool vfaCalc(){
  vf_stage1_ml=vf_acid51-vf_acidB4;
  vf_stage2_ml=vf_acid35-vf_acid51;
  float totalMl=vf_acid35-vf_acidB4;
  vfaTraceReport(vf_stage1_ml, vf_stage2_ml, totalMl);
  float vfaRaw=0, alkRaw=0;
  if(!vfaSolveRaw(vf_initPH, vf_stage1_ml, totalMl, ee.acid_N, ee.sample_ml, VFA_BLANK_ML, &vfaRaw, &alkRaw)){
    vfaCalcError("INVALID_RESULT");
    return false;
  }
  eeExt.vfa_raw=vfaRaw;
  eeExt.alk_raw=alkRaw;
  eeExt.result_valid=1;
  resultRecalcAndPersist();
  return true;
}

void vfaObserveStart(){
  stopAllPumps();
  vf_initPH=0; vf_acidB4=0; vf_acid51=0; vf_acid35=0;
  vf_obsSum=0; vf_obsMin=0; vf_obsMax=0; vf_obsCount=0;
  vf_stage1_ml=0; vf_stage2_ml=0;
  vf_totalStart=0; vf_pauseEnd=0;
  vst=V_OBSERVE; vf_phaseStart=millis(); rs_doneIsVfa=false;
  rstate=RS_VFA;
  Serial.println(F("VFA:START OBSERVE"));
}

unsigned long vfaPulseMs(float gap){
  return (unsigned long)(getPumpDurToTarget(gap, 0.0) * 1000.0);
}

unsigned long vfaMixWaitMs(){
  unsigned long ms=(unsigned long)(ee.mix_wait*1000.0);
  return ms<1000UL ? 1000UL : ms;
}

void vfaAbort(const char* reason){
  stopAllPumps();
  vst=V_IDLE;
  rstate=RS_IDLE;
  rs_doneIsVfa=false;
  setVfaNotice(reason);
  Serial.print(F("VFA:CANCELLED "));
  Serial.println(reason);
}

void vfaStartPulse(uint8_t doseState, float gap){
  if(anyPumpRunning()) stopAllPumpsUnsaved();
  if(vfaPulseMs(gap)==0){ return; }
  setPumpState(PUMP_CH_ACID,true);
  pumpStateReport();
  vf_pauseEnd=millis()+vfaPulseMs(gap);
  vst=(VFASt)doseState;
}

void vfaAdmitAndDose(float avgPH){
  vf_initPH=avgPH; vf_acidB4=ee.vol_a; vf_acid51=0; vf_acid35=0;
  vf_totalStart=millis();
  vf_phaseStart=millis();
  vf_pauseEnd=millis();
  vst=V_S1_MIX;
  Serial.print(F("VFA:ADMIT AVG:"));
  Serial.println(vf_initPH,2);
}

void vfaCancel(){
  if(vst==V_IDLE) return;
  stopAllPumps();
  vst=V_IDLE;
  rstate=RS_IDLE;
  rs_doneIsVfa=false;
  Serial.println(F("VFA:CANCELLED"));
}

void vfaReject(const char* code, float avgPH){
  Serial.print(F("VFA:REJECT "));
  Serial.print(code);
  Serial.print(F(" AVG:"));
  Serial.print(avgPH,2);
  Serial.print(F(" MIN:"));
  Serial.print(vf_obsMin,2);
  Serial.print(F(" MAX:"));
  Serial.println(vf_obsMax,2);
  if(strcmp(code,"LOW_PH")==0) setVfaNotice("START PH LOW");
  else setVfaNotice("PH UNSTABLE");
  stopAllPumps();
  vst=V_IDLE;
  rstate=RS_IDLE;
}

void vfaObserveTick(){
  if(vst!=V_OBSERVE) return;
  if(vf_obsCount==0){
    vf_obsMin=curPH;
    vf_obsMax=curPH;
  } else {
    if(curPH<vf_obsMin) vf_obsMin=curPH;
    if(curPH>vf_obsMax) vf_obsMax=curPH;
  }
  vf_obsSum+=curPH;
  vf_obsCount++;
  if(millis()-vf_phaseStart<(unsigned long)CFG_VFA_OBSERVE_SECONDS*1000UL) return;
  float avgPH=vf_obsCount?(vf_obsSum/vf_obsCount):curPH;
  if(avgPH<CFG_VFA_MIN_START_PH){
    vfaReject("LOW_PH", avgPH);
  } else if((vf_obsMax-vf_obsMin)>CFG_VFA_STABILITY_PH){
    vfaReject("UNSTABLE", avgPH);
  } else {
    vfaAdmitAndDose(avgPH);
  }
}

void vfaDoseTick(bool hasNew){
  if(vf_totalStart>0 && (millis()-vf_totalStart)>=VFA_TOTAL_TIMEOUT_MS){ vfaAbort("TIMEOUT"); return; }
  if(vst==V_OBSERVE){
    if(hasNew) vfaObserveTick();
    return;
  }
  if((vst==V_S1_DOSE || vst==V_S2_DOSE) && millis()>=vf_pauseEnd){
    stopAllPumpsUnsaved();
    vf_pauseEnd=millis()+vfaMixWaitMs();
    vst=(vst==V_S1_DOSE)?V_S1_MIX:V_S2_MIX;
    return;
  }
  if(vst!=V_S1_MIX && vst!=V_S2_MIX) return;
  if(millis()<vf_pauseEnd || !hasNew || curPH<=0) return;

  float target=(vst==V_S1_MIX)?CFG_VFA_STAGE1_PH:CFG_VFA_STAGE2_PH;
  float gap=curPH-target;
  if(gap<=0){
    stopAllPumps();
    if(vst==V_S1_MIX){
      vf_acid51=ee.vol_a;
      vf_stage1_ml=vf_acid51-vf_acidB4;
      Serial.print(F("VFA:pH5.1 VOL=")); Serial.println(vf_acid51-vf_acidB4,1);
      vf_phaseStart=millis();
      vf_pauseEnd=millis()+vfaMixWaitMs();
      vst=V_S2_MIX;
    } else {
      vf_acid35=ee.vol_a;
      if(vfaCalc()){
        vst=V_DONE; rstate=RS_DONE; rs_doneIsVfa=true;
        resultReport();
        Serial.println(F("FLOW:DONE"));
      } else {
        vst=V_IDLE; rstate=RS_IDLE; rs_doneIsVfa=false;
        setVfaNotice("CALC ERROR");
        Serial.println(F("FLOW:IDLE"));
      }
    }
    return;
  }
  vfaStartPulse(vst==V_S1_MIX ? V_S1_DOSE : V_S2_DOSE, gap);
}

// OLED 页面刷新
void updOLED(){
  ol_clear();
  if(!g_configReady){
    ol_cursor(0,0); OL("CONFIG ERROR");
    ol_cursor(0,2); OL("FIELD:");
    ol_print(g_configError);
    ol_cursor(0,4); OL("PUMPS DISABLED");
    ol_cursor(0,6); OL("CHECK TOP CONFIG");
    return;
  }
  switch(rstate){
    case RS_IDLE:
      ol_cursor(0,0); OL("READY. PRESS D4");
      ol_cursor(0,2); OL("PH:"); ol_printF(curPH,2);
      ol_cursor(0,4);
      if(vf_noticeUntil>millis()){
        OL("VFA:"); ol_print(vf_notice);
      } else {
        OL("VFA:");
        if(eeExt.result_valid) ol_printF(resultVfa(),1); else OL("--.-");
        OL(" ALK:");
        if(eeExt.result_valid) ol_printF(resultAlk(),1); else OL("--.-");
      }
      ol_cursor(0,6); OL("D4 START VFA/ALK");
      break;
    case RS_TITR:
      ol_cursor(0,0); OL("TITRATING...");
      ol_cursor(0,2); OL("PH:"); ol_printF(curPH,2); OL("->"); ol_printF(ee.target_ph,2);
      ol_cursor(0,4); OL("PUMP:"); if(rs_isBase) OL("BASE "); else OL("ACID ");
      if(rs_timer>0 && rs_timer>millis()) ol_printI((rs_timer-millis())/1000);
      else OL("--");
      OL("S");
      ol_cursor(0,6); OL("DOSE#"); ol_printI(rs_doseCount); OL(" GAP:"); ol_printF(abs(curPH-ee.target_ph),2);
      break;
    case RS_MIX:
      ol_cursor(0,0); OL("MIXING...   ");
      if(rs_timer>0 && rs_timer>millis()) ol_printI((rs_timer-millis())/1000);
      else OL("--");
      OL("S");
      ol_cursor(0,2); OL("PH:"); ol_printF(curPH,2);
      ol_cursor(0,4); OL("V1:"); ol_printF(ee.vol_b,1); OL(" V2:"); ol_printF(ee.vol_a,1); OL("ML");
      ol_cursor(0,6); OL("TGT:"); ol_printF(ee.target_ph,1); OL(" TOL:"); ol_printF(ee.tolerance,2);
      break;
    case RS_VFA:
      ol_cursor(0,0); OL("VFA MEASURE");
      ol_cursor(0,2); OL("PH0:");
      if(vst==V_OBSERVE) OL("--");
      else ol_printF(vf_initPH,2);
      OL(" PH:"); ol_printF(curPH,2);
      if(vst==V_OBSERVE){
        ol_cursor(0,4); OL("OBS WAIT 10S");
        ol_cursor(0,6); OL("PH0:--");
      } else if(vst==V_S1_DOSE){ OL(" S1"); ol_cursor(0,4); OL("S1 DOSING"); }
      else if(vst==V_S1_MIX){ OL(" S1"); ol_cursor(0,4); OL("S1 MIXING"); }
      else if(vst==V_S2_DOSE){ OL(" S2"); ol_cursor(0,4); OL("S2 DOSING"); }
      else if(vst==V_S2_MIX){ OL(" S2"); ol_cursor(0,4); OL("S2 MIXING"); }
      if(vst==V_S1_DOSE || vst==V_S1_MIX){
        ol_cursor(0,6);
        OL("V1:"); ol_printF(ee.vol_a-vf_acidB4,1);
      } else if(vst==V_S2_DOSE || vst==V_S2_MIX){
        ol_cursor(0,6);
        OL("V1:"); ol_printF(vf_stage1_ml,1);
        OL(" V2:"); ol_printF(ee.vol_a-vf_acid51,1);
      }
      break;
    case RS_DONE: {
      if(rs_doneIsVfa){
        ol_cursor(0,0); OL("DONE VFA/ALK");
        ol_cursor(0,2); OL("PH0:"); ol_printF(vf_initPH,2); OL(" V1:"); ol_printF(vf_stage1_ml,1);
        ol_cursor(0,4); OL("V2:"); ol_printF(vf_stage2_ml,1); OL(" VFA:"); if(eeExt.result_valid) ol_printF(resultVfa(),1); else OL("--.-");
        ol_cursor(0,6); OL("ALK:"); if(eeExt.result_valid) ol_printF(resultAlk(),1); else OL("--.-");
      } else {
        ol_cursor(0,0); OL("DONE");
        ol_cursor(0,2); OL("PH:"); ol_printF(curPH,2); OL(" TGT:"); ol_printF(ee.target_ph,1);
        ol_cursor(0,4); OL("V1:"); ol_printF(ee.vol_b,1); OL(" V2:"); ol_printF(ee.vol_a,1); OL("ML");
        ol_cursor(0,6); OL("BTN TO RESET");
      }
      break;}
  }
}

// 状态机驱动
void startFlow(){
  if(!ensureConfigReady()) return;
  if(anyPumpRunning() || rstate!=RS_IDLE) return;
  stopAllPumps();
  rs_initPH=curPH;
  rs_doseCount=0;
  rs_isBase=(curPH < ee.target_ph);
  rs_doneIsVfa=false;
  rstate=RS_TITR; rs_phaseStart=millis(); rs_timer=0;
  runTitrTick();
  Serial.println(F("FLOW:START"));
}

void startVfaMeasure(){
  if(!ensureConfigReady()) return;
  if(anyPumpRunning() || rstate!=RS_IDLE) return;
  rs_doneIsVfa=false;
  vfaObserveStart();
}

void stopFlow(){
  stopAllPumps();
  rstate=RS_IDLE; vst=V_IDLE; rs_doneIsVfa=false;
  Serial.println(F("FLOW:STOP"));
}

void runTitrTick(){
  if(rstate!=RS_TITR) return;
  float gap=rs_isBase?(ee.target_ph-curPH):(curPH-ee.target_ph);
  if(gap<=ee.tolerance){
    stopAllPumps();
    rstate=RS_DONE;
    rs_doneIsVfa=false;
    Serial.println(F("FLOW:DONE"));
    return;
  }
  if(rs_doseCount>=CFG_MAX_ORDINARY_DOSES){ stopFlow(); return; }

  float dur=getPumpDur(gap);
  if(dur<=0){ rstate=RS_MIX; rs_timer=millis()+(unsigned long)(ee.mix_wait*1000); return; }

  stopAllPumps();
  if(rs_isBase){ digitalWrite(PUMP_BASE,HIGH); pumpB=true; pumpBst=millis(); }
  else         { digitalWrite(PUMP_ACID,HIGH); pumpA=true; pumpAst=millis(); }
  rs_timer=millis()+(unsigned long)(dur*1000);
  rs_doseCount++;
}

void runStateMachine(){
  switch(rstate){
    case RS_IDLE: break;
    case RS_TITR:
      if(rs_timer>0 && millis()>=rs_timer){
        stopAllPumps();
        rstate=RS_MIX; rs_timer=millis()+(unsigned long)(ee.mix_wait*1000);
        Serial.print(F("FLOW:DOSE#")); Serial.print(rs_doseCount); Serial.println(F(" DONE->MIX"));
      }
      break;
    case RS_MIX:
      if(millis()>=rs_timer){
        rstate=RS_TITR; rs_phaseStart=millis();
        runTitrTick();
      }
      break;
    case RS_VFA:
      break;
    case RS_DONE: break;
  }
}

// 串口状态字符串
void printFlowState(){
  switch(rstate){
    case RS_IDLE: Serial.println(F("IDLE")); return;
    case RS_TITR: Serial.println(F("TITRATION")); return;
    case RS_MIX:  Serial.println(F("MIXING")); return;
    case RS_VFA:  Serial.println(F("VFA")); return;
    case RS_DONE: Serial.println(F("DONE")); return;
  }
  Serial.println(F("?"));
}

// ORP 通信
void ORP_Parse(ORPTypeDef*o);
unsigned int mbCRC(unsigned char*p,int l);
void ORP_Send(unsigned char*d,unsigned char l);
void ORP_Read(unsigned char a);

unsigned long _500ms=0,_10ms=0,_oled=0,_configReport=0;
unsigned char rbuf[64],rcnt=0,rflag=0,rtoutfl=0;
unsigned int rtout=0;

unsigned int mbCRC(unsigned char*p,int l){
  int i,j; unsigned int c=0xffff;
  for(j=0;j<l;j++){ c^=p[j]; for(i=0;i<8;i++){ if(c&1) c=(c>>1)^0xA001; else c>>=1; } }
  return c;
}
void ORP_Send(unsigned char*d,unsigned char l){ DL.write(d,l); }
void ORP_Read(unsigned char a){
  unsigned char t[8]; t[0]=a;t[1]=0x03;t[2]=0;t[3]=0;t[4]=0;t[5]=0x0B;
  unsigned short c=mbCRC(t,6); t[6]=c;t[7]=c>>8; ORP_Send(t,8);
}
void ORP_Parse(ORPTypeDef*o){
  if(!rflag) return; rflag=0;
  unsigned short sc=mbCRC(rbuf,rcnt-2),gc=rbuf[rcnt-1]; gc=(gc<<8)|rbuf[rcnt-2]; rcnt=0;
  if(gc!=sc||rbuf[0]!=ORP_ADDR||rbuf[1]!=0x03) return;
  o->orpstatus=rbuf[4];
  unsigned short v=rbuf[5]; v=(v<<8)|rbuf[6];
  if(v&0x8000){ o->orpValue=v&0x7fff; o->orpValue=-o->orpValue; } else o->orpValue=v;
  v=rbuf[7]; v=(v<<8)|rbuf[8];
  if(v&0x8000){ o->orpValue_temp=v&0x7fff; o->orpValue_temp=-o->orpValue_temp; } else o->orpValue_temp=v;
  unsigned short t=rbuf[9]; t=(t<<8)|rbuf[10]; o->tempValue=t/10.0;
  o->ntcstatus=rbuf[14];
  o->orpADC=rbuf[21]; o->orpADC=(o->orpADC<<8)|rbuf[22];
  o->tempADC=rbuf[23]; o->tempADC=(o->tempADC<<8)|rbuf[24];
  o->flag=1;
}
void ORP_Rx(unsigned char d){ rbuf[rcnt]=d; rcnt++; if(rcnt>=64) rcnt=0; rtoutfl=1; rtout=0; }
void ORP_Timer(){
  if(rtoutfl){ rtout++; if(rtout>=ORP_RX_TIMEOUT/ORP_TIMER){ rtout=0;rtoutfl=0; rflag=1; } }
}

// 初始化与主循环
void setup(){
  Serial.begin(115200);
  pinMode(PUMP_BASE,OUTPUT); pinMode(PUMP_ACID,OUTPUT); pinMode(PUMP_WATER,OUTPUT);
  digitalWrite(PUMP_BASE,LOW); digitalWrite(PUMP_ACID,LOW); digitalWrite(PUMP_WATER,LOW);
  pinMode(BTN_PIN,INPUT_PULLUP);
  DL.begin(9600);
  Wire.begin(); ol_init(); ol_clear(); ol_cursor(0,0); OL("ORP PH V10"); delay(300);
  loadConfig();
  Serial.println(F("ORP PH LITE START"));
  if(!g_configReady) reportConfigError();
  ol_clear();
  updOLED();
}

void loop(){
  if(!g_configReady){
    if(anyPumpRunning()) stopAllPumpsRaw();
    if(millis()-_oled>=1000){ _oled=millis(); updOLED(); }
    if(millis()-_configReport>=2000){ _configReport=millis(); reportConfigError(); }
    return;
  }
  // ORP
  ORP_Parse(&ORP);
  bool hasNew = ORP.flag;
  if(hasNew){ ORP.flag=0;
    curORP=ORP.orpValue_temp;
    float phInstant = curORP*ee.ph_k+ee.ph_b;
    if(!phFilterPrimed){
      curPH=phInstant;
      phFilterPrimed=true;
    } else {
      curPH=curPH*0.7 + phInstant*0.3;
    }
    Serial.print(F("STS:"));
    switch(ORP.orpstatus){
      case 0: Serial.println(F("RUN")); break;
      case 1: Serial.println(F("CAL")); break;
      case 2: Serial.println(F("CALOK")); break;
      case 3: Serial.println(F("CALFAIL")); break;
      default: Serial.println(F("?")); break;
    }
    Serial.print(F("ORPADC:")); Serial.println(ORP.orpADC);
    Serial.print(F("ORPMV:")); Serial.println(ORP.orpValue_temp);
    Serial.print(F("PH:")); Serial.println(curPH,2);
    Serial.print(F("TADC:")); Serial.println(ORP.tempADC);
    if(ORP.ntcstatus) {
      Serial.print(F("TEMP:"));
      if(ORP.ntcstatus==1) Serial.println(F("OPEN"));
      else if(ORP.ntcstatus==2) Serial.println(F("SHORT"));
      else Serial.println(F("?"));
    }
    else {
      Serial.print(F("TEMP:")); Serial.println(ORP.tempValue,1);
    }
    pumpStateReport();
    Serial.print(F("VOL:")); Serial.print(ee.vol_b,1); Serial.print(','); Serial.print(ee.vol_a,1); Serial.print(','); Serial.println(ee.vol_w,1);
    Serial.print(F("FLOW:")); printFlowState();
  }

  runStateMachine();
  if(rstate==RS_VFA && vst!=V_IDLE && vst!=V_DONE) vfaDoseTick(hasNew);

  // 500ms
  if(millis()-_500ms>=500){ _500ms=millis(); ORP_Read(ORP_ADDR); }

  // ORP 模块到 Arduino 的串口数据
  if(DL.available()) ORP_Rx(DL.read());

  // 按键
  if(millis()-_btnChk>=50){ _btnChk=millis();
    int b=digitalRead(BTN_PIN);
    if(b==LOW&&_btnLast==HIGH){
      if(rstate==RS_IDLE) startVfaMeasure();
      else if(rstate==RS_DONE){ rstate=RS_IDLE; vst=V_IDLE; Serial.println(F("FLOW:RESET")); }
    }
    _btnLast=b;
  }

  // OLED (1s)
  if(millis()-_oled>=1000){ _oled=millis(); updOLED(); }

  // 10 ms 接收超时计时
  if(millis()-_10ms>=10){ _10ms=millis(); ORP_Timer(); }
}
