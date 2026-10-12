"""上海科技大学 SmileLab 医生端产品页。"""

from __future__ import annotations

from agentic import dashboard_server as _dashboard


CLINIC_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AutoRecon · SmileLab</title>
  <style>
    :root{
      --brand:#9d1822;--brand-deep:#681019;--brand-soft:#f8e8e8;--brand-pale:#fff8f7;
      --ink:#20191a;--muted:#71666a;--line:#eadfe1;--paper:#f8f6f5;--panel:#fff;
      --gold:#bd9750;--gold-bg:#faf3e5;--info:#647d8d;--info-bg:#eef3f5;
      --shadow:0 18px 48px rgba(87,28,34,.08);
    }
    *{box-sizing:border-box}
    html,body{margin:0;min-height:100%;background:var(--paper);color:var(--ink);font:15px/1.6 "Source Han Sans SC","Noto Sans SC","PingFang SC","Segoe UI",sans-serif}
    button,input,select,textarea{font:inherit}
    button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible,.dropzone:focus-visible{outline:3px solid rgba(157,24,34,.22);outline-offset:2px}
    .topbar{
      min-height:82px;padding:13px max(24px,calc((100vw - 1320px)/2));
      display:flex;align-items:center;justify-content:space-between;gap:28px;
      background:linear-gradient(112deg,#fff 0%,#fff9f8 42%,#f5d9da 76%,#b84a51 132%);
      border-bottom:1px solid rgba(157,24,34,.14);
    }
    .school-logo{width:min(265px,34vw);height:auto;display:block}
    .product-id{display:flex;align-items:center;gap:18px;min-width:0}
    .smilelab-logo{height:48px;width:auto;max-width:min(280px,38vw);display:block}
    .product-copy{display:grid;line-height:1.25;white-space:nowrap}
    .product-copy strong{font-size:16px;letter-spacing:.04em}
    .product-copy span{margin-top:3px;color:var(--brand-deep);font-size:11px;letter-spacing:.13em}
    main{max-width:1320px;margin:0 auto;padding:34px 24px 64px}
    .intro{margin-bottom:24px;display:flex;align-items:flex-end;justify-content:space-between;gap:24px}
    .eyebrow{margin:0 0 7px;color:var(--brand);font-size:12px;font-weight:700;letter-spacing:.16em}
    h1{margin:0;font-size:clamp(26px,3vw,38px);line-height:1.2;letter-spacing:-.02em}
    .intro p:last-child{max-width:520px;margin:0;color:var(--muted);text-align:right}
    .composer,.panel{background:var(--panel);border:1px solid var(--line);border-radius:20px;box-shadow:var(--shadow)}
    .composer{padding:12px}
    .section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:20px;margin-bottom:18px}
    .section-head h2,.panel-head h2{margin:0;font-size:18px;line-height:1.35}
    .section-head p,.panel-head p{margin:5px 0 0;color:var(--muted);font-size:13px}
    .step-no{display:inline-grid;place-items:center;width:28px;height:28px;margin-right:10px;border-radius:9px;background:var(--brand-soft);color:var(--brand);font-size:12px}
    .module-tabs{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:5px;border-radius:15px;background:#f4eff0}
    .module-tab{min-height:82px;padding:11px 14px;border:1px solid transparent;border-radius:11px;display:flex;align-items:center;gap:14px;text-align:left;color:#71666a;background:transparent;cursor:pointer}
    .module-tab:hover{color:var(--brand-deep);background:rgba(255,255,255,.65)}
    .module-tab.active{border-color:#dfc5c8;color:var(--brand-deep);background:#fff;box-shadow:0 5px 15px rgba(78,34,39,.07)}
    .module-illustration{width:58px;height:58px;flex:0 0 auto;border:1px solid #ead9db;border-radius:14px;display:block;object-fit:cover;opacity:.68;filter:saturate(.72);box-shadow:0 4px 12px rgba(92,34,40,.08)}
    .module-tab.active .module-illustration{opacity:1;filter:saturate(1);box-shadow:0 7px 16px rgba(92,34,40,.13)}
    .module-tab strong,.module-tab span{display:block}.module-tab strong{font-size:15px}.module-tab span{margin-top:2px;font-size:11px;font-weight:400;color:#8a7d80}
    .module-panel{display:none;padding:26px 14px 14px}.module-panel.active{display:block}
    .module-heading{margin-bottom:19px}.module-kicker{display:block;margin-bottom:5px;color:var(--brand);font-size:10px;font-weight:750;letter-spacing:.16em}
    .module-heading h2{margin:0;font-size:21px}.module-heading p{margin:6px 0 0;color:var(--muted);font-size:13px}
    .source-choice{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:0 0 16px;padding:4px;border-radius:14px;background:#f4eff0}
    .source-choice-btn{min-height:68px;padding:12px 14px;border:1px solid transparent;border-radius:11px;text-align:left;color:#71666a;background:transparent;cursor:pointer}
    .source-choice-btn:hover{color:var(--brand-deep);background:rgba(255,255,255,.65)}
    .source-choice-btn.active{border-color:#dfc5c8;color:var(--brand-deep);background:#fff;box-shadow:0 5px 15px rgba(78,34,39,.07)}
    .source-choice-btn strong,.source-choice-btn span{display:block}
    .source-choice-btn strong{font-size:14px}
    .source-choice-btn span{margin-top:3px;font-size:12px;font-weight:400;color:#8a7d80}
    .source-pane{display:none}.source-pane.active{display:block}
    .source-grid{display:grid;gap:16px}
    .source-card{min-width:0;padding:19px;border:1px solid var(--line);border-radius:16px;background:#fff}
    .source-card h3{margin:0 0 14px;font-size:15px}
    .intake-card{margin-top:16px}
    .intake-grid{display:grid;grid-template-columns:minmax(140px,200px) minmax(0,1fr);gap:12px 16px}
    .choice-row{display:flex;flex-wrap:wrap;gap:8px}
    .choice-row label{display:flex;align-items:center;gap:7px;height:44px;padding:0 13px;border:1px solid #d9cbce;border-radius:11px;background:#fff;font-weight:650;cursor:pointer}
    .choice-row label:has(input:checked){border-color:var(--brand);background:var(--brand-pale);color:var(--brand-deep)}
    .choice-row input{margin:0;accent-color:var(--brand)}
    #fetal_description,#clinical_notes{min-height:88px}
    .intake-body{padding:4px 22px 22px}
    .result-picker{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:12px;align-items:end}
    label.field,div.field{display:grid;gap:7px;color:#4f4548;font-size:13px;font-weight:650}
    [hidden]{display:none!important}
    select,textarea,input[type=text],input[type=number]{width:100%;min-width:0;border:1px solid #d9cbce;border-radius:11px;background:#fff;color:var(--ink);padding:12px 13px}
    select,input[type=number]{height:48px}
    textarea{display:block;min-height:148px;resize:vertical;line-height:1.65}
    .dropzone{min-height:112px;padding:18px;border:1.5px dashed #cb9ba0;border-radius:13px;display:flex;align-items:center;justify-content:center;gap:15px;background:linear-gradient(145deg,#fffafa,#fff);cursor:pointer;transition:.18s ease}
    .dropzone:hover,.dropzone.drag{border-color:var(--brand);background:var(--brand-pale);transform:translateY(-1px)}
    .upload-icon{width:42px;height:42px;flex:0 0 auto;border-radius:13px;display:grid;place-items:center;background:var(--brand-soft);color:var(--brand);font-size:24px;line-height:1}
    .dropzone strong{display:block;color:var(--brand-deep)}
    .dropzone small{display:block;margin-top:3px;color:var(--muted)}
    #files,#folder{position:absolute;width:1px;height:1px;opacity:0;pointer-events:none}
    .upload-picks{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
    .case-name-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center}
    .ghost{height:48px;border:1px solid #e0c9cc;border-radius:11px;padding:0 14px;background:#fff;color:var(--brand-deep);font-weight:650;cursor:pointer}
    .ghost:hover{border-color:var(--brand);background:var(--brand-pale)}
    .ghost[hidden]{display:none}
    .upload-list{margin-top:12px;display:grid;gap:8px}
    .upload-list.ready .upload-scroll{max-height:min(360px,46vh);overflow:auto;display:grid;gap:8px;padding-right:2px;overscroll-behavior:contain}
    .queue-head{display:flex;justify-content:space-between;align-items:baseline;color:var(--muted);font-size:12px}
    .queue-head button{border:0;background:transparent;color:var(--brand);font-weight:650;cursor:pointer;padding:0}
    .file-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 12px;align-items:center;padding:11px 13px;border:1px solid var(--line);border-radius:13px;background:linear-gradient(180deg,#fff,#fffbfb)}
    .file-row.uploading{border-color:#e8c9cc}
    .file-row.done{border-color:#cde3d7;background:linear-gradient(180deg,#fff,#f4faf6)}
    .file-meta{min-width:0}
    .file-meta strong{display:block;font-size:13px;font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .file-meta small{color:var(--muted);font-size:11px}
    .file-remove{width:30px;height:30px;border:0;border-radius:9px;background:var(--brand-soft);color:var(--brand);font-size:16px;line-height:1;cursor:pointer}
    .file-remove:disabled{opacity:.35;cursor:not-allowed}
    .file-progress{grid-column:1/-1;height:4px;border-radius:999px;background:#f1e6e7;overflow:hidden}
    .file-progress>span{display:block;height:100%;width:0;border-radius:inherit;background:linear-gradient(90deg,#c44751,#9d1822);transition:width .18s ease}
    .upload-empty{padding:12px 2px;color:var(--muted);font-size:12px}
    .request-block{margin-top:20px;padding-top:22px;border-top:1px solid var(--line)}
    .request-row{display:grid;grid-template-columns:minmax(0,1fr) 160px;gap:14px;align-items:end}
    .primary{height:50px;border:0;border-radius:12px;padding:0 20px;color:#fff;font-weight:700;letter-spacing:.06em;cursor:pointer;background:linear-gradient(135deg,#b62530,#83131c);box-shadow:0 10px 22px rgba(131,19,28,.2)}
    .primary:hover{filter:brightness(1.04);transform:translateY(-1px)}
    .primary:disabled{cursor:wait;opacity:.55;transform:none}
    .secondary{height:48px;border:1px solid #cda8ac;border-radius:11px;padding:0 18px;color:var(--brand-deep);font-weight:700;cursor:pointer;background:#fff}
    .secondary:hover{border-color:var(--brand);background:var(--brand-pale)}
    .status{min-height:22px;margin-top:10px;color:var(--muted);font-size:13px}
    .status.error{color:var(--brand)}
    .dev-only{display:none;margin-top:12px}.dev .dev-only{display:block}
    .workspace{display:grid;grid-template-columns:1fr;gap:22px;margin-top:22px;align-items:start}
    .panel{min-width:0;overflow:hidden;box-shadow:0 14px 38px rgba(53,35,37,.05)}
    .panel-head{padding:19px 22px 15px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#fff,#fffbfb)}
    .report{padding:12px 22px 24px;max-height:78vh;overflow:auto}
    .report h1{font-size:22px;margin:10px 0 4px}
    .report h2{font-size:12px;margin:18px 0 8px;padding:0;border:0;color:#8a7d80;font-weight:750;letter-spacing:.14em}
    .report table{width:100%;border-collapse:collapse;font-size:12px;margin:12px 0}
    .report th,.report td{border:1px solid var(--line);padding:8px;text-align:left;vertical-align:top}
    .report th{background:#f8f1f2}
    .report h2.refusal-heading{color:#7a4a12;font-size:17px;letter-spacing:.04em;margin:8px 0 10px}
    .report h2.finding-heading{color:#315f85;font-size:15px;letter-spacing:.06em;margin:14px 0 8px}
    .callout{margin:14px 0;padding:15px 17px;border-radius:14px;border:1px solid #ead6a8;border-left:5px solid var(--gold);background:linear-gradient(180deg,#fffaf0,#faf3e5);box-shadow:0 8px 18px rgba(157,24,34,.05)}
    .callout.missing,.callout.finding{border-color:#cfdbe2;border-left-color:var(--info);background:linear-gradient(180deg,#f7fafb,#eef3f5)}
    .callout.checklist{border-color:#e8c9cc;border-left-color:var(--brand);background:linear-gradient(180deg,#fff,#fff6f5)}
    .callout h3{margin:0 0 8px;font-size:15px;letter-spacing:.04em}
    .callout.refusal h3,.refusal-heading{color:#7a4a12}
    .callout.finding h3,.finding-heading{color:#315f85}
    .callout.checklist h3{color:var(--brand)}
    .callout p{margin:5px 0}
    .report-boundary{margin:18px 0 4px;color:var(--muted);font-size:12px;line-height:1.55}
    .checklist-items{list-style:none;margin:4px 0 0;padding:0}
    .checklist-items li{display:flex;gap:10px;align-items:flex-start;margin:8px 0;line-height:1.5}
    .check-box{flex:0 0 16px;width:16px;height:16px;margin-top:4px;border:1.5px solid var(--brand);border-radius:4px;background:#fff}
    .gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:18px;padding:22px}
    .card{min-width:0;border:1px solid var(--line);border-radius:16px;overflow:hidden;background:#fff;box-shadow:0 8px 22px rgba(53,35,37,.05)}
    .card header{display:flex;justify-content:space-between;gap:8px;padding:13px 14px;font-size:14px;font-weight:650}
    .status-badge{min-width:78px;height:27px;padding:0 9px;display:inline-flex;align-items:center;justify-content:center;gap:6px;border-radius:999px;font-size:11px;font-weight:700;white-space:nowrap}
    .status-icon{width:15px;height:15px;border-radius:50%;display:grid;place-items:center;color:#fff;font-size:9px;line-height:1}
    .status-completed{color:#28664d;background:#e8f4ee}.status-completed .status-icon{background:#3f8668}
    .status-running{color:#315f85;background:#eaf2f8}.status-running .status-icon{background:#4d82aa;animation:pulse 1.4s ease-in-out infinite}
    .status-failed{color:#8a3037;background:#fae9eb}.status-failed .status-icon{background:#a8444c}
    .status-skipped{color:#6c6869;background:#efedee}.status-skipped .status-icon{background:#8c8789}
    .status-pending{color:#896520;background:#f8f0dc}.status-pending .status-icon{background:#b18735}
    @keyframes pulse{50%{box-shadow:0 0 0 4px rgba(77,130,170,.18)}}
    .thumbnail{overflow:hidden;background:#f8f6f5}
    .thumbnail img{width:100%;height:auto;display:block;background:#fbf7ef}
    .thumbnail-empty{height:120px;display:grid;place-items:center;color:#9b8e91;font-size:13px}
    .card-note{margin:0;padding:0 14px 10px;color:#8a3037;font-size:12px;line-height:1.45}
    .card-actions{display:grid;grid-template-columns:1fr 1fr;gap:8px;padding:12px 14px 14px}
    .view-button{width:100%;height:40px;border:1px solid #d8bdc0;border-radius:10px;background:#fff;color:var(--brand-deep);font-weight:700;cursor:pointer}
    .view-button:hover{border-color:var(--brand);background:var(--brand-pale)}
    .view-button:disabled{opacity:.45;cursor:not-allowed;transform:none}
    .log-view{margin:0;height:100%;padding:16px 18px;overflow:auto;background:#1c1617;color:#f4ecec;font:12px/1.55 ui-monospace,SFMono-Regular,Consolas,monospace;white-space:pre-wrap;word-break:break-word}
    .log-empty{margin:0;padding:24px;color:var(--muted)}
    dialog{width:min(1180px,94vw);height:min(78vh,820px);padding:0;border:1px solid rgba(157,24,34,.14);border-radius:20px;overflow:hidden;box-shadow:0 28px 90px rgba(31,14,17,.35)}
    dialog.rename-dialog{width:min(400px,92vw);height:auto;padding:22px 22px 18px;overflow:visible;background:#fff}
    .rename-dialog h3{margin:0 0 6px;font-size:17px;font-weight:650}
    .rename-dialog p{margin:0 0 14px;font-size:13px}
    .rename-dialog input[type=text]{height:46px}
    .rename-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:16px}
    .rename-actions .ghost,.rename-actions .primary{width:auto;min-width:88px;height:44px}
    dialog::backdrop{background:rgba(31,18,20,.68);backdrop-filter:blur(3px)}
    .viewer-head{height:52px;padding:0 16px 0 20px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);background:linear-gradient(105deg,#fff 0%,#fffafa 72%,#f7e5e6 130%)}
    .viewer-head h3{margin:0;font-size:16px;font-weight:650}.viewer-close{width:36px;height:36px;border:0;border-radius:10px;background:var(--brand-soft);color:var(--brand);font-size:20px;cursor:pointer}
    .viewer-body{height:calc(100% - 52px);background:var(--paper);display:grid;place-items:center;overflow:hidden}
    .viewer-body:has(.log-view){place-items:stretch;background:#1c1617}
    .viewer-body iframe{width:100%;height:100%;display:block;border:0}
    .viewer-body img{max-width:100%;max-height:100%;display:block;border:0;object-fit:contain}
    .muted{color:var(--muted)}.badge{font-size:11px;letter-spacing:.06em}
    @media(max-width:900px){
      .topbar{min-height:70px;padding:12px 18px}.school-logo{width:220px}.smilelab-logo{height:40px}.product-copy span{display:none}
      main{padding:26px 16px 48px}.intro{display:block}.intro p:last-child{margin-top:9px;text-align:left}
      .source-grid,.workspace,.intake-grid{grid-template-columns:1fr}.request-row{grid-template-columns:1fr}.primary,.secondary{width:100%}
    }
    @media(max-width:560px){
      .school-logo{width:168px}.smilelab-logo{height:32px}.product-copy{display:none}.composer{padding:18px}.source-card{padding:15px}
      .module-tabs{grid-template-columns:1fr}.module-tab{min-height:76px}.module-illustration{width:52px;height:52px}.module-panel{padding:22px 2px 2px}
      .source-choice{grid-template-columns:1fr 1fr}
      .dropzone{align-items:flex-start;justify-content:flex-start}.gallery{grid-template-columns:1fr}.card-actions{grid-template-columns:1fr}
    }
  </style>
</head>
<body>
<header class="topbar">
  <img class="school-logo" src="/brand/logo.png" alt="上海科技大学">
  <div class="product-id">
    <img class="smilelab-logo" src="/brand/smilelab.svg" alt="ShanghaiTech · SmileLab">
    <div class="product-copy"><strong>AutoRecon</strong><span>SmileLab</span></div>
  </div>
</header>
<main>
  <section class="intro">
    <div><p class="eyebrow">FETAL BRAIN MRI ANALYSIS</p><h1>胎儿脑 MRI 重建与定量分析</h1></div>
    <p>面向科研与临床阅片支持的影像重建、配准、分割及技术质控平台。</p>
  </section>
  <section class="composer">
    <div class="module-tabs" role="tablist" aria-label="分析功能">
      <button class="module-tab active" type="button" role="tab" aria-selected="true" data-module="resultsPanel">
        <img class="module-illustration" src="/brand/results-center.png" alt=""><strong>结果中心</strong>
      </button>
      <button class="module-tab" type="button" role="tab" aria-selected="false" data-module="newAnalysisPanel">
        <img class="module-illustration" src="/brand/new-analysis.png" alt=""><strong>新建分析</strong>
      </button>
    </div>
    <section id="resultsPanel" class="module-panel active" role="tabpanel">
      <div class="module-heading">
        <span class="module-kicker">ARCHIVED ANALYSES</span>
        <h2>既往分析结果</h2>
      </div>
      <div class="result-picker">
        <label class="field">分析记录<select id="result_id"><option>正在加载结果…</option></select></label>
        <button id="renameResultBtn" class="ghost" type="button">改名</button>
      </div>
    </section>
    <section id="newAnalysisPanel" class="module-panel" role="tabpanel" hidden>
      <div class="module-heading">
        <span class="module-kicker">NEW IMAGE ANALYSIS</span>
        <h2>新建影像分析</h2>
      </div>
      <div class="source-choice" role="radiogroup" aria-label="分析起点">
        <button class="source-choice-btn active" type="button" role="radio" aria-checked="true" data-source="upload">
          <strong>上传新影像</strong>
        </button>
        <button class="source-choice-btn" type="button" role="radio" aria-checked="false" data-source="continue">
          <strong>从已有结果继续</strong>
        </button>
      </div>
      <div id="uploadSource" class="source-pane active">
        <div class="source-card">
        <h3>影像数据导入</h3>
        <input id="files" type="file" multiple>
        <input id="folder" type="file" webkitdirectory directory multiple>
        <div id="dropzone" class="dropzone" role="button" tabindex="0" aria-label="选择 DICOM 文件夹或影像文件">
          <span class="upload-icon">↑</span>
          <span><strong>选择文件、文件夹，或拖放至此</strong><small>DICOM 文件夹 / 一个 zip / NIfTI；JPG 与预览文件会自动筛掉</small></span>
        </div>
        <div class="upload-picks">
          <button id="pickFilesBtn" class="ghost" type="button">选择文件</button>
          <button id="pickFolderBtn" class="ghost" type="button">选择文件夹</button>
        </div>
        <label class="field">病例名称
          <div class="case-name-row">
            <input id="case_label" type="text" maxlength="40" placeholder="可选，例如 AnHuiJing" autocomplete="off">
            <button id="renameCaseBtn" class="ghost" type="button" hidden>保存名称</button>
          </div>
        </label>
        <div id="uploadList" class="upload-list"><div class="upload-empty">尚未选择 DICOM 文件夹、压缩包或 NIfTI</div></div>
        </div>
      </div>
      <div id="continueSource" class="source-pane">
        <div class="source-card">
        <h3>选择已有分析结果</h3>
        <label class="field">分析记录<select id="continue_result_id"><option>正在加载结果…</option></select></label>
        </div>
      </div>
      <div class="request-block">
        <div class="module-heading"><h2>分析方案说明</h2></div>
        <div class="request-row">
          <label class="field">分析目标<textarea id="request" placeholder="例如：完成全部六步（脑提取、三维重建、图像配准、组织分割、脑区划分、表面重建），并生成含分步质控的技术报告。"></textarea></label>
          <button id="goBtn" class="primary" type="button">提交分析任务</button>
        </div>
        <div class="dev-only"><label class="field">受试者目录<input id="subject_dir" type="text" placeholder="/path/to/BTFE"></label></div>
      </div>
    </section>
    <div id="status" class="status" aria-live="polite"></div>
  </section>
  <section class="workspace">
    <article class="panel">
      <div class="panel-head"><h2>技术分析报告</h2></div>
      <div id="reportBox" class="report muted">请选择一条既往分析记录，或提交新的影像分析任务。</div>
    </article>
    <article class="panel">
      <div class="panel-head"><h2>处理流程影像</h2></div>
      <div id="gallery" class="gallery"><p class="muted">打开分析结果后，将按处理阶段展示可用影像。</p></div>
    </article>
    <article class="panel" id="caseIntake">
      <div class="panel-head"><h2>病例记录</h2></div>
      <div class="intake-body">
        <div class="intake-grid">
          <label class="field">胎龄（周+天）
            <input id="gestational_age" type="text" maxlength="16" placeholder="例如 34 或 34+1" autocomplete="off">
          </label>
          <div class="field">
            <span>临床所见</span>
            <div class="choice-row" role="radiogroup" aria-label="临床所见">
              <label><input type="radio" name="clinical_status" value="none">未见异常</label>
              <label><input type="radio" name="clinical_status" value="present">存在异常</label>
              <label><input type="radio" name="clinical_status" value="unknown">不确定</label>
            </div>
          </div>
        </div>
        <label class="field" id="conditionField" hidden>疾病
          <input id="clinical_condition" type="text" maxlength="80" placeholder="例如 侧脑室轻度扩张" autocomplete="off">
        </label>
        <label class="field">胎儿描述
          <textarea id="fetal_description" maxlength="400" placeholder="例如 单胎，头位，羊水量正常"></textarea>
        </label>
        <label class="field">备注
          <textarea id="clinical_notes" maxlength="400" placeholder="例如 重建伪影明显、组织分割边界不清"></textarea>
        </label>
        <div class="request-row" style="margin-top:16px">
          <p id="intakeCaseHint" class="muted" style="margin:0;align-self:center">先打开一条分析结果。</p>
          <button id="saveIntakeBtn" class="primary" type="button">保存病例记录</button>
        </div>
      </div>
    </article>
  </section>
</main>
<dialog id="renameDialog" class="rename-dialog">
  <form id="renameForm" method="dialog">
    <h3>病例名称</h3>
    <p class="muted">仅修改列表中的显示名称。</p>
    <input id="result_rename" type="text" maxlength="40" autocomplete="off" aria-label="病例名称">
    <div class="rename-actions">
      <button class="ghost" type="button" id="renameCancelBtn">取消</button>
      <button class="primary" type="submit">确定</button>
    </div>
  </form>
</dialog>
<dialog id="viewerDialog">
  <div class="viewer-head"><h3 id="viewerTitle">流程影像查看</h3><button id="viewerClose" class="viewer-close" type="button" aria-label="关闭">×</button></div>
  <div id="viewerBody" class="viewer-body"></div>
</dialog>
<script>
const params=new URLSearchParams(location.search);
const dev=params.get("dev")==="1";
if(dev) document.body.classList.add("dev");
const $=id=>document.getElementById(id);
if(params.get("subject_dir")) $("subject_dir").value=params.get("subject_dir");
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const fileUrl=path=>`/api/file?path=${encodeURIComponent(path)}`;
const LAST_RUN_KEY="autorecon.clinic.lastRunId";
const LAST_UI_KEY="autorecon.clinic.ui";
let latestRunId=params.get("run_id")||"";
let selectedFiles=[];
let uploadedCaseId="";
let uploadedCaseLabel="";
let uploadBusy=false;
let analysisSource="upload";
let lastReportMarkdown=null;
let lastGallerySignature="";
let cachedRuns=[];
let refreshTimer=null;
let openLogPath="";
let restoringUi=false;
let persistScrollTimer=null;
let openedRunId="";
let refreshGen=0;
let syncingSelect=false;
let intakeLoadedFor="";
const labels={extraction:"脑提取",reconstruction:"三维重建",registration:"图像配准",tissue:"组织分割",roi:"脑区划分",surface:"表面重建"};
const statusMeta={
  completed:{label:"已完成",icon:"✓",className:"completed"},
  running:{label:"处理中",icon:"•",className:"running"},
  failed:{label:"未完成",icon:"!",className:"failed"},
  skipped:{label:"未执行",icon:"–",className:"skipped"},
  pending:{label:"等待中",icon:"·",className:"pending"}
};

function clinicStoreUser(){
  const named=String(window.__clinicUser||"").trim();
  if(named&&named!=="未登录")return named;
  const who=($("who")&&$("who").textContent||"").trim();
  if(who&&who!=="未登录")return who;
  return "local";
}
function clinicRunKey(){return LAST_RUN_KEY+"."+clinicStoreUser()}
function clinicUiKey(){return LAST_UI_KEY+"."+clinicStoreUser()}
function sessionRunKey(){return clinicRunKey()}
function readClinicUi(){
  try{return JSON.parse(localStorage.getItem(clinicUiKey())||"{}")}catch(_){return {}}
}
function persistClinicView(patch){
  if(restoringUi)return;
  const next=Object.assign({},readClinicUi(),patch||{},{updatedAt:Date.now()});
  localStorage.setItem(clinicUiKey(),JSON.stringify(next));
}
function currentModule(){
  return document.querySelector(".module-tab.active")?.dataset.module||"resultsPanel";
}
function rememberRun(runId){
  latestRunId=runId||"";
  if(latestRunId){
    localStorage.setItem(clinicRunKey(),latestRunId);
    localStorage.setItem(LAST_RUN_KEY,latestRunId);
  }else{
    localStorage.removeItem(clinicRunKey());
    localStorage.removeItem(LAST_RUN_KEY);
  }
  persistClinicView({runId:latestRunId,module:currentModule(),source:analysisSource});
  const url=new URL(location.href);
  if(latestRunId)url.searchParams.set("run_id",latestRunId);else url.searchParams.delete("run_id");
  history.replaceState({run_id:latestRunId},"",url);
}
function persistScroll(){
  persistClinicView({scrollY:Math.round(window.scrollY||0),reportScroll:Math.round(($("reportBox")&&$("reportBox").scrollTop)||0)});
}
function restoreScroll(saved){
  const y=Number(saved.scrollY||0),r=Number(saved.reportScroll||0);
  const apply=()=>{if(y)window.scrollTo(0,y);if(r&&$("reportBox"))$("reportBox").scrollTop=r};
  requestAnimationFrame(()=>requestAnimationFrame(apply));
  setTimeout(apply,400);
}
async function restoreClinicSession(){
  restoringUi=true;
  const saved=readClinicUi();
  try{
    latestRunId=params.get("run_id")||latestRunId||saved.runId||localStorage.getItem(clinicRunKey())||localStorage.getItem(LAST_RUN_KEY)||"";
    const runs=await loadResults(latestRunId);
    if(latestRunId&&!(runs||[]).some(item=>item.run_id===latestRunId)){
      latestRunId="";
      const url=new URL(location.href);
      url.searchParams.delete("run_id");
      history.replaceState({run_id:""},"",url);
    }else if(latestRunId){
      const url=new URL(location.href);
      url.searchParams.set("run_id",latestRunId);
      history.replaceState({run_id:latestRunId},"",url);
    }
    if(!latestRunId&&(runs||[]).length) latestRunId=runs[0].run_id;
    if(saved.source==="continue"||saved.source==="upload")selectAnalysisSource(saved.source);
    if(saved.module==="newAnalysisPanel")await selectModule("newAnalysisPanel");
    else await selectModule("resultsPanel");
    restoreScroll(saved);
  }finally{
    restoringUi=false;
    persistClinicView({runId:latestRunId,module:currentModule(),source:analysisSource,scrollY:saved.scrollY||0,reportScroll:saved.reportScroll||0});
  }
}

async function api(path,body,opts){
  const method=(opts&&opts.method)||(body!==undefined?"POST":"GET");
  const headers={};if(body!==undefined)headers["Content-Type"]="application/json";
  const r=await fetch(path,{method,headers,body:body!==undefined?JSON.stringify(body):undefined});
  const text=await r.text();let data={};try{data=JSON.parse(text)}catch(_){data={error:text}}
  if(!r.ok) throw new Error(data.error||"请求失败");
  return data;
}
function inlineMd(value){return esc(value).replace(/`([^`]+)`/g,"<code>$1</code>").replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>")}
function cleanQuote(value){return value.replace(/^\s*>\s?/,"").replace(/^\[!.*?\]\s*/,"").replace(/^##\s*/,"").replace(/^\*\*(.+)\*\*$/,"$1").replace(/^\s*[-*]\s+/,"").replace(/^\[ \]\s*/,"")}
function renderMarkdown(md){
  const lines=String(md||"").split(/\r?\n/),html=[];let paragraph=[],list="";
  const flush=()=>{if(paragraph.length){html.push(`<p>${paragraph.map(inlineMd).join("<br>")}</p>`);paragraph=[]}};
  const closeList=()=>{if(list){html.push(`</${list}>`);list=""}};
  const cells=line=>line.trim().replace(/^\||\|$/g,"").split("|").map(c=>c.trim());
  let i=0;
  while(i<lines.length){
    const line=lines[i],trim=line.trim();
    if(trim.startsWith("> [!refusal]")||trim.startsWith("> [!missing]")||trim.startsWith("> [!finding]")){
      flush();closeList();
      const kind=trim.includes("finding")?"finding":trim.includes("missing")?"missing":"refusal";
      const body=[];i++;
      while(i<lines.length&&lines[i].trim().startsWith(">")){body.push(cleanQuote(lines[i]));i++}
      const title=body.shift()||(kind==="finding"?"阅片要点":"未完成与拒绝");
      html.push(`<aside class="callout ${kind}"><h3>${inlineMd(title)}</h3>${body.filter(Boolean).map(x=>`<p>${inlineMd(x)}</p>`).join("")}</aside>`);continue;
    }
    if(trim.includes("|")&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}/.test(lines[i+1])){
      flush();closeList();const heads=cells(line);i++;const rows=[];
      while(i+1<lines.length&&lines[i+1].includes("|")&&lines[i+1].trim()) rows.push(cells(lines[++i]));
      html.push(`<table><thead><tr>${heads.map(x=>`<th>${inlineMd(x)}</th>`).join("")}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(x=>`<td>${inlineMd(x)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);i++;continue;
    }
    const heading=line.match(/^(#{1,3})\s+(.+)$/);
    if(heading){
      flush();closeList();
      const title=heading[2];
      if(/未完成与拒绝/.test(title)){
        html.push(`<h${heading[1].length} class="refusal-heading">${inlineMd(title)}</h${heading[1].length}>`);i++;
        while(i<lines.length&&!lines[i].trim()) i++;
        if(i<lines.length&&(lines[i].trim().startsWith("> [!refusal]")||lines[i].trim().startsWith("> [!missing]"))) continue;
        const body=[];
        while(i<lines.length&&!lines[i].match(/^#{1,3}\s+/)){if(lines[i].trim()) body.push(cleanQuote(lines[i]));i++}
        const calloutTitle=body.shift()||"未完成与拒绝";
        html.push(`<aside class="callout refusal"><h3>${inlineMd(calloutTitle)}</h3>${body.filter(Boolean).map(x=>`<p>${inlineMd(x)}</p>`).join("")}</aside>`);continue;
      }
      if(/阅片要点/.test(title)){
        html.push(`<h${heading[1].length} class="finding-heading">${inlineMd(title)}</h${heading[1].length}>`);i++;
        while(i<lines.length&&!lines[i].trim()) i++;
        if(i<lines.length&&lines[i].trim().startsWith("> [!finding]")) continue;
        continue;
      }
      if(/能力边界/.test(title)){
        i++;const body=[];
        while(i<lines.length&&!lines[i].match(/^#{1,3}\s+/)){if(lines[i].trim()) body.push(cleanQuote(lines[i]));i++}
        html.push(`<p class="report-boundary">${inlineMd(body.join(" "))}</p>`);continue;
      }
      if(/阅片复核清单|待审清单/.test(title)){
        i++;const items=[];
        while(i<lines.length&&!lines[i].match(/^#{1,3}\s+/)){if(lines[i].trim()) items.push(cleanQuote(lines[i]));i++}
        html.push(`<aside class="callout checklist"><h3>待审清单</h3><ul class="checklist-items">${items.map(x=>`<li><span class="check-box"></span><span>${inlineMd(x)}</span></li>`).join("")}</ul></aside>`);continue;
      }
      html.push(`<h${heading[1].length}>${inlineMd(title)}</h${heading[1].length}>`);i++;continue;
    }
    const item=line.match(/^\s*[-*]\s+(?:\[ \]\s+)?(.+)$/);
    if(item){flush();if(list!=="ul"){closeList();list="ul";html.push("<ul>")}html.push(`<li>${inlineMd(item[1])}</li>`);i++;continue}
    if(!trim){flush();closeList();i++;continue}paragraph.push(line);i++;
  }
  flush();closeList();return html.join("")||'<p class="muted">暂无报告。</p>';
}
function setStatus(text,error=false){$("status").textContent=text||"";$("status").classList.toggle("error",error)}
function clinicalStatus(){
  const picked=document.querySelector('input[name="clinical_status"]:checked');
  return picked?picked.value:"";
}
function setClinicalStatus(value){
  document.querySelectorAll('input[name="clinical_status"]').forEach(input=>{input.checked=input.value===value});
  syncConditionField();
}
function syncConditionField(){
  const status=clinicalStatus();
  const wrap=$("conditionField");
  if(wrap) wrap.hidden=status!=="present"&&status!=="unknown";
  if(status==="none") $("clinical_condition").value="";
}
function clearIntakeForm(){
  $("gestational_age").value="";
  $("fetal_description").value="";
  $("clinical_condition").value="";
  if($("clinical_notes")) $("clinical_notes").value="";
  document.querySelectorAll('input[name="clinical_status"]').forEach(input=>{input.checked=false});
  syncConditionField();
  if($("intakeCaseHint")) $("intakeCaseHint").textContent="先打开一条分析结果。";
}
function formatGaInput(value){
  if(value==null||value==="") return "";
  if(typeof value==="string" && !/^\d+(\.\d+)?$/.test(value.trim())) return value.trim();
  const n=Number(value);
  if(!Number.isFinite(n)) return String(value);
  let weeks=Math.floor(n+1e-9);
  let days=Math.round((n-weeks)*7);
  if(days>=7){weeks+=Math.floor(days/7); days=days%7}
  if(days>0) return weeks+"+"+days;
  return String(weeks);
}
function applyIntake(src){
  if(!src){clearIntakeForm();return}
  $("gestational_age").value=formatGaInput(src.gestational_age);
  $("fetal_description").value=src.fetal_description||"";
  $("clinical_condition").value=src.clinical_condition||"";
  if($("clinical_notes")) $("clinical_notes").value=src.clinical_notes||"";
  if(src.clinical_status) setClinicalStatus(src.clinical_status);
  else document.querySelectorAll('input[name="clinical_status"]').forEach(input=>{input.checked=false});
  syncConditionField();
}
function readIntake(){
  const ga=$("gestational_age").value.trim();
  const desc=$("fetal_description").value.trim();
  const status=clinicalStatus();
  const condition=$("clinical_condition").value.trim();
  const notes=($("clinical_notes")&&$("clinical_notes").value.trim())||"";
  if(!ga) throw new Error("请填写胎龄（例如 34 或 34+1）。");
  if(!desc) throw new Error("请填写胎儿描述。");
  if(!status) throw new Error("请选择临床所见。");
  if(status==="present"&&!condition) throw new Error("请填写疾病名称。");
  return {gestational_age:ga,fetal_description:desc,clinical_status:status,clinical_condition:condition,clinical_notes:notes};
}
function intakeCaseName(runId){
  const item=cachedRuns.find(row=>row.run_id===runId);
  return item?resultLabel(item):"";
}
function applyIntakeFromState(state, runId){
  const src=Object.assign({},state.request||{},state.plan||{},state.clinical_intake||{});
  if(!state.clinical_intake && (src.atlas_rule==="default_middle")) src.gestational_age="";
  applyIntake(src);
  intakeLoadedFor=runId||"";
  if($("intakeCaseHint")) $("intakeCaseHint").textContent=runId?("正在记录："+(intakeCaseName(runId)||runId)):"先打开一条分析结果。";
}
async function saveIntake(){
  const runId=openedRunId||latestRunId;
  if(!runId)throw new Error("请先打开一条分析结果。");
  const intake=readIntake();
  $("saveIntakeBtn").disabled=true;
  setStatus("正在保存病例记录…");
  try{
    const done=await api("/api/clinic-intake",Object.assign({run_id:runId},intake));
    intakeLoadedFor=runId;
    if(done.report_markdown){
      lastReportMarkdown=null;
      $("reportBox").innerHTML=renderMarkdown(done.report_markdown);
      $("reportBox").classList.remove("muted");
    }
    await loadResults(runId);
    await refresh(runId);
    setStatus("病例记录已保存。");
  }finally{
    $("saveIntakeBtn").disabled=false;
  }
}
async function payload(){
  const data={clinic:true,raw_text:$("request").value.trim()};
  if(analysisSource==="continue"){
    const runId=$("continue_result_id").value;
    if(!runId)throw new Error("请选择一条已有分析结果。");
    const state=await api(`/api/state?run_id=${encodeURIComponent(runId)}`);
    const plan=state.plan||{},req=state.request||{};
    const existing=plan.work_root||plan.existing_run_dir||req.existing_run_dir||req.work_root;
    if(!existing)throw new Error("所选记录没有可继续的运行目录。");
    const subject=req.subject_dir||plan.subject_dir||"";
    data.execution_mode="continue_from_run";
    data.existing_run_dir=existing;
    data.work_root=existing;
    data.resume=true;
    data.case_id=state.case_id||req.case_id||"";
    data.explicit_fields=["execution_mode","existing_run_dir","work_root","resume","report_language"];
    if(subject){data.subject_dir=subject;data.explicit_fields.push("subject_dir")}
    return data;
  }
  data.case_id=uploadedCaseId;
  data.execution_mode="run_pipeline";
  data.explicit_fields=["execution_mode","report_language"];
  if(dev&&$("subject_dir").value.trim()){data.subject_dir=$("subject_dir").value.trim();data.explicit_fields.push("subject_dir")}
  return data;
}
function statusBadge(status){
  const meta=statusMeta[status]||{label:status||"未知",icon:"·",className:"pending"};
  return `<span class="status-badge status-${meta.className}"><span class="status-icon">${meta.icon}</span>${esc(meta.label)}</span>`;
}
function failureSummaryFromState(s){
  const failure=s?.report_json?.failure||{};
  const summary=String(failure.summary_zh||"").trim();
  if(summary)return summary;
  const errors=s?.report_json?.errors||[];
  if(errors.length)return String(errors[0]||"").trim();
  const err=String(s?.report_json?.error||"").trim();
  return err||"";
}
function shortFailureReason(text,limit=36){
  const value=String(text||"").trim().replace(/^计划未通过：/,"").replace(/^分析未完成：/,"");
  if(!value)return "";
  return value.length>limit?value.slice(0,limit-1)+"…":value;
}
function progressLine(ds, runStatus, state){
  const reason=failureSummaryFromState(state||{});
  const steps=(ds?.steps||[]).filter(step=>labels[step.id]);
  const failed=steps.find(step=>step.status==="failed");
  if(failed||runStatus==="failed"){
    if(reason)return reason;
    const target=failed||steps.find(step=>step.status==="running")||steps[0];
    return target?`未完成 · ${labels[target.id]||target.id}`:"分析未完成，请查看报告中的说明。";
  }
  const current=steps.find(step=>step.status==="running")||steps.find(step=>step.status==="pending");
  if(!current){
    const allDone=steps.length&&steps.every(step=>step.status==="completed"||step.status==="skipped");
    if(allDone&&runStatus==="running")return "影像处理已完成，正在生成报告…";
    if(allDone||runStatus==="completed")return "分析已完成";
    return "正在分析，请稍候…";
  }
  const index=Math.max(0,steps.findIndex(step=>step.id===current.id));
  const done=steps.filter(step=>step.status==="completed");
  const parts=["处理中",`${labels[current.id]||current.id}（${index+1}/${steps.length}）`];
  if(done.length)parts.push(`${labels[done[done.length-1].id]||done[done.length-1].id}已完成`);
  return parts.join(" · ");
}
function pickInteractiveViewer(step){
  const items=step.artifacts||[];
  const byPath=item=>/_interactive\.html$/i.test(String(item.path||""));
  const byLabel=item=>/(interactive|mpr|viewer|交互)/i.test(String(item.label||"")) && /\.html$/i.test(String(item.path||""));
  return items.find(byPath)||items.find(byLabel);
}
function stepLogPath(ds, step){
  if(!step.log_relpath||!ds?.run?.work_root)return "";
  return `${ds.run.work_root}/dashboard/${step.log_relpath}`;
}
function gallerySteps(ds){
  return (ds?.steps||[]).filter(step=>labels[step.id] && step.status!=="skipped" && step.status!=="pending");
}
function renderGallery(ds){
  const box=$("gallery");
  const named=(ds?.steps||[]).filter(step=>labels[step.id]);
  const steps=gallerySteps(ds);
  if(!steps.length){
    box.innerHTML=named.length
      ?'<p class="muted">本次没有已执行步骤的影像。未执行内容见报告。</p>'
      :'<p class="muted">尚无可展示影像。</p>';
    return;
  }
  const media=[];
  box.innerHTML=steps.map((step,index)=>{
    const preview=step.preview_relpath?fileUrl(`${ds.run.work_root}/dashboard/${step.preview_relpath}`):"";
    const viewer=pickInteractiveViewer(step);
    const log=stepLogPath(ds,step);
    media[index]={title:labels[step.id],preview,viewer:viewer?.path?fileUrl(viewer.path):"",log,message:step.message||""};
    const thumbnail=preview?`<img src="${preview}" alt="${esc(labels[step.id])}缩略图" loading="lazy">`:'<span class="thumbnail-empty">暂无缩略图</span>';
    const imageDisabled=preview||viewer?.path?"":" disabled";
    const logDisabled=log?"":" disabled";
    const note=step.status==="failed"&&step.message?`<p class="card-note">${esc(step.message)}</p>`:"";
    return `<div class="card"><header><span>${esc(labels[step.id])}</span>${statusBadge(step.status)}</header><div class="thumbnail">${thumbnail}</div>${note}<div class="card-actions"><button class="view-button" type="button" data-media="${index}"${imageDisabled}>${imageDisabled?"暂无可查看影像":"查看影像"}</button><button class="view-button" type="button" data-log="${index}"${logDisabled}>${logDisabled?"暂无步骤日志":"查看日志"}</button></div></div>`;
  }).join("");
  box.querySelectorAll("[data-media]").forEach(button=>button.addEventListener("click",()=>openViewer(media[Number(button.dataset.media)])));
  box.querySelectorAll("[data-log]").forEach(button=>button.addEventListener("click",()=>openLog(media[Number(button.dataset.log)])));
}
function openViewer(item){
  if(!item||( !item.viewer&&!item.preview))return;
  openLogPath="";
  $("viewerTitle").textContent=item.title;
  $("viewerBody").innerHTML=item.viewer?`<iframe src="${item.viewer}" title="${esc(item.title)}交互查看"></iframe>`:`<img src="${item.preview}" alt="${esc(item.title)}">`;
  $("viewerDialog").showModal();
}
function stickLogToBottom(view,force){
  if(!view)return;
  const pin=force||(view.scrollHeight-view.scrollTop-view.clientHeight<64);
  const apply=()=>{view.scrollTop=view.scrollHeight};
  if(!pin)return;
  apply();
  requestAnimationFrame(apply);
}
async function loadOpenLog(forceBottom){
  if(!openLogPath)return;
  const body=$("viewerBody");
  const existing=body.querySelector("pre.log-view");
  const pin=forceBottom||!existing||(existing.scrollHeight-existing.scrollTop-existing.clientHeight<64);
  try{
    const data=await api(`/api/log-tail?path=${encodeURIComponent(openLogPath)}&lines=2000`);
    const text=String(data.text||"").trim()||"（日志文件为空）";
    let view=existing;
    if(!view){
      body.innerHTML=`<pre class="log-view"></pre>`;
      view=body.querySelector("pre.log-view");
    }
    if(view.textContent!==text)view.textContent=text;
    stickLogToBottom(view,pin);
  }catch(error){
    body.innerHTML=`<p class="log-empty">${esc(error.message||"无法读取日志")}</p>`;
  }
}
function openLog(item){
  if(!item?.log)return;
  openLogPath=item.log;
  $("viewerTitle").textContent=`${item.title} · 步骤日志`;
  $("viewerBody").innerHTML=`<pre class="log-view">正在读取日志…</pre>`;
  $("viewerDialog").showModal();
  loadOpenLog(true);
}
function closeViewer(){
  openLogPath="";
  $("viewerDialog").close();
  $("viewerBody").innerHTML="";
}
function bindOpenedRun(runId){
  refreshGen+=1;
  if(refreshTimer){clearTimeout(refreshTimer);refreshTimer=null}
  openedRunId=runId||"";
  if(!openedRunId){intakeLoadedFor="";clearIntakeForm()}
  else if(intakeLoadedFor!==openedRunId) intakeLoadedFor="";
}
function renderIdleWorkspace(report,gallery){
  if($("viewerDialog")&&$("viewerDialog").open)closeViewer();
  $("reportBox").innerHTML=`<p class="muted">${esc(report)}</p>`;
  $("gallery").innerHTML=`<p class="muted">${esc(gallery)}</p>`;
  $("reportBox").classList.add("muted");
  lastReportMarkdown=null;
  lastGallerySignature="";
}
function showMissingResult(message){
  renderIdleWorkspace(message,"该记录没有可展示的流程影像。");
  setStatus(message,true);
}
function withPreservedScroll(fn){
  const y=window.scrollY||0;
  const report=$("reportBox");
  const r=report?report.scrollTop:0;
  fn();
  if(window.scrollY!==y)window.scrollTo(0,y);
  if(report)report.scrollTop=r;
}
function showReportPlaceholder(text){
  if(lastReportMarkdown===text&&$("reportBox").classList.contains("muted"))return;
  withPreservedScroll(()=>{
    $("reportBox").innerHTML=`<p class="muted">${esc(text)}</p>`;
    $("reportBox").classList.add("muted");
  });
  lastReportMarkdown=text;
}
async function refresh(runId){
  if(!runId)return;
  const gen=refreshGen;
  if(openedRunId!==runId)return;
  if(refreshTimer){clearTimeout(refreshTimer);refreshTimer=null}
  try{
    const s=await api(`/api/state?run_id=${encodeURIComponent(runId)}`);
    if(gen!==refreshGen||openedRunId!==runId)return;
    if(!s.run_id){
      showMissingResult("当前没有可打开的分析结果。");
      return;
    }
    const markdown=String(s.report_markdown||"");
    if(!markdown.trim()){
      const empty=s.status==="running"||s.status==="planned"
        ?"分析进行中，报告生成后将显示在这里。"
        :"该分析记录还没有可查看的报告。";
      showReportPlaceholder(empty);
      if(!(s.status==="running"||s.status==="planned"))setStatus(empty,true);
    }else if(markdown!==lastReportMarkdown){
      withPreservedScroll(()=>{
        $("reportBox").innerHTML=renderMarkdown(markdown);$("reportBox").classList.remove("muted");
      });
      lastReportMarkdown=markdown;
    }
    const dash=s.dashboard?.dashboard_state;
    let line="";
    if(dash){
      try{
        const ds=await api(`/api/dashboard-state?path=${encodeURIComponent(dash)}`);
        if(gen!==refreshGen||openedRunId!==runId)return;
        const signature=JSON.stringify((ds.steps||[]).map(step=>[step.id,step.status,step.preview_relpath,step.log_relpath,step.artifacts]));
        if(signature!==lastGallerySignature){
          withPreservedScroll(()=>renderGallery(ds));
          lastGallerySignature=signature;
        }
        if(openLogPath&&$("viewerDialog").open)loadOpenLog();
        line=progressLine(ds,s.status,s);
      }catch(_){}
    }else if(!(s.status==="running"||s.status==="planned")||markdown.trim()){
      withPreservedScroll(()=>{
        $("gallery").innerHTML='<p class="muted">该记录没有可展示的流程影像。</p>';
      });
      lastGallerySignature="";
    }
    if(gen!==refreshGen||openedRunId!==runId)return;
    if(intakeLoadedFor!==runId) applyIntakeFromState(s, runId);
    if(!line&&s.status==="failed") line=failureSummaryFromState(s);
    if(s.status==="running"||s.status==="planned"){
      setStatus(line||"正在分析，请稍候…");
      refreshTimer=setTimeout(()=>refresh(runId),2000);
    }else{
      await loadResults(runId);
      if(gen!==refreshGen||openedRunId!==runId)return;
      if(!markdown.trim())setStatus(line||failureSummaryFromState(s)||"该分析记录还没有可查看的报告。",true);
      else if(s.status==="failed")setStatus(line||failureSummaryFromState(s)||"分析未完成，请查看报告中的说明。",true);
      else setStatus(line||"分析已完成。");
    }
  }catch(error){
    if(gen===refreshGen&&openedRunId===runId){
      showMissingResult(error.message||"无法加载分析结果。");
    }
  }
}
function formatSize(bytes){
  if(bytes<1024)return bytes+" B";
  if(bytes<1024*1024)return (bytes/1024).toFixed(1)+" KB";
  return (bytes/1024/1024).toFixed(1)+" MB";
}
function renderUploadList(){
  const box=$("uploadList");
  const rename=$("renameCaseBtn");
  if(rename) rename.hidden=!uploadedCaseId;
  if(!selectedFiles.length){
    box.classList.remove("ready");
    box.innerHTML=uploadedCaseId
      ?`<div class="queue-head"><span>已上传 ${esc(uploadedCaseLabel||uploadedCaseId)}</span></div>`
      :`<div class="upload-empty">尚未选择 DICOM 文件夹、压缩包或 NIfTI</div>`;
    return;
  }
  const total=selectedFiles.reduce((sum,file)=>sum+file.size,0);
  const rows=selectedFiles.map((file,index)=>{
    const pct=file._progress||0;
    const state=pct>=100?"done":(pct>0?"uploading":"");
    const label=uploadRelPath(file);
    return `<div class="file-row ${state}" data-index="${index}">
      <div class="file-meta"><strong title="${esc(label)}">${esc(label)}</strong><small>${formatSize(file.size)}${pct>0&&pct<100?` · ${pct}%`:pct>=100?" · 完成":""}</small></div>
      <button class="file-remove" type="button" data-remove="${index}" ${uploadBusy?"disabled":""} aria-label="移除 ${esc(label)}">×</button>
      <div class="file-progress" aria-hidden="true"><span style="width:${pct}%"></span></div>
    </div>`;
  }).join("");
  box.classList.add("ready");
  box.innerHTML=`<div class="queue-head"><span>待提交 ${selectedFiles.length} 个文件 · ${formatSize(total)}</span>${uploadBusy?"":`<button type="button" id="clearFilesBtn">清空</button>`}</div><div class="upload-scroll">${rows}</div>`;
  box.querySelectorAll("[data-remove]").forEach(btn=>btn.addEventListener("click",event=>{
    event.preventDefault();
    removeFile(Number(btn.dataset.remove));
  }));
  const clear=$("clearFilesBtn");
  if(clear) clear.addEventListener("click",()=>{if(!uploadBusy){selectedFiles=[];renderUploadList();}});
}
const MAX_UPLOAD_FILES=20000;
const MAX_NIFTI_FILES=20;
const SKIP_DIR=/^(Viewer|DICOMDIR|.+_JPG)$/i;
const JUNK_FILE=/^(DICOMDIR|Thumbs\.db|desktop\.ini|StudyInfo\.dat)$|\.(jpg|jpeg|png|gif|bmp|pdf|exe|txt|dat|xlsx|xls|doc|docx|json)$/i;
function uploadRelPath(file){
  const raw=String(file._rel||file.webkitRelativePath||file.name||"").replace(/\\/g,"/").replace(/^\/+/,"");
  return raw||file.name||"";
}
function isIrrelevantUpload(rel){
  const text=String(rel||"").replace(/\\/g,"/").trim();
  if(!text)return true;
  const parts=text.split("/").filter(Boolean);
  if(!parts.length)return true;
  const name=parts[parts.length-1];
  if(name.charAt(0)==="."||JUNK_FILE.test(name))return true;
  return parts.some(part=>SKIP_DIR.test(part));
}
function isZipName(rel){return /\.zip$/i.test((String(rel||"").split("/").pop()||""))}
function isNiftiName(rel){
  const name=(String(rel||"").split("/").pop()||"").toLowerCase();
  return name.endsWith(".nii.gz")||name.endsWith(".nii");
}
function validateFiles(files){
  const incoming=[...files];
  const skipped=incoming.filter(file=>isIrrelevantUpload(uploadRelPath(file)));
  const kept=incoming.filter(file=>!isIrrelevantUpload(uploadRelPath(file)));
  for(const file of kept) file._rel=uploadRelPath(file);
  if(!kept.length){
    if(skipped.length)throw new Error("所选文件均为预览图、PDF 或无关文件，未加入上传清单。");
    return [];
  }
  const zips=kept.filter(file=>isZipName(file._rel));
  const niftis=kept.filter(file=>isNiftiName(file._rel));
  if(zips.length&&zips.length!==kept.length)throw new Error("请不要把压缩包和其它文件混在一次上传里。");
  if(zips.length>1)throw new Error("一次只上传一个 DICOM 压缩包。");
  if(niftis.length&&niftis.length!==kept.length)throw new Error("请不要把 NIfTI 和 DICOM 混在一次上传里。");
  if(niftis.length>MAX_NIFTI_FILES)throw new Error(`NIfTI 一次最多 ${MAX_NIFTI_FILES} 个。`);
  kept._skipped=skipped.length;
  return kept;
}
function addFiles(files){
  try{
    const incoming=validateFiles(files);
    if(!incoming.length)return;
    const addingZip=incoming.some(file=>isZipName(file._rel));
    const haveZip=selectedFiles.some(file=>isZipName(uploadRelPath(file)));
    if((addingZip||haveZip)&&selectedFiles.length+incoming.length>1)throw new Error("一次只上传一个 DICOM 压缩包。");
    const known=new Set(selectedFiles.map(file=>uploadRelPath(file).toLowerCase()));
    const unique=incoming.filter(file=>!known.has(file._rel.toLowerCase()));
    if(selectedFiles.length+unique.length>MAX_UPLOAD_FILES)throw new Error(`一次最多上传 ${MAX_UPLOAD_FILES} 个文件。`);
    for(const file of unique){
      known.add(file._rel.toLowerCase());
      file._progress=0;
      selectedFiles.push(file);
    }
    renderUploadList();
    const skipped=incoming._skipped||0;
    const skipNote=skipped?`已跳过 ${skipped} 个无关文件。`:"";
    setStatus(selectedFiles.length?`已加入清单 ${selectedFiles.length} 个文件。${skipNote}可再选一批，确认后点击“提交分析任务”开始上传。`:skipNote);
  }catch(error){setStatus(error.message,true);renderUploadList()}
}
function removeFile(index){
  if(uploadBusy)return;
  selectedFiles.splice(index,1);
  renderUploadList();
}
function putUploadHeaders(){
  const headers={"Content-Type":"application/octet-stream"};
  if(typeof token==="string"&&token) headers.Authorization="Bearer "+token;
  return headers;
}
function putUploadChunk(url,blob,onProgress){
  return new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest();
    xhr.open("PUT",url);
    xhr.withCredentials=true;
    const headers=putUploadHeaders();
    Object.keys(headers).forEach(key=>xhr.setRequestHeader(key,headers[key]));
    xhr.upload.onprogress=event=>{
      if(onProgress&&event.lengthComputable)onProgress(event.loaded,event.total);
    };
    xhr.onload=()=>{
      let data={};try{data=JSON.parse(xhr.responseText||"")}catch(_){data={error:xhr.responseText}}
      if(xhr.status>=200&&xhr.status<300)resolve(data);
      else reject(new Error(data.error||`上传失败（${xhr.status}）`));
    };
    xhr.onerror=()=>reject(new Error("上传中断，请重试。"));
    xhr.send(blob);
  });
}
async function discardUpload(caseId){
  if(!caseId)return;
  try{await api(`/api/clinic-upload/${caseId}`,undefined,{method:"DELETE"})}catch(_){}
}
async function uploadFiles(){
  if(!selectedFiles.length)return;
  let caseId="";
  uploadBusy=true;
  selectedFiles.forEach(file=>{file._progress=0});
  renderUploadList();
  setStatus(`正在上传 0 / ${selectedFiles.length}`);
  try{
  const init=await api("/api/clinic-upload",{
    files:selectedFiles.map(file=>({name:uploadRelPath(file),size:file.size})),
    label:$("case_label").value.trim()
  });
  caseId=init.case_id;
  if(init.label)$("case_label").value=init.label;
  uploadedCaseLabel=init.label||init.case_id;
  const chunk=init.chunk_bytes;
  const totalBytes=selectedFiles.reduce((sum,file)=>sum+file.size,0);
  let finishedBytes=0;
  let lastPaint=0;
  const paint=(index,force)=>{
    const now=performance.now();
    if(!force&&now-lastPaint<80)return;
    lastPaint=now;
    renderUploadList();
    const file=selectedFiles[index];
    const pct=file?file._progress||0:100;
    const overall=totalBytes?Math.min(100,Math.round(finishedBytes/totalBytes*100)):0;
    setStatus(`正在上传 ${index+1} / ${selectedFiles.length} · ${pct}% · 合计 ${overall}%`);
  };
  for(let index=0;index<selectedFiles.length;index++){
    const file=selectedFiles[index];let offset=0;
    file._progress=1;
    paint(index,true);
    while(offset<file.size){
      const blob=file.slice(offset,offset+chunk);
      await putUploadChunk(`/api/clinic-upload/${caseId}/${index}?offset=${offset}`,blob,loaded=>{
        finishedBytes=selectedFiles.slice(0,index).reduce((sum,item)=>sum+item.size,0)+offset+loaded;
        file._progress=Math.min(99,Math.max(1,Math.round((offset+loaded)/file.size*100)));
        paint(index,false);
      });
      offset+=blob.size;
      finishedBytes=selectedFiles.slice(0,index).reduce((sum,item)=>sum+item.size,0)+offset;
      file._progress=Math.min(100,Math.round(offset/file.size*100));
      paint(index,true);
    }
    file._progress=100;
    paint(index,true);
  }
  if(!selectedFiles.every(file=>isNiftiName(uploadRelPath(file))))setStatus("正在把 DICOM 转为 NIfTI…");
  const done=await api(`/api/clinic-upload/${caseId}/complete`,{complete:true});
  const item=done.case;
  uploadedCaseId=item.id;
  uploadedCaseLabel=item.label||item.id;
  if(uploadedCaseLabel)$("case_label").value=uploadedCaseLabel;
  selectedFiles=[];$("files").value="";if($("folder"))$("folder").value="";
  renderUploadList();
  }catch(error){
    await discardUpload(caseId);
    throw error;
  }
}
async function analyze(){
  if(!$("request").value.trim())throw new Error("请填写分析目标。");
  $("goBtn").disabled=true;setStatus(analysisSource==="continue"?"正在提交续跑任务…":(selectedFiles.length?"正在上传影像…":"正在提交分析…"));
  try{
    if(analysisSource==="upload"){
      await uploadFiles();
      if(!uploadedCaseId)throw new Error("请先选择 DICOM 文件夹、压缩包或 NIfTI。");
      setStatus("上传完成，正在提交分析…");
    }
    if(!$("request").value.trim())throw new Error("请填写分析目标。");
    const result=await api("/api/analyze",await payload());
    lastReportMarkdown=null;lastGallerySignature="";
    rememberRun(result.run_id);
    bindOpenedRun(result.run_id);
    await loadResults(result.run_id);
    await refresh(result.run_id);
  }catch(error){setStatus(error.message||"分析失败",true)}finally{uploadBusy=false;$("goBtn").disabled=false;renderUploadList()}
}
async function renameCase(){
  if(!uploadedCaseId)return;
  const label=$("case_label").value.trim();
  if(!label){setStatus("请填写病例名称。",true);return}
  const done=await api(`/api/clinic-upload/${uploadedCaseId}/rename`,{label});
  uploadedCaseLabel=done.case.label;
  $("case_label").value=uploadedCaseLabel;
  setStatus(`病例已命名为 ${uploadedCaseLabel}。`);
  await loadResults(latestRunId);
}
function resultLabel(item){
  const status={completed:"已完成",running:"处理中",planned:"等待中",failed:"未完成"}[item.status]||item.status;
  const time=item.updated_at?new Date(item.updated_at).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}):"";
  const name=item.case_label||item.subject||item.case_id||"未命名";
  const reason=item.status==="failed"?shortFailureReason(item.failure_summary||""):"";
  return `${name} · ${status}${reason?" · "+reason:""}${time?" · "+time:""}`;
}
function fillResultSelect(id,runs,selected){
  syncingSelect=true;
  try{
    const previous=$(id).value;
    $(id).innerHTML=runs.map(item=>{
      const tip=[item.goal,item.failure_summary].filter(Boolean).join(" · ");
      return `<option value="${esc(item.run_id)}" title="${esc(tip)}">${esc(resultLabel(item))}</option>`;
    }).join("")||'<option value="">暂无已保存的分析结果</option>';
    const pick=[selected,previous,runs[0]&&runs[0].run_id].find(value=>value&&runs.some(item=>item.run_id===value));
    if(pick)$(id).value=pick;
  }finally{syncingSelect=false}
}
async function loadResults(selected=""){
  const data=await api("/api/results");
  const runs=data.runs||[];
  cachedRuns=runs;
  fillResultSelect("result_id",runs,selected||$("result_id").value);
  fillResultSelect("continue_result_id",runs,selected||$("continue_result_id").value||latestRunId);
  return runs;
}
function selectedResult(){
  const runId=$("result_id").value;
  return cachedRuns.find(item=>item.run_id===runId)||null;
}
function closeRenameDialog(){
  const dialog=$("renameDialog");
  if(dialog.open)dialog.close();
}
function beginResultRename(){
  const item=selectedResult();
  if(!item){setStatus("请先选择一条分析记录。",true);return}
  if(!item.case_id){setStatus("该记录没有可修改的病例名称。",true);return}
  $("result_rename").value=item.case_label||item.subject||"";
  $("renameDialog").showModal();
  $("result_rename").focus();
  $("result_rename").select();
}
async function saveResultRename(){
  const item=selectedResult();
  if(!item?.case_id){setStatus("请先选择一条分析记录。",true);return}
  const label=$("result_rename").value.trim();
  if(!label){setStatus("请填写病例名称。",true);return}
  await api(`/api/clinic-upload/${item.case_id}/rename`,{label});
  closeRenameDialog();
  await loadResults(item.run_id);
  setStatus(`已命名为 ${label}。`);
}
async function onResultPickerChange(){
  if(restoringUi||syncingSelect)return;
  const runId=$("result_id").value;
  if(runId&&runId===openedRunId)return;
  await openExistingResult();
}
async function openExistingResult(){
  const runId=$("result_id").value;
  if(!runId){
    bindOpenedRun("");
    showMissingResult("当前没有可打开的分析结果。");
    return;
  }
  rememberRun(runId);
  bindOpenedRun(runId);
  renderIdleWorkspace("正在打开已有结果…","正在载入流程影像…");
  setStatus("正在打开已有结果…");
  await refresh(runId);
}
async function previewContinueResult(){
  const runId=$("continue_result_id").value;
  if(!runId){
    bindOpenedRun("");
    showMissingResult("当前没有可继续的分析结果。");
    return;
  }
  lastReportMarkdown=null;lastGallerySignature="";
  rememberRun(runId);
  bindOpenedRun(runId);
  setStatus("已载入所选结果，填写分析目标后可继续处理。");
  await refresh(runId);
}
function selectAnalysisSource(source){
  analysisSource=source==="continue"?"continue":"upload";
  document.querySelectorAll(".source-choice-btn").forEach(btn=>{
    const active=btn.dataset.source===analysisSource;
    btn.classList.toggle("active",active);
    btn.setAttribute("aria-checked",String(active));
  });
  $("uploadSource").classList.toggle("active",analysisSource==="upload");
  $("continueSource").classList.toggle("active",analysisSource==="continue");
  $("request").placeholder=analysisSource==="continue"
    ?"例如：接着完成组织分割、脑区划分与表面重建。六步顺序：脑提取、三维重建、图像配准、组织分割、脑区划分、表面重建。"
    :"例如：完成全部六步（脑提取、三维重建、图像配准、组织分割、脑区划分、表面重建），并生成含分步质控的技术报告。";
  persistClinicView({source:analysisSource,module:currentModule(),runId:latestRunId});
}
async function boot(){
  try{
    await restoreClinicSession();
  }catch(error){$("result_id").innerHTML='<option value="">结果记录加载失败</option>';setStatus(error.message,true)}
}
function clearDisplayedResult(){
  bindOpenedRun("");
  renderIdleWorkspace("提交新任务后，将在此生成技术分析报告。","提交新任务后，将在此展示各处理阶段的影像。");
  setStatus("");
}
async function selectModule(panelId){
  document.querySelectorAll(".module-tab").forEach(tab=>{
    const active=tab.dataset.module===panelId;
    tab.classList.toggle("active",active);
    tab.setAttribute("aria-selected",String(active));
  });
  document.querySelectorAll(".module-panel").forEach(panel=>{
    const active=panel.id===panelId;
    panel.classList.toggle("active",active);
    panel.hidden=!active;
  });
  if(panelId==="newAnalysisPanel"){
    if(analysisSource==="continue"){
      if($("continue_result_id").value)await previewContinueResult();
      else clearDisplayedResult();
    }else clearDisplayedResult();
  }else if(panelId==="resultsPanel"){
    const runId=latestRunId||$("result_id").value;
    if(runId){
      lastReportMarkdown=null;
      lastGallerySignature="";
      rememberRun(runId);
      bindOpenedRun(runId);
      setStatus("正在打开已有结果…");
      await refresh(runId);
    }else{
      bindOpenedRun("");
      renderIdleWorkspace("请选择一条既往分析记录，或提交新的影像分析任务。","打开分析结果后，将按处理阶段展示可用影像。");
    }
  }
  persistClinicView({module:panelId,source:analysisSource,runId:latestRunId});
}
function readAllEntries(reader){
  return new Promise((resolve,reject)=>{
    const all=[];
    const pump=()=>reader.readEntries(batch=>{
      if(!batch.length){resolve(all);return}
      all.push(...batch);
      pump();
    },reject);
    pump();
  });
}
function entryToFile(entry,rel){
  return new Promise((resolve,reject)=>entry.file(file=>{
    file._rel=rel;
    resolve(file);
  },reject));
}
async function walkEntry(entry,prefix){
  const rel=prefix?prefix+"/"+entry.name:entry.name;
  if(entry.isFile)return [await entryToFile(entry,rel)];
  if(!entry.isDirectory)return [];
  const children=await readAllEntries(entry.createReader());
  const out=[];
  for(const child of children) out.push(...await walkEntry(child,rel));
  return out;
}
async function filesFromDataTransfer(transfer){
  const items=transfer&&transfer.items;
  if(items&&items.length){
    const entries=[];
    for(const item of items){
      const entry=item.webkitGetAsEntry?item.webkitGetAsEntry():null;
      if(entry)entries.push(entry);
    }
    if(entries.length){
      const out=[];
      for(const entry of entries) out.push(...await walkEntry(entry,""));
      if(out.length)return out;
    }
  }
  return [...(transfer&&transfer.files||[])];
}
const dropzone=$("dropzone");
dropzone.addEventListener("click",()=>$("folder").click());
dropzone.addEventListener("keydown",event=>{if(event.key==="Enter"||event.key===" "){event.preventDefault();$("folder").click()}});
dropzone.addEventListener("dragover",event=>{event.preventDefault();dropzone.classList.add("drag")});
dropzone.addEventListener("dragleave",()=>dropzone.classList.remove("drag"));
dropzone.addEventListener("drop",event=>{
  event.preventDefault();
  dropzone.classList.remove("drag");
  if(uploadBusy)return;
  filesFromDataTransfer(event.dataTransfer).then(addFiles).catch(error=>setStatus(error.message||"无法读取文件夹",true));
});
$("pickFilesBtn").addEventListener("click",event=>{event.preventDefault();event.stopPropagation();if(!uploadBusy)$("files").click()});
$("pickFolderBtn").addEventListener("click",event=>{event.preventDefault();event.stopPropagation();if(!uploadBusy)$("folder").click()});
$("files").addEventListener("change",event=>{if(!uploadBusy)addFiles(event.target.files);event.target.value=""});
$("folder").addEventListener("change",event=>{if(!uploadBusy)addFiles(event.target.files);event.target.value=""});
$("goBtn").addEventListener("click",analyze);
$("saveIntakeBtn").addEventListener("click",()=>saveIntake().catch(error=>setStatus(error.message||"保存失败",true)));
document.querySelectorAll('input[name="clinical_status"]').forEach(input=>{
  input.addEventListener("change",syncConditionField);
});
$("renameCaseBtn").addEventListener("click",()=>renameCase().catch(error=>setStatus(error.message,true)));
$("renameResultBtn").addEventListener("click",beginResultRename);
$("renameForm").addEventListener("submit",event=>{
  event.preventDefault();
  saveResultRename().catch(error=>setStatus(error.message,true));
});
$("renameCancelBtn").addEventListener("click",closeRenameDialog);
$("renameDialog").addEventListener("click",event=>{if(event.target===$("renameDialog"))closeRenameDialog()});
$("result_id").addEventListener("change",()=>onResultPickerChange().catch(error=>setStatus(error.message,true)));
$("continue_result_id").addEventListener("change",()=>previewContinueResult().catch(error=>setStatus(error.message,true)));
document.querySelectorAll(".source-choice-btn").forEach(btn=>btn.addEventListener("click",()=>{
  selectAnalysisSource(btn.dataset.source);
  if(analysisSource==="continue")previewContinueResult().catch(error=>setStatus(error.message,true));
  else clearDisplayedResult();
}));
document.querySelectorAll(".module-tab").forEach(tab=>tab.addEventListener("click",()=>selectModule(tab.dataset.module).catch(error=>setStatus(error.message,true))));
$("viewerClose").addEventListener("click",closeViewer);
window.addEventListener("scroll",()=>{
  clearTimeout(persistScrollTimer);
  persistScrollTimer=setTimeout(persistScroll,200);
},{passive:true});
$("reportBox").addEventListener("scroll",()=>{
  clearTimeout(persistScrollTimer);
  persistScrollTimer=setTimeout(persistScroll,200);
},{passive:true});
$("viewerDialog").addEventListener("click",event=>{if(event.target===$("viewerDialog"))closeViewer()});
boot();
</script>
</body>
</html>
"""

_dashboard.PAGE_HTML = CLINIC_HTML


def _translated_html() -> str:
    return CLINIC_HTML


def main() -> int:
    return _dashboard.main()


if __name__ == "__main__":
    raise SystemExit(main())
