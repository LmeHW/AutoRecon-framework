const progress=document.querySelector('.progress');
window.addEventListener('scroll',()=>{const h=document.documentElement.scrollHeight-innerHeight;progress.style.width=`${h?scrollY/h*100:0}%`});

const observer=new IntersectionObserver(entries=>entries.forEach(entry=>{if(entry.isIntersecting){entry.target.classList.add('visible');observer.unobserve(entry.target)}}),{threshold:.12});
document.querySelectorAll('.reveal').forEach(el=>observer.observe(el));

const resultImage=document.querySelector('#result-image');
const resultTitle=document.querySelector('#result-title');
const resultCaption=document.querySelector('#result-caption');
document.querySelectorAll('.viewer-tab').forEach(tab=>tab.addEventListener('click',()=>{
  document.querySelectorAll('.viewer-tab').forEach(item=>item.classList.remove('active'));
  tab.classList.add('active'); resultImage.style.opacity='.25';
  const preload=new Image(); preload.src=tab.dataset.image; preload.onload=()=>{resultImage.src=preload.src;resultImage.alt=`${tab.dataset.title}结果预览`;resultTitle.textContent=tab.dataset.title;resultCaption.textContent=tab.dataset.caption;resultImage.style.opacity='1'};
}));
resultImage.style.transition='opacity .2s ease';

document.querySelector('#copy-code').addEventListener('click',async event=>{
  const text='cp .env.example .env\n\nAUTORECON_SECRET_FILE=<secret-file> scripts/run_agentic_dashboard.sh --host 127.0.0.1 --port 8899';
  await navigator.clipboard.writeText(text);
  event.currentTarget.textContent='已复制';
  setTimeout(()=>event.currentTarget.textContent='复制',1600);
});
