#!/usr/bin/env python3
"""Chinese clinic-styled interactive viewers shared by new runs and archived HTML."""

from __future__ import annotations

import json
import re
from pathlib import Path

from agentic.legacy_paths import rewrite_legacy_file_urls

STEP_TITLE_ZH = {
    "extraction": "脑提取",
    "reconstruction": "三维重建",
    "registration": "图像配准",
    "tissue": "组织分割",
    "roi": "脑区划分",
    "surface": "表面重建",
}

TITLE_SUFFIX_TO_STEP = (
    (": all extraction stacks", "extraction"),
    (": reconstructed MRI", "reconstruction"),
    (": registered MRI", "registration"),
    (": tissue segmentation", "tissue"),
    (": ROI segmentation", "roi"),
    (": interactive surface", "surface"),
    (": surface reconstruction", "surface"),
    (": extraction", "extraction"),
    (": reconstruction", "reconstruction"),
    (": registration", "registration"),
    (": tissue", "tissue"),
    (": roi", "roi"),
    (": surface", "surface"),
)

OVERLAY_LABEL_ZH = {
    "Tissue labels": "组织标签",
    "ROI labels": "脑区标签",
    "Labels": "标签",
}

SURFACE_MODEL_LABEL_ZH = {
    "LH white": "左侧白质面",
    "RH white": "右侧白质面",
    "LH pial": "左侧软脑膜面",
    "RH pial": "右侧软脑膜面",
}

SURFACE_MODELS = (
    ("lh", "white", "左侧白质面"),
    ("rh", "white", "右侧白质面"),
    ("lh", "pial", "左侧软脑膜面"),
    ("rh", "pial", "右侧软脑膜面"),
)

_STACK_PAYLOAD = re.compile(
    r"const TITLE=(.+?),SEQUENCES=(.+?);\s*const q=id=>",
    re.DOTALL,
)
_MPR_PAYLOAD = re.compile(r"const TITLE=(.+?),DATA=(.+?);const q=id=>", re.DOTALL)
_SURFACE_PAYLOAD = re.compile(
    r"const TITLE\s*=\s*(.+?);\s*const MODELS\s*=\s*(.+?);\s*const canvas",
    re.DOTALL,
)


def clinic_viewer_title(subject_name: str, step_id: str) -> str:
    label = STEP_TITLE_ZH.get(step_id, step_id)
    subject = str(subject_name or "").strip()
    return f"{subject} · {label}" if subject else label


def infer_step_id(title: str, path: Path | None = None) -> str | None:
    name = path.name if path else ""
    for step_id in STEP_TITLE_ZH:
        if f"_{step_id}_interactive" in name:
            return step_id
    text = str(title or "").strip()
    for suffix, step_id in TITLE_SUFFIX_TO_STEP:
        if text.endswith(suffix):
            return step_id
    for step_id, label in STEP_TITLE_ZH.items():
        if text == label or text.endswith(f" · {label}") or text.endswith(f": {label}"):
            return step_id
        if text.lower().endswith(f": {step_id}") or text.lower().endswith(f" · {step_id}"):
            return step_id
    return None


def localize_viewer_title(title: str, path: Path | None = None) -> str:
    text = str(title or "").strip()
    step_id = infer_step_id(text, path)
    if not step_id:
        return text
    subject = text
    for suffix, mapped in TITLE_SUFFIX_TO_STEP:
        if mapped == step_id and subject.endswith(suffix):
            subject = subject[: -len(suffix)].rstrip()
            break
    else:
        for sep in (" · ", ": "):
            if sep in subject:
                head, tail = subject.rsplit(sep, 1)
                if tail in STEP_TITLE_ZH.values() or tail.lower() in STEP_TITLE_ZH:
                    subject = head
                    break
        if subject == STEP_TITLE_ZH[step_id]:
            subject = ""
    return clinic_viewer_title(subject, step_id)


def _localize_overlay_label(payload: str) -> str:
    updated = payload
    for english, chinese in OVERLAY_LABEL_ZH.items():
        updated = updated.replace(f'"overlay_label":"{english}"', f'"overlay_label":"{chinese}"')
        updated = updated.replace(f'"overlay_label": "{english}"', f'"overlay_label": "{chinese}"')
    return updated


def _localize_surface_labels(payload: str) -> str:
    updated = payload
    for english, chinese in SURFACE_MODEL_LABEL_ZH.items():
        updated = updated.replace(f'"label":"{english}"', f'"label":"{chinese}"')
        updated = updated.replace(f'"label": "{english}"', f'"label": "{chinese}"')
    return updated


def compose_stack_viewer_html(title: str, sequences_json: str, path: Path | None = None) -> str:
    title_json = json.dumps(localize_viewer_title(title, path), ensure_ascii=False)
    return STACK_VIEWER_HTML.replace("__TITLE__", title_json).replace("__SEQUENCES__", sequences_json)


def compose_mpr_viewer_html(title: str, manifest_json: str, path: Path | None = None) -> str:
    title_json = json.dumps(localize_viewer_title(title, path), ensure_ascii=False)
    return MPR_VIEWER_HTML.replace("__TITLE__", title_json).replace("__MANIFEST__", _localize_overlay_label(manifest_json))


def compose_surface_viewer_html(title: str, models_json: str, path: Path | None = None) -> str:
    localized = localize_viewer_title(title, path)
    title_json = json.dumps(localized, ensure_ascii=False)
    page_title = localized.replace("<", "").replace(">", "")
    return (
        SURFACE_VIEWER_HTML.replace("__PAGE_TITLE__", page_title)
        .replace("__TITLE__", title_json)
        .replace("__MODELS__", _localize_surface_labels(models_json))
    )


def extract_interactive_payload(html: str) -> tuple[str, str, str] | None:
    stack = _STACK_PAYLOAD.search(html)
    if stack:
        return "stack", stack.group(1), stack.group(2)
    mpr = _MPR_PAYLOAD.search(html)
    if mpr:
        return "mpr", mpr.group(1), mpr.group(2)
    surface = _SURFACE_PAYLOAD.search(html)
    if surface:
        return "surface", surface.group(1), surface.group(2)
    return None


def restyle_interactive_source(html: str, path: Path | None = None) -> str | None:
    payload = extract_interactive_payload(html)
    if payload is None:
        return None
    kind, title_json, body_json = payload
    try:
        title = json.loads(title_json)
    except json.JSONDecodeError:
        title = title_json.strip().strip('"')
    if kind == "stack":
        updated = compose_stack_viewer_html(title, body_json, path)
    elif kind == "mpr":
        updated = compose_mpr_viewer_html(title, body_json, path)
    else:
        updated = compose_surface_viewer_html(title, body_json, path)
    return rewrite_legacy_file_urls(updated)


def restyle_interactive_html(path: Path) -> bool:
    html = path.read_text(encoding="utf-8")
    updated = restyle_interactive_source(html, path)
    if updated is None or updated == html:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


def refreshed_interactive_html(path: Path, data: bytes) -> bytes:
    """Serve the current viewer chrome/runtime for archived interactive pages."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    updated = restyle_interactive_source(text, path)
    if not updated or updated == text:
        return data
    return updated.encode("utf-8")


STACK_VIEWER_HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>交互阅片</title><style>
:root{--brand:#9d1822;--brand-deep:#681019;--brand-soft:#f8e8e8;--brand-pale:#fff8f7;--ink:#20191a;--muted:#71666a;--line:#eadfe1;--paper:#f8f6f5;--panel:#fff;--gold:#bd9750;--x:#9d1822;--y:#bd9750;--z:#647d8d;--shadow:0 18px 48px rgba(87,28,34,.09)}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:radial-gradient(circle at 92% 4%,rgba(157,24,34,.07),transparent 24%),linear-gradient(145deg,#fbfaf9,var(--paper));color:var(--ink);font:14px/1.5 "Source Han Sans SC","Noto Sans SC","PingFang SC","Segoe UI",sans-serif}
.app{min-height:100%;display:grid;grid-template-rows:auto auto minmax(0,1fr) auto;gap:10px;padding:16px 18px 12px}
.topbar{display:flex;align-items:flex-end;justify-content:space-between;gap:24px}
.kicker{margin:0 0 4px;color:var(--brand);font-size:10px;font-weight:750;letter-spacing:.18em}
h1{margin:0;font-size:20px;line-height:1.25;letter-spacing:-.02em;font-weight:650}
.status{padding:7px 12px;border:1px solid rgba(157,24,34,.13);border-radius:999px;background:rgba(255,255,255,.88);color:var(--muted);font-size:11px;white-space:nowrap}
.toolbar{position:relative;display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding:9px 11px;background:rgba(255,255,255,.9);border:1px solid rgba(157,24,34,.12);border-radius:15px;box-shadow:0 10px 30px rgba(87,28,34,.06)}
.toolbar:before{content:"";position:absolute;left:16px;right:16px;top:0;height:2px;background:linear-gradient(90deg,transparent,var(--brand),var(--gold),transparent);opacity:.72}
.group{min-width:0;display:flex;align-items:center;gap:8px;margin-left:auto}.label{flex:0 0 auto;font-size:11px;color:var(--muted);font-weight:650}
.select,button{height:32px;border:1px solid #dfd2d4;border-radius:9px;background:#fff;color:var(--ink);font:inherit}
.select{width:100%;min-width:0;padding:0 26px 0 8px;font-size:12px}
.button{padding:0 10px;cursor:pointer}.button:hover,.button.active{border-color:var(--brand);background:var(--brand-pale)}
.button.primary{min-width:64px;border:0;color:#fff;font-weight:700;background:linear-gradient(135deg,#b62530,#7c111a)}
.icon-button{width:32px;padding:0;font-size:16px}
input[type=range]{appearance:none;width:100%;min-width:64px;height:4px;border-radius:99px;background:#eadfe1;accent-color:var(--brand)}
input[type=range]::-webkit-slider-thumb{appearance:none;width:14px;height:14px;border-radius:50%;background:#fff;border:4px solid var(--brand)}
.switch{position:relative;width:38px;height:22px}.switch input{opacity:0;position:absolute}
.switch span{position:absolute;inset:0;border-radius:99px;background:#d9cbce;transition:.18s}
.switch span:after{content:"";position:absolute;width:16px;height:16px;left:3px;top:3px;border-radius:50%;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.12);transition:.18s}
.switch input:checked+span{background:var(--brand)}.switch input:checked+span:after{transform:translateX(16px)}
.views{min-height:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.panel{min-width:0;min-height:0;display:grid;grid-template-rows:auto auto 1fr;background:linear-gradient(180deg,#fff,#fdfafa);border:1px solid rgba(157,24,34,.13);border-radius:15px;overflow:hidden;box-shadow:var(--shadow)}
.panel.is-focus{border-color:rgba(157,24,34,.35);box-shadow:0 0 0 1px rgba(157,24,34,.18),var(--shadow)}
.panel h2{margin:0;padding:8px 10px;display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:12px;font-weight:650}
.plane-name{display:flex;align-items:center;gap:7px}.plane-dot{width:8px;height:8px;border-radius:50%;background:var(--plane-color)}
.panel h2 .counter{color:var(--muted);font-size:11px;font-weight:500;font-variant-numeric:tabular-nums}
.panel-tools{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:6px;align-items:center;padding:0 8px 8px}
.panel-tools .slice-row{grid-column:1/-1;display:grid;grid-template-columns:auto minmax(0,1fr);gap:6px;align-items:center}
.viewport{min-height:0;position:relative;margin:0 8px 8px;border-radius:10px;overflow:hidden;background:radial-gradient(circle at 50% 42%,#383033 0%,#1d181a 64%,#140f11 100%);touch-action:none;cursor:grab}
.viewport.is-dragging{cursor:grabbing}
.viewport.empty{display:grid;place-items:center;color:#c5b6b8;font-size:12px;padding:16px;text-align:center}
.frame{position:absolute;left:50%;top:50%;display:grid;place-items:center;transform-origin:center center}
.frame img{grid-area:1/1;display:block;width:auto;height:auto;max-width:none;max-height:none;object-fit:contain;border-radius:6px;user-select:none;-webkit-user-drag:none}
.frame .mask{pointer-events:none}
.hint{display:flex;justify-content:space-between;gap:16px;color:var(--muted);font-size:11px}.hint strong{color:#4f4548;font-weight:650}
html.embedded .kicker,html.embedded header h1{display:none}html.embedded .app{padding:10px 12px;gap:8px}html.embedded .topbar{min-height:0}
@media(max-width:900px){.views{grid-template-columns:1fr}.app{padding:12px}.hint{flex-direction:column}}
</style></head><body><main class="app"><header class="topbar"><div><p class="kicker">交互阅片</p><h1 id="title"></h1></div><div class="status" id="status"></div></header>
<nav class="toolbar"><div class="group"><label class="switch" title="显示掩膜"><input id="maskOn" type="checkbox" checked><span></span></label><span class="label">掩膜</span><span class="label">不透明度</span><input id="opacity" type="range" min="0" max="100" value="45" title="掩膜不透明度，向右更不透明"></div></nav>
<section class="views" id="views"></section>
<footer class="hint"><span><strong>三面</strong> 按采集方向分列矢状 / 冠状 / 轴状，各列可切换同向序列</span><span><strong>操作</strong> 滚动切层 · Ctrl + 滚轮缩放 · 拖拽移动 · Alt + 拖拽旋转 · R 旋转 90°</span></footer></main>
<script>if(window.self!==window.top)document.documentElement.classList.add("embedded");
const TITLE=__TITLE__,SEQUENCES=__SEQUENCES__;
const q=id=>document.getElementById(id);
const imageCache=new Map();
const ORIENTS=[{id:"sagittal",title:"矢状面",color:"var(--x)"},{id:"coronal",title:"冠状面",color:"var(--y)"},{id:"axial",title:"轴状面",color:"var(--z)"}];
const FRAME_MS=160,MIN_ZOOM=0.25,MAX_ZOOM=8,DEFAULT_VIEW_PX=420;
q("title").textContent=TITLE;
function inferOrientation(item){if(item&&item.orientation)return item.orientation;const n=String(item&&item.name||"").toLowerCase();if(/sag|矢/.test(n))return"sagittal";if(/cor|冠/.test(n))return"coronal";if(/ax|tra|轴/.test(n))return"axial";return"unknown"}
function sequencesFor(orient){return SEQUENCES.map((item,index)=>({item,index,orientation:inferOrientation(item)})).filter(entry=>entry.orientation===orient)}
const groups={};ORIENTS.forEach(spec=>{groups[spec.id]=sequencesFor(spec.id)});
const knownCount=ORIENTS.reduce((n,spec)=>n+(groups[spec.id].length?1:0),0);
const useTriplane=knownCount>=2;
const panels=[];
let focusPanel=0,playPanel=null,timer=null,playing=false,loading=false,playToken=0;
function clamp(v,max){return Math.max(0,Math.min(max,v))}
function loadImage(url){if(!url)return Promise.resolve(true);if(imageCache.has(url))return imageCache.get(url);const promise=new Promise(resolve=>{const image=new Image();image.onload=async()=>{try{await image.decode()}catch(_){}resolve(true)};image.onerror=()=>{imageCache.delete(url);resolve(false)};image.src=url});imageCache.set(url,promise);return promise}
function warm(item,index){for(let offset=1;offset<=6;offset++){const next=(index+offset)%item.count;loadImage(item.raw[next]);loadImage(item.mask[next])}}
function stopPlay(){playing=false;loading=false;playToken++;if(timer){clearTimeout(timer);timer=null}if(playPanel!=null&&panels[playPanel]){const btn=panels[playPanel].root.querySelector("[data-play]");if(btn){btn.disabled=false;btn.textContent="播放"}}playPanel=null}
function applyMaskOpacity(){const value=Number(q("opacity").value)/100;document.querySelectorAll(".mask").forEach(node=>{node.style.opacity=value})}
function setFocus(panelIndex){focusPanel=panelIndex;panels.forEach((panel,index)=>panel.root.classList.toggle("is-focus",index===panelIndex))}
function layoutPanel(panel){const raw=panel.raw,mask=panel.mask,nw=raw.naturalWidth||0,nh=raw.naturalHeight||0;if(!nw||!nh)return;const box=panel.viewport.getBoundingClientRect();const maxW=Math.max(48,Math.min(DEFAULT_VIEW_PX,box.width-16)),maxH=Math.max(48,Math.min(DEFAULT_VIEW_PX,box.height-16));const fit=Math.min(maxW/nw,maxH/nh);const w=nw*fit*panel.zoom,h=nh*fit*panel.zoom;raw.style.width=w+"px";raw.style.height=h+"px";mask.style.width=w+"px";mask.style.height=h+"px";panel.frame.style.transform=`translate(-50%,-50%) translate(${panel.panX}px,${panel.panY}px) rotate(${panel.rotate}deg)`}
async function renderPanel(panel){const token=++panel.renderToken;if(!panel.entries.length){panel.viewport.classList.add("empty");panel.viewport.textContent="本检查无此方向序列";panel.counter.textContent="";return}panel.viewport.classList.remove("empty");if(!panel.viewport.contains(panel.frame)){panel.viewport.textContent="";panel.viewport.appendChild(panel.frame)}const entry=panel.entries[panel.sequencePos];const item=entry.item;panel.sliceIndex=clamp(panel.sliceIndex,item.count-1);const rawUrl=item.raw[panel.sliceIndex],maskUrl=item.mask[panel.sliceIndex];const loaded=await Promise.all([loadImage(rawUrl),loadImage(maskUrl)]);if(!loaded[0]||token!==panel.renderToken)return;panel.raw.src=rawUrl;panel.mask.src=maskUrl||"";panel.mask.style.display=q("maskOn").checked&&maskUrl?"block":"none";panel.mask.style.opacity=Number(q("opacity").value)/100;panel.slice.max=String(item.count-1);panel.slice.value=String(panel.sliceIndex);panel.counter.textContent=`${panel.sliceIndex+1} / ${item.count}`;panel.select.value=String(panel.sequencePos);layoutPanel(panel);warm(item,panel.sliceIndex);updateStatus()}
function updateStatus(){const parts=panels.filter(p=>p.entries.length).map(p=>`${p.spec.title[0]}${p.sequencePos+1}/${p.entries.length}`);q("status").textContent=parts.length?`序列 ${SEQUENCES.length} · ${parts.join(" · ")}`:`序列 ${SEQUENCES.length}`}
function movePanel(panel,delta){if(!panel.entries.length)return;const item=panel.entries[panel.sequencePos].item;panel.sliceIndex=clamp(panel.sliceIndex+delta,item.count-1);renderPanel(panel)}
async function playLoop(panel,token,nextAt){if(!playing||token!==playToken||playPanel!==panel.index)return;const item=panel.entries[panel.sequencePos].item;panel.sliceIndex=(panel.sliceIndex+1)%item.count;await renderPanel(panel);if(!playing||token!==playToken)return;const following=nextAt+FRAME_MS;timer=setTimeout(()=>playLoop(panel,token,following),Math.max(0,following-performance.now()))}
async function startPlay(panel){if(playing||loading||!panel.entries.length)return;stopPlay();loading=true;playPanel=panel.index;const btn=panel.root.querySelector("[data-play]");btn.disabled=true;btn.textContent="载入中";const item=panel.entries[panel.sequencePos].item;const ready=await Promise.all([...item.raw,...item.mask].filter(Boolean).map(loadImage)).then(r=>r.every(Boolean));if(playPanel!==panel.index)return;loading=false;btn.disabled=false;if(!ready){btn.textContent="重试";return}playing=true;btn.textContent="暂停";const token=++playToken;playLoop(panel,token,performance.now())}
function buildPanel(spec,entries,index){const panel={spec,entries,index,sequencePos:0,sliceIndex:0,zoom:1,panX:0,panY:0,rotate:0,renderToken:0,dragging:false,rotating:false,dragX:0,dragY:0};
const root=document.createElement("article");root.className="panel";root.style.setProperty("--plane-color",spec.color);
root.innerHTML=`<h2><span class="plane-name"><i class="plane-dot"></i>${spec.title}</span><span class="counter"></span></h2><div class="panel-tools"><select class="select" data-seq></select><div><button class="button icon-button" data-prev title="上一层">‹</button><button class="button primary" data-play>播放</button><button class="button icon-button" data-next title="下一层">›</button><button class="button" data-rotate title="顺时针旋转 90°">旋转</button></div><div class="slice-row"><span class="label">切片</span><input data-slice type="range"></div></div><div class="viewport"></div>`;
q("views").appendChild(root);
panel.root=root;panel.select=root.querySelector("[data-seq]");panel.slice=root.querySelector("[data-slice]");panel.counter=root.querySelector(".counter");panel.viewport=root.querySelector(".viewport");
panel.frame=document.createElement("div");panel.frame.className="frame";panel.raw=document.createElement("img");panel.raw.alt="MRI 切片";panel.mask=document.createElement("img");panel.mask.className="mask";panel.mask.alt="掩膜叠加";panel.frame.append(panel.raw,panel.mask);
if(!entries.length){panel.select.disabled=true;root.querySelectorAll("button,input").forEach(node=>node.disabled=true);panel.viewport.classList.add("empty");panel.viewport.textContent="本检查无此方向序列";return panel}
entries.forEach((entry,pos)=>{const opt=document.createElement("option");opt.value=String(pos);opt.textContent=entry.item.name;panel.select.appendChild(opt)});
panel.sliceIndex=Math.floor(entries[0].item.count/2);
panel.select.onchange=()=>{stopPlay();panel.sequencePos=Number(panel.select.value);panel.sliceIndex=Math.floor(panel.entries[panel.sequencePos].item.count/2);panel.zoom=1;panel.panX=0;panel.panY=0;panel.rotate=0;renderPanel(panel)};
panel.slice.oninput=()=>{stopPlay();panel.sliceIndex=Number(panel.slice.value);renderPanel(panel)};
root.querySelector("[data-prev]").onclick=()=>{stopPlay();setFocus(index);movePanel(panel,-1)};
root.querySelector("[data-next]").onclick=()=>{stopPlay();setFocus(index);movePanel(panel,1)};
root.querySelector("[data-play]").onclick=()=>{setFocus(index);if(playing&&playPanel===index){stopPlay();return}startPlay(panel)};
root.querySelector("[data-rotate]").onclick=()=>{setFocus(index);panel.rotate=(panel.rotate+90)%360;layoutPanel(panel)};
panel.viewport.addEventListener("pointerdown",e=>{if(e.button!==0)return;setFocus(index);panel.dragX=e.clientX;panel.dragY=e.clientY;if(e.altKey){panel.rotating=true;panel.dragging=false}else{panel.dragging=true;panel.rotating=false}panel.viewport.classList.add("is-dragging");panel.viewport.setPointerCapture(e.pointerId)});
panel.viewport.addEventListener("pointermove",e=>{if(panel.rotating){panel.rotate=(panel.rotate+(e.clientX-panel.dragX)*0.4)%360;if(panel.rotate<0)panel.rotate+=360;panel.dragX=e.clientX;panel.dragY=e.clientY;layoutPanel(panel);return}if(!panel.dragging)return;panel.panX+=e.clientX-panel.dragX;panel.panY+=e.clientY-panel.dragY;panel.dragX=e.clientX;panel.dragY=e.clientY;layoutPanel(panel)});
panel.viewport.addEventListener("pointerup",()=>{panel.dragging=false;panel.rotating=false;panel.viewport.classList.remove("is-dragging")});
panel.viewport.addEventListener("pointercancel",()=>{panel.dragging=false;panel.rotating=false;panel.viewport.classList.remove("is-dragging")});
panel.viewport.addEventListener("wheel",e=>{setFocus(index);if(e.ctrlKey||e.metaKey){e.preventDefault();panel.zoom=Math.max(MIN_ZOOM,Math.min(MAX_ZOOM,panel.zoom*(e.deltaY>0?0.9:1.12)));layoutPanel(panel);return}e.preventDefault();stopPlay();movePanel(panel,e.deltaY>0?1:-1)},{passive:false});
panel.viewport.addEventListener("dblclick",()=>{panel.zoom=1;panel.panX=0;panel.panY=0;panel.rotate=0;layoutPanel(panel)});
panel.raw.addEventListener("load",()=>layoutPanel(panel));
return panel}
if(useTriplane){ORIENTS.forEach((spec,index)=>panels.push(buildPanel(spec,groups[spec.id],index)))}
else{
  const all=SEQUENCES.map((item,index)=>({item,index,orientation:inferOrientation(item)}));
  q("views").style.gridTemplateColumns="1fr";
  panels.push(buildPanel({id:"all",title:"采集序列",color:"var(--brand)"},all,0));
}
q("maskOn").onchange=()=>panels.forEach(renderPanel);
q("opacity").oninput=applyMaskOpacity;
window.addEventListener("resize",()=>panels.forEach(layoutPanel));
window.addEventListener("keydown",e=>{
  const panel=panels[focusPanel];if(!panel||!panel.entries.length)return;
  if(e.key==="r"||e.key==="R"){if(e.ctrlKey||e.metaKey||e.altKey)return;e.preventDefault();panel.rotate=(panel.rotate+(e.shiftKey?-90:90))%360;if(panel.rotate<0)panel.rotate+=360;layoutPanel(panel);return}
  if(!(e.ctrlKey||e.metaKey))return;
  if(e.key==="0"){e.preventDefault();panel.zoom=1;panel.panX=0;panel.panY=0;panel.rotate=0;layoutPanel(panel);return}
  if(e.key==="-"||e.key==="_"||e.key==="="||e.key==="+"){e.preventDefault();panel.zoom=Math.max(MIN_ZOOM,Math.min(MAX_ZOOM,panel.zoom*((e.key==="-"||e.key==="_")?0.9:1.12)));layoutPanel(panel)}
});
setFocus(panels.findIndex(p=>p.entries.length)||0);
panels.forEach(renderPanel);
</script></body></html>'''

MPR_VIEWER_HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>交互阅片</title><style>
:root{--brand:#9d1822;--brand-deep:#681019;--brand-soft:#f8e8e8;--ink:#20191a;--muted:#71666a;--line:#eadfe1;--paper:#f8f6f5;--panel:#fff;--x:#9d1822;--y:#bd9750;--z:#647d8d;--shadow:0 16px 42px rgba(87,28,34,.1)}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:radial-gradient(circle at 92% 4%,rgba(157,24,34,.07),transparent 24%),linear-gradient(145deg,#fbfaf9,var(--paper));color:var(--ink);font:14px/1.5 "Source Han Sans SC","Noto Sans SC","PingFang SC","Segoe UI",sans-serif}
.app{min-height:100%;display:grid;grid-template-rows:auto auto minmax(300px,1fr) auto;gap:10px;padding:16px 18px 12px}
.topbar{display:flex;align-items:flex-end;justify-content:space-between;gap:24px}
.kicker{margin:0 0 4px;color:var(--brand);font-size:10px;font-weight:750;letter-spacing:.18em}
h1{margin:0;font-size:20px;line-height:1.25;letter-spacing:-.02em;font-weight:650}
.volume-meta{padding:6px 11px;border:1px solid rgba(157,24,34,.13);border-radius:999px;background:rgba(255,255,255,.88);color:var(--muted);font-size:11px;white-space:nowrap}
.toolbar{position:relative;display:grid;grid-template-columns:repeat(3,minmax(150px,1fr)) auto;align-items:center;gap:10px;padding:9px 11px;background:rgba(255,255,255,.9);border:1px solid rgba(157,24,34,.12);border-radius:15px;box-shadow:0 10px 30px rgba(87,28,34,.06);backdrop-filter:blur(12px)}
.toolbar:before{content:"";position:absolute;left:16px;right:16px;top:0;height:2px;background:linear-gradient(90deg,transparent,var(--brand),#bd9750,transparent);opacity:.72}
.axis-control{min-width:0;display:grid;grid-template-columns:25px minmax(60px,1fr) 52px;align-items:center;gap:7px}
.axis-tag{width:25px;height:25px;display:grid;place-items:center;border-radius:7px;color:#fff;font-size:11px;font-weight:700;box-shadow:0 4px 10px rgba(42,23,26,.12)}
.axis-tag.x{background:var(--x)}.axis-tag.y{background:var(--y)}.axis-tag.z{background:var(--z)}
.axis-value{font-size:10px;color:var(--muted);font-variant-numeric:tabular-nums;text-align:right}
input[type=range]{appearance:none;width:100%;height:4px;border-radius:99px;background:#eadfe1;accent-color:var(--brand)}
input[type=range]::-webkit-slider-thumb{appearance:none;width:15px;height:15px;border-radius:50%;background:#fff;border:4px solid var(--brand)}
.tools{display:flex;align-items:center;gap:7px;margin-left:auto;white-space:nowrap}
.button{height:32px;padding:0 10px;border:1px solid #dfd2d4;border-radius:9px;background:#fff;color:var(--ink);font:inherit;cursor:pointer}
.button:hover,.button.active{border-color:var(--brand);background:#fff8f7;color:var(--brand-deep)}
.overlay-tools{display:flex;align-items:center;gap:7px;padding-left:10px;border-left:1px solid var(--line)}
.overlay-tools[hidden]{display:none}.label{font-size:11px;color:var(--muted);font-weight:650}.overlay-tools input[type=range]{width:72px}
.views{min-height:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.panel{min-width:0;min-height:0;display:grid;grid-template-rows:auto 1fr;background:linear-gradient(180deg,#fff,#fdfafa);border:1px solid rgba(157,24,34,.13);border-radius:15px;overflow:hidden;box-shadow:var(--shadow)}
.panel h2{font-size:12px;margin:0;padding:8px 11px;display:flex;align-items:center;justify-content:space-between;font-weight:650}
.plane-name{display:flex;align-items:center;gap:8px}.plane-dot{width:8px;height:8px;border-radius:50%;background:var(--plane-color)}
.panel h2 .counter{color:var(--muted);font-size:12px;font-weight:500;font-variant-numeric:tabular-nums}
.viewport-shell{min-height:0;height:100%;container-type:size;display:grid;place-items:center;padding:0 8px 8px}
.image-layer{position:relative;aspect-ratio:var(--ar,1);width:min(100cqw,calc(100cqh * var(--ar,1)));height:min(100cqh,calc(100cqw / var(--ar,1)));overflow:hidden;background:radial-gradient(circle at center,#2d2729,#120f10 72%);border-radius:10px;box-shadow:inset 0 0 0 1px rgba(255,255,255,.05);touch-action:none;cursor:crosshair}
.image-layer.is-rotating{cursor:grabbing}
.view-transform{position:absolute;inset:0;transform-origin:center center;will-change:transform}
.view-transform img{display:block;width:100%;height:100%;object-fit:fill;user-select:none;-webkit-user-drag:none}
.view-transform .label-overlay{position:absolute;inset:0;pointer-events:none;object-fit:fill}
.cross-v,.cross-h{position:absolute;background:rgba(189,151,80,.9);pointer-events:none}
.cross-v{top:0;bottom:0;width:1px}.cross-h{left:0;right:0;height:1px}
.hint{display:flex;justify-content:space-between;gap:24px;color:var(--muted);font-size:11px}.hint strong{color:#4f4548;font-weight:650}
html.embedded .kicker,html.embedded header h1{display:none}html.embedded .app{padding-top:10px}
@media(max-width:1180px){.toolbar{grid-template-columns:repeat(3,minmax(140px,1fr))}.tools{grid-column:1/-1;justify-content:flex-end}}
@media(max-width:760px){.views{grid-template-columns:1fr}.toolbar{grid-template-columns:1fr}.tools{grid-column:auto;justify-content:flex-start;flex-wrap:wrap}.app{padding:12px}.hint{flex-direction:column}}
</style></head><body><main class="app"><header class="topbar"><div><p class="kicker">交互阅片</p><h1 id="title"></h1></div><div class="volume-meta" id="volumeMeta"></div></header>
<nav class="toolbar"><label class="axis-control"><span class="axis-tag x">矢</span><input id="x" type="range"><span class="axis-value" id="xv"></span></label><label class="axis-control"><span class="axis-tag y">冠</span><input id="y" type="range"><span class="axis-value" id="yv"></span></label><label class="axis-control"><span class="axis-tag z">轴</span><input id="z" type="range"><span class="axis-value" id="zv"></span></label><div class="tools"><button class="button" id="center">居中</button><button class="button active" id="crosshair">十字线</button><button class="button" id="rotate" title="当前视图顺时针旋转 90°">旋转 90°</button><div class="overlay-tools" id="overlayTools" hidden><button class="button active" id="overlayToggle"></button><span class="label">透明度</span><input id="overlayOpacity" type="range" min="0" max="100" value="0"></div></div></nav>
<section class="views" id="views"></section><footer class="hint"><span><strong>定位</strong> 点击任一视图移动十字线</span><span><strong>浏览</strong> 滚动切换切片 · Ctrl + 滚轮缩放 · Alt + 拖拽旋转 · R 旋转 90°</span></footer></main>
<script>if(window.self!==window.top)document.documentElement.classList.add("embedded");const TITLE=__TITLE__,DATA=__MANIFEST__;const q=id=>document.getElementById(id),dims=DATA.dims;let pos={x:Math.floor(dims.x/2),y:Math.floor(dims.y/2),z:Math.floor(dims.z/2)},showCrosshair=true,showOverlay=true,focusPlane="axial",rotations={sagittal:0,coronal:0,axial:0},rotatePlane=null,rotateLast=null;
const specs={sagittal:{title:"矢状面",normal:"x",h:"y",v:"z",invertV:true,color:"var(--x)"},coronal:{title:"冠状面",normal:"y",h:"x",v:"z",invertV:true,color:"var(--y)"},axial:{title:"轴状面",normal:"z",h:"x",v:"y",invertV:false,color:"var(--z)"}};q("title").textContent=TITLE;q("volumeMeta").textContent=`${dims.x} × ${dims.y} × ${dims.z} · ${DATA.spacing.map(v=>Number(v).toFixed(2)).join(" × ")} mm`;
function planeAspect(name,plane){const [sx,sy,sz]=(DATA.spacing||[1,1,1]).map(v=>Number(v)||1);const w=plane.width,h=plane.height;if(name==="sagittal")return (w*sy)/(h*sz);if(name==="coronal")return (w*sx)/(h*sz);return (w*sx)/(h*sy)}
function applyLayerView(layer,plane){const node=layer.querySelector(".view-transform");if(!node)return;const zoom=Number(layer.dataset.zoom||1);node.style.transform=`rotate(${rotations[plane]||0}deg) scale(${zoom})`}
function unrotatePoint(px,py,deg){if(!deg)return[px,py];const rad=-deg*Math.PI/180,cx=px-0.5,cy=py-0.5;return[cx*Math.cos(rad)-cy*Math.sin(rad)+0.5,cx*Math.sin(rad)+cy*Math.cos(rad)+0.5]}
Object.entries(specs).forEach(([name,spec])=>{const plane=DATA.planes[name],panel=document.createElement("article");panel.className="panel";panel.style.setProperty("--plane-color",spec.color);panel.innerHTML=`<h2><span class="plane-name"><i class="plane-dot"></i>${spec.title}</span><span class="counter"></span></h2><div class="viewport-shell"><div class="image-layer"><div class="view-transform"><img class="base" draggable="false"><img class="label-overlay" draggable="false"><i class="cross-v"></i><i class="cross-h"></i></div></div></div>`;panel.dataset.plane=name;q("views").appendChild(panel);const layer=panel.querySelector(".image-layer");layer.style.setProperty("--ar",String(planeAspect(name,plane)));layer.addEventListener("pointerdown",e=>{focusPlane=name;if(!(e.altKey||e.button===1))return;e.preventDefault();rotatePlane=name;rotateLast={x:e.clientX,y:e.clientY};layer.classList.add("is-rotating");layer.setPointerCapture(e.pointerId)});layer.addEventListener("pointermove",e=>{if(rotatePlane!==name||!rotateLast)return;rotations[name]=((rotations[name]||0)+(e.clientX-rotateLast.x)*0.4)%360;if(rotations[name]<0)rotations[name]+=360;rotateLast={x:e.clientX,y:e.clientY};applyLayerView(layer,name)});layer.addEventListener("pointerup",()=>{rotatePlane=null;rotateLast=null;layer.classList.remove("is-rotating")});layer.addEventListener("pointercancel",()=>{rotatePlane=null;rotateLast=null;layer.classList.remove("is-rotating")});layer.addEventListener("wheel",e=>{focusPlane=name;if(e.ctrlKey||e.metaKey){e.preventDefault();const scale=Number(layer.dataset.zoom||1),next=Math.max(0.25,Math.min(8,scale*(e.deltaY>0?0.9:1.12)));layer.dataset.zoom=String(next);applyLayerView(layer,name);return}e.preventDefault();pos[spec.normal]+=e.deltaY>0?1:-1;render()},{passive:false});layer.addEventListener("dblclick",()=>{rotations[name]=0;layer.dataset.zoom="1";applyLayerView(layer,name)});layer.onclick=e=>{if(e.altKey)return;focusPlane=name;const rect=layer.getBoundingClientRect();let px=(e.clientX-rect.left)/rect.width,py=(e.clientY-rect.top)/rect.height;[px,py]=unrotatePoint(px,py,rotations[name]||0);px=Math.max(0,Math.min(1,px));py=Math.max(0,Math.min(1,py));pos[spec.h]=Math.round(px*(dims[spec.h]-1));pos[spec.v]=Math.round((spec.invertV?1-py:py)*(dims[spec.v]-1));render()}});
for(const axis of ["x","y","z"]){q(axis).max=dims[axis]-1;q(axis).oninput=e=>{pos[axis]=Number(e.target.value);render()}}if(DATA.has_overlay){q("overlayTools").hidden=false;q("overlayToggle").textContent=DATA.overlay_label;q("overlayToggle").onclick=()=>{showOverlay=!showOverlay;q("overlayToggle").classList.toggle("active",showOverlay);render()};q("overlayOpacity").oninput=applyOverlayOpacity}
q("center").onclick=()=>{pos={x:Math.floor(dims.x/2),y:Math.floor(dims.y/2),z:Math.floor(dims.z/2)};render()};q("crosshair").onclick=()=>{showCrosshair=!showCrosshair;q("crosshair").classList.toggle("active",showCrosshair);render()};
q("rotate").onclick=()=>{rotations[focusPlane]=((rotations[focusPlane]||0)+90)%360;document.querySelectorAll(".panel").forEach(panel=>{if(panel.dataset.plane===focusPlane)applyLayerView(panel.querySelector(".image-layer"),focusPlane)})};
window.addEventListener("keydown",e=>{if(e.key!=="r"&&e.key!=="R")return;if(e.ctrlKey||e.metaKey||e.altKey)return;e.preventDefault();rotations[focusPlane]=((rotations[focusPlane]||0)+(e.shiftKey?-90:90))%360;if(rotations[focusPlane]<0)rotations[focusPlane]+=360;document.querySelectorAll(".panel").forEach(panel=>{if(panel.dataset.plane===focusPlane)applyLayerView(panel.querySelector(".image-layer"),focusPlane)})});
function clamp(){for(const axis of ["x","y","z"])pos[axis]=Math.max(0,Math.min(dims[axis]-1,pos[axis]))}function pct(axis,value,invert=false){const result=dims[axis]>1?value/(dims[axis]-1)*100:50;return invert?100-result:result}
function overlayOpacity(){return Math.max(0,Math.min(1,1-Number(q("overlayOpacity")?.value ?? 0)/100))}
function applyOverlayOpacity(){const value=overlayOpacity();document.querySelectorAll(".label-overlay").forEach(node=>{node.style.opacity=value})}
function setImageSrc(img,url){const next=url||"";if(!next){if(img.getAttribute("src"))img.removeAttribute("src");return}if(img.src!==new URL(next,document.baseURI).href)img.src=next}
function render(){clamp();for(const axis of ["x","y","z"]){q(axis).value=pos[axis];q(`${axis}v`).textContent=`${pos[axis]+1} / ${dims[axis]}`}document.querySelectorAll(".panel").forEach(panel=>{const name=panel.dataset.plane,spec=specs[name],plane=DATA.planes[name],index=pos[spec.normal],overlay=panel.querySelector(".label-overlay"),layer=panel.querySelector(".image-layer");setImageSrc(panel.querySelector(".base"),plane.images[index]);panel.querySelector(".counter").textContent=`${index+1} / ${dims[spec.normal]}`;setImageSrc(overlay,DATA.has_overlay?plane.overlays[index]:"");overlay.style.display=DATA.has_overlay&&showOverlay?"block":"none";overlay.style.opacity=overlayOpacity();panel.querySelectorAll(".cross-v,.cross-h").forEach(line=>line.style.display=showCrosshair?"block":"none");panel.querySelector(".cross-v").style.left=`${pct(spec.h,pos[spec.h])}%`;panel.querySelector(".cross-h").style.top=`${pct(spec.v,pos[spec.v],spec.invertV)}%`;applyLayerView(layer,name)})}render();</script></body></html>'''

SURFACE_VIEWER_HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>__PAGE_TITLE__</title>
  <style>
    :root {
      --brand: #9d1822;
      --brand-deep: #681019;
      --ink: #20191a;
      --muted: #71666a;
      --line: #eadfe1;
      --paper: #f8f6f5;
      --panel: #fff;
      --gold: #bd9750;
      --shadow: 0 18px 48px rgba(87,28,34,.1);
    }
    * { box-sizing: border-box; }
    html, body { margin: 0; height: 100%; background: radial-gradient(circle at 92% 4%,rgba(157,24,34,.07),transparent 24%),linear-gradient(145deg,#fbfaf9,var(--paper)); color: var(--ink); font: 14px/1.5 "Source Han Sans SC","Noto Sans SC","PingFang SC","Segoe UI",sans-serif; }
    .app { min-height: 100%; display: grid; grid-template-rows: auto auto minmax(320px,1fr) auto; gap: 10px; padding: 16px 18px 12px; }
    .kicker { margin: 0 0 4px; color: var(--brand); font-size: 10px; font-weight: 750; letter-spacing: .18em; }
    h1 { margin: 0; font-size: 20px; line-height: 1.25; letter-spacing: -.02em; font-weight: 650; }
    .controls { position:relative; display: flex; gap: 8px; flex-wrap: nowrap; align-items: center; padding: 9px 11px; border: 1px solid rgba(157,24,34,.12); border-radius: 15px; background: rgba(255,255,255,.9); box-shadow: 0 10px 30px rgba(87,28,34,.06); backdrop-filter:blur(12px); }
    .controls:before { content:""; position:absolute; left:16px; right:16px; top:0; height:2px; background:linear-gradient(90deg,transparent,var(--brand),var(--gold),transparent); opacity:.72; }
    .controls label { display: inline-flex; align-items: center; gap: 7px; color: var(--muted); font-size: 12px; font-weight: 650; white-space:nowrap; }
    .controls label:first-child { margin-right:auto; }
    select, button { height: 34px; border: 1px solid #dfd2d4; border-radius: 9px; padding: 0 11px; background: #fff; color: var(--ink); font: inherit; }
    button { cursor: pointer; }
    button:hover, select:hover { border-color: var(--brand); background: #fff8f7; }
    canvas { width: 100%; min-height: 0; height: 100%; max-height: 72vh; display: block; border-radius: 16px; background: radial-gradient(circle at 50% 42%,#fff 0%,#f2e8e9 72%,#e8dcde 100%); border: 1px solid rgba(157,24,34,.14); touch-action: none; box-shadow: var(--shadow); }
    .hint { margin:0; color: var(--muted); font-size: 11px; }
    html.embedded .kicker, html.embedded header h1 { display: none; }
    html.embedded .app { padding-top: 10px; }
    @media(max-width:700px){.controls{flex-wrap:wrap}.controls label:first-child{width:100%}.app{padding:12px}}
  </style>
</head>
<body>
  <main class="app">
    <header><p class="kicker">交互阅片</p><h1 id="title"></h1></header>
    <div class="controls">
      <label>表面 <select id="surfaceSelect"></select></label>
      <label><input id="showMesh" type="checkbox" checked> 网格</label>
      <label><input id="showRoi" type="checkbox" checked> 脑区着色</label>
      <button id="resetBtn" type="button">复位视角</button>
    </div>
    <canvas id="viewer" width="1200" height="860"></canvas>
    <p class="hint">拖拽旋转视角 · Ctrl + 滚轮缩放 · 复位视角。首次切换表面时会载入完整网格。</p>
  </main>
  <script>
    if(window.self!==window.top)document.documentElement.classList.add("embedded");
    const TITLE=__TITLE__;const MODELS=__MODELS__;const canvas = document.getElementById("viewer");
    const gl = canvas.getContext("webgl2", { antialias: true, alpha: true });
    const surfaceSelect = document.getElementById("surfaceSelect");
    const showMesh = document.getElementById("showMesh");
    const showRoi = document.getElementById("showRoi");
    const resetBtn = document.getElementById("resetBtn");
    document.getElementById("title").textContent = TITLE;

    if (!gl) {
      canvas.replaceWith(Object.assign(document.createElement("div"), {
        textContent: "当前浏览器无法启用 WebGL2，三维表面无法显示。",
        className: "hint"
      }));
      throw new Error("WebGL2 unavailable");
    }

    const meshVsSource = `#version 300 es
      in vec3 aPosition;
      in vec3 aNormal;
      in vec3 aRoiColor;
      in float aRoiMask;
      uniform mat4 uProjection;
      uniform mat4 uView;
      out float vLight;
      out vec3 vRoiColor;
      out float vRoiMask;
      void main() {
        vec3 lightDir = normalize(vec3(0.35, -0.25, 0.9));
        vec3 normal = normalize(mat3(uView) * aNormal);
        vLight = max(0.18, dot(normal, lightDir) * 0.45 + 0.55);
        vRoiColor = aRoiColor;
        vRoiMask = aRoiMask;
        gl_Position = uProjection * uView * vec4(aPosition, 1.0);
      }
    `;

    const meshFsSource = `#version 300 es
      precision mediump float;
      in float vLight;
      in vec3 vRoiColor;
      in float vRoiMask;
      uniform float uShowMesh;
      uniform float uShowRoi;
      out vec4 outColor;
      void main() {
        vec3 base = vec3(0.86, 0.81, 0.80);
        vec3 litBase = base * vLight;
        vec3 litRoi = mix(vRoiColor * 0.72, vRoiColor, min(1.0, vLight + 0.18));
        float overlay = uShowRoi * clamp(vRoiMask, 0.0, 1.0);
        if (uShowMesh < 0.5) {
          if (overlay < 0.04) discard;
          outColor = vec4(litRoi, 1.0);
          return;
        }
        outColor = vec4(mix(litBase, litRoi, overlay * 0.86), 1.0);
      }
    `;

    function compileShader(type, source) {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        throw new Error(gl.getShaderInfoLog(shader) || "Shader compile failed");
      }
      return shader;
    }

    function createProgram(vsSource, fsSource) {
      const program = gl.createProgram();
      gl.attachShader(program, compileShader(gl.VERTEX_SHADER, vsSource));
      gl.attachShader(program, compileShader(gl.FRAGMENT_SHADER, fsSource));
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
        throw new Error(gl.getProgramInfoLog(program) || "Program link failed");
      }
      return program;
    }

    const meshProgram = createProgram(meshVsSource, meshFsSource);
    const meshHandles = {
      position: gl.getAttribLocation(meshProgram, "aPosition"),
      normal: gl.getAttribLocation(meshProgram, "aNormal"),
      roiColor: gl.getAttribLocation(meshProgram, "aRoiColor"),
      roiMask: gl.getAttribLocation(meshProgram, "aRoiMask"),
      projection: gl.getUniformLocation(meshProgram, "uProjection"),
      view: gl.getUniformLocation(meshProgram, "uView"),
      showMesh: gl.getUniformLocation(meshProgram, "uShowMesh"),
      showRoi: gl.getUniformLocation(meshProgram, "uShowRoi"),
    };

    MODELS.forEach((model, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = model.label;
      surfaceSelect.appendChild(option);
    });

    function decodeArray(encoded, ArrayType) {
      const binary = atob(encoded);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i);
      }
      return new ArrayType(bytes.buffer);
    }

    function buildGpuModel(model) {
      const gpu = {};
      gpu.indexCount = model.index_count;
      gpu.vertexBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, gpu.vertexBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, decodeArray(model.vertices, Float32Array), gl.STATIC_DRAW);
      gpu.normalBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, gpu.normalBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, decodeArray(model.normals, Float32Array), gl.STATIC_DRAW);
      gpu.indexBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gpu.indexBuffer);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, decodeArray(model.faces, Uint32Array), gl.STATIC_DRAW);
      gpu.roiColorBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, gpu.roiColorBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, decodeArray(model.roi_vertex_colors, Float32Array), gl.STATIC_DRAW);
      gpu.roiMaskBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, gpu.roiMaskBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, decodeArray(model.roi_vertex_mask, Float32Array), gl.STATIC_DRAW);
      return gpu;
    }

    const GPU_MODELS = new Array(MODELS.length);
    function getGpuModel(index) {
      if (!GPU_MODELS[index]) GPU_MODELS[index] = buildGpuModel(MODELS[index]);
      return GPU_MODELS[index];
    }

    let rotX = -0.25;
    let rotY = 0.72;
    let zoom = 1.7;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let renderQueued = false;

    function resetView() {
      rotX = -0.25;
      rotY = 0.72;
      zoom = 1.7;
      queueRender();
    }

    function perspectiveMatrix(fovY, aspect, near, far) {
      const f = 1.0 / Math.tan(fovY / 2.0);
      const nf = 1.0 / (near - far);
      return new Float32Array([
        f / aspect, 0, 0, 0,
        0, f, 0, 0,
        0, 0, (far + near) * nf, -1,
        0, 0, (2 * far * near) * nf, 0
      ]);
    }

    function viewMatrix() {
      const cy = Math.cos(rotY);
      const sy = Math.sin(rotY);
      const cx = Math.cos(rotX);
      const sx = Math.sin(rotX);
      return new Float32Array([
        cy, sx * sy, cx * sy, 0,
        0, cx, -sx, 0,
        -sy, sx * cy, cx * cy, 0,
        0, 0, -2.45 / zoom, 1
      ]);
    }

    function render() {
      renderQueued = false;
      const model = getGpuModel(Number(surfaceSelect.value || 0));
      if (!model) return;
      const ratio = Math.max(1, window.devicePixelRatio || 1);
      const width = Math.max(1, Math.floor(canvas.clientWidth * ratio));
      const height = Math.max(1, Math.floor(canvas.clientHeight * ratio));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.enable(gl.DEPTH_TEST);
      gl.clearColor(0.973, 0.965, 0.961, 1.0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      const projection = perspectiveMatrix(Math.PI / 4.0, canvas.width / canvas.height, 0.1, 20.0);
      const view = viewMatrix();
      if (showMesh.checked || showRoi.checked) {
        gl.useProgram(meshProgram);
        gl.uniformMatrix4fv(meshHandles.projection, false, projection);
        gl.uniformMatrix4fv(meshHandles.view, false, view);
        gl.uniform1f(meshHandles.showMesh, showMesh.checked ? 1.0 : 0.0);
        gl.uniform1f(meshHandles.showRoi, showRoi.checked ? 1.0 : 0.0);
        gl.bindBuffer(gl.ARRAY_BUFFER, model.vertexBuffer);
        gl.enableVertexAttribArray(meshHandles.position);
        gl.vertexAttribPointer(meshHandles.position, 3, gl.FLOAT, false, 0, 0);
        gl.bindBuffer(gl.ARRAY_BUFFER, model.normalBuffer);
        gl.enableVertexAttribArray(meshHandles.normal);
        gl.vertexAttribPointer(meshHandles.normal, 3, gl.FLOAT, false, 0, 0);
        gl.bindBuffer(gl.ARRAY_BUFFER, model.roiColorBuffer);
        gl.enableVertexAttribArray(meshHandles.roiColor);
        gl.vertexAttribPointer(meshHandles.roiColor, 3, gl.FLOAT, false, 0, 0);
        gl.bindBuffer(gl.ARRAY_BUFFER, model.roiMaskBuffer);
        gl.enableVertexAttribArray(meshHandles.roiMask);
        gl.vertexAttribPointer(meshHandles.roiMask, 1, gl.FLOAT, false, 0, 0);
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, model.indexBuffer);
        gl.drawElements(gl.TRIANGLES, model.indexCount, gl.UNSIGNED_INT, 0);
      }
    }

    function queueRender() {
      if (renderQueued) return;
      renderQueued = true;
      requestAnimationFrame(render);
    }

    canvas.addEventListener("pointerdown", (event) => {
      dragging = true;
      lastX = event.clientX;
      lastY = event.clientY;
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;
      lastX = event.clientX;
      lastY = event.clientY;
      rotY += dx * 0.01;
      rotX += dy * 0.01;
      queueRender();
    });
    canvas.addEventListener("pointerup", () => { dragging = false; });
    canvas.addEventListener("pointerleave", () => { dragging = false; });
    canvas.addEventListener("wheel", (event) => {
      event.preventDefault();
      zoom *= event.deltaY > 0 ? 0.92 : 1.08;
      zoom = Math.max(0.55, Math.min(3.8, zoom));
      queueRender();
    }, { passive: false });
    surfaceSelect.addEventListener("change", queueRender);
    showMesh.addEventListener("change", queueRender);
    showRoi.addEventListener("change", queueRender);
    resetBtn.addEventListener("click", resetView);
    window.addEventListener("resize", queueRender);
    resetView();
  </script>
</body>
</html>
'''
