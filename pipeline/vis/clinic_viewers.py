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

_STACK_PAYLOAD = re.compile(r"const TITLE=(.+?),SEQUENCES=(.+?);const q=id=>", re.DOTALL)
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


def restyle_interactive_html(path: Path) -> bool:
    html = path.read_text(encoding="utf-8")
    payload = extract_interactive_payload(html)
    if payload is None:
        return False
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
    updated = rewrite_legacy_file_urls(updated)
    if updated == html:
        return False
    path.write_text(updated, encoding="utf-8")
    return True


STACK_VIEWER_HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>交互阅片</title><style>
:root{--brand:#9d1822;--brand-deep:#681019;--brand-soft:#f8e8e8;--brand-pale:#fff8f7;--ink:#20191a;--muted:#71666a;--line:#eadfe1;--paper:#f8f6f5;--panel:#fff;--gold:#bd9750;--shadow:0 18px 48px rgba(87,28,34,.09)}
*{box-sizing:border-box}html,body{margin:0;height:100%;background:radial-gradient(circle at 92% 4%,rgba(157,24,34,.07),transparent 24%),linear-gradient(145deg,#fbfaf9,var(--paper));color:var(--ink);font:14px/1.5 "Source Han Sans SC","Noto Sans SC","PingFang SC","Segoe UI",sans-serif}
.app{min-height:100%;display:grid;grid-template-rows:auto auto minmax(0,1fr);gap:12px;padding:18px 20px}
.topbar{display:flex;align-items:flex-end;justify-content:space-between;gap:24px}
.kicker{margin:0 0 4px;color:var(--brand);font-size:10px;font-weight:750;letter-spacing:.18em}
h1{margin:0;font-size:20px;line-height:1.25;letter-spacing:-.02em;font-weight:650}
.status{padding:7px 12px;border:1px solid rgba(157,24,34,.13);border-radius:999px;background:rgba(255,255,255,.88);color:var(--muted);font-size:11px;white-space:nowrap;box-shadow:0 5px 16px rgba(87,28,34,.05)}
.toolbar{position:relative;display:grid;grid-template-columns:minmax(210px,1.35fr) auto minmax(180px,1fr) minmax(190px,1fr);align-items:center;gap:10px;padding:9px 11px;background:rgba(255,255,255,.9);border:1px solid rgba(157,24,34,.12);border-radius:15px;box-shadow:0 10px 30px rgba(87,28,34,.06);backdrop-filter:blur(12px)}
.toolbar:before{content:"";position:absolute;left:16px;right:16px;top:0;height:2px;border-radius:0 0 2px 2px;background:linear-gradient(90deg,transparent,var(--brand),var(--gold),transparent);opacity:.72}
.group{min-width:0;display:flex;align-items:center;gap:8px}.label{flex:0 0 auto;font-size:11px;color:var(--muted);font-weight:650;letter-spacing:.04em}
.select,button{height:34px;border:1px solid #dfd2d4;border-radius:9px;background:#fff;color:var(--ink);font:inherit}
.select{width:100%;min-width:0;padding:0 28px 0 10px}
.button{padding:0 14px;cursor:pointer}.button:hover{border-color:var(--brand);background:var(--brand-pale)}
.button.primary{min-width:70px;border:0;color:#fff;font-weight:700;background:linear-gradient(135deg,#b62530,#7c111a);box-shadow:0 7px 16px rgba(131,19,28,.2)}
.icon-button{width:34px;padding:0;font-size:17px}
input[type=range]{appearance:none;width:100%;min-width:70px;height:4px;border-radius:99px;background:#eadfe1;accent-color:var(--brand)}
input[type=range]::-webkit-slider-thumb{appearance:none;width:14px;height:14px;border-radius:50%;background:#fff;border:4px solid var(--brand);box-shadow:0 1px 5px rgba(157,24,34,.22)}
.switch{position:relative;width:38px;height:22px}.switch input{opacity:0;position:absolute}
.switch span{position:absolute;inset:0;border-radius:99px;background:#d9cbce;transition:.18s}
.switch span:after{content:"";position:absolute;width:16px;height:16px;left:3px;top:3px;border-radius:50%;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.12);transition:.18s}
.switch input:checked+span{background:var(--brand)}.switch input:checked+span:after{transform:translateX(16px)}
.stage{position:relative;min-height:0;display:grid;place-items:center;overflow:hidden;touch-action:none;cursor:grab;border:1px solid #ded1d3;border-radius:18px;background:radial-gradient(circle at 50% 42%,#383033 0%,#1d181a 64%,#140f11 100%);box-shadow:var(--shadow),inset 0 0 0 1px rgba(255,255,255,.04)}
.stage.is-dragging{cursor:grabbing}
.stage:before{content:"";position:absolute;inset:0;z-index:0;background:linear-gradient(120deg,rgba(255,255,255,.035),transparent 30%),radial-gradient(circle at 50% 50%,transparent 55%,rgba(0,0,0,.28));pointer-events:none}
.frame{position:relative;z-index:1;width:max-content;height:max-content;display:grid;place-items:center}
.frame img{grid-area:1/1;display:block;width:auto;height:auto;max-width:none;max-height:none;object-fit:contain;image-rendering:auto;border-radius:8px;filter:drop-shadow(0 12px 28px rgba(0,0,0,.24));user-select:none;-webkit-user-drag:none}
.frame .mask{pointer-events:none;filter:none}
.hint{position:absolute;right:12px;bottom:10px;padding:5px 9px;border:1px solid rgba(255,255,255,.1);border-radius:999px;background:rgba(25,20,22,.7);color:#d5cacc;font-size:11px;backdrop-filter:blur(8px)}
html.embedded .kicker,html.embedded header h1{display:none}html.embedded .app{padding:10px 12px;gap:8px}html.embedded .topbar{min-height:0}
@media(max-width:1050px){.toolbar{grid-template-columns:minmax(210px,1fr) auto minmax(180px,1fr)}.toolbar .group:last-child{grid-column:1/-1}}
@media(max-width:720px){.app{padding:12px}.toolbar{display:flex;gap:10px}.group{flex:1 1 220px}.select,input[type=range]{width:100%;min-width:0}}
</style></head><body><main class="app"><header class="topbar"><div><p class="kicker">交互阅片</p><h1 id="title"></h1></div><div class="status" id="status"></div></header>
<nav class="toolbar"><div class="group"><span class="label">序列</span><select class="select" id="sequence"></select></div><div class="group"><button class="button icon-button" id="prev" title="上一层">‹</button><button class="button primary" id="play">播放</button><button class="button icon-button" id="next" title="下一层">›</button></div><div class="group"><span class="label">切片</span><input id="slice" type="range"></div><div class="group"><label class="switch" title="显示掩膜"><input id="maskOn" type="checkbox" checked><span></span></label><span class="label">掩膜</span><input id="opacity" type="range" min="0" max="100" value="24" title="掩膜透明度"></div></nav>
<section class="stage" id="stage"><div class="frame" id="frame"><img id="raw" alt="MRI 切片"><img id="mask" class="mask" alt="掩膜叠加"></div><span class="hint">滚动切换切片 · Ctrl + 滚轮缩放 · Ctrl - 缩小 · 拖拽移动</span></section></main>
<script>if(window.self!==window.top)document.documentElement.classList.add("embedded");const TITLE=__TITLE__,SEQUENCES=__SEQUENCES__;const q=id=>document.getElementById(id);const imageCache=new Map(),seriesReady=new Map();const FRAME_MS=160;let sequenceIndex=0,sliceIndex=0,timer=null,playing=false,loading=false,playToken=0,renderToken=0;q("title").textContent=TITLE;SEQUENCES.forEach((item,index)=>{const option=document.createElement("option");option.value=index;option.textContent=item.name;q("sequence").appendChild(option)});
function clamp(value,max){return Math.max(0,Math.min(max,value))}function loadImage(url){if(!url)return Promise.resolve(true);if(imageCache.has(url))return imageCache.get(url);const promise=new Promise(resolve=>{const image=new Image();image.onload=async()=>{try{await image.decode()}catch(_){}resolve(true)};image.onerror=()=>{imageCache.delete(url);resolve(false)};image.src=url});imageCache.set(url,promise);return promise}function warm(item,index){for(let offset=1;offset<=8;offset++){const next=(index+offset)%item.count;loadImage(item.raw[next]);loadImage(item.mask[next])}}function preloadSeries(index){if(seriesReady.has(index))return seriesReady.get(index);const item=SEQUENCES[index],urls=[...item.raw,...item.mask].filter(Boolean);const ready=Promise.all(urls.map(loadImage)).then(results=>results.every(Boolean));seriesReady.set(index,ready);return ready}
async function render(){const token=++renderToken,item=SEQUENCES[sequenceIndex],expectedSequence=sequenceIndex;sliceIndex=clamp(sliceIndex,item.count-1);const expectedSlice=sliceIndex,rawUrl=item.raw[expectedSlice],maskUrl=item.mask[expectedSlice];const loaded=await Promise.all([loadImage(rawUrl),loadImage(maskUrl)]);if(!loaded[0]||token!==renderToken||expectedSequence!==sequenceIndex||expectedSlice!==sliceIndex)return false;q("slice").max=item.count-1;q("slice").value=expectedSlice;q("raw").src=rawUrl;q("mask").src=maskUrl||"";q("mask").style.display=q("maskOn").checked&&maskUrl?"block":"none";q("mask").style.opacity=Number(q("opacity").value)/100;q("status").textContent=`切片 ${String(expectedSlice+1).padStart(2,"0")} / ${item.count} · 序列 ${expectedSequence+1} / ${SEQUENCES.length}`;layoutImages();warm(item,expectedSlice);return true}
function move(delta){sliceIndex=clamp(sliceIndex+delta,SEQUENCES[sequenceIndex].count-1);render()}function stop(){playing=false;loading=false;playToken++;if(timer){clearTimeout(timer);timer=null}q("play").disabled=false;q("play").textContent="播放"}async function playLoop(token,nextAt){if(!playing||token!==playToken)return;const item=SEQUENCES[sequenceIndex];sliceIndex=(sliceIndex+1)%item.count;await render();if(!playing||token!==playToken)return;const following=nextAt+FRAME_MS,delay=Math.max(0,following-performance.now());timer=setTimeout(()=>playLoop(token,following),delay)}async function startPlay(){if(playing||loading)return;loading=true;const token=++playToken;q("play").disabled=true;q("play").textContent="载入中";const ready=await preloadSeries(sequenceIndex);if(token!==playToken)return;loading=false;q("play").disabled=false;if(!ready){q("play").textContent="重试";q("status").textContent="部分切片未能载入";return}playing=true;q("play").textContent="暂停";playLoop(token,performance.now())}q("sequence").onchange=e=>{stop();sequenceIndex=Number(e.target.value);sliceIndex=Math.floor(SEQUENCES[sequenceIndex].count/2);render()};q("slice").oninput=e=>{stop();sliceIndex=Number(e.target.value);render()};q("maskOn").onchange=()=>{const item=SEQUENCES[sequenceIndex],maskUrl=item.mask[sliceIndex];q("mask").style.display=q("maskOn").checked&&maskUrl?"block":"none"};q("opacity").oninput=()=>q("mask").style.opacity=Number(q("opacity").value)/100;q("prev").onclick=()=>{stop();move(-1)};q("next").onclick=()=>{stop();move(1)};
q("play").onclick=()=>{if(playing){stop();return}startPlay()};
let viewScale=1,panX=0,panY=0,dragging=false,dragX=0,dragY=0,fitScale=1;const frame=q("frame"),stage=q("stage"),MIN_ZOOM=0.25,MAX_ZOOM=8,DEFAULT_VIEW_PX=480;
function applyView(){frame.style.transform=`translate(${panX}px,${panY}px)`}
function layoutImages(){
  const raw=q("raw"),mask=q("mask"),nw=raw.naturalWidth||0,nh=raw.naturalHeight||0;
  if(!nw||!nh)return;
  const box=stage.getBoundingClientRect(),maxW=Math.max(64,Math.min(DEFAULT_VIEW_PX,box.width-24)),maxH=Math.max(64,Math.min(DEFAULT_VIEW_PX,box.height-24));
  fitScale=Math.min(maxW/nw,maxH/nh);
  const w=nw*fitScale*viewScale,h=nh*fitScale*viewScale;
  raw.style.width=w+"px";raw.style.height=h+"px";mask.style.width=w+"px";mask.style.height=h+"px";
  applyView();
}
function resetView(){viewScale=1;panX=0;panY=0;layoutImages()}
function zoomBy(factor){viewScale=Math.max(MIN_ZOOM,Math.min(MAX_ZOOM,viewScale*factor));layoutImages()}
stage.addEventListener("wheel",e=>{
  if(e.ctrlKey||e.metaKey){e.preventDefault();zoomBy(e.deltaY>0?0.9:1.12);return}
  e.preventDefault();stop();move(e.deltaY>0?1:-1);
},{passive:false});
window.addEventListener("keydown",e=>{
  if(!(e.ctrlKey||e.metaKey))return;
  if(e.key==="0"){e.preventDefault();resetView();return}
  if(e.key!=="-"&&e.key!=="_"&&e.key!=="="&&e.key!=="+")return;
  e.preventDefault();zoomBy(e.key==="-"||e.key==="_"?0.9:1.12);
});
stage.addEventListener("pointerdown",e=>{
  if(e.button!==0)return;
  dragging=true;dragX=e.clientX;dragY=e.clientY;stage.classList.add("is-dragging");stage.setPointerCapture(e.pointerId);
});
stage.addEventListener("pointermove",e=>{
  if(!dragging)return;
  panX+=e.clientX-dragX;panY+=e.clientY-dragY;dragX=e.clientX;dragY=e.clientY;applyView();
});
stage.addEventListener("pointerup",()=>{dragging=false;stage.classList.remove("is-dragging")});
stage.addEventListener("pointercancel",()=>{dragging=false;stage.classList.remove("is-dragging")});
window.addEventListener("resize",layoutImages);
q("sequence").addEventListener("change",resetView);
stage.addEventListener("dblclick",resetView);
sliceIndex=Math.floor(SEQUENCES[0].count/2);render();preloadSeries(0);</script></body></html>'''


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
.image-layer{position:relative;aspect-ratio:var(--ar,1);width:min(100cqw,calc(100cqh * var(--ar,1)));height:min(100cqh,calc(100cqw / var(--ar,1)));overflow:hidden;background:radial-gradient(circle at center,#2d2729,#120f10 72%);border-radius:10px;box-shadow:inset 0 0 0 1px rgba(255,255,255,.05)}
.image-layer img{display:block;width:100%;height:100%;object-fit:fill;user-select:none;transform-origin:center center}
.image-layer .label-overlay{position:absolute;inset:0;pointer-events:none;object-fit:fill}
.cross-v,.cross-h{position:absolute;background:rgba(189,151,80,.9);pointer-events:none}
.cross-v{top:0;bottom:0;width:1px}.cross-h{left:0;right:0;height:1px}
.hint{display:flex;justify-content:space-between;gap:24px;color:var(--muted);font-size:11px}.hint strong{color:#4f4548;font-weight:650}
html.embedded .kicker,html.embedded header h1{display:none}html.embedded .app{padding-top:10px}
@media(max-width:1180px){.toolbar{grid-template-columns:repeat(3,minmax(140px,1fr))}.tools{grid-column:1/-1;justify-content:flex-end}}
@media(max-width:760px){.views{grid-template-columns:1fr}.toolbar{grid-template-columns:1fr}.tools{grid-column:auto;justify-content:flex-start;flex-wrap:wrap}.app{padding:12px}.hint{flex-direction:column}}
</style></head><body><main class="app"><header class="topbar"><div><p class="kicker">交互阅片</p><h1 id="title"></h1></div><div class="volume-meta" id="volumeMeta"></div></header>
<nav class="toolbar"><label class="axis-control"><span class="axis-tag x">矢</span><input id="x" type="range"><span class="axis-value" id="xv"></span></label><label class="axis-control"><span class="axis-tag y">冠</span><input id="y" type="range"><span class="axis-value" id="yv"></span></label><label class="axis-control"><span class="axis-tag z">轴</span><input id="z" type="range"><span class="axis-value" id="zv"></span></label><div class="tools"><button class="button" id="center">居中</button><button class="button active" id="crosshair">十字线</button><div class="overlay-tools" id="overlayTools" hidden><button class="button active" id="overlayToggle"></button><span class="label">透明度</span><input id="overlayOpacity" type="range" min="0" max="100" value="28"></div></div></nav>
<section class="views" id="views"></section><footer class="hint"><span><strong>定位</strong> 点击任一视图移动十字线</span><span><strong>浏览</strong> 滚动切换切片 · Ctrl + 滚轮缩放</span></footer></main>
<script>if(window.self!==window.top)document.documentElement.classList.add("embedded");const TITLE=__TITLE__,DATA=__MANIFEST__;const q=id=>document.getElementById(id),dims=DATA.dims;let pos={x:Math.floor(dims.x/2),y:Math.floor(dims.y/2),z:Math.floor(dims.z/2)},showCrosshair=true,showOverlay=true;
const specs={sagittal:{title:"矢状面",normal:"x",h:"z",v:"y",invertV:true,color:"var(--x)"},coronal:{title:"冠状面",normal:"y",h:"z",v:"x",invertV:true,color:"var(--y)"},axial:{title:"轴状面",normal:"z",h:"x",v:"y",invertV:true,color:"var(--z)"}};q("title").textContent=TITLE;q("volumeMeta").textContent=`${dims.x} × ${dims.y} × ${dims.z} · ${DATA.spacing.map(v=>Number(v).toFixed(2)).join(" × ")} mm`;
function planeAspect(name,plane){const [sx,sy,sz]=(DATA.spacing||[1,1,1]).map(v=>Number(v)||1);const w=plane.width,h=plane.height;if(name==="sagittal")return (w*sz)/(h*sy);if(name==="coronal")return (w*sz)/(h*sx);return (w*sx)/(h*sy)}
Object.entries(specs).forEach(([name,spec])=>{const plane=DATA.planes[name],panel=document.createElement("article");panel.className="panel";panel.style.setProperty("--plane-color",spec.color);panel.innerHTML=`<h2><span class="plane-name"><i class="plane-dot"></i>${spec.title}</span><span class="counter"></span></h2><div class="viewport-shell"><div class="image-layer"><img class="base" draggable="false"><img class="label-overlay" draggable="false"><i class="cross-v"></i><i class="cross-h"></i></div></div>`;panel.dataset.plane=name;q("views").appendChild(panel);const layer=panel.querySelector(".image-layer");layer.style.setProperty("--ar",String(planeAspect(name,plane)));layer.addEventListener("wheel",e=>{if(e.ctrlKey||e.metaKey){e.preventDefault();const scale=Number(layer.dataset.zoom||1),next=Math.max(0.25,Math.min(8,scale*(e.deltaY>0?0.9:1.12)));layer.dataset.zoom=String(next);layer.querySelectorAll("img").forEach(img=>img.style.transform=`scale(${next})`);return}e.preventDefault();pos[spec.normal]+=e.deltaY>0?1:-1;render()},{passive:false});layer.onclick=e=>{const rect=layer.getBoundingClientRect(),px=(e.clientX-rect.left)/rect.width,py=(e.clientY-rect.top)/rect.height;pos[spec.h]=Math.round(px*(dims[spec.h]-1));pos[spec.v]=Math.round((spec.invertV?1-py:py)*(dims[spec.v]-1));render()}});
for(const axis of ["x","y","z"]){q(axis).max=dims[axis]-1;q(axis).oninput=e=>{pos[axis]=Number(e.target.value);render()}}if(DATA.has_overlay){q("overlayTools").hidden=false;q("overlayToggle").textContent=DATA.overlay_label;q("overlayToggle").onclick=()=>{showOverlay=!showOverlay;q("overlayToggle").classList.toggle("active",showOverlay);render()};q("overlayOpacity").oninput=render()}
q("center").onclick=()=>{pos={x:Math.floor(dims.x/2),y:Math.floor(dims.y/2),z:Math.floor(dims.z/2)};render()};q("crosshair").onclick=()=>{showCrosshair=!showCrosshair;q("crosshair").classList.toggle("active",showCrosshair);render()};
function clamp(){for(const axis of ["x","y","z"])pos[axis]=Math.max(0,Math.min(dims[axis]-1,pos[axis]))}function pct(axis,value,invert=false){const result=dims[axis]>1?value/(dims[axis]-1)*100:50;return invert?100-result:result}
function render(){clamp();for(const axis of ["x","y","z"]){q(axis).value=pos[axis];q(`${axis}v`).textContent=`${pos[axis]+1} / ${dims[axis]}`}document.querySelectorAll(".panel").forEach(panel=>{const spec=specs[panel.dataset.plane],plane=DATA.planes[panel.dataset.plane],index=pos[spec.normal],overlay=panel.querySelector(".label-overlay");panel.querySelector(".base").src=plane.images[index];panel.querySelector(".counter").textContent=`${index+1} / ${dims[spec.normal]}`;overlay.src=DATA.has_overlay?plane.overlays[index]:"";overlay.style.display=DATA.has_overlay&&showOverlay?"block":"none";overlay.style.opacity=Number(q("overlayOpacity")?.value||28)/100;panel.querySelectorAll(".cross-v,.cross-h").forEach(line=>line.style.display=showCrosshair?"block":"none");panel.querySelector(".cross-v").style.left=`${pct(spec.h,pos[spec.h])}%`;panel.querySelector(".cross-h").style.top=`${pct(spec.v,pos[spec.v],spec.invertV)}%`})}render();</script></body></html>'''


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
    <p class="hint">拖拽旋转 · Ctrl + 滚轮缩放。首次切换表面时会载入完整网格。</p>
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
