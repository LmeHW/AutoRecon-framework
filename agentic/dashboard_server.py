from __future__ import annotations

import argparse
from collections import deque
import errno
import html
import json
import mimetypes
import os
import re
import sys
import threading
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agentic.coordinator import coordinate_with_llm
from agentic.env_config import load_llm_config, redacted_config_status
from agentic.executor import AgenticExecutor, results_indicate_failure
from agentic.llm_analysis import analyze_results_with_llm
from agentic.llm_client import OpenAICompatibleClient
from agentic.models import RunState, task_plan_from_dict, user_request_from_dict
from agentic.planner import plan_with_llm, validate_plan, validate_runtime
from agentic.failure_catalog import summarize_execution_failure, summarize_plan_failure
from agentic.reporter import build_plan_failure_report, build_report, prepend_failure_banner, refresh_case_record_section
from agentic.state_store import StateStore
from agentic.schema_validation import validate_agentic_objects
from agentic.clinic_paths import (
    allocate_case_id,
    apply_clinic_defaults,
    clinic_intake_errors,
    normalized_clinical_intake,
    discard_upload_dir,
    is_case_id,
    list_cases,
    cases_root,
    purge_incomplete_uploads,
    sanitize_case_label,
    upload_root,
)

_INTAKE_FIELDS = (
    "gestational_age",
    "fetal_description",
    "clinical_status",
    "clinical_condition",
    "clinical_notes",
)
from agentic.legacy_paths import resolve_relocated_run_file
from pipeline.vis.clinic_viewers import refreshed_interactive_html
from pipeline.scripts.dicom_to_btfe import (
    ConvertError,
    MAX_DICOM_FILES,
    MAX_STACKS,
    allowed_upload_relpath,
    clear_non_btfe_outputs,
    convert_dicom_dir,
    convert_dicom_zip,
    is_dicom_upload,
    is_nifti_upload,
    is_zip_upload,
    normalize_uploaded_niftis,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_ROOT = PROJECT_ROOT / "agentic_runs"


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AutoRecon Agentic Dashboard</title>
  <style>
    :root{--bg:#f4f6f3;--panel:#fff;--ink:#17211d;--muted:#60706a;--line:#d8e0dc;--accent:#167d70;--ok:#237a57;--run:#9a6500;--fail:#b63636;--skip:#6e7471}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px "Segoe UI","Aptos",sans-serif}.shell{max-width:1440px;margin:0 auto;padding:20px;display:grid;gap:16px}
    header{display:flex;justify-content:space-between;align-items:end;gap:16px}.title h1{margin:0;font-size:26px}.title p{margin:6px 0 0;color:var(--muted)}
    .grid{display:grid;grid-template-columns:390px minmax(0,1fr);gap:16px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px}.panel h2{font-size:16px;margin:0 0 12px}
    label{display:grid;gap:5px;margin-bottom:10px;color:var(--muted);font-size:12px}input,textarea,select,button{font:inherit}textarea,input,select{width:100%;border:1px solid var(--line);border-radius:6px;padding:9px;background:#fbfcfb;color:var(--ink)}textarea{min-height:116px;resize:vertical}.hint{margin:-4px 0 10px;color:var(--muted);font-size:11px;line-height:1.45;word-break:break-all}
    .row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}button{border:1px solid var(--accent);background:var(--accent);color:#fff;border-radius:6px;padding:9px 12px;cursor:pointer}button.secondary{background:#fff;color:var(--accent)}button:disabled{cursor:wait;opacity:.6}
    .progress-note{display:none;align-items:center;gap:9px;margin-top:10px;padding:9px 10px;border:1px solid #ead6a5;border-radius:6px;background:#fff8e8;color:#74500a;line-height:1.4}.progress-note.visible{display:flex}.progress-note.completed{border-color:#b9ddcd;background:#edf8f3;color:var(--ok)}.progress-note.failed{border-color:#edbaba;background:#fff0f0;color:var(--fail)}.progress-note.completed .spinner,.progress-note.failed .spinner{display:none}.spinner{width:15px;height:15px;flex:0 0 auto;border:2px solid #e4c87e;border-top-color:var(--run);border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
    .badge{display:inline-flex;border-radius:999px;padding:4px 10px;font-weight:700;font-size:12px;background:#eef2f0;color:var(--muted)}.completed{color:var(--ok);background:#e8f3ee}.running{color:var(--run);background:#fff3d8}.failed{color:var(--fail);background:#fde9e9}.skipped{color:var(--skip);background:#eff1f0}
    pre{white-space:pre-wrap;word-break:break-word;background:#f4f6f5;border:1px solid var(--line);border-radius:6px;padding:10px;max-height:360px;overflow:auto}.markdown{background:#fbfcfb;border:1px solid var(--line);border-radius:6px;padding:12px;max-height:520px;overflow:auto;line-height:1.55}.markdown h1,.markdown h2,.markdown h3{margin:10px 0 8px}.markdown h1{font-size:20px}.markdown h2{font-size:17px;border-top:1px solid var(--line);padding-top:12px}.markdown h3{font-size:14px;color:var(--accent)}.markdown ul,.markdown ol{margin:6px 0 12px;padding-left:24px}.markdown li{margin:4px 0}.markdown code{background:#edf3f1;border:1px solid #d7e3df;border-radius:4px;padding:1px 4px}.markdown pre code{background:none;border:0;padding:0}.markdown strong{font-weight:700}.markdown a{color:var(--accent)}.markdown table{width:100%;border-collapse:collapse;margin:10px 0;font-size:12px}.markdown th,.markdown td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}.markdown th{background:#edf3f1}.markdown blockquote{margin:8px 0;padding:6px 10px;border-left:3px solid var(--accent);background:#f1f6f4;color:var(--muted)}.steps{display:grid;gap:12px}.step{border:1px solid var(--line);border-radius:8px;padding:12px;background:#fff}.step-head{display:flex;justify-content:space-between;gap:8px}.artifacts{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}.artifacts a{color:var(--accent);text-decoration:none;border:1px solid var(--line);border-radius:6px;padding:6px 8px}
    .preview{margin-top:10px;border:1px solid var(--line);border-radius:8px;overflow:hidden;background:#f6f8f7}.preview img{display:block;max-width:100%;height:auto}.preview iframe{width:100%;height:620px;border:0;display:block}.muted{color:var(--muted)}.split{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:12px}.split>div{min-width:0}.split pre,.split .markdown{width:100%;overflow-wrap:anywhere}
    .live-log{margin-top:10px;border:1px solid var(--line);border-radius:6px;background:#17211d;color:#dce8e3;overflow:hidden}.live-log-head{display:flex;justify-content:space-between;padding:6px 9px;background:#24332d;color:#b9cbc4;font-size:11px}.live-log pre{margin:0;border:0;border-radius:0;background:transparent;color:inherit;max-height:150px;min-height:44px;padding:8px 9px;font:11px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}
    .qc-card{margin-top:10px;padding:9px;border:1px solid #cfe0d9;border-radius:6px;background:#f5faf8}.qc-head{display:flex;justify-content:space-between;gap:8px;margin-bottom:6px;font-size:12px}.qc-metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:6px}.qc-metric{padding:6px 7px;border-radius:5px;background:#fff;border:1px solid #e0e9e5;font-size:11px}.qc-metric small{display:block;color:var(--muted);margin-top:3px}.qc-pass{color:var(--ok)}.qc-review{color:var(--run)}.qc-fail{color:var(--fail)}
    @media(max-width:980px){.grid,.split{grid-template-columns:1fr}.preview iframe{height:520px}}
  </style>
</head>
<body>
<main class="shell">
  <header>
    <div class="title"><h1>AutoRecon Agentic Dashboard</h1><p>Natural-language requests, structured plans, controlled execution, verification reports, and visualization in one page.</p></div>
    <div id="config" class="badge">config</div>
  </header>
  <section class="grid">
    <aside class="panel">
      <h2>Request</h2>
      <label>Natural-language request<textarea id="request"></textarea></label>
      <div class="hint">Example: Reconstruct this fetal brain from multi-orientation stacks and generate GA-matched ROI statistics.</div>
      <label>Execution mode<select id="execution_mode"><option value="import_existing">Import existing run demo</option><option value="plan_only">Plan only</option><option value="run_pipeline" selected>Run full pipeline</option></select></label>
      <label>Existing run directory<input id="existing_run_dir" value="/mnt/sda/huangwei/projects/AutoRecon/runs/legacy/CaiYuYu/raw_run01" placeholder="/mnt/sda/huangwei/projects/AutoRecon/runs/legacy/CaiYuYu/raw_run01"></label>
      <div class="hint">Use this for demo/import mode. This default is an existing migrated run.</div>
      <label>Subject directory<input id="subject_dir" value="/mnt/sda/huangwei/projects/AutoRecon/backend_validation/input/AnHuiJing" placeholder="/mnt/sda/huangwei/projects/AutoRecon/backend_validation/input/AnHuiJing"></label>
      <div class="hint">Use this for plan-only or full pipeline mode. It should contain top-level *.nii.gz stacks.</div>
      <label>Work root<input id="work_root" value="/mnt/sda/huangwei/projects/AutoRecon/agentic_runs/manual_full_pipeline_AnHuiJing" placeholder="/mnt/sda/huangwei/projects/AutoRecon/agentic_runs/manual_full_pipeline_AnHuiJing"></label>
      <div class="hint">Use this for full pipeline mode. Outputs, logs, and dashboard assets will be written here.</div>
      <div class="row"><label>Gestational age (GA)<input id="gestational_age" value="31" placeholder="31"></label><label>ROI mode<select id="roi_mode"><option value="warp" selected>warp</option><option value="segresnet">segresnet</option><option value="skip">skip</option></select></label></div>
      <label>Reconstruction backend<select id="reconstruction_tool"><option value="frost" selected>FROST</option><option value="nesvor">NeSVoR</option><option value="autosvrtk">auto-proc-svrtk</option><option value="niftymic">NiftyMIC</option></select></label>
      <label>Reconstruction comparison<select id="reconstruction_compare_tools"><option value="" selected>Selected backend only</option><option value="all">Run all four backends</option></select></label>
      <label>Atlas<input id="atlas" value="/mnt/sda/huangwei/projects/AutoRecon/pipeline/data/FBA_Chinese_Atlas/img/31w.nii.gz" placeholder="/mnt/sda/huangwei/projects/AutoRecon/pipeline/data/FBA_Chinese_Atlas/img/31w.nii.gz"></label>
      <div class="hint">Optional for rigid registration. ROI warp can use the internal GA atlas when this is empty.</div>
      <label>Surface<select id="surface"><option value="auto">auto</option><option value="on" selected>on</option><option value="off">off</option></select></label>
      <div class="actions"><button id="planBtn">Generate plan</button><button id="runBtn" class="secondary">Run / Demo</button></div>
      <div id="planProgress" class="progress-note" role="status" aria-live="polite"><span class="spinner" aria-hidden="true"></span><span id="planProgressText">Preparing request...</span></div>
    </aside>
    <section class="panel">
      <h2>Run status <span id="runBadge" class="badge">idle</span></h2>
      <div class="split">
        <div><h2>Task Plan</h2><pre id="planBox">Waiting for a generated plan...</pre></div>
        <div><h2>Report</h2><div id="reportBox" class="markdown"><p>Waiting for execution results...</p></div></div>
      </div>
    </section>
  </section>
  <section class="panel"><h2>Steps and Visualization</h2><div id="steps" class="steps"></div></section>
</main>
<script>
const initialRunId=new URLSearchParams(location.search).get("run_id");
const initialFocusStep=new URLSearchParams(location.search).get("focus_step");
let initialFocusApplied=false;
let latestRunId=initialRunId;
let lastVizSignature="";
const explicitFields=new Set(["execution_mode","existing_run_dir","subject_dir","work_root","gestational_age","reconstruction_tool","reconstruction_compare_tools","roi_mode","atlas","surface"]);
const $=id=>document.getElementById(id);
const formFields=["execution_mode","existing_run_dir","subject_dir","work_root","gestational_age","reconstruction_tool","reconstruction_compare_tools","roi_mode","atlas","surface"];
for(const id of formFields){$(id).addEventListener("change",()=>explicitFields.add(id))}
function payload(){const data={raw_text:$("request").value,explicit_fields:[...explicitFields]};for(const id of explicitFields)data[id]=$(id).value;return data}
async function api(path, body){const r=await fetch(path,{method:body?"POST":"GET",headers:{"Content-Type":"application/json"},body:body?JSON.stringify(body):undefined});if(!r.ok)throw new Error(await r.text());return r.json()}
function fileUrl(path){return `/api/file?path=${encodeURIComponent(path)}`}
function statusBadge(status){return `<span class="badge ${status||""}">${status||"pending"}</span>`}
function esc(value){return String(value??"").replace(/[&<>"']/g, ch=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch]))}
function inlineMd(value){return esc(value).replace(/`([^`]+)`/g,"<code>$1</code>").replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>").replace(/\*([^*]+)\*/g,"<em>$1</em>").replace(/\[([^\]]+)\]\(([^)]+)\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>')}
function renderMarkdown(md){
  const lines=String(md||"").split(/\r?\n/),html=[];let list="",paragraph=[],inCode=false,code=[];
  const flushParagraph=()=>{if(paragraph.length){html.push(`<p>${paragraph.map(inlineMd).join("<br>")}</p>`);paragraph=[]}};
  const closeList=()=>{if(list){html.push(`</${list}>`);list=""}};
  const closeBlocks=()=>{flushParagraph();closeList()};
  const cells=line=>line.trim().replace(/^\||\|$/g,"").split("|").map(cell=>cell.trim());
  for(let i=0;i<lines.length;i++){
    const line=lines[i],trim=line.trim();
    if(trim.startsWith("```")){closeBlocks();if(inCode){html.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);code=[];inCode=false}else inCode=true;continue}
    if(inCode){code.push(line);continue}
    if(trim.includes("|")&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])){closeBlocks();const heads=cells(line);i++;const rows=[];while(i+1<lines.length&&lines[i+1].includes("|")&&lines[i+1].trim()){rows.push(cells(lines[++i]))}html.push(`<table><thead><tr>${heads.map(x=>`<th>${inlineMd(x)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(x=>`<td>${inlineMd(x)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);continue}
    const heading=line.match(/^(#{1,6})\s+(.+)$/);if(heading){closeBlocks();const n=Math.min(3,heading[1].length);html.push(`<h${n}>${inlineMd(heading[2])}</h${n}>`);continue}
    const item=line.match(/^\s*([-*+]|\d+\.)\s+(.+)$/);if(item){flushParagraph();const wanted=/\d/.test(item[1])?"ol":"ul";if(list!==wanted){closeList();list=wanted;html.push(`<${list}>`)}html.push(`<li>${inlineMd(item[2])}</li>`);continue}
    if(trim.startsWith(">")){closeBlocks();html.push(`<blockquote>${inlineMd(trim.replace(/^>\s?/,""))}</blockquote>`);continue}
    if(/^([-*_])\1\1+$/.test(trim)){closeBlocks();html.push("<hr>");continue}
    if(!trim){closeBlocks();continue}
    paragraph.push(line);
  }
  if(inCode)html.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);closeBlocks();
  return html.join("");
}
function artifactLinks(arts){return (arts||[]).map(a=>`<a href="${fileUrl(a.path)}" target="_blank">${esc(a.label)}</a>`).join("")}
function vizSignature(ds,agenticResults,displaySteps){
  const pipeline=(ds?.steps||[]).map(s=>({id:s.id,status:s.status,message:s.message,preview:s.preview_relpath,artifacts:s.artifacts}));
  const agentic=(agenticResults||[]).map(r=>({id:r.step_id,status:r.status,message:r.message||r.error,outputs:r.outputs}));
  return JSON.stringify({pipeline,agentic,displaySteps});
}
function renderVizContent(ds,agenticResults,displaySteps){
  const signature=vizSignature(ds,agenticResults,displaySteps);
  if(signature===lastVizSignature){refreshLiveLogs();refreshQc(ds);return;}
  lastVizSignature=signature;
  const box=$("steps"),next=document.createElement("div");
  if(ds)renderDashboardSteps(next,ds,agenticResults,displaySteps);
  else renderAgenticSteps(next,agenticResults,displaySteps);
  reconcileSteps(box,[...next.children]);
  refreshLiveLogs();
  refreshQc(ds);
  if(initialFocusStep&&!initialFocusApplied){const target=[...box.children].find(node=>node.dataset.stepKey===`pipeline:${initialFocusStep}`);if(target){initialFocusApplied=true;setTimeout(()=>target.scrollIntoView({block:"start"}),100)}}
}
function reconcileSteps(box,nextNodes){
  const existing=new Map([...box.children].map(node=>[node.dataset.stepKey,node]));
  const wanted=new Set();
  for(const fresh of nextNodes){
    const key=fresh.dataset.stepKey;wanted.add(key);
    const current=existing.get(key);
    if(!current){box.appendChild(fresh);continue;}
    current.dataset.logPath=fresh.dataset.logPath||"";
    for(const selector of [".step-head",".muted",".artifacts",".output-json"]){
      const oldPart=current.querySelector(selector),newPart=fresh.querySelector(selector);
      if(oldPart&&newPart&&oldPart.outerHTML!==newPart.outerHTML)oldPart.replaceWith(newPart);
      else if(!oldPart&&newPart)current.appendChild(newPart);
      else if(oldPart&&!newPart)oldPart.remove();
    }
    const oldPreview=current.querySelector(".preview"),newPreview=fresh.querySelector(".preview");
    const oldMedia=oldPreview?.querySelector("iframe,img")?.getAttribute("src");
    const newMedia=newPreview?.querySelector("iframe,img")?.getAttribute("src");
    if(!oldPreview&&newPreview)current.appendChild(newPreview);
    else if(oldPreview&&!newPreview)oldPreview.remove();
    else if(oldPreview&&newPreview&&oldMedia!==newMedia)oldPreview.replaceWith(newPreview);
    const oldLog=current.querySelector(".live-log"),newLog=fresh.querySelector(".live-log");
    if(!oldLog&&newLog)current.appendChild(newLog);
    else if(oldLog&&!newLog)oldLog.remove();
  }
  for(const [key,node] of existing){if(!wanted.has(key))node.remove()}
}
async function refreshLiveLogs(){
  for(const card of $("steps").querySelectorAll("[data-log-path]")){
    const path=card.dataset.logPath;if(!path)continue;
    const pre=card.querySelector(".live-log pre"),meta=card.querySelector(".live-log-meta");
    if(!pre)continue;
    try{
      const data=await api(`/api/log-tail?path=${encodeURIComponent(path)}&lines=12`);
      const content=data.text||"Log file is empty.";
      if(pre.textContent!==content){pre.textContent=content;pre.scrollTop=pre.scrollHeight;}
      if(meta)meta.textContent=`last ${data.line_count||0} lines`;
    }catch(_){if(pre.textContent!=="Log not available yet.")pre.textContent="Log not available yet.";if(meta)meta.textContent="waiting";}
  }
}
async function refreshQc(ds){
  if(!ds?.run?.work_root)return;
  try{
    const qc=await api(fileUrl(`${ds.run.work_root}/dashboard/qc_summary.json`));
    for(const step of qc.steps||[]){
      const card=[...$("steps").children].find(node=>node.dataset.stepKey===`pipeline:${step.step_id}`);
      if(!card)continue;
      let panel=card.querySelector(".qc-card");if(!panel){panel=document.createElement("div");panel.className="qc-card";const log=card.querySelector(".live-log");log?log.before(panel):card.appendChild(panel)}
      const metrics=(step.metrics||[]).map(m=>`<div class="qc-metric"><span>${esc(m.label||m.name)}</span>: <strong class="qc-${esc(m.status)}">${esc(m.value)} ${esc(m.unit||"")}</strong><small>${esc(m.criterion||"")} · ${esc(m.status)}</small></div>`).join("");
      const html=`<div class="qc-head"><strong>QC metrics</strong><span class="qc-${esc(step.status)}">${esc(step.status)}</span></div><div class="qc-metrics">${metrics||'<span class="muted">Waiting for measurable artifacts…</span>'}</div>`;
      if(panel.innerHTML!==html)panel.innerHTML=html;
    }
  }catch(_){}
}
function renderViz(state){
  const agenticResults=state.step_results||[];
  const displaySteps=state.request?.display_steps||[];
  const dashStatePath=state.dashboard?.dashboard_state;
  if(dashStatePath){fetch(fileUrl(dashStatePath)).then(r=>{if(!r.ok)throw new Error(`dashboard state ${r.status}`);return r.json()}).then(ds=>renderVizContent(ds,agenticResults,displaySteps)).catch(()=>renderVizContent(null,agenticResults,displaySteps));}
  else renderVizContent(null,agenticResults,displaySteps);
}
function renderAgenticSteps(box, results, displaySteps=[]){ for(const r of results){if(displaySteps.length&&!displaySteps.includes(r.step_id))continue;const div=document.createElement("div");div.className="step";div.dataset.stepKey=`agentic:${r.step_id}`;div.innerHTML=`<div class="step-head"><strong>${esc(r.step_id)}</strong>${statusBadge(r.status)}</div><p class="muted">${esc(r.message||r.error||"")}</p><pre class="output-json">${esc(JSON.stringify(r.outputs||{},null,2))}</pre>`;box.appendChild(div)}}
function renderDashboardSteps(box, ds, agenticResults, displaySteps=[]){
  if(!displaySteps.length)renderAgenticSteps(box, agenticResults, displaySteps);
  for(const s of ds.steps||[]){if(displaySteps.length&&!displaySteps.includes(s.id))continue;const viewer=(s.artifacts||[]).find(a=>/Interactive|MPR|viewer/i.test(a.label));const div=document.createElement("div");div.className="step";div.dataset.stepKey=`pipeline:${s.id}`;div.dataset.logPath=s.log_relpath?`${ds.run.work_root}/dashboard/${s.log_relpath}`:"";let media=""; if(viewer) media=`<div class="preview"><iframe src="${fileUrl(viewer.path)}"></iframe></div>`; else if(s.preview_relpath) media=`<div class="preview"><img src="${fileUrl(ds.run.work_root + "/dashboard/" + s.preview_relpath)}"></div>`;const liveLog=s.log_relpath?`<div class="live-log"><div class="live-log-head"><span>Live log</span><span class="live-log-meta">waiting</span></div><pre>Log not available yet.</pre></div>`:""; div.innerHTML=`<div class="step-head"><strong>${esc(s.index)}. ${esc(s.title)}</strong>${statusBadge(s.status)}</div><p class="muted">${esc(s.message||"")}</p><div class="artifacts">${artifactLinks(s.artifacts)}</div>${liveLog}${media}`;box.appendChild(div)}
}
function planOutcome(state,elapsedSeconds=0){
  const events=state.report_json?.llm?.events||[];
  const planning=events.find(event=>event.stage==="planning")||{};
  const seconds=elapsedSeconds?` in ${elapsedSeconds}s`:"";
  if(state.status==="failed")return {message:state.report_json?.failure?.summary_zh||`Plan failed: ${(state.report_json?.errors||[])[0]||"See Report for details."}`,style:"failed"};
  if((state.report_json?.dashboard_conflicts||[]).length)return {message:state.report_json?.failure?.summary_zh||`Plan has ${state.report_json.dashboard_conflicts.length} request/form conflict(s). Review the warnings.`,style:"failed"};
  if(state.plan?.planner_source==="llm"&&planning.used)return {message:`Validated LLM plan ready${seconds} (${planning.model||"configured model"}). Review it before clicking Run.`,style:"completed"};
  if(planning.status==="fallback")return {message:`Validated rules plan ready${seconds}; LLM planning fell back after validation errors. Review planner_notes.`,style:"completed"};
  if(planning.reason==="deterministic_import_plan")return {message:`Validated deterministic import plan ready${seconds}; LLM DAG generation is intentionally bypassed for import mode.`,style:"completed"};
  return {message:`Validated rules plan ready${seconds}; LLM planning is disabled or unavailable.`,style:"completed"};
}
function applyLoadedRequest(req){
  if(!req)return;
  if(req.raw_text!=null)$("request").value=req.raw_text;
  const assign=(id,val)=>{if(val==null||val==="")return;const el=$(id);if(el)el.value=String(val)};
  assign("execution_mode",req.execution_mode);
  assign("existing_run_dir",req.existing_run_dir);
  assign("subject_dir",req.subject_dir);
  assign("work_root",req.work_root);
  assign("gestational_age",req.gestational_age);
  assign("roi_mode",req.roi_mode);
  assign("reconstruction_tool",req.reconstruction_tool);
  assign("atlas",req.atlas);
  assign("surface",req.surface);
  const compare=req.reconstruction_compare_tools;
  if(Array.isArray(compare))$("reconstruction_compare_tools").value=compare.length?"all":"";
  else assign("reconstruction_compare_tools",compare);
}
async function refresh(runId){if(!runId)return; const s=await api(`/api/state?run_id=${encodeURIComponent(runId)}`);applyLoadedRequest(s.request);$("runBadge").outerHTML=`<span id="runBadge" class="badge ${s.status}">${s.status}</span>`;const errors=s.report_json?.errors||[];if(s.plan){const prefix=s.status==="failed"&&errors.length?`PLAN FAILED\n${errors.map(e=>`- ${e}`).join("\n")}\n\n`:"";$("planBox").textContent=prefix+JSON.stringify(s.plan,null,2)}$("reportBox").innerHTML=renderMarkdown(s.report_markdown||"No report yet.");if(s.status==="planned"||s.status==="failed"){const outcome=planOutcome(s);setPlanProgress(outcome.message,outcome.style)}renderViz(s);if(s.status==="running")setTimeout(()=>refresh(runId),2000)}
function setPlanProgress(message, state="loading"){
  const progress=$("planProgress");
  $("planProgressText").textContent=message;
  progress.classList.add("visible");
  progress.classList.toggle("completed",state==="completed");
  progress.classList.toggle("failed",state==="failed");
}
$("planBtn").onclick=async()=>{
  const button=$("planBtn"), runButton=$("runBtn"), started=Date.now();
  button.disabled=true;runButton.disabled=true;button.textContent="Planning...";
  $("runBadge").className="badge running";$("runBadge").textContent="planning";
  $("planBox").textContent="LLM is interpreting the request. The validated plan will appear here when ready.";
  setPlanProgress("Step 1/3 · Interpreting the natural-language request…");
  const timers=[
    setTimeout(()=>setPlanProgress("Step 2/3 · Building a tool-constrained execution DAG…"),5000),
    setTimeout(()=>setPlanProgress("Step 3/3 · Validating dependencies, paths, and runtime capabilities…"),15000),
    setInterval(()=>{const seconds=Math.floor((Date.now()-started)/1000);if(seconds>=15)setPlanProgress(`Still validating the plan… ${seconds}s elapsed`)},1000)
  ];
  try{
    const data=await api("/api/plan", payload());
    $("planBox").textContent=JSON.stringify(data.plan,null,2);latestRunId=data.run_id;
    const outcome=planOutcome(data.state,Math.max(1,Math.round((Date.now()-started)/1000)));
    setPlanProgress(outcome.message,outcome.style);
    await refresh(latestRunId);
  }catch(error){
    $("runBadge").className="badge failed";$("runBadge").textContent="plan failed";
    $("planBox").textContent=`Plan generation failed:\n${error.message}`;
    setPlanProgress("Plan generation failed. Check the error shown in Task Plan.","failed");
  }finally{
    timers.forEach(timer=>{clearTimeout(timer);clearInterval(timer)});
    button.disabled=false;runButton.disabled=false;button.textContent="Generate plan";
  }
}
$("runBtn").onclick=async()=>{if(!latestRunId){alert("Generate and review a plan first.");return;}const data=await api("/api/run", {confirmed_run_id:latestRunId});$("planBox").textContent=JSON.stringify(data.plan,null,2);await refresh(latestRunId)}
api("/api/config").then(c=>$("config").textContent=`API key: ${c.api_key_configured?"configured":"not configured"}`);
if(initialRunId)refresh(initialRunId);
</script>
</body></html>
"""

PAGE_HTML = INDEX_HTML


_DASHBOARD_STEP_ORDER = {
    "extraction": "01",
    "reconstruction": "02",
    "registration": "03",
    "tissue": "04",
    "roi": "05",
    "surface": "06",
}
_DASHBOARD_VIEWER_LABEL = {
    "extraction": "脑提取交互查看",
    "reconstruction": "三维重建交互查看",
    "registration": "图像配准交互查看",
    "tissue": "组织分割交互查看",
    "roi": "脑区分割交互查看",
    "surface": "表面重建交互查看",
}


def load_enriched_dashboard_state(path: Path) -> dict:
    """Restore visualization metadata omitted by older/resumed dashboards."""
    data = json.loads(path.read_text(encoding="utf-8"))
    preview_root = path.parent / "previews"
    for step in data.get("steps") or []:
        step_id = str(step.get("id") or "")
        prefix = _DASHBOARD_STEP_ORDER.get(step_id)
        if not prefix:
            continue
        preview_relpath = f"previews/{prefix}_{step_id}.png"
        preview_path = path.parent / preview_relpath
        if not step.get("preview_relpath") and preview_path.is_file():
            step["preview_relpath"] = preview_relpath
        viewer_path = preview_root / f"{prefix}_{step_id}_interactive.html"
        artifacts = step.setdefault("artifacts", [])
        if viewer_path.is_file() and not any(str(item.get("path") or "") == str(viewer_path) for item in artifacts):
            artifacts.append({
                "label": _DASHBOARD_VIEWER_LABEL[step_id],
                "path": str(viewer_path),
            })
    return data


class AgenticHandler(BaseHTTPRequestHandler):
    store: StateStore
    executor: AgenticExecutor
    allow_roots: list[Path]
    dashboard_url: str
    llm: OpenAICompatibleClient
    worker_lock = threading.Lock()

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[agentic-dashboard] " + fmt % args + "\n")

    def _json(self, data: object, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _text(self, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        payload = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _body(self) -> dict:
        size = int(self.headers.get("Content-Length", "0"))
        if size <= 0:
            return {}
        return json.loads(self.rfile.read(size).decode("utf-8"))

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                return self._text(PAGE_HTML, content_type="text/html; charset=utf-8")
            if parsed.path == "/api/cases":
                return self._json({"cases_root": str(cases_root()), "cases": list_cases()})
            if parsed.path in {"/brand/logo.png", "/brand/shanghaitech.png"}:
                logo = PROJECT_ROOT / "docs" / "design" / "shanghaitech-university-seeklogo.png"
                return self._serve_file(str(logo))
            if parsed.path in {"/brand/smilelab.svg", "/brand/smilelab_red.svg"}:
                logo = PROJECT_ROOT / "docs" / "design" / "smilelab_red.svg"
                return self._serve_file(str(logo))
            feature_icons = {
                "/brand/results-center.png": "autorecon-results-center.png",
                "/brand/new-analysis.png": "autorecon-new-analysis.png",
            }
            if parsed.path in feature_icons:
                return self._serve_file(str(PROJECT_ROOT / "docs" / "design" / feature_icons[parsed.path]))
            if parsed.path == "/api/config":
                return self._json(redacted_config_status(PROJECT_ROOT))
            if parsed.path in {"/api/runs", "/api/results"}:
                return self._json({"runs": self.store.list_runs()})
            if parsed.path == "/api/state":
                qs = parse_qs(parsed.query)
                run_id = qs.get("run_id", [None])[0]
                data = self.store.load(run_id) if run_id else self.store.latest()
                data = self._recover_state_if_needed(data)
                return self._json(data or {})
            if parsed.path == "/api/dashboard-state":
                qs = parse_qs(parsed.query)
                return self._serve_dashboard_state(qs.get("path", [""])[0])
            if parsed.path == "/api/file":
                qs = parse_qs(parsed.query)
                path = qs.get("path", [""])[0]
                return self._serve_file(path)
            if parsed.path == "/api/log-tail":
                qs = parse_qs(parsed.query)
                path = qs.get("path", [""])[0]
                try:
                    lines = max(1, min(4000, int(qs.get("lines", ["12"])[0])))
                except ValueError:
                    lines = 12
                return self._serve_log_tail(path, lines)
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/clinic-upload":
                return self._handle_upload_init()
            upload_complete = re.fullmatch(r"/api/clinic-upload/([A-Za-z0-9_-]+)/complete", parsed.path)
            if upload_complete:
                return self._handle_upload_complete(upload_complete.group(1))
            upload_rename = re.fullmatch(r"/api/clinic-upload/([A-Za-z0-9_-]+)/rename", parsed.path)
            if upload_rename:
                return self._handle_upload_rename(upload_rename.group(1))
            if self.path == "/api/plan":
                return self._handle_plan(execute=False)
            if self.path == "/api/run":
                return self._handle_confirmed_run()
            if self.path == "/api/analyze":
                return self._handle_plan(execute=True)
            if self.path == "/api/clinic-intake":
                return self._handle_clinic_intake()
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    def do_PUT(self) -> None:
        try:
            parsed = urlparse(self.path)
            match = re.fullmatch(r"/api/clinic-upload/([A-Za-z0-9_-]+)/(\d+)", parsed.path)
            if not match:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self._handle_upload_chunk(match.group(1), int(match.group(2)), parsed.query)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)

    @staticmethod
    def _safe_upload_name(value: object) -> str | None:
        return allowed_upload_relpath(value)

    def _upload_manifest(self, case_id: str) -> tuple[Path, dict] | None:
        if not is_case_id(case_id):
            return None
        directory = (upload_root() / case_id).resolve()
        root = upload_root().resolve()
        if root not in directory.parents:
            return None
        manifest_path = directory / ".upload.json"
        if not manifest_path.is_file():
            return None
        try:
            return directory, json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _handle_upload_init(self) -> None:
        body = self._body()
        raw_files = body.get("files")
        if not isinstance(raw_files, list) or not 1 <= len(raw_files) <= MAX_DICOM_FILES:
            return self._json({"error": "请选择影像文件、DICOM 文件夹或一个压缩包。"}, 400)
        files: list[dict[str, object]] = []
        total = 0
        names: set[str] = set()
        max_total = int(os.environ.get("AUTORECON_CLINIC_MAX_UPLOAD_BYTES", str(2 * 1024 ** 3)))
        for index, item in enumerate(raw_files):
            if not isinstance(item, dict):
                return self._json({"error": "上传文件清单格式无效。"}, 400)
            name = self._safe_upload_name(item.get("name"))
            try:
                size = int(item.get("size") or 0)
            except (TypeError, ValueError):
                size = 0
            if not name or name.casefold() in names or size <= 0:
                return self._json({"error": "含有无法上传的文件，请去掉预览图、PDF 后再试。"}, 400)
            names.add(name.casefold())
            total += size
            files.append({"index": index, "name": name, "size": size})
        zip_names = [item["name"] for item in files if is_zip_upload(str(item["name"]))]
        nifti_names = [item["name"] for item in files if is_nifti_upload(str(item["name"]))]
        dicom_names = [item["name"] for item in files if is_dicom_upload(str(item["name"]))]
        if zip_names and (len(zip_names) != 1 or nifti_names or dicom_names):
            return self._json({"error": "压缩包请单独上传，不要与其它文件混在一起。"}, 400)
        if nifti_names and dicom_names:
            return self._json({"error": "请不要把 NIfTI 和 DICOM 混在一次上传里。"}, 400)
        if nifti_names and len(nifti_names) > MAX_STACKS:
            return self._json({"error": f"NIfTI 一次最多 {MAX_STACKS} 个。"}, 400)
        if total > max_total:
            return self._json({"error": "上传总大小超过本机限制。"}, 413)
        purge_incomplete_uploads()
        label = sanitize_case_label(body.get("label") or body.get("case_label"))
        existing = {path.name for path in upload_root().iterdir()} if upload_root().is_dir() else set()
        requested = str(body.get("case_id") or "").strip()
        if requested:
            if not is_case_id(requested) or requested.casefold() in {name.casefold() for name in existing}:
                return self._json({"error": "病例名称不可用，请更换后重试。"}, 409)
            case_id = requested
        else:
            case_id = allocate_case_id(label, existing)
        directory = upload_root() / case_id
        directory.mkdir(parents=True, exist_ok=False)
        manifest = {"case_id": case_id, "label": label or case_id, "status": "uploading", "files": files}
        (directory / ".upload.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self._json({"case_id": case_id, "label": manifest["label"], "chunk_bytes": 8 * 1024 * 1024})

    def _handle_upload_chunk(self, case_id: str, index: int, query: str) -> None:
        loaded = self._upload_manifest(case_id)
        if not loaded:
            return self._json({"error": "上传任务不存在。"}, 404)
        directory, manifest = loaded
        files = manifest.get("files") or []
        if not 0 <= index < len(files):
            return self._json({"error": "上传文件序号无效。"}, 404)
        item = files[index]
        try:
            offset = int(parse_qs(query).get("offset", ["-1"])[0])
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json({"error": "上传偏移量无效。"}, 400)
        if length <= 0 or length > 8 * 1024 * 1024:
            return self._json({"error": "上传分块大小无效。"}, 400)
        target = directory / str(item["name"])
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            resolved = target.resolve()
            if directory.resolve() not in resolved.parents and resolved != directory.resolve():
                return self._json({"error": "上传路径不合法。"}, 400)
        except OSError:
            return self._json({"error": "无法写入上传文件。"}, 400)
        current = target.stat().st_size if target.is_file() else 0
        if offset != current or current + length > int(item["size"]):
            return self._json({"error": "上传偏移量不匹配，请重新上传。"}, 409)
        remaining = length
        with target.open("ab") as handle:
            while remaining:
                chunk = self.rfile.read(min(1024 * 1024, remaining))
                if not chunk:
                    return self._json({"error": "上传数据提前结束。"}, 400)
                handle.write(chunk)
                remaining -= len(chunk)
        self._json({"ok": True, "received": current + length, "size": item["size"]})

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        match = re.fullmatch(r"/api/clinic-upload/([A-Za-z0-9_-]+)", parsed.path)
        if not match:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._handle_upload_abort(match.group(1))

    def _handle_upload_abort(self, case_id: str) -> None:
        if not is_case_id(case_id):
            return self._json({"error": "上传任务不存在。"}, 404)
        directory = (upload_root() / case_id).resolve()
        root = upload_root().resolve()
        if root not in directory.parents:
            return self._json({"error": "上传任务不存在。"}, 404)
        if not directory.exists():
            return self._json({"ok": True, "discarded": True})
        loaded = self._upload_manifest(case_id)
        if loaded and str(loaded[1].get("status") or "") == "complete":
            return self._json({"error": "已完成的上传不能撤销。"}, 409)
        discard_upload_dir(directory)
        return self._json({"ok": True, "discarded": True})

    def _handle_upload_complete(self, case_id: str) -> None:
        self._body()
        loaded = self._upload_manifest(case_id)
        if not loaded:
            return self._json({"error": "上传任务不存在。"}, 404)
        directory, manifest = loaded

        def fail(message: str, status: int = 400):
            discard_upload_dir(directory)
            return self._json({"error": message}, status)

        for item in manifest.get("files") or []:
            path = directory / str(item["name"])
            if not path.is_file() or path.stat().st_size != int(item["size"]):
                return fail(f"{item['name']} 尚未上传完整。", 409)
        zip_items = [item for item in manifest.get("files") or [] if is_zip_upload(str(item["name"]))]
        nifti_items = [item for item in manifest.get("files") or [] if is_nifti_upload(str(item["name"]))]
        dicom_items = [item for item in manifest.get("files") or [] if is_dicom_upload(str(item["name"]))]
        try:
            if zip_items:
                if len(zip_items) != 1 or nifti_items or dicom_items:
                    return fail("压缩包请单独上传，不要与其它文件混在一起。")
                zip_path = directory / str(zip_items[0]["name"])
                with zip_path.open("rb") as handle:
                    if handle.read(2) != b"PK":
                        return fail(f"{zip_path.name} 不是有效的 zip 文件。")
                report = convert_dicom_zip(zip_path, directory)
                zip_path.unlink(missing_ok=True)
                converted = report.get("stacks") or report.get("btfe") or []
                manifest["conversion"] = {
                    "dropped": report.get("dropped") or [],
                    "series": report.get("series") or [],
                    "kept_family": report.get("kept_family"),
                    "kept_family_label": report.get("kept_family_label"),
                    "stacks": converted,
                }
            elif dicom_items:
                report = convert_dicom_dir(directory, directory)
                converted = report.get("stacks") or report.get("btfe") or []
                manifest["conversion"] = {
                    "dropped": report.get("dropped") or [],
                    "series": report.get("series") or [],
                    "kept_family": report.get("kept_family"),
                    "kept_family_label": report.get("kept_family_label"),
                    "stacks": converted,
                }
            else:
                converted = normalize_uploaded_niftis(directory)
                conversion_path = directory / "conversion.json"
                if conversion_path.is_file():
                    try:
                        manifest["conversion"] = json.loads(conversion_path.read_text(encoding="utf-8"))
                    except (OSError, ValueError):
                        pass
            clear_non_btfe_outputs(directory)
        except ConvertError as exc:
            return fail(str(exc))
        except Exception as exc:
            return fail(str(exc), 500)
        files_out: list[dict[str, object]] = []
        for index, name in enumerate(converted):
            path = directory / str(name)
            if not path.is_file():
                return fail("转换后未找到可用的三维栈。", 500)
            files_out.append({"index": index, "name": name, "size": path.stat().st_size})
        manifest["files"] = files_out
        manifest["status"] = "complete"
        (directory / ".upload.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        self._json({
            "ok": True,
            "case": {
                "id": case_id,
                "label": sanitize_case_label(manifest.get("label")) or case_id,
                "subject_dir": str(directory),
                "stack_count": str(len(manifest.get("files") or [])),
                "source": "upload",
            },
        })

    def _handle_upload_rename(self, case_id: str) -> None:
        body = self._body()
        label = sanitize_case_label(body.get("label") or body.get("case_label"))
        if not label:
            return self._json({"error": "请填写病例名称。"}, 400)
        loaded = self._upload_manifest(case_id)
        if not loaded:
            return self._json({"error": "上传任务不存在。"}, 404)
        directory, manifest = loaded
        manifest["label"] = label
        (directory / ".upload.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        updated = 0
        for path in self.store.root.glob("*/agentic_state.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            request = data.get("request") if isinstance(data.get("request"), dict) else {}
            subject = Path(str(request.get("subject_dir") or "")).name
            if subject != case_id and str(data.get("case_id") or "") != case_id:
                continue
            request["case_label"] = label
            data["request"] = request
            data["case_label"] = label
            self.store.save(data)
            updated += 1
        self._json({"ok": True, "case": {"id": case_id, "label": label, "subject_dir": str(directory)}, "updated_runs": updated})

    def _handle_clinic_intake(self) -> None:
        body = self._body()
        run_id = str(body.get("run_id") or "").strip()
        if not run_id:
            return self._json({"error": "请先选择一条分析结果。"}, 400)
        errors = clinic_intake_errors(body)
        if errors:
            return self._json({"error": errors[0], "errors": errors}, 400)
        try:
            data = self.store.load(run_id)
        except FileNotFoundError:
            return self._json({"error": "找不到该分析记录。"}, 404)
        if not data:
            return self._json({"error": "找不到该分析记录。"}, 404)
        intake = normalized_clinical_intake(body)
        request = dict(data.get("request") or {})
        plan = dict(data.get("plan") or {})
        request.update(intake)
        plan.update(intake)
        data["request"] = request
        data["plan"] = plan
        data["clinical_intake"] = intake
        try:
            task_plan = task_plan_from_dict(plan)
        except TypeError:
            task_plan = None
        if task_plan is not None:
            data["report_markdown"] = refresh_case_record_section(
                data.get("report_markdown") or "",
                task_plan,
                data.get("step_results") or [],
            )
        saved = self.store.save(data)
        self._json({"ok": True, "run_id": run_id, "intake": intake, "report_markdown": saved.get("report_markdown")})

    def _persist_run_state(self, state: RunState) -> dict:
        """Save execution progress without wiping concurrent clinical intake edits."""
        data = state.to_dict()
        try:
            current = self.store.load(state.run_id)
        except FileNotFoundError:
            current = {}
        intake = current.get("clinical_intake") if isinstance(current, dict) else None
        if isinstance(intake, dict):
            data["clinical_intake"] = intake
            request = dict(data.get("request") or {})
            plan = dict(data.get("plan") or {}) if data.get("plan") else None
            request.update({key: intake[key] for key in _INTAKE_FIELDS if key in intake})
            data["request"] = request
            state.request = request
            if plan is not None:
                plan.update({key: intake[key] for key in _INTAKE_FIELDS if key in intake})
                data["plan"] = plan
                state.plan = plan
            state.clinical_intake = intake
        for key in ("case_id", "case_label"):
            if data.get(key) in (None, "") and isinstance(current, dict) and current.get(key):
                data[key] = current[key]
                setattr(state, key, current[key])
        return self.store.save(data)

    def _sync_task_plan_intake(self, task_plan, state: RunState):
        intake = state.clinical_intake
        if not isinstance(intake, dict):
            try:
                current = self.store.load(state.run_id)
            except FileNotFoundError:
                return task_plan
            intake = current.get("clinical_intake") if isinstance(current, dict) else None
        if not isinstance(intake, dict):
            return task_plan
        for key in _INTAKE_FIELDS:
            if key in intake:
                setattr(task_plan, key, intake[key])
        return task_plan

    def _handle_plan(self, execute: bool) -> None:
        payload = self._body()
        if payload.get("clinic") or payload.get("case_id"):
            payload = apply_clinic_defaults(payload)
        raw_text = payload.pop("raw_text", "")
        payload.pop("clinic", None)
        payload.pop("case_id", None)
        request, request_event = coordinate_with_llm(raw_text, payload, self.llm)
        task_plan, plan_event = plan_with_llm(request, self.llm)
        config = load_llm_config(PROJECT_ROOT)
        errors = validate_agentic_objects(PROJECT_ROOT, request.to_dict(), task_plan.to_dict()) + validate_plan(task_plan) + validate_runtime(task_plan, config.ants_dir, config.roi_warp_env)
        conflicts = request_event.get("dashboard_conflicts", [])
        errors.extend(
            f"Request/Dashboard conflict for {item['field']}: natural language={item['natural_language']!r}, dashboard={item['dashboard']!r}. Dashboard fields take precedence."
            for item in conflicts
        )
        run_id = self.store.new_run_id()
        state = RunState(run_id=run_id, status="planned", request=request.to_dict(), plan=task_plan.to_dict())
        run_dir = self.store.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "task_plan.json").write_text(json.dumps(task_plan.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        if errors:
            state.status = "failed"
            failure = summarize_plan_failure(errors, conflicts)
            state.report_markdown, state.report_json = build_plan_failure_report(
                task_plan, failure, llm_events=[request_event, plan_event],
            )
        elif execute:
            state.status = "running"
            state.report_json = {"llm": {"events": [request_event, plan_event]}, "validation": {"errors": []}}
            self.store.save(state)
            worker = threading.Thread(
                target=self._execute_run,
                args=(state, task_plan, run_id, request_event, plan_event),
                daemon=True,
                name=f"autorecon-{run_id}",
            )
            worker.start()
        else:
            state.report_markdown = "# Plan ready\n\nReview the validated plan, then click Run / Demo to execute it.\n"
            state.report_json = {"llm": {"events": [request_event, plan_event]}, "validation": {"errors": []}}

        saved = self.store.save(state)
        self._json({"run_id": run_id, "request": request.to_dict(), "plan": task_plan.to_dict(), "state": saved})

    def _handle_confirmed_run(self) -> None:
        payload = self._body()
        run_id = str(payload.get("confirmed_run_id") or "")
        if not run_id:
            return self._json({"error": "Generate and review a plan before execution."}, 409)
        data = self.store.load(run_id)
        if data.get("status") != "planned":
            return self._json({"error": f"Run {run_id} is not awaiting confirmation."}, 409)
        request = user_request_from_dict(data["request"])
        task_plan = task_plan_from_dict(data["plan"])
        config = load_llm_config(PROJECT_ROOT)
        errors = validate_agentic_objects(PROJECT_ROOT, request.to_dict(), task_plan.to_dict()) + validate_plan(task_plan) + validate_runtime(task_plan, config.ants_dir, config.roi_warp_env)
        if errors:
            return self._json({"error": "Confirmed plan is no longer valid.", "errors": errors}, 409)
        state = RunState(**{key: value for key, value in data.items() if key in RunState.__dataclass_fields__})
        state.status = "running"
        self.store.save(state)
        events = ((data.get("report_json") or {}).get("llm") or {}).get("events") or []
        request_event = next((item for item in events if item.get("stage") == "request_parsing"), {})
        plan_event = next((item for item in events if item.get("stage") == "planning"), {})
        threading.Thread(
            target=self._execute_run, args=(state, task_plan, run_id, request_event, plan_event),
            daemon=True, name=f"autorecon-{run_id}",
        ).start()
        self._json({"run_id": run_id, "request": request.to_dict(), "plan": task_plan.to_dict(), "state": state.to_dict()})

    def _execute_run(self, state: RunState, task_plan, run_id: str, request_event: dict, plan_event: dict) -> None:
        try:
            if task_plan.execution_mode in {"run_pipeline", "continue_from_run"} and task_plan.work_root:
                work_root = Path(task_plan.work_root).expanduser().resolve()
                state.dashboard = {
                    "dashboard_dir": str(work_root / "dashboard"),
                    "dashboard_file": str(work_root / "dashboard" / "index.html"),
                    "dashboard_state": str(work_root / "dashboard" / "run_state.json"),
                    "url": "http://127.0.0.1:8765",
                }
                self._persist_run_state(state)
            results, dashboard = self.executor.execute(task_plan, run_id, self.dashboard_url)
            state.step_results = results
            state.dashboard = dashboard
            failed = results_indicate_failure(results)
            state.status = "running"
            state.report_markdown = "# 报告生成中\n\n结果与可视化已就绪，正在单独生成技术分析报告……\n"
            state.report_json = {
                "phase": "reporting",
                "visualization_ready": True,
                "llm": {"events": [request_event, plan_event]},
            }
            # Publish visualization/QC immediately. Report generation may use
            # remote LLM calls and must not delay access to imported artifacts.
            self._persist_run_state(state)
            result_event = analyze_results_with_llm(results, self.llm)
            task_plan = self._sync_task_plan_intake(task_plan, state)
            state.report_markdown, state.report_json = build_report(
                task_plan, results, dashboard, self.llm, [request_event, plan_event, result_event]
            )
            state.status = "failed" if failed else "completed"
            if failed:
                failure = summarize_execution_failure(results)
                state.report_json["failure"] = failure
                state.report_markdown = prepend_failure_banner(
                    state.report_markdown, failure, zh=str(task_plan.report_language or "auto").lower() != "en",
                )
        except Exception as exc:
            state.status = "failed"
            failure = summarize_execution_failure(exc=exc)
            zh = str(getattr(task_plan, "report_language", "auto") or "auto").lower() != "en"
            if zh:
                state.report_markdown = (
                    "# 分析未完成\n\n"
                    f"> [!refusal]\n> **运行异常**\n> {failure['summary_zh']}\n\n"
                    f"## 需要处理\n- {failure['next_action_zh']}\n\n"
                    f"```\n{type(exc).__name__}: {exc}\n```\n"
                )
            else:
                state.report_markdown = f"# Execution failed\n\n{type(exc).__name__}: {exc}\n"
            state.report_json = {
                "error": f"{type(exc).__name__}: {exc}",
                "failure": failure,
                "errors": list(failure.get("errors") or []),
            }
        self._persist_run_state(state)

    def _recover_state_if_needed(self, data: dict | None) -> dict | None:
        if not data or data.get("status") != "running":
            return data
        # Imported artifacts are already available while the report is being
        # generated. Never reinterpret that reporting phase as a recoverable
        # live pipeline run; doing so can overwrite imported results with an
        # empty collection.
        if (data.get("plan") or {}).get("execution_mode") == "import_existing":
            return data
        dashboard_path = Path((data.get("dashboard") or {}).get("dashboard_state") or "")
        if not dashboard_path.is_file():
            return data
        try:
            pipeline_state = json.loads(dashboard_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return data
        pipeline_status = pipeline_state.get("run", {}).get("status")
        reporting = (data.get("report_json") or {}).get("phase") == "reporting"
        if reporting and pipeline_status not in {"completed", "failed"}:
            return data
        run_id = str(data.get("run_id"))
        task_plan = task_plan_from_dict(data["plan"])
        if pipeline_status in {"completed", "failed"}:
            results, dashboard = self.executor.collect_pipeline_results(task_plan, run_id)
            state = RunState(**{key: value for key, value in data.items() if key in RunState.__dataclass_fields__})
            state.step_results = results; state.dashboard = dashboard; state.status = pipeline_status
            state.report_markdown, state.report_json = build_report(
                task_plan, results, dashboard, llm=None,
                llm_events=[{"stage": "recovery", "used": False, "reason": "dashboard_state_reconciliation"}],
            )
            if pipeline_status == "failed":
                failure = summarize_execution_failure(results)
                state.report_json["failure"] = failure
                state.report_markdown = prepend_failure_banner(
                    state.report_markdown,
                    failure,
                    zh=str(getattr(task_plan, "report_language", "auto") or "auto").lower() != "en",
                )
            return self.store.save(state)
        pid_path = dashboard_path.parent / "pipeline.pid"
        alive = False
        if pid_path.is_file():
            try:
                os.kill(int(pid_path.read_text().strip()), 0); alive = True
            except (OSError, ValueError):
                alive = False
        updated = pipeline_state.get("run", {}).get("updated_at")
        age = 0.0
        if updated:
            try: age = (datetime.now(timezone.utc) - datetime.fromisoformat(updated)).total_seconds()
            except ValueError: age = 0.0
        if not alive and age > 1800:
            state = RunState(**{key: value for key, value in data.items() if key in RunState.__dataclass_fields__})
            state.status = "failed"
            state.report_markdown = "# Execution interrupted\n\nThe agent server restarted and no live pipeline process was found. Resume from verified artifacts.\n"
            state.report_json = {"error": "stale_running_state", "recovery": {"pipeline_alive": False, "last_update_age_seconds": age}}
            return self.store.save(state)
        return data

    def _serve_file(self, raw_path: str) -> None:
        path = resolve_relocated_run_file(Path(unquote(raw_path)))
        if self._is_denied_file(path):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not any(path == root or root in path.parents for root in self.allow_roots):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if path.is_dir():
            items = []
            try:
                children = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
            except OSError:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            for child in children:
                if self._is_denied_file(child):
                    continue
                label = child.name + ("/" if child.is_dir() else "")
                href = "/api/file?path=" + quote(str(child), safe="")
                items.append(f'<li><a href="{href}">{html.escape(label)}</a></li>')
            title = html.escape(str(path))
            body = (
                "<!doctype html><html><head><meta charset=\"utf-8\">"
                f"<title>{title}</title>"
                "<style>body{font:15px system-ui;margin:2rem;line-height:1.6}"
                "ul{padding-left:1.4rem}a{color:#1769aa;text-decoration:none}"
                "a:hover{text-decoration:underline}</style></head><body>"
                f"<h2>{title}</h2><ul>{''.join(items)}</ul></body></html>"
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        if path.name.endswith("_interactive.html"):
            data = refreshed_interactive_html(path, data)
            content_type = "text/html; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_dashboard_state(self, raw_path: str) -> None:
        path = Path(unquote(raw_path)).expanduser().resolve()
        if (
            path.name != "run_state.json"
            or self._is_denied_file(path)
            or not any(path == root or root in path.parents for root in self.allow_roots)
            or not path.is_file()
        ):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._json(load_enriched_dashboard_state(path))

    def _serve_log_tail(self, raw_path: str, lines: int) -> None:
        path = Path(unquote(raw_path)).expanduser().resolve()
        if self._is_denied_file(path) or not any(path == root or root in path.parents for root in self.allow_roots):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not path.is_file() or path.suffix.lower() != ".log":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            tail = list(deque(handle, maxlen=lines))
        self._json({"text": "".join(tail).rstrip(), "line_count": len(tail)})

    def _is_denied_file(self, path: Path) -> bool:
        denied_names = {".env", ".env.local", ".envrc"}
        if path.name in denied_names or path.name.startswith(".env."):
            return True
        return any(part in {".git", ".codex", ".agents"} for part in path.parts)


def _bind_server(
    host: str,
    port: int,
    handler: type[BaseHTTPRequestHandler],
    *,
    auto_port: bool,
    port_search_limit: int = 100,
) -> ThreadingHTTPServer:
    """Bind the requested port, optionally falling forward to the next free one."""
    attempts = port_search_limit + 1 if auto_port else 1
    for offset in range(attempts):
        candidate = port + offset
        if candidate > 65535:
            break
        try:
            return ThreadingHTTPServer((host, candidate), handler)
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE or not auto_port:
                raise
    raise OSError(
        errno.EADDRINUSE,
        f"No available port found in range {port}-{min(port + port_search_limit, 65535)}",
    )


def serve(host: str, port: int, run_root: Path, *, auto_port: bool = True) -> None:
    store = StateStore(run_root)
    executor = AgenticExecutor(PROJECT_ROOT, run_root)
    handler = AgenticHandler
    handler.store = store
    handler.executor = executor
    handler.allow_roots = [PROJECT_ROOT.resolve(), run_root.resolve(), Path("/tmp").resolve()]
    handler.llm = OpenAICompatibleClient(load_llm_config(PROJECT_ROOT))
    server = _bind_server(host, port, handler, auto_port=auto_port)
    actual_port = int(server.server_address[1])
    handler.dashboard_url = f"http://{host}:{actual_port}"
    if actual_port != port:
        print(f"Port {port} is in use; using {actual_port} instead.")
    print(f"Agentic dashboard: http://{host}:{actual_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAgentic dashboard stopped.")
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the AutoRecon agentic dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    parser.add_argument(
        "--strict-port",
        action="store_true",
        help="Fail instead of automatically trying the next port when --port is occupied.",
    )
    parser.add_argument("--run-root", default=str(DEFAULT_RUN_ROOT))
    args = parser.parse_args()
    serve(args.host, args.port, Path(args.run_root), auto_port=not args.strict_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
