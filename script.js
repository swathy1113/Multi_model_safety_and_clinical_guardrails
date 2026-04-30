const API = "http://127.0.0.1:8000";
const WS  = "ws://127.0.0.1:8000/ws/reminders";

let patientsMap = {};
let lastMedData = null;
let medStats    = { total: 0, safe: 0, warn: 0 };
let currentUser = null;

// ── Boot ──────────────────────────────────────────────────────────
window.onload = () => {
  // Auth check — redirect to login if not signed in
  const token = localStorage.getItem("ms_token");
  if (!token) {
    // Redirect to login — works whether using Live Server or file://
    const base = window.location.href.replace(/[^/]*$/, "");
    window.location.href = base + "login.html";
    return;
  }

  // Load user info into header
  currentUser = {
    token:    token,
    username: localStorage.getItem("ms_username") || "",
    name:     localStorage.getItem("ms_fullname")  || "User",
    role:     localStorage.getItem("ms_role")      || "carer"
  };
  renderUserHeader();

  // Show/hide admin schedule section based on role
  const isPrivileged = ["admin","doctor"].includes(currentUser.role);
  const adminSec = document.getElementById("adminScheduleSection");
  if (adminSec) adminSec.style.display = isPrivileged ? "block" : "none";

  loadPatients();
  connectWS();
  if (Notification?.permission === "default") Notification.requestPermission();
  loadMedTimes();
  setupDrags();
};

// ── Diagnostic: fetch patients and show count inline ──────────────
async function loadPatients() {
  try {
    const res = await fetch(`${API}/patients`);
    console.log("[loadPatients] status:", res.status);
    if (!res.ok) {
      console.error(`[loadPatients] HTTP ${res.status}:`, await res.text());
      showPatientError(`Server returned ${res.status}`);
      return 0;
    }
    const d = await res.json();
    const patients = d.patients || [];
    console.log(`[loadPatients] Got ${patients.length} patients:`, patients.map(p=>p.name));

    if (patients.length === 0) {
      showPatientError("No patients found in database — check http://127.0.0.1:8000/debug/db");
      return 0;
    }

    ["med-patient","nut-patient","wound-patient","rem-patient"].forEach(id => {
      const s = document.getElementById(id); if (!s) return;
      s.innerHTML = '<option value="" disabled selected>Choose a patient...</option>';
      patients.forEach(p => {
        const o = document.createElement("option");
        o.value = p.name; o.textContent = p.name;
        s.appendChild(o);
      });
    });

    const countEl = document.getElementById("patientCount");
    if (countEl) countEl.textContent = `${patients.length} patients`;
    patients.forEach(p => patientsMap[p.name] = p);
    fillPatientsTable(patients);
    return patients.length;

  } catch(e) {
    console.error("[loadPatients] Error:", e);
    showPatientError("Cannot reach server — is backend running on port 8000?");
    return 0;
  }
}

function showPatientError(msg) {
  const existing = document.getElementById("_patientErr");
  if (existing) existing.remove();
  const banner = document.createElement("div");
  banner.id = "_patientErr";
  banner.style.cssText = "position:fixed;top:0;left:0;right:0;z-index:9999;background:#FEF2F2;border-bottom:2px solid #FECACA;padding:10px 20px;font-size:.83rem;font-weight:700;color:#DC2626;display:flex;justify-content:space-between;align-items:center;gap:12px";
  banner.innerHTML = `<span>⚠ ${msg}</span><a href="http://127.0.0.1:8000/debug/db" target="_blank" style="color:#DC2626;white-space:nowrap;text-decoration:underline">Open DB debug →</a><button onclick="this.parentElement.remove()" style="background:none;border:none;cursor:pointer;font-size:1.1rem;color:#DC2626;flex-shrink:0">✕</button>`;
  document.body.prepend(banner);
}

function renderUserHeader() {
  const initials = currentUser.name.split(" ").map(w=>w[0]).join("").toUpperCase().slice(0,2);
  document.getElementById("userAvatar").textContent = initials;
  document.getElementById("userName").textContent   = currentUser.name;
  const roleLabels = { admin:"Administrator", doctor:"Doctor", carer:"Carer" };
  document.getElementById("userRole").textContent   = roleLabels[currentUser.role] || currentUser.role;
}

function authHeaders() {
  const token = currentUser?.token || localStorage.getItem("ms_token") || "";
  return { "Authorization": `Bearer ${token}` };
}

async function doLogout() {
  try {
    await fetch(`${API}/auth/logout`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" }
    });
  } catch(_) {}
  localStorage.clear();
  const base = window.location.href.replace(/[^/]*$/, "");
  window.location.href = base + "login.html";
}

// ── Tab switching ─────────────────────────────────────────────────
function switchTab(name) {
  ["medication","hazard","monitor","reminders"].forEach(t => {
    document.getElementById(`page-${t}`)?.classList.toggle("active", t === name);
    document.getElementById(`page-${t}`)?.classList.toggle("hidden",  t !== name);
    document.getElementById(`tab-${t}`)?.classList.toggle("active",   t === name);
  });
}

function switchMonitorTab(name) {
  ["nutrition","wound"].forEach(t => {
    document.getElementById(`monitor-${t}`)?.classList.toggle("hidden", t !== name);
    document.getElementById(`stab-${t}`)?.classList.toggle("active",    t === name);
  });
}

// ── WebSocket ─────────────────────────────────────────────────────
function connectWS() {
  try {
    const ws = new WebSocket(WS);
    ws.onopen  = () => setInterval(() => ws.readyState===1 && ws.send("ping"), 30000);
    ws.onmessage = e => { const d=JSON.parse(e.data); if(d.type==="reminder") showReminderBanner(d.message); };
    ws.onclose = () => setTimeout(connectWS, 5000);
    ws.onerror = () => {};
  } catch(_) {}
}

function showReminderBanner(msg) {
  if (Notification?.permission==="granted") new Notification("Medication Reminder", {body:msg, requireInteraction:true});
  const b=document.getElementById("reminderBanner"), t=document.getElementById("reminderText");
  if(b&&t){t.textContent=msg;b.classList.remove("hidden");setTimeout(()=>b.classList.add("hidden"),30000);}
  addReminderLog(msg);
  playChime();
}
function addReminderLog(msg){
  const log=document.getElementById("reminderLog"); if(!log) return;
  const d=document.createElement("div"); d.className="rl-item";
  d.innerHTML=`<span class="rl-time">${new Date().toLocaleTimeString()}</span><span class="rl-msg">${msg}</span>`;
  log.prepend(d); log.classList.remove("hidden");
}
function dismissReminder(){ document.getElementById("reminderBanner").classList.add("hidden"); }
function playChime(){
  try{
    const ctx=new(window.AudioContext||window.webkitAudioContext)();
    [523,659,784].forEach((f,i)=>{const o=ctx.createOscillator(),g=ctx.createGain();o.connect(g);g.connect(ctx.destination);o.frequency.value=f;o.type="sine";g.gain.setValueAtTime(.25,ctx.currentTime+i*.15);g.gain.exponentialRampToValueAtTime(.001,ctx.currentTime+i*.15+.28);o.start(ctx.currentTime+i*.15);o.stop(ctx.currentTime+i*.15+.28);});
  }catch(_){}
}

function onMedPatientChange() {
  const sel = document.getElementById("med-patient");
  const p   = patientsMap[sel.value]; if(!p) return;
  const init = p.name.split(" ").map(w=>w[0]).join("").toUpperCase().slice(0,2);
  document.getElementById("medPatientAvatar").textContent   = init;
  document.getElementById("medPatientName").textContent     = p.name;
  document.getElementById("medPatientCond").textContent     = p.condition || "";
  document.getElementById("medPatientChip").classList.remove("hidden");
}

function fillPatientsTable(list) {
  const tb = document.getElementById("patientsBody"); tb.innerHTML = "";
  list.forEach(p => {
    const tr = document.createElement("tr");
    let meds = parseMeds(String(p.care_plan||""));
    const pills = meds.map(m=>`<span class="med-pill">${m}</span>`).join(" ") || "—";
    tr.innerHTML = `<td>${p.name||"—"}</td><td>${p.condition||"—"}</td><td>${pills}</td>`;
    tb.appendChild(tr);
  });
}

function parseMeds(cp) {
  if (!cp || cp.trim() === "") return [];

  // Try JSON parse first
  try {
    const fixed = cp.replace(/'/g, '"');
    const parsed = JSON.parse(fixed);
    if (parsed.medications) return parsed.medications.map(m => `${m.name} ${m.dosage}`.trim());
    if (Array.isArray(parsed)) return parsed.map(m => typeof m === "object" ? `${m.name||""} ${m.dosage||""}`.trim() : String(m));
  } catch(e) {}

  // Plain text fallback — "Metformin 500mg, Aspirin 75mg"
  return cp.split(",").map(s => s.trim()).filter(Boolean);
}

// ── File preview ──────────────────────────────────────────────────
function previewFile(inputId, previewId, hintId) {
  const file = document.getElementById(inputId).files[0]; if(!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    document.getElementById(previewId).src = e.target.result;
    document.getElementById(previewId).classList.remove("hidden");
    document.getElementById(hintId).classList.add("hidden");
  };
  reader.readAsDataURL(file);
}

function setupDrags() {
  [["medUpload","medFile","medPreview","medUploadHint"],
   ["hazUpload","hazFile","hazPreview","hazUploadHint"]].forEach(([zoneId, fileId, previewId, hintId]) => {
    const z = document.getElementById(zoneId); if(!z) return;
    z.addEventListener("dragover", e=>{e.preventDefault();z.style.borderColor="var(--sky)"});
    z.addEventListener("dragleave",()=>z.style.borderColor="");
    z.addEventListener("drop", e=>{
      e.preventDefault(); z.style.borderColor="";
      const f=e.dataTransfer.files[0]; if(!f?.type.startsWith("image/")) return;
      const dt=new DataTransfer(); dt.items.add(f);
      document.getElementById(fileId).files = dt.files;
      previewFile(fileId, previewId, hintId);
    });
  });
}

// ── Helpers ───────────────────────────────────────────────────────
function btnState(btnId, spinId, loading) {
  const btn=document.getElementById(btnId); if(btn) btn.disabled=loading;
  document.getElementById(btnId.replace("Btn","BtnLabel"))?.classList.toggle("hidden",  loading);
  document.getElementById(btnId.replace("Btn","BtnSpin"))?.classList.toggle("hidden",  !loading);
}
function show(id){document.getElementById(id)?.classList.remove("hidden")}
function hide(id){document.getElementById(id)?.classList.add("hidden")}
function toast(msg,type="success"){
  document.getElementById("_t")?.remove();
  const t=document.createElement("div");t.id="_t";t.className=`toast ${type}`;t.textContent=msg;
  document.body.appendChild(t);setTimeout(()=>t.remove(),4000);
}
function animateSteps(ids){
  let i=0; const iv=setInterval(()=>{
    if(i>0){document.getElementById(ids[i-1])?.classList.remove("active");document.getElementById(ids[i-1])?.classList.add("done");}
    if(i<ids.length){document.getElementById(ids[i])?.classList.add("active");i++;}
    else clearInterval(iv);
  },900);
}

// ── STATUS CARD BUILDER ───────────────────────────────────────────
function makeStatusCard(cls, icon, title, msg) {
  return `<div class="status-card ${cls}"><div class="sc-icon">${icon}</div><div><div class="sc-title">${title}</div><div class="sc-msg">${msg}</div></div></div>`;
}

// ══════════════════════════════════════════════════════════════════
//  TAB 1: MEDICATION CHECK
// ══════════════════════════════════════════════════════════════════
async function runMedCheck() {
  const file        = document.getElementById("medFile").files[0];
  const patientName = document.getElementById("med-patient").value;
  if (!file || !patientName) { toast("Please choose a patient and upload a photo first.", "warn"); return; }

  btnState("medCheckBtn","medCheckBtnSpin",true);
  hide("medIdle"); hide("medResult");
  show("medScanning");
  animateSteps(["ms1","ms2","ms3"]);

  const form = new FormData();
  form.append("file", file); form.append("patient_name", patientName);

  try {
    const res  = await fetch(`${API}/verify`, {method:"POST", body:form, headers: authHeaders()});
    const data = await res.json();
    if (!res.ok) { renderMedError(data.detail || `Server error ${res.status}`); return; }
    lastMedData = data;
    hide("medScanning");
    renderMedResult(data);
    updateMedStats(data.status);
  } catch(e) {
    hide("medScanning");
    renderMedError("Could not reach the server. Please make sure the backend is running.");
    console.error("[Med check error]", e);
  } finally {
    btnState("medCheckBtn","medCheckBtnSpin",false);
  }
}

function renderMedResult(data) {
  show("medResult");
  hide("medConsult"); hide("medDoctorBox");
  const status = (data.status||"").trim().toUpperCase();

  // Clean detected text
  let det = "";
  if (data.ocr_text) {
    const lines = data.ocr_text.split("\n");
    const line  = lines.find(l=>l.toLowerCase().startsWith("detected:"));
    if (line) det = "Found on packaging: " + line.replace(/^detected:\s*/i,"").trim();
  }
  document.getElementById("medDetected").textContent = det;

  const card = document.getElementById("medStatusCard");

  if (status === "SAFE") {
    card.innerHTML = makeStatusCard("safe","✓","Safe to give","This medicine matches the patient's prescription. It is safe to administer.");
    updateMedStats("SAFE");
  } else if (status === "WARNING") {
    card.innerHTML = makeStatusCard("warning","!","This medicine doesn't match the prescription","This medicine does not match what is on the patient's care plan.");
    const med = det.replace("Found on packaging: ","").trim() || "this medicine";
    document.getElementById("medConsultQ").textContent = `Did the doctor prescribe ${med} for this patient?`;
    show("medConsult");
    playChime();
  } else if (status === "UNREGISTERED") {
    card.innerHTML = makeStatusCard("amber","?","Not in care plan","This medicine is not listed in the patient's current care plan.");
    const med = det.replace("Found on packaging: ","").trim() || "this medicine";
    document.getElementById("medConsultQ").textContent = `Did the doctor prescribe ${med} for this patient?`;
    show("medConsult");
  } else if (status === "NO_CARE_PLAN") {
    card.innerHTML = makeStatusCard("purple","i","No care plan on record","This patient has no care plan. Please contact the doctor or administrator.");
    showMedDoctorBox("danger","Action needed","Please ask the doctor or admin to set up a care plan before giving any medicine.",false);
  } else {
    card.innerHTML = makeStatusCard("warning","!","Something went wrong","Please try again.");
  }
}

function renderMedError(msg) {
  show("medResult"); hide("medConsult"); hide("medDoctorBox");
  document.getElementById("medStatusCard").innerHTML = makeStatusCard("warning","!","Could not check","There was a problem. Please try again.");
  document.getElementById("medDetected").textContent = "";
  console.error(msg);
}

function medConsultNo() {
  hide("medConsult");
  document.getElementById("medStatusCard").innerHTML = makeStatusCard("warning","!","Do NOT give this medicine","This medicine has not been confirmed by a doctor. Do not administer it. Return it and contact the doctor immediately.");
  showMedDoctorBox("danger","⚠ Do not administer","Return this medicine and contact the doctor before giving anything to the patient.",false);
  playChime();
  updateMedStats("WARNING");
}

function medConsultYes() {
  hide("medConsult");
  document.getElementById("medStatusCard").innerHTML = makeStatusCard("amber","✓","Doctor confirmed — update the record","You confirmed the doctor prescribed this. Safe to give now — please update the patient's care plan.");
  const alertMsg = lastMedData?.doctor_alert || "Add this medicine to the patient's care plan so future scans recognise it.";
  showMedDoctorBox("warn","Update patient record", alertMsg, true);
  updateMedStats("SAFE");
}

function showMedDoctorBox(type, head, msg, showUpdate) {
  const box = document.getElementById("medDoctorBox");
  box.className = `doctor-box ${type}`;
  box.innerHTML = `<div class="db-head">${head}</div><div class="db-msg">${msg}</div>` +
    (showUpdate ? `<button class="open-update" onclick="openMedUpdate()">Update care plan</button><div class="update-note">Safe to give — please update the record when you can.</div>` : "");
  show("medDoctorBox");
}

function openMedUpdate() {
  const patientName = document.getElementById("med-patient").value;
  const box = document.getElementById("medDoctorBox");
  const existing = box.querySelector(".open-update");
  if (existing) existing.remove();
  const note = box.querySelector(".update-note");
  if (note) note.remove();
  const form = document.createElement("div");
  form.className = "update-form";
  form.innerHTML = `
    <input id="_upd" type="text" class="update-input" placeholder="e.g. Aspirin 75mg"
      onkeydown="if(event.key==='Enter') saveMedPlan('${patientName}')"/>
    <button class="update-save" onclick="saveMedPlan('${patientName}')">Save</button>
    <button class="update-cancel" onclick="this.parentElement.remove();openMedUpdate()">Cancel</button>`;
  box.appendChild(form);
  setTimeout(()=>document.getElementById("_upd")?.focus(),40);
}

async function saveMedPlan(patientName) {
  const input = document.getElementById("_upd"); if(!input) return;
  const med   = input.value.trim(); if(!med){input.style.borderColor="#EF4444";return;}
  input.disabled=true;
  try {
    const res  = await fetch(`${API}/update_care_plan`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({patient_name:patientName,new_medicine:med})});
    const data = await res.json();
    if(!res.ok||data.detail||data.error){toast("Could not save: "+(data.detail||data.error),"warn");input.disabled=false;return;}
    const box = document.getElementById("medDoctorBox");
    box.className="doctor-box success";
    box.innerHTML=`<div class="db-head">Care plan updated</div><div class="db-msg">New care plan: ${data.care_plan}<br/><small style="color:#15803D;font-size:.78rem;">Next scan of this medicine will show as safe.</small></div>`;
    toast("Care plan updated!","success");
    loadPatients();
  } catch(_){toast("Server error. Please try again.","warn");input.disabled=false;}
}

function resetMed() {
  ["medResult","medConsult","medDoctorBox"].forEach(id=>hide(id));
  show("medIdle");
  ["ms1","ms2","ms3"].forEach(id=>document.getElementById(id)?.classList.remove("active","done"));
  document.getElementById("medFile").value="";
  document.getElementById("medPreview").classList.add("hidden");
  document.getElementById("medUploadHint").classList.remove("hidden");
  document.getElementById("med-patient").value="";
  document.getElementById("medPatientChip").classList.add("hidden");
  lastMedData=null;
}

function updateMedStats(status){
  medStats.total++;
  if(status==="SAFE") medStats.safe++; else medStats.warn++;
  document.getElementById("totalChecks").textContent=medStats.total;
  document.getElementById("safeCount").textContent=medStats.safe;
  document.getElementById("warnCount").textContent=medStats.warn;
}

// ══════════════════════════════════════════════════════════════════
//  TAB 2: HAZARD CHECK
// ══════════════════════════════════════════════════════════════════
async function runHazardCheck() {
  const file = document.getElementById("hazFile").files[0];
  if (!file) { toast("Please upload a photo of the room first.", "warn"); return; }

  const btn = document.getElementById("hazBtn"); btn.disabled=true;
  document.getElementById("hazBtnLabel").classList.add("hidden");
  document.getElementById("hazBtnSpin").classList.remove("hidden");
  hide("hazIdle"); hide("hazResult"); show("hazScanning");

  const form = new FormData(); form.append("file", file);

  try {
    const res  = await fetch(`${API}/scan_hazards`, { method: "POST", body: form, headers: authHeaders() });
    const data = await res.json();
    if (!res.ok) {
      hide("hazScanning");
      document.getElementById("hazStatusCard").innerHTML = makeStatusCard("warning","!","Could not scan", data.detail || "Server error. Please try again.");
      show("hazResult"); return;
    }
    hide("hazScanning");
    renderHazardResult(data);
  } catch(_) {
    hide("hazScanning");
    document.getElementById("hazStatusCard").innerHTML = makeStatusCard("warning","!","Could not scan","There was a problem. Please try again.");
    show("hazResult");
  } finally {
    btn.disabled=false;
    document.getElementById("hazBtnLabel").classList.remove("hidden");
    document.getElementById("hazBtnSpin").classList.add("hidden");
  }
}

function renderHazardResult(data) {
  show("hazResult");
  const risk = (data.risk_level || "MEDIUM").toUpperCase();
  console.log("[Hazard result full]", JSON.stringify(data));

  // Status card
  const card = document.getElementById("hazStatusCard");
  const cfgs = {
    LOW:    { cls:"safe",    icon:"✓", title:"Environment looks safe",       msg: data.summary || "No significant hazards detected." },
    MEDIUM: { cls:"amber",  icon:"⚠", title:"Some concerns noted",           msg: data.summary || "Please review the identified items." },
    HIGH:   { cls:"warning",icon:"!", title:"Hazards found — action needed", msg: data.summary || "Please address these hazards immediately." }
  };
  const cfg = cfgs[risk] || cfgs.MEDIUM;
  card.innerHTML = makeStatusCard(cfg.cls, cfg.icon, cfg.title, cfg.msg);

  // ── Normalise hazards: handle both new (array) and old (comma string) formats ──
  let hazards = [];
  if (Array.isArray(data.hazards) && data.hazards.length > 0) {
    hazards = data.hazards;
  } else if (data.hazards_raw && data.hazards_raw.toLowerCase() !== "none detected") {
    hazards = data.hazards_raw.split(",").map(h => h.trim()).filter(Boolean);
  }

  let recs = [];
  if (Array.isArray(data.recommendations) && data.recommendations.length > 0) {
    recs = data.recommendations;
  } else if (data.recs_raw && data.recs_raw.toLowerCase() !== "no action needed") {
    recs = data.recs_raw.split(",").map(r => r.trim()).filter(Boolean);
  }

  // Alert message — use data.alert, or derive from summary for MEDIUM/HIGH
  const alertMsg = data.alert || (risk !== "LOW" ? data.summary : null);

  // Alert banner
  const alertBox = document.getElementById("hazAlertBox");
  if (alertBox && alertMsg && risk !== "LOW") {
    const prefix = risk === "HIGH" ? "🚨 <strong>Immediate action needed:</strong>" : "⚠️ <strong>Action needed:</strong>";
    alertBox.innerHTML = `${prefix} ${alertMsg}`;
    alertBox.className = `haz-alert haz-alert-${risk === "HIGH" ? "high" : "medium"}`;
    alertBox.classList.remove("hidden");
    if (risk === "HIGH") playChime();
  } else if (alertBox) {
    alertBox.classList.add("hidden");
  }

  // Hazards list
  const hazBox     = document.getElementById("hazHazardsList");
  const hazContent = document.getElementById("hazHazardsContent");
  if (hazards.length > 0) {
    hazContent.innerHTML = hazards.map((h, i) =>
      `<div class="haz-item"><span class="haz-num">${i + 1}</span><span class="haz-text">${h}</span></div>`
    ).join("");
    hazBox.classList.remove("hidden");
  } else {
    hazBox.classList.add("hidden");
  }

  // Recommendations list
  const recBox     = document.getElementById("hazRecsList");
  const recContent = document.getElementById("hazRecsContent");
  if (recs.length > 0) {
    recContent.innerHTML = recs.map((r, i) =>
      `<div class="haz-action"><span class="haz-action-num">${i + 1}</span><span class="haz-text">${r}</span></div>`
    ).join("");
    recBox.classList.remove("hidden");
  } else {
    recBox.classList.add("hidden");
  }

  addHazardLog(risk, data.summary || alertMsg || "");
}

function addHazardLog(risk, summary) {
  const tb = document.getElementById("hazLog");
  if (tb.querySelector(".empty-row")) tb.innerHTML="";
  const tr = document.createElement("tr");
  const riskBadge = `<span class="risk-${risk.toLowerCase()}">${risk}</span>`;
  tr.innerHTML = `<td>${new Date().toLocaleTimeString()}</td><td>${riskBadge}</td><td>${summary}</td>`;
  tb.prepend(tr);
}

function resetHaz() {
  hide("hazResult"); show("hazIdle");
  document.getElementById("hazFile").value="";
  document.getElementById("hazPreview").classList.add("hidden");
  document.getElementById("hazUploadHint").classList.remove("hidden");
}

// ══════════════════════════════════════════════════════════════════
//  TAB 3a: NUTRITION — before + after comparison
// ══════════════════════════════════════════════════════════════════
async function runNutritionCheck() {
  const beforeFile  = document.getElementById("nutBeforeFile").files[0];
  const afterFile   = document.getElementById("nutAfterFile").files[0];
  const patientName = document.getElementById("nut-patient").value;
  const mealType    = document.getElementById("nut-mealtype").value;

  if (!beforeFile) { toast("Please upload the before meal photo.", "warn"); return; }
  if (!afterFile)  { toast("Please upload the after meal photo.", "warn");  return; }

  const btn = document.getElementById("nutBtn"); btn.disabled = true;
  document.getElementById("nutBtnLabel").classList.add("hidden");
  document.getElementById("nutBtnSpin").classList.remove("hidden");
  hide("nutIdle"); hide("nutResult"); show("nutScanning");

  const form = new FormData();
  form.append("before_file",  beforeFile);
  form.append("after_file",   afterFile);
  form.append("meal_type",    mealType);
  form.append("patient_name", patientName || "");

  try {
    const res  = await fetch(`${API}/analyse_nutrition`, { method: "POST", body: form, headers: authHeaders() });
    const data = await res.json();
    if (!res.ok) {
      hide("nutScanning");
      document.getElementById("nutStatusCard").innerHTML = makeStatusCard("warning","!","Could not analyse", data.detail || "Server error. Please try again.");
      show("nutResult"); return;
    }
    hide("nutScanning");
    renderNutritionResult(data);
    addMonitorLog(patientName || "Patient", "Nutrition", `${data.percent ?? 0}% consumed`);
  } catch(e) {
    hide("nutScanning");
    document.getElementById("nutStatusCard").innerHTML = makeStatusCard("warning","!","Could not analyse","Cannot reach server. Please check the backend is running.");
    show("nutResult");
    console.error("[Nutrition error]", e);
  } finally {
    btn.disabled = false;
    document.getElementById("nutBtnLabel").classList.remove("hidden");
    document.getElementById("nutBtnSpin").classList.add("hidden");
  }
}

function renderNutritionResult(data) {
  show("nutResult");
  const pct    = data.percent ?? 0;
  const status = (data.status || "Low").toLowerCase().replace(" ", "_");

  const configs = {
    good:     { cls:"safe",    icon:"✓", title:"Good intake",    msg:`The patient ate well — approximately ${pct}% of the meal was consumed.` },
    low:      { cls:"amber",   icon:"⚠", title:"Low intake",     msg:`Only about ${pct}% of the meal was consumed. Please monitor and offer alternatives.` },
    very_low: { cls:"warning", icon:"!", title:"Very low intake", msg:`Only ${pct}% consumed. Please inform the nurse — the patient may need support with eating.` }
  };
  const cfg = configs[status] || configs.low;
  document.getElementById("nutStatusCard").innerHTML = makeStatusCard(cfg.cls, cfg.icon, cfg.title, cfg.msg);

  const barClass = status === "good" ? "good" : status === "very_low" ? "very_low" : "low";
  const pctColor = status === "good" ? "var(--green)" : status === "very_low" ? "var(--red)" : "var(--amber)";

  document.getElementById("nutProgress").innerHTML = `
    <div class="progress-section">
      <div class="progress-percent" style="color:${pctColor}">${pct}%</div>
      <div class="progress-label">of meal consumed</div>
      <div class="progress-bar-wrap">
        <div class="progress-bar ${barClass}" style="width:${pct}%"></div>
      </div>
    </div>`;

  let details = "";
  if (data.item_breakdown)        details += `<div class="detail-row"><span class="detail-lbl">Breakdown</span><span class="detail-val" style="font-weight:700">${data.item_breakdown}</span></div>`;
  if (data.foods_served?.length)  details += `<div class="detail-row"><span class="detail-lbl">Served</span><span class="detail-val">${data.foods_served.join(", ")}</span></div>`;
  if (data.foods_left?.length)    details += `<div class="detail-row"><span class="detail-lbl">Left on plate</span><span class="detail-val">${data.foods_left.join(", ")}</span></div>`;
  if (data.observations)          details += `<div class="detail-row"><span class="detail-lbl">Observation</span><span class="detail-val">${data.observations}</span></div>`;
  if (data.alert && data.alert !== "No concerns") details += `<div class="detail-row"><span class="detail-lbl">Alert</span><span class="detail-val" style="color:var(--red);font-weight:700">${data.alert}</span></div>`;

  document.getElementById("nutDetails").innerHTML = details ? `<div class="details-box">${details}</div>` : "";
}

function resetNut() {
  hide("nutResult"); show("nutIdle");
  ["nutBeforeFile","nutAfterFile"].forEach(id => { document.getElementById(id).value = ""; });
  ["nutBeforePreview","nutAfterPreview"].forEach(id => { document.getElementById(id).classList.add("hidden"); document.getElementById(id).src = ""; });
  ["nutBeforeHint","nutAfterHint"].forEach(id => { document.getElementById(id).classList.remove("hidden"); });
}

// ══════════════════════════════════════════════════════════════════
//  TAB 3b: WOUND — auto-compare with DB previous image
// ══════════════════════════════════════════════════════════════════

async function loadWoundHistory() {
  const patientName = document.getElementById("wound-patient").value;
  if (!patientName) return;

  try {
    // Use query param instead of path segment to avoid URL encoding issues
    const res  = await fetch(`${API}/wound_history?patient_name=${encodeURIComponent(patientName)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    const prevBox  = document.getElementById("prevWoundInfo");
    const noneBox  = document.getElementById("noWoundHistory");
    const prevDate = document.getElementById("prevWoundDate");

    if (data.records && data.records.length > 0) {
      prevDate.textContent = `Last saved: ${data.records[0].recorded_at}`;
      prevBox.classList.remove("hidden");
      noneBox.classList.add("hidden");
    } else {
      prevBox.classList.add("hidden");
      noneBox.classList.remove("hidden");
    }
  } catch(e) {
    console.log("[Wound history]", e);
    document.getElementById("prevWoundInfo").classList.add("hidden");
    document.getElementById("noWoundHistory").classList.remove("hidden");
  }
}

async function runWoundCheck() {
  const currentFile = document.getElementById("woundFile").files[0];
  const prevFile    = document.getElementById("woundPrevFile").files[0];
  const patientName = document.getElementById("wound-patient").value;
  const notes       = document.getElementById("wound-notes").value.trim();

  if (!currentFile)  { toast("Please upload today's wound photo.", "warn");  return; }
  if (!patientName)  { toast("Please select a patient first.", "warn");       return; }

  const btn = document.getElementById("woundBtn"); btn.disabled = true;
  document.getElementById("woundBtnLabel").classList.add("hidden");
  document.getElementById("woundBtnSpin").classList.remove("hidden");
  hide("woundIdle"); hide("woundResult"); show("woundScanning");

  const form = new FormData();
  form.append("current_file",  currentFile);
  form.append("patient_name",  patientName);
  form.append("notes",         notes);
  if (prevFile) {
    form.append("previous_file", prevFile);
    console.log("[Wound] Sending manual previous photo:", prevFile.name);
  } else {
    console.log("[Wound] No manual previous photo — backend will check DB");
  }

  try {
    const res  = await fetch(`${API}/analyse_wound`, { method: "POST", body: form, headers: authHeaders() });
    const data = await res.json();
    if (!res.ok) {
      hide("woundScanning");
      document.getElementById("woundStatusCard").innerHTML = makeStatusCard("warning","!","Could not assess", data.detail || "Server error. Please try again.");
      show("woundResult"); return;
    }
    console.log("[Wound result]", data);
    hide("woundScanning");
    renderWoundResult(data);
    addMonitorLog(patientName, "Wound", data.healing_status || "Assessed");
    loadWoundHistory();
  } catch(e) {
    console.error("[Wound error]", e);
    hide("woundScanning");
    document.getElementById("woundStatusCard").innerHTML = makeStatusCard("warning","!","Could not assess","Cannot reach server. Please check the backend is running.");
    show("woundResult");
  } finally {
    btn.disabled = false;
    document.getElementById("woundBtnLabel").classList.remove("hidden");
    document.getElementById("woundBtnSpin").classList.add("hidden");
  }
}

function renderWoundResult(data) {
  show("woundResult");
  const status = (data.healing_status || "Monitor").toLowerCase().replace(/ /g, "_");

  const badge = document.getElementById("woundComparisonBadge");
  if (data.is_first_check) {
    badge.innerHTML = `📋 First check — saved as baseline for future comparisons`;
    badge.style.background  = "rgba(139,92,246,.1)";
    badge.style.color       = "#7C3AED";
    badge.style.borderColor = "#DDD6FE";
    badge.classList.remove("hidden");
  } else if (data.comparison_source === "manual") {
    badge.innerHTML = `🔄 Compared with manually uploaded previous photo`;
    badge.style.cssText = "";
    badge.classList.remove("hidden");
  } else if (data.comparison_source === "database" && data.previous_date) {
    badge.innerHTML = `🔄 Compared with saved record from ${data.previous_date}`;
    badge.style.cssText = "";
    badge.classList.remove("hidden");
  } else {
    badge.classList.add("hidden");
  }

  const configs = {
    healing_well:    { cls:"safe",    icon:"✓", title:"Healing well",       msg:"The wound is improving. Continue current care plan." },
    monitor:         { cls:"amber",   icon:"⚠", title:"Monitor closely",    msg:"Some changes noted. Watch carefully and document any further changes." },
    needs_attention: { cls:"warning", icon:"!", title:"Nurse should review", msg:"Concerning changes detected. Please alert the nurse immediately." }
  };
  const cfg = configs[status] || configs.monitor;
  document.getElementById("woundStatusCard").innerHTML = makeStatusCard(cfg.cls, cfg.icon, cfg.title, cfg.msg);

  let details = "";
  if (data.change_summary && !data.is_first_check) details += `<div class="detail-row"><span class="detail-lbl">Change since last</span><span class="detail-val" style="font-weight:700">${data.change_summary}</span></div>`;
  if (data.appearance)       details += `<div class="detail-row"><span class="detail-lbl">Today's wound</span><span class="detail-val">${data.appearance}</span></div>`;
  if (data.concerns?.length) details += `<div class="detail-row"><span class="detail-lbl">Concerns</span><span class="detail-val" style="color:var(--red)">${data.concerns.join(", ")}</span></div>`;
  if (data.recommendation)   details += `<div class="detail-row"><span class="detail-lbl">Recommendation</span><span class="detail-val" style="font-weight:700">${data.recommendation}</span></div>`;
  if (data.history_count)    details += `<div class="detail-row"><span class="detail-lbl">Total records</span><span class="detail-val">${data.history_count} wound checks saved</span></div>`;
  document.getElementById("woundDetails").innerHTML = details ? `<div class="details-box">${details}</div>` : "";

  const alertEl = document.getElementById("woundNurseAlert");
  if (data.alert_nurse) {
    alertEl.innerHTML = "🚨 Please alert the nurse to review this wound now.";
    alertEl.classList.remove("hidden");
    playChime();
  } else {
    alertEl.classList.add("hidden");
  }
}

function resetWound() {
  hide("woundResult"); show("woundIdle");
  ["woundFile","woundPrevFile"].forEach(id => { document.getElementById(id).value = ""; });
  ["woundPreview","woundPrevPreview"].forEach(id => { document.getElementById(id).classList.add("hidden"); document.getElementById(id).src = ""; });
  ["woundHint","woundPrevHint"].forEach(id => { document.getElementById(id).classList.remove("hidden"); });
  document.getElementById("wound-notes").value = "";
  document.getElementById("woundComparisonBadge").classList.add("hidden");
}

function addMonitorLog(patient, type, result) {
  const tb = document.getElementById("monitorLog");
  if (tb.querySelector(".empty-row")) tb.innerHTML="";
  const tr = document.createElement("tr");
  tr.innerHTML = `<td>${new Date().toLocaleTimeString()}</td><td>${patient}</td><td>${type}</td><td>${result}</td>`;
  tb.prepend(tr);
}

// ══════════════════════════════════════════════════════════════════
//  TAB 4: REMINDERS — auto from DB medication_times
// ══════════════════════════════════════════════════════════════════

async function loadMedTimes() {
  try {
    const res  = await fetch(`${API}/medication_times`, { headers: authHeaders() });
    const data = await res.json();
    renderMedTimes(data.schedule || []);
  } catch(_) {
    document.getElementById("scheduleBody").innerHTML =
      `<tr><td colspan="5" class="empty-row">Could not load schedule</td></tr>`;
  }
}

function renderMedTimes(list) {
  const tb = document.getElementById("scheduleBody");
  tb.innerHTML = "";
  if (!list.length) {
    tb.innerHTML = `<tr><td colspan="5" class="empty-row">No medication times set yet. A doctor or admin can add them below.</td></tr>`;
    return;
  }
  list.forEach(item => {
    const tr   = document.createElement("tr");
    const [h, m] = item.time.split(":");
    const remind = `${String(parseInt(h) - (parseInt(m) >= 10 ? 0 : 1)).padStart(2,"0")}:${String((parseInt(m) - 10 + 60) % 60).padStart(2,"0")}`;
    tr.innerHTML = `
      <td>${item.patient}</td>
      <td><span class="med-pill">${item.medicine}</span></td>
      <td><span class="time-badge">${item.time}</span></td>
      <td><span class="time-badge" style="background:#FEF3C7;color:#92400E">${remind}</span></td>
      <td><span style="font-size:.75rem;color:var(--sl4)">${item.created_by || "—"}</span></td>`;
    tb.appendChild(tr);
  });
}

// Load medicines from care plan when patient is selected in reminders tab
async function loadPatientMeds() {
  const patient = document.getElementById("rem-patient").value;
  const medSel  = document.getElementById("rem-med");
  if (!patient) return;

  const p = patientsMap[patient];
  if (!p) return;

  // Parse care plan medicines
  const meds = parseMeds(String(p.care_plan || ""));
  medSel.innerHTML = meds.length
    ? meds.map(m => `<option value="${m}">${m}</option>`).join("")
    : `<option value="" disabled>No medicines in care plan</option>`;

  // Also show existing schedule for this patient
  try {
    const res  = await fetch(`${API}/medication_times/${encodeURIComponent(patient)}`, { headers: authHeaders() });
    const data = await res.json();
    renderPatientSchedule(patient, data.schedule || []);
  } catch(_) {}
}

function renderPatientSchedule(patient, list) {
  const wrap  = document.getElementById("patientScheduleWrap");
  const title = document.getElementById("patientScheduleTitle");
  const items = document.getElementById("patientScheduleItems");
  title.textContent = `Current schedule for ${patient}`;
  items.innerHTML   = "";
  if (!list.length) {
    items.innerHTML = `<div style="font-size:.8rem;color:var(--sl4);padding:8px 0">No times set yet for this patient.</div>`;
  } else {
    list.forEach(item => {
      const row = document.createElement("div");
      row.className = "med-time-row";
      row.innerHTML = `
        <div class="med-time-info">
          <span class="med-pill">${item.medicine}</span>
          <span class="time-badge">${item.time}</span>
        </div>
        <button class="med-time-delete" onclick="deleteMedTime(${item.id})">Remove</button>`;
      items.appendChild(row);
    });
  }
  wrap.classList.remove("hidden");
}

async function addMedTime() {
  const patient = document.getElementById("rem-patient").value;
  const med     = document.getElementById("rem-med").value;
  const time    = document.getElementById("rem-time").value;

  if (!patient) { toast("Please select a patient.", "warn");   return; }
  if (!med)     { toast("Please select a medicine.", "warn");  return; }
  if (!time)    { toast("Please set a dose time.", "warn");    return; }

  try {
    const res  = await fetch(`${API}/medication_times`, {
      method: "POST",
      headers: { ...authHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ patient_name: patient, medicine: med, dose_time: time })
    });
    const data = await res.json();
    if (data.error) { toast(data.error, "warn"); return; }
    toast(`Reminder set: ${med} for ${patient} at ${time}`, "success");
    document.getElementById("rem-time").value = "";
    loadMedTimes();
    loadPatientMeds(); // refresh patient list
  } catch(_) { toast("Could not save. Please try again.", "warn"); }
}

async function deleteMedTime(id) {
  try {
    const res = await fetch(`${API}/medication_times/${id}`, {
      method: "DELETE",
      headers: authHeaders()
    });
    const data = await res.json();
    if (data.error) { toast(data.error, "warn"); return; }
    toast("Reminder removed.", "success");
    loadMedTimes();
    loadPatientMeds();
  } catch(_) { toast("Could not remove reminder.", "warn"); }
}

// Keep for backward compat
async function loadSchedule() { return loadMedTimes(); }