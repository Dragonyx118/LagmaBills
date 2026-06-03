import processing.serial.*;

Serial myPort;
int[] pos = {90, 90, 90, 90, 90, 120};
String[] names = {"Vita", "Spalla", "Gomito", "Polso R", "Polso P", "Gripper"};
String logMsg = "In attesa...";
boolean connected = false;

// Layout
int VIZ_W = 200;
int CTRL_X = 220;
int SLIDER_W = 180;
int SLIDER_H = 16;
int[] sliderY = new int[6];

// Lunghezze segmenti braccio (pixel)
float L1 = 60;  // spalla->gomito
float L2 = 55;  // gomito->polso
float L3 = 30;  // polso->gripper

// Animazione fluida
float[] anim = {90, 90, 90, 90, 90, 120};

// Sequenze
String[] seqNames = {"Ciao", "Pick up", "Place", "Saluto", "Apri", "Chiudi"};
int seqStartY = 430;
int homeBtnY   = 395;

void setup() {
  size(500, 630);
  smooth(4);
  textFont(createFont("Monospaced", 12));

  for (int i = 0; i < 6; i++) sliderY[i] = 58 + i * 52;

  println("Porte disponibili:");
  printArray(Serial.list());
  try {
    myPort = new Serial(this, Serial.list()[0], 9600);
    connected = true;
    logMsg = "Connesso: " + Serial.list()[0];
  } catch (Exception e) {
    logMsg = "Nessuna porta. Controlla Serial.list()";
  }
}

void draw() {
  background(240, 240, 237);

  // Animazione fluida
  for (int i = 0; i < 6; i++)
    anim[i] += (pos[i] - anim[i]) * 0.14;

  drawHeader();
  drawArmViz();
  drawSliders();
  drawHomeBtn();
  drawSeqButtons();
  drawLog();
}

// ---- HEADER ----
void drawHeader() {
  fill(29, 158, 117);
  noStroke();
  rect(0, 0, width, 38);
  fill(255);
  textSize(13);
  textAlign(LEFT, CENTER);
  text("Robot Arm Controller  |  ESP32 + PCA9685", 14, 19);
  fill(connected ? color(159, 225, 203) : color(240, 153, 123));
  noStroke();
  ellipse(478, 19, 10, 10);
}

// ---- VISUALIZZAZIONE BRACCIO (forward kinematics 2D) ----
void drawArmViz() {
  // Sfondo pannello
  fill(228, 242, 236);
  noStroke();
  rect(8, 44, VIZ_W - 8, 330, 8);

  // Label
  fill(15, 110, 86);
  textSize(9);
  textAlign(CENTER);
  text("Vista laterale", VIZ_W / 2, 57);

  // Origine base al centro-basso del pannello
  float ox = VIZ_W / 2.0;
  float oy = 355;

  // Angoli (da gradi servo a radianti per disegno)
  // Vita  (anim[0]): rotazione base, in vista laterale non si vede -> ignoriamo
  // Spalla (anim[1]): 90=verticale, 0=avanti orizzontale, 180=indietro
  // Gomito (anim[2]): 90=dritto, 0=piega avanti, 180=piega indietro
  // Polso pitch (anim[4]): inclinazione polso

  float angSpalla = radians(-(anim[1] - 90));       // 90° = su
  float angGomito  = radians(-(anim[2] - 90));       // relativo al segmento precedente
  float angPolso   = radians(-(anim[4] - 90));

  // Punto 1: base -> spalla
  float x1 = ox;
  float y1 = oy - 18;

  // Punto 2: spalla -> gomito
  float dir1 = angSpalla - HALF_PI;
  float x2 = x1 + L1 * cos(dir1);
  float y2 = y1 + L1 * sin(dir1);

  // Punto 3: gomito -> polso
  float dir2 = dir1 + angGomito;
  float x3 = x2 + L2 * cos(dir2);
  float y3 = y2 + L2 * sin(dir2);

  // Punto 4: polso -> gripper
  float dir3 = dir2 + angPolso;
  float x4 = x3 + L3 * cos(dir3);
  float y4 = y3 + L3 * sin(dir3);

  // --- BASE ---
  fill(93, 202, 165);
  noStroke();
  ellipse(ox, oy, 44, 14);
  fill(29, 158, 117);
  rect(ox - 10, oy - 18, 20, 20, 3);

  // --- ROTAZIONE VITA (cerchio sopra base) ---
  float vitaAngle = radians(anim[0] - 90);
  pushMatrix();
  translate(ox, oy - 9);
  rotate(vitaAngle);
  fill(93, 202, 165);
  noStroke();
  ellipse(0, 0, 22, 10);
  popMatrix();

  // --- SEGMENTO SPALLA (braccio superiore) ---
  drawSegment(x1, y1, x2, y2, 12, color(29, 158, 117), color(15, 110, 86));

  // Giunto spalla
  fill(255);
  stroke(29, 158, 117);
  strokeWeight(1.5);
  ellipse(x1, y1, 14, 14);

  // --- SEGMENTO GOMITO (avambraccio) ---
  drawSegment(x2, y2, x3, y3, 10, color(15, 110, 86), color(8, 80, 65));

  // Giunto gomito
  fill(255);
  stroke(15, 110, 86);
  strokeWeight(1.5);
  ellipse(x2, y2, 12, 12);

  // --- SEGMENTO POLSO ---
  drawSegment(x3, y3, x4, y4, 7, color(8, 80, 65), color(4, 52, 44));

  // Giunto polso
  fill(255);
  stroke(8, 80, 65);
  strokeWeight(1.2);
  ellipse(x3, y3, 10, 10);

  // --- GRIPPER ---
  float gripOpen = map(anim[5], 60, 160, 3, 11);
  float perpX = cos(dir3 + HALF_PI);
  float perpY = sin(dir3 + HALF_PI);
  float fwdX  = cos(dir3);
  float fwdY  = sin(dir3);

  // Dita gripper
  strokeWeight(4);
  stroke(4, 52, 44);
  // Dito superiore
  line(x4 + perpX * gripOpen,       y4 + perpY * gripOpen,
       x4 + perpX * gripOpen + fwdX * 14, y4 + perpY * gripOpen + fwdY * 14);
  // Dito inferiore
  line(x4 - perpX * gripOpen,       y4 - perpY * gripOpen,
       x4 - perpX * gripOpen + fwdX * 14, y4 - perpY * gripOpen + fwdY * 14);
  // Palmo
  strokeWeight(3);
  line(x4 + perpX * gripOpen, y4 + perpY * gripOpen,
       x4 - perpX * gripOpen, y4 - perpY * gripOpen);

  // Punta gripper
  fill(4, 52, 44);
  noStroke();
  ellipse(x4, y4, 8, 8);

  // --- COORDINATE XY live ---
  fill(15, 110, 86);
  textSize(9);
  textAlign(LEFT);
  text("x:" + nf(x4 - ox, 1, 0) + "  y:" + nf(oy - y4, 1, 0), 14, 368);
}

// Disegna segmento arrotondato come un "osso"
void drawSegment(float x1, float y1, float x2, float y2, float w, color c1, color c2) {
  float angle = atan2(y2 - y1, x2 - x1);
  float hw = w / 2.0;

  // Corpo
  noStroke();
  fill(c1);
  pushMatrix();
  translate((x1 + x2) / 2, (y1 + y2) / 2);
  rotate(angle);
  float len = dist(x1, y1, x2, y2);
  rect(-len / 2, -hw, len, w, hw);
  popMatrix();

  // Bordo scuro
  stroke(c2);
  strokeWeight(1);
  noFill();
  pushMatrix();
  translate((x1 + x2) / 2, (y1 + y2) / 2);
  rotate(angle);
  float l = dist(x1, y1, x2, y2);
  rect(-l / 2, -hw, l, w, hw);
  popMatrix();
}

// ---- SLIDERS ----
void drawSliders() {
  for (int i = 0; i < 6; i++) {
    int y = sliderY[i];

    // Nome
    fill(50);
    noStroke();
    textSize(11);
    textAlign(LEFT, CENTER);
    text(names[i], CTRL_X, y + 2);

    // Canale badge
    fill(225, 245, 238);
    noStroke();
    rect(CTRL_X + 68, y - 7, 22, 16, 4);
    fill(15, 110, 86);
    textSize(9);
    textAlign(CENTER, CENTER);
    text("C" + i, CTRL_X + 79, y + 1);

    // Track
    fill(210);
    noStroke();
    rect(CTRL_X, y + 16, SLIDER_W, SLIDER_H, SLIDER_H / 2);

    // Fill
    float fw = map(pos[i], 0, 180, 0, SLIDER_W);
    fill(93, 202, 165);
    noStroke();
    rect(CTRL_X, y + 16, fw, SLIDER_H, SLIDER_H / 2);

    // Thumb
    float tx = CTRL_X + fw;
    fill(29, 158, 117);
    noStroke();
    ellipse(tx, y + 16 + SLIDER_H / 2, 20, 20);

    // Valore
    fill(29, 158, 117);
    textSize(12);
    textAlign(RIGHT, CENTER);
    text(pos[i] + "°", 492, y + 16 + SLIDER_H / 2);

    // Pulsanti -5 e +5
    drawMiniBtn(CTRL_X - 52, y + 16, "-", i, false);
    drawMiniBtn(CTRL_X - 27, y + 16, "+", i, true);
  }
}

void drawMiniBtn(int x, int y, String lbl, int ch, boolean plus) {
  boolean ov = mouseX > x && mouseX < x + 22 && mouseY > y && mouseY < y + SLIDER_H;
  fill(ov ? color(29, 158, 117) : color(210, 235, 225));
  stroke(29, 158, 117);
  strokeWeight(0.7);
  rect(x, y, 22, SLIDER_H, 4);
  fill(ov ? 255 : color(10, 90, 70));
  noStroke();
  textSize(14);
  textAlign(CENTER, CENTER);
  text(lbl, x + 11, y + SLIDER_H / 2);
}

// ---- HOME ----
void drawHomeBtn() {
  boolean ov = mouseX > CTRL_X && mouseX < CTRL_X + 200 && mouseY > homeBtnY && mouseY < homeBtnY + 28;
  fill(ov ? color(29, 158, 117) : color(235, 235, 230));
  stroke(160);
  strokeWeight(0.7);
  rect(CTRL_X, homeBtnY, 200, 28, 6);
  fill(ov ? 255 : 50);
  noStroke();
  textSize(11);
  textAlign(CENTER, CENTER);
  text("↩  HOME (tutti a 90°)", CTRL_X + 100, homeBtnY + 14);
}

// ---- SEQUENZE ----
void drawSeqButtons() {
  fill(80);
  noStroke();
  textSize(10);
  textAlign(LEFT);
  text("Sequenze:", CTRL_X, seqStartY - 12);

  int bw = 84, bh = 44, gap = 7;
  for (int i = 0; i < seqNames.length; i++) {
    int col = i % 3, row = i / 3;
    int bx = CTRL_X + col * (bw + gap);
    int by = seqStartY + row * (bh + gap);
    boolean ov = mouseX > bx && mouseX < bx + bw && mouseY > by && mouseY < by + bh;
    fill(ov ? color(93, 202, 165) : color(228, 242, 236));
    stroke(ov ? color(29, 158, 117) : color(180));
    strokeWeight(0.7);
    rect(bx, by, bw, bh, 6);
    fill(ov ? color(4, 52, 44) : color(15, 110, 86));
    noStroke();
    textSize(10);
    textAlign(CENTER, CENTER);
    // Icona testuale semplice
    String[] icons = {"~~>", "/\\", "\\/", "^^", "<>", "><"};
    textSize(9);
    text(icons[i], bx + bw / 2, by + 14);
    textSize(10);
    text(seqNames[i], bx + bw / 2, by + 30);
  }
}

// ---- LOG ----
void drawLog() {
  int ly = 572;
  fill(228, 242, 236);
  stroke(180);
  strokeWeight(0.5);
  rect(8, ly, width - 16, 50, 6);
  fill(15, 110, 86);
  textSize(11);
  textAlign(LEFT, TOP);
  text("→ " + logMsg, 16, ly + 8);
  fill(120);
  textSize(9);
  text("Porta: " + (connected ? Serial.list()[0] : "N/A")
       + "   |   baud: 9600", 16, ly + 28);
}

// ---- MOUSE ----
void mousePressed() {
  // HOME
  if (mouseX > CTRL_X && mouseX < CTRL_X + 200 && mouseY > homeBtnY && mouseY < homeBtnY + 28) {
    goHome(); return;
  }

  // +/- per ogni servo
  for (int i = 0; i < 6; i++) {
    int y = sliderY[i] + 16;
    if (mouseY > y && mouseY < y + SLIDER_H) {
      if (mouseX > CTRL_X - 52 && mouseX < CTRL_X - 30) setServo(i, pos[i] - 5);
      if (mouseX > CTRL_X - 27 && mouseX < CTRL_X - 5) setServo(i, pos[i] + 5);
    }
  }

  // Sequenze
  int bw = 84, bh = 44, gap = 7;
  for (int i = 0; i < seqNames.length; i++) {
    int col = i % 3, row = i / 3;
    int bx = CTRL_X + col * (bw + gap);
    int by = seqStartY + row * (bh + gap);
    if (mouseX > bx && mouseX < bx + bw && mouseY > by && mouseY < by + bh) runSeq(i);
  }
}

void mouseDragged() {
  for (int i = 0; i < 6; i++) {
    int y = sliderY[i] + 16;
    if (mouseY > y - 6 && mouseY < y + SLIDER_H + 6) {
      if (mouseX > CTRL_X - 5 && mouseX < CTRL_X + SLIDER_W + 5) {
        setServo(i, (int) map(mouseX, CTRL_X, CTRL_X + SLIDER_W, 0, 180));
      }
    }
  }
}

// ---- COMANDI ----
void setServo(int ch, int val) {
  val = constrain(val, 0, 180);
  pos[ch] = val;
  String cmd = "C" + ch + "=" + val + "\n";
  if (connected) myPort.write(cmd);
  logMsg = cmd.trim();
}

void goHome() {
  int[] def = {90, 90, 90, 90, 90, 120};
  for (int i = 0; i < 6; i++) { setServo(i, def[i]); delay(25); }
  logMsg = "HOME";
}

void runSeq(int idx) {
  int[][][] seqs = {
    {{0,90,0},{1,55,0},{2,45,0},{4,45,0},{5,90,0},
     {3,0,400},{3,180,800},{3,0,1200},{3,180,1600},{3,90,2000}},
    {{5,160,0},{1,130,0},{2,30,400},{5,90,900},{1,60,1300},{2,90,1700}},
    {{0,135,0},{1,90,0},{2,45,400},{5,150,900},{0,90,1300}},
    {{1,45,0},{2,45,0},{4,45,400},{4,135,900},{4,45,1400},{4,90,1800}},
    {{5,160,0}},
    {{5,60,0}}
  };
  logMsg = "Seq: " + seqNames[idx];
  final int[][] steps = seqs[idx];
  new Thread(new Runnable() {
    public void run() {
      for (int[] s : steps) {
        try { Thread.sleep(s[2]); } catch (Exception e) {}
        setServo(s[0], s[1]);
      }
    }
  }).start();
}
