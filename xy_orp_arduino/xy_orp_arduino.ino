// ORP V10 - 脱机自动调控 + VFA
// 模块 VIN->UNO 5V, GND->GND, TX->D2, RX->D3
// OLED SDA->A4, SCL->A5, 按键->D4
// 继电器: 碱泵 D13, 酸泵 D12, 水泵 D11

#include <SoftwareSerial.h>
#include <Wire.h>
#include <EEPROM.h>
#include <avr/pgmspace.h>
#include <string.h>
#include <stdlib.h>

// 鈹€鈹€ 寮曡剼 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
#define PUMP_BASE  13
#define PUMP_ACID  12
#define PUMP_WATER 11
#define BTN_PIN    4

// 鈹€鈹€ OLED 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
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

// 鈹€鈹€ EEPROM 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
#define EE_MAGIC 0xBEEF0001UL
#define EE_EXT_MAGIC 0xBEEF1001UL
#define EE_EXT_VERSION 2
struct EEData {
  float vol_b, vol_a, vol_w;
  float flow_b, flow_a, flow_w;
  float acid_N, sample_ml;
  float target_ph, trigger_ph, tolerance, mix_wait;
  float ph_k, ph_b;
  uint8_t titr_dir;  // 0=鍔犵⒈, 1=鍔犻吀
  uint32_t magic;
};
EEData ee;

struct EEExtData {
  uint32_t magic;
  uint8_t version;
  uint8_t result_valid;
  float kv;
  float ka;
  float vfa_raw;
  float alk_raw;
};
EEExtData eeExt;
const int EE_EXT_ADDR = sizeof(EEData);

void eeSave(){
  EEPROM.put(0,ee);
}

void eeExtSave(){
  EEPROM.put(EE_EXT_ADDR,eeExt);
}
void resultRecalcAndPersist();
void resultClearAndPersist();
void resultReport();
void resultStatusReport();
bool setResultFactor(char which, float value);
void stopAllPumpsRaw();
void runTitrTick();
float resultVfa(){ return eeExt.result_valid ? eeExt.vfa_raw * eeExt.kv : 0; }
float resultAlk(){ return eeExt.result_valid ? eeExt.alk_raw * eeExt.ka : 0; }

void eeExtDefault(){
  eeExt.magic=EE_EXT_MAGIC;
  eeExt.version=EE_EXT_VERSION;
  eeExt.result_valid=0;
  eeExt.kv=1.0;
  eeExt.ka=1.0;
  eeExt.vfa_raw=0;
  eeExt.alk_raw=0;
}

void eeExtLoad(){
  EEPROM.get(EE_EXT_ADDR,eeExt);
  bool valid=(eeExt.magic==EE_EXT_MAGIC && eeExt.version==EE_EXT_VERSION);
  if(!valid){
    eeExtDefault();
    eeExtSave();
    return;
  }
  if(eeExt.kv<0.2 || eeExt.kv>5.0) eeExt.kv=1.0;
  if(eeExt.ka<0.2 || eeExt.ka>5.0) eeExt.ka=1.0;
  eeExtSave();
}

void eeLoad(){
  EEPROM.get(0,ee);
  if(ee.magic!=EE_MAGIC){
    ee.vol_b=0; ee.vol_a=0; ee.vol_w=0;
    ee.flow_b=10; ee.flow_a=10; ee.flow_w=10;
    ee.acid_N=0.1; ee.sample_ml=50;
    ee.target_ph=5.0; ee.trigger_ph=3.7; ee.tolerance=0.2; ee.mix_wait=5;
    ee.ph_k=1.0/200.0; ee.ph_b=4.0;
    ee.titr_dir=0;
    ee.magic=EE_MAGIC;
    eeSave();
  }
  eeExtLoad();
}

// 鈹€鈹€ 鍏ㄥ眬鍙橀噺 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
// ORP
unsigned char const ORP_TIMER=10, ORP_RX_TIMEOUT=50, ORP_ADDR=0xFE;
typedef struct { unsigned char flag,orpstatus,ntcstatus; unsigned int orpADC,tempADC; int orpValue,orpValue_temp; float tempValue; } ORPTypeDef;
ORPTypeDef ORP;
float curPH=7, curORP=0;
bool phFilterPrimed=false;

// Pump runtime state
bool pumpB=false,pumpA=false,pumpW=false;
unsigned long pumpBst=0,pumpAst=0,pumpWst=0;
bool pumpVolumeDirty=false;

const uint8_t FCAL_PUMP_NONE=0, FCAL_PUMP_BASE=1, FCAL_PUMP_ACID=2, FCAL_PUMP_WATER=3;
const uint8_t FCAL_MODE_IDLE=0, FCAL_MODE_PRIME=1, FCAL_MODE_RUN=2;
uint8_t fcalMode=FCAL_MODE_IDLE;
uint8_t fcalPump=FCAL_PUMP_NONE;
unsigned long fcalStartMs=0, fcalPlanMs=0, fcalHardStopMs=0, fcalLastReportMs=0;
bool fcalLastWasEarlyStop=false;
char fcalLastEvent[10]="IDLE";
char fcalLastReason[10]="NONE";
unsigned long fcalLastActualMs=0, fcalLastPlanMs=0;
unsigned long fcalDoneUntil=0;
const unsigned long FCAL_PRIME_MAX_MS = 30000UL;
const unsigned long FCAL_RUN_MIN_MS = 3000UL;

// 鎸夐敭
unsigned long _btnChk=0; int _btnLast=HIGH;

// 鎸囦护
SoftwareSerial DL(2,3);
char cbuf[48]; unsigned char cidx=0;
float parseF(){ char *p=strchr(cbuf,' '); return p?atof(p+1):0; }
char* parseWordAfter(const char* prefix){
  size_t n=strlen(prefix);
  if(strncmp(cbuf,prefix,n)!=0) return 0;
  char *p=cbuf+n;
  while(*p==' ') p++;
  return *p ? p : 0;
}
uint8_t fcalPumpFromCode(char code){
  if(code=='B') return FCAL_PUMP_BASE;
  if(code=='A') return FCAL_PUMP_ACID;
  if(code=='W') return FCAL_PUMP_WATER;
  return FCAL_PUMP_NONE;
}
char fcalPumpCode(uint8_t pump){
  if(pump==FCAL_PUMP_BASE) return 'B';
  if(pump==FCAL_PUMP_ACID) return 'A';
  if(pump==FCAL_PUMP_WATER) return 'W';
  return '?';
}
const __FlashStringHelper* fcalModeLabel(){
  if(fcalMode==FCAL_MODE_PRIME) return F("PRIME");
  if(fcalMode==FCAL_MODE_RUN) return F("RUN");
  return F("IDLE");
}
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
  if(pump==FCAL_PUMP_ACID) return &ee.flow_a;
  if(pump==FCAL_PUMP_WATER) return &ee.flow_w;
  return &ee.flow_b;
}
float* pumpVolRef(uint8_t pump){
  if(pump==FCAL_PUMP_ACID) return &ee.vol_a;
  if(pump==FCAL_PUMP_WATER) return &ee.vol_w;
  return &ee.vol_b;
}
unsigned long* pumpStartRef(uint8_t pump){
  if(pump==FCAL_PUMP_ACID) return &pumpAst;
  if(pump==FCAL_PUMP_WATER) return &pumpWst;
  return &pumpBst;
}
bool* pumpFlagRef(uint8_t pump){
  if(pump==FCAL_PUMP_ACID) return &pumpA;
  if(pump==FCAL_PUMP_WATER) return &pumpW;
  return &pumpB;
}
void setPumpState(uint8_t pump, bool on){
  uint8_t pin = PUMP_BASE;
  bool *flag = pumpFlagRef(pump);
  unsigned long *startMs = pumpStartRef(pump);
  if(pump==FCAL_PUMP_ACID) pin=PUMP_ACID;
  else if(pump==FCAL_PUMP_WATER) pin=PUMP_WATER;
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
  stopPumpCounted(FCAL_PUMP_BASE);
  stopPumpCounted(FCAL_PUMP_ACID);
  stopPumpCounted(FCAL_PUMP_WATER);
  if(persist && pumpVolumeDirty){
    eeSave();
    pumpVolumeDirty=false;
  }
  pumpStateReport();
}
void stopAllPumpsRaw(){
  setPumpState(FCAL_PUMP_BASE,false);
  setPumpState(FCAL_PUMP_ACID,false);
  setPumpState(FCAL_PUMP_WATER,false);
  pumpStateReport();
}

// 鈹€鈹€ 鑷姩鐘舵€佹満 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
enum RunState { RS_IDLE, RS_TITR, RS_MIX, RS_VFA, RS_DONE };
RunState rstate=RS_IDLE;
unsigned long rs_timer=0;     // 娉佃鏃?娣峰悎璁℃椂 鎴鏃跺埢
unsigned long rs_phaseStart=0;
int rs_doseCount=0;           // 鏈疆婊村姞娆℃暟 (闃叉鏃犻檺寰幆鏈€澶?0娆?
bool rs_isBase=true;          // true=鍔犵⒈, false=鍔犻吀
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
const unsigned long VFA_TOTAL_TIMEOUT_MS = 1000000UL;

// 鏄剧ず缂撳瓨
float dsp_V1=0, dsp_V2=0, dsp_vfa=0, dsp_alk=0;
char dsp_state[16]="IDLE";

// 鈹€鈹€ getPumpDur 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
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
  Serial.print(F("VFA_RAW:")); Serial.print(eeExt.vfa_raw,3);
  Serial.print(F(",ALK_RAW:")); Serial.print(eeExt.alk_raw,3);
  Serial.print(F(",VFA:")); Serial.print(resultVfa(),3);
  Serial.print(F(",ALK:")); Serial.println(resultAlk(),3);
}

void resultStatusReport(){
  Serial.print(F("RSTR:VALID="));
  Serial.print(eeExt.result_valid?1:0);
  Serial.print(F(",KV:"));
  Serial.print(eeExt.kv,6);
  Serial.print(F(",KA:"));
  Serial.print(eeExt.ka,6);
  Serial.print(F(",VFA_RAW:"));
  Serial.print(eeExt.vfa_raw,3);
  Serial.print(F(",ALK_RAW:"));
  Serial.print(eeExt.alk_raw,3);
  Serial.print(F(",VFA:"));
  Serial.print(resultVfa(),3);
  Serial.print(F(",ALK:"));
  Serial.println(resultAlk(),3);
}

bool setResultFactor(char which, float value){
  if(value<0.2 || value>5.0) return false;
  if(which=='V') eeExt.kv=value;
  else eeExt.ka=value;
  resultRecalcAndPersist();
  return true;
}

void setVfaNotice(const char* msg){
  strncpy(vf_notice,msg,sizeof(vf_notice)-1);
  vf_notice[sizeof(vf_notice)-1]=0;
  vf_noticeUntil=millis()+5000;
}

// 鈹€鈹€ 鍋滄鎵€鏈夋车 + 缁撶畻浣撶Н 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
void stopAllPumps(){
  stopAllPumpsCounted(true);
}
void stopAllPumpsUnsaved(){
  stopAllPumpsCounted(false);
}

bool fcalSessionActive(){
  return fcalMode!=FCAL_MODE_IDLE;
}

bool fcalBusy(){
  return fcalSessionActive() || anyPumpRunning() || (rstate!=RS_IDLE);
}

void fcalResetRuntime(){
  fcalMode=FCAL_MODE_IDLE;
  fcalPump=FCAL_PUMP_NONE;
  fcalStartMs=0;
  fcalPlanMs=0;
  fcalHardStopMs=0;
  fcalLastReportMs=0;
  fcalLastWasEarlyStop=false;
}

void fcalStatusReport(){
  Serial.print(F("FCAL:STATE "));
  if(fcalMode==FCAL_MODE_IDLE){
    Serial.println(F("IDLE"));
    return;
  }
  Serial.print(fcalModeLabel());
  Serial.print(F(" PUMP:"));
  Serial.print(fcalPumpCode(fcalPump));
  Serial.print(F(" PLAN_MS:"));
  Serial.print(fcalPlanMs);
  Serial.print(F(" ELAPSED_MS:"));
  Serial.println(millis()-fcalStartMs);
}

void fcalEmitTerminal(const char* eventName, const char* reason){
  unsigned long actualMs = fcalStartMs ? (millis()-fcalStartMs) : 0;
  uint8_t mode = fcalMode;
  stopAllPumpsRaw();
  strncpy(fcalLastReason, reason, sizeof(fcalLastReason)-1);
  fcalLastReason[sizeof(fcalLastReason)-1]=0;
  if(strcmp(eventName,"DONE")==0) strncpy(fcalLastEvent,"DONE",sizeof(fcalLastEvent)-1);
  else if(strcmp(eventName,"STOPPED")==0) strncpy(fcalLastEvent,"STOPPED",sizeof(fcalLastEvent)-1);
  else strncpy(fcalLastEvent,"ABORTED",sizeof(fcalLastEvent)-1);
  fcalLastEvent[sizeof(fcalLastEvent)-1]=0;
  fcalLastActualMs=actualMs;
  fcalLastPlanMs=fcalPlanMs;
  Serial.print(F("FCAL:"));
  Serial.print(eventName);
  Serial.print(F(" PUMP:"));
  Serial.print(fcalPumpCode(fcalPump));
  Serial.print(F(" MODE:"));
  Serial.print(fcalModeLabel());
  Serial.print(F(" PLAN_MS:"));
  Serial.print(fcalPlanMs);
  Serial.print(F(" ACTUAL_MS:"));
  Serial.print(actualMs);
  Serial.print(F(" REASON:"));
  Serial.println(reason);
  if(mode==FCAL_MODE_RUN && (strcmp(eventName,"DONE")==0 || strcmp(eventName,"STOPPED")==0)){
    fcalDoneUntil=millis()+5000UL;
  } else {
    fcalDoneUntil=0;
  }
  fcalResetRuntime();
}

void fcalStart(uint8_t mode, uint8_t pump, unsigned long planMs){
  stopAllPumps();
  fcalMode=mode;
  fcalPump=pump;
  fcalPlanMs=planMs;
  fcalStartMs=millis();
  fcalHardStopMs=fcalStartMs + planMs;
  fcalLastReportMs=0;
  fcalLastWasEarlyStop=false;
  setPumpState(pump,true);
  Serial.print(F("FCAL:START "));
  Serial.print(mode==FCAL_MODE_PRIME ? F("PRIME") : F("RUN"));
  Serial.print(F(" PUMP:"));
  Serial.print(fcalPumpCode(pump));
  Serial.print(F(" PLAN_MS:"));
  Serial.println(planMs);
  fcalStatusReport();
}

void fcalStopByReason(const char* reason){
  if(!fcalSessionActive()) return;
  unsigned long actualMs = fcalStartMs ? (millis()-fcalStartMs) : 0;
  bool isRun = (fcalMode==FCAL_MODE_RUN);
  bool userLike = (strcmp(reason,"USER")==0 || strcmp(reason,"BUTTON")==0);
  bool validEarlyStop = isRun && userLike && actualMs >= FCAL_RUN_MIN_MS;
  if(isRun && strcmp(reason,"BUTTON")==0){
    fcalEmitTerminal("ABORTED", reason);
    return;
  }
  if(isRun && actualMs >= fcalPlanMs && strcmp(reason,"AUTO")==0){
    fcalEmitTerminal("DONE", reason);
  } else if(validEarlyStop || fcalMode==FCAL_MODE_PRIME){
    fcalLastWasEarlyStop = validEarlyStop;
    fcalEmitTerminal("STOPPED", reason);
  } else {
    fcalEmitTerminal("ABORTED", reason);
  }
}

void fcalTick(){
  if(!fcalSessionActive()) return;
  if(millis() - fcalLastReportMs >= 1000){
    fcalLastReportMs = millis();
    fcalStatusReport();
  }
  if(fcalPlanMs && (millis()-fcalStartMs) >= fcalPlanMs){
    fcalStopByReason("AUTO");
  }
}

// 鈹€鈹€ VFA 璁＄畻 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
const float VFA_BLANK_ML = 0.25f;
const float VFA_RESULT_NEG_TOL_MMOL = 0.05f;

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
  float H1=pow(10,-initPH), H2=pow(10,-5.1f), H3=pow(10,-3.5f);
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
  setPumpState(FCAL_PUMP_ACID,true);
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
  if(strcmp(code,"LOW_PH")==0) setVfaNotice("START PH<5.5");
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
  if(millis()-vf_phaseStart<10000) return;
  float avgPH=vf_obsCount?(vf_obsSum/vf_obsCount):curPH;
  if(avgPH<5.5){
    vfaReject("LOW_PH", avgPH);
  } else if((vf_obsMax-vf_obsMin)>0.10){
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

  float target=(vst==V_S1_MIX)?5.1:3.5;
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

// 鈹€鈹€ OLED 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
void updOLED(){
  ol_clear();
  if(fcalSessionActive()){
    ol_cursor(0,0); OL("FLOW CAL");
    ol_cursor(0,2); OL("PUMP:");
    if(fcalPump==FCAL_PUMP_BASE) OL("BASE");
    else if(fcalPump==FCAL_PUMP_ACID) OL("ACID");
    else if(fcalPump==FCAL_PUMP_WATER) OL("WATER");
    ol_cursor(0,4);
    if(fcalMode==FCAL_MODE_PRIME) OL("MODE:PRIME");
    else OL("MODE:RUN");
    OL(" PH:"); ol_printF(curPH,2);
    ol_cursor(0,6); OL("T:");
    ol_printI((millis()-fcalStartMs)/1000);
    OL("/");
    ol_printI(fcalPlanMs/1000);
    OL(" BTN STOP");
    return;
  }
  switch(rstate){
    case RS_IDLE:
      if(fcalDoneUntil>millis()){
        ol_cursor(0,0); OL("FLOW CAL DONE");
        ol_cursor(0,2); OL("PH:"); ol_printF(curPH,2);
        ol_cursor(0,4); OL("T:"); ol_printF(fcalLastActualMs/1000.0,1); OL("S");
        ol_cursor(0,6); OL("ENTER VOL PC");
      } else {
        ol_cursor(0,0); OL("READY. PRESS BTN");
        ol_cursor(0,2); OL("PH:"); ol_printF(curPH,2); OL(" TGT:"); ol_printF(ee.target_ph,1);
        ol_cursor(0,4);
        if(vf_noticeUntil>millis()){
          OL("VFA:");
          ol_print(vf_notice);
        } else {
          OL("VFA:");
          if(eeExt.result_valid) ol_printF(resultVfa(),1); else OL("--.-");
          OL(" ALK:");
          if(eeExt.result_valid) ol_printF(resultAlk(),1); else OL("--.-");
        }
        ol_cursor(0,6); OL("V1:"); ol_printF(ee.vol_b,1); OL(" V2:"); ol_printF(ee.vol_a,1); OL("ML");
      }
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

// 鈹€鈹€ 鐘舵€佹満椹卞姩 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
void startFlow(){
  if(fcalBusy()) return;
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
  if(fcalBusy()) return;
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
  if(rs_doseCount>=20){ stopFlow(); return; }

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

// 鈹€鈹€ 涓插彛鐘舵€佸瓧绗︿覆 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
void printFlowState(){
  if(fcalSessionActive()){
    Serial.println(F("FCAL"));
    return;
  }
  switch(rstate){
    case RS_IDLE: Serial.println(F("IDLE")); return;
    case RS_TITR: Serial.println(F("TITRATION")); return;
    case RS_MIX:  Serial.println(F("MIXING")); return;
    case RS_VFA:  Serial.println(F("VFA")); return;
    case RS_DONE: Serial.println(F("DONE")); return;
  }
  Serial.println(F("?"));
}

// 鈹€鈹€ ORP 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
void ORP_Parse(ORPTypeDef*o);
unsigned int mbCRC(unsigned char*p,int l);
void ORP_Send(unsigned char*d,unsigned char l);
void ORP_Read(unsigned char a);

unsigned long _500ms=0,_10ms=0,_oled=0;
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

// 鈹€鈹€ setup / loop 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
void setup(){
  Serial.begin(115200);
  pinMode(PUMP_BASE,OUTPUT); pinMode(PUMP_ACID,OUTPUT); pinMode(PUMP_WATER,OUTPUT);
  digitalWrite(PUMP_BASE,LOW); digitalWrite(PUMP_ACID,LOW); digitalWrite(PUMP_WATER,LOW);
  pinMode(BTN_PIN,INPUT_PULLUP);
  DL.begin(9600);
  Wire.begin(); ol_init(); ol_clear(); ol_cursor(0,0); OL("ORP PH V10"); delay(300);
  eeLoad();
  Serial.println(F("ORP PH V10 START"));
  resultStatusReport();
  ol_clear();
  updOLED();
}

void loop(){
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
  fcalTick();
  if(rstate==RS_VFA && vst!=V_IDLE && vst!=V_DONE) vfaDoseTick(hasNew);

  // 500ms
  if(millis()-_500ms>=500){ _500ms=millis(); ORP_Read(ORP_ADDR); }

  // ORP鈫扐rduino
  if(DL.available()) ORP_Rx(DL.read());

  // 鎸囦护
  while(Serial.available()){
    char c=Serial.read();
    if(c=='\n'||c=='\r'){
      if(cidx>0){ cbuf[cidx]=0; cidx=0;
        bool busy=fcalBusy();
        if(strcmp(cbuf,"B1")==0){ if(busy) Serial.println(F("ACK:B1 BUSY")); else{ digitalWrite(PUMP_BASE,HIGH); pumpB=true; pumpBst=millis(); Serial.println(F("ACK:B1 OK")); } }
        else if(strcmp(cbuf,"B0")==0){
          if(fcalSessionActive()){
            if(fcalPump==FCAL_PUMP_BASE){ fcalStopByReason("USER"); Serial.println(F("ACK:B0 FCAL")); }
            else Serial.println(F("ACK:B0 BUSY"));
          } else { digitalWrite(PUMP_BASE,LOW); pumpB=false; if(pumpBst>0){ ee.vol_b+=ee.flow_b*(millis()-pumpBst)/1000.0; pumpBst=0; eeSave(); } Serial.println(F("ACK:B0 OK")); }
        }
        else if(strcmp(cbuf,"A1")==0){ if(busy) Serial.println(F("ACK:A1 BUSY")); else{ digitalWrite(PUMP_ACID,HIGH); pumpA=true; pumpAst=millis(); Serial.println(F("ACK:A1 OK")); } }
        else if(strcmp(cbuf,"A0")==0){
          if(fcalSessionActive()){
            if(fcalPump==FCAL_PUMP_ACID){ fcalStopByReason("USER"); Serial.println(F("ACK:A0 FCAL")); }
            else Serial.println(F("ACK:A0 BUSY"));
          } else { digitalWrite(PUMP_ACID,LOW); pumpA=false; if(pumpAst>0){ ee.vol_a+=ee.flow_a*(millis()-pumpAst)/1000.0; pumpAst=0; eeSave(); } Serial.println(F("ACK:A0 OK")); }
        }
        else if(strcmp(cbuf,"W1")==0){ if(busy) Serial.println(F("ACK:W1 BUSY")); else{ digitalWrite(PUMP_WATER,HIGH); pumpW=true; pumpWst=millis(); Serial.println(F("ACK:W1 OK")); } }
        else if(strcmp(cbuf,"W0")==0){
          if(fcalSessionActive()){
            if(fcalPump==FCAL_PUMP_WATER){ fcalStopByReason("USER"); Serial.println(F("ACK:W0 FCAL")); }
            else Serial.println(F("ACK:W0 BUSY"));
          } else { digitalWrite(PUMP_WATER,LOW); pumpW=false; if(pumpWst>0){ ee.vol_w+=ee.flow_w*(millis()-pumpWst)/1000.0; pumpWst=0; eeSave(); } Serial.println(F("ACK:W0 OK")); }
        }
        else if(strncmp(cbuf,"FB ",3)==0){
          if(fcalSessionActive()) Serial.println(F("ERR:FB BUSY"));
          else { ee.flow_b=parseF(); eeSave(); Serial.print(F("ACK:FB ")); Serial.println(ee.flow_b,6); }
        }
        else if(strncmp(cbuf,"FA ",3)==0){
          if(fcalSessionActive()) Serial.println(F("ERR:FA BUSY"));
          else { ee.flow_a=parseF(); eeSave(); Serial.print(F("ACK:FA ")); Serial.println(ee.flow_a,6); }
        }
        else if(strncmp(cbuf,"FW ",3)==0){
          if(fcalSessionActive()) Serial.println(F("ERR:FW BUSY"));
          else { ee.flow_w=parseF(); eeSave(); Serial.print(F("ACK:FW ")); Serial.println(ee.flow_w,6); }
        }
        else if(strncmp(cbuf,"FN ",3)==0){ ee.acid_N=parseF(); eeSave(); Serial.print(F("ACK:FN ")); Serial.println(ee.acid_N,3); }
        else if(strncmp(cbuf,"FS ",3)==0){ ee.sample_ml=parseF(); eeSave(); Serial.print(F("ACK:FS ")); Serial.println(ee.sample_ml,1); }
        else if(strncmp(cbuf,"TT ",3)==0){ ee.target_ph=parseF(); eeSave(); Serial.print(F("ACK:TT ")); Serial.println(ee.target_ph,2); }
        else if(strncmp(cbuf,"TP ",3)==0){ ee.trigger_ph=parseF(); eeSave(); Serial.print(F("ACK:TP ")); Serial.println(ee.trigger_ph,2); }
        else if(strncmp(cbuf,"TL ",3)==0){ ee.tolerance=parseF(); eeSave(); Serial.print(F("ACK:TL ")); Serial.println(ee.tolerance,3); }
        else if(strncmp(cbuf,"TM ",3)==0){ ee.mix_wait=parseF(); eeSave(); Serial.print(F("ACK:TM ")); Serial.println(ee.mix_wait,1); }
        else if(strncmp(cbuf,"TK ",3)==0){ ee.ph_k=parseF(); phFilterPrimed=false; eeSave(); Serial.print(F("ACK:TK ")); Serial.println(ee.ph_k,6); }
        else if(strncmp(cbuf,"TB ",3)==0){ ee.ph_b=parseF(); phFilterPrimed=false; eeSave(); Serial.print(F("ACK:TB ")); Serial.println(ee.ph_b,4); }
        else if(strncmp(cbuf,"TD ",3)==0){ ee.titr_dir=(uint8_t)parseF(); eeSave(); Serial.print(F("ACK:TD ")); Serial.println(ee.titr_dir); }
        else if(strncmp(cbuf,"KV ",3)==0){
          float v=parseF();
          if(setResultFactor('V', v)){ Serial.print(F("ACK:KV ")); Serial.println(eeExt.kv,6); resultStatusReport(); }
          else Serial.println(F("ERR:KV RANGE"));
        }
        else if(strncmp(cbuf,"KA ",3)==0){
          float v=parseF();
          if(setResultFactor('A', v)){ Serial.print(F("ACK:KA ")); Serial.println(eeExt.ka,6); resultStatusReport(); }
          else Serial.println(F("ERR:KA RANGE"));
        }
        else if(strcmp(cbuf,"RV")==0){ Serial.print(F("VOL:")); Serial.print(ee.vol_b,1); Serial.print(','); Serial.print(ee.vol_a,1); Serial.print(','); Serial.println(ee.vol_w,1); }
        else if(strcmp(cbuf,"RR")==0){ resultClearAndPersist(); Serial.println(F("ACK:RR OK")); resultStatusReport(); }
        else if(strcmp(cbuf,"RSTR")==0){ resultStatusReport(); }
        else if(strcmp(cbuf,"RSTVOL")==0){ ee.vol_b=ee.vol_a=ee.vol_w=0; eeSave(); Serial.println(F("ACK:RSTVOL OK")); }
        else if(strcmp(cbuf,"FCAL?")==0){ Serial.println(F("FCAL:CAPS V1 PRIME RUN STOP STATUS")); }
        else if(strcmp(cbuf,"FCAL STATUS")==0){ fcalStatusReport(); }
        else if(strcmp(cbuf,"FCAL STOP")==0){
          if(fcalSessionActive()){ fcalStopByReason("USER"); Serial.println(F("ACK:FCAL STOP")); }
          else Serial.println(F("ACK:FCAL STOP IDLE"));
        }
        else if(strncmp(cbuf,"FCAL PRIME ",11)==0){
          char *arg=parseWordAfter("FCAL PRIME ");
          uint8_t pump = arg ? fcalPumpFromCode(arg[0]) : FCAL_PUMP_NONE;
          if(pump==FCAL_PUMP_NONE) Serial.println(F("ERR:FCAL ARG"));
          else if(fcalBusy()) Serial.println(F("ERR:FCAL BUSY"));
          else { fcalStart(FCAL_MODE_PRIME, pump, FCAL_PRIME_MAX_MS); Serial.println(F("ACK:FCAL PRIME")); }
        }
        else if(strncmp(cbuf,"FCAL RUN ",9)==0){
          char *arg=parseWordAfter("FCAL RUN ");
          if(!arg){ Serial.println(F("ERR:FCAL ARG")); }
          else{
            uint8_t pump = fcalPumpFromCode(arg[0]);
            char *space = strchr(arg,' ');
            long secs = space ? atol(space+1) : 0;
            if(pump==FCAL_PUMP_NONE || secs<3 || secs>120) Serial.println(F("ERR:FCAL RANGE"));
            else if(fcalBusy()) Serial.println(F("ERR:FCAL BUSY"));
            else { fcalStart(FCAL_MODE_RUN, pump, (unsigned long)secs*1000UL); Serial.println(F("ACK:FCAL RUN")); }
          }
        }
        else if(strcmp(cbuf,"VF")==0){
          if(fcalSessionActive() || rstate!=RS_IDLE) Serial.println(F("ACK:VF BUSY"));
          else { startVfaMeasure(); Serial.println(F("ACK:VF OK")); }
        }
        else if(strcmp(cbuf,"VC")==0){
          if(fcalSessionActive()) Serial.println(F("ACK:VC BUSY"));
          else { vfaCancel(); Serial.println(F("ACK:VC OK")); }
        }
        else if(strcmp(cbuf,"START")==0){
          if(busy) Serial.println(F("ACK:START BUSY"));
          else { startFlow(); Serial.println(F("ACK:START OK")); }
        }
        else if(strcmp(cbuf,"STOP")==0){
          if(fcalSessionActive()){ fcalStopByReason("USER"); Serial.println(F("ACK:STOP FCAL")); }
          else { stopFlow(); Serial.println(F("ACK:STOP OK")); }
        }
        else { Serial.print(F("ACK:UNKNOWN ")); Serial.println(cbuf); }
      }
    } else if(cidx<sizeof(cbuf)-1) cbuf[cidx++]=c;
  }

  // 按键
  if(millis()-_btnChk>=50){ _btnChk=millis();
    int b=digitalRead(BTN_PIN);
    if(b==LOW&&_btnLast==HIGH){
      if(fcalSessionActive()) fcalStopByReason("BUTTON");
      else if(rstate==RS_IDLE) startVfaMeasure();
      else if(rstate==RS_DONE){ rstate=RS_IDLE; vst=V_IDLE; Serial.println(F("FLOW:RESET")); }
    }
    _btnLast=b;
  }

  // OLED (1s)
  if(millis()-_oled>=1000){ _oled=millis(); updOLED(); }

  // 10ms 瓒呮椂
  if(millis()-_10ms>=10){ _10ms=millis(); ORP_Timer(); }
}
