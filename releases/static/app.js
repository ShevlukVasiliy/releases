'use strict';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="releases-token"]').content;
const selected = new Set();
const picked = new Map(); let currentResults = [];
let artists = [], lastArtists = '', lastJobs = '', lastResults = '', timer = null, matchArtist = null;
const element = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };
function notify(message, error = false) { const el = $('notice'); el.textContent = message; el.className = `notice${error ? ' error' : ''}`; el.hidden = false; clearTimeout(notify.timer); notify.timer = setTimeout(() => el.hidden = true, 5000); }
async function get(path) { const response = await fetch(path); if (!response.ok) throw new Error('Не удалось получить данные'); return response.json(); }
async function post(path, body) { try { const response = await fetch(path, {method:'POST', headers:{'X-Releases-Token':token,'Content-Type':'application/json'}, body:body ? JSON.stringify(body) : null}); const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Не удалось выполнить действие'); clearTimeout(timer); refresh(); return result; } catch(error) { notify(error.message, true); return null; } }
function visible() { const q = $('search').value.trim().toLocaleLowerCase(); return artists.filter(a => a.name.toLocaleLowerCase().includes(q)); }
function selection() { $('selectionInfo').textContent = selected.size ? `Выбрано: ${selected.size}` : 'Ничего не выбрано'; $('check').disabled = selected.size === 0; }
function renderArtists() {
  const list = $('artists'); const rows = visible().map(a => {
    const row = element('div', `artist${a.excluded ? ' excluded' : ''}`); const label = document.createElement('label');
    const cb = document.createElement('input'); cb.type='checkbox'; cb.checked=selected.has(a.id); cb.disabled=!!a.excluded;
    cb.onchange=()=>{cb.checked ? selected.add(a.id) : selected.delete(a.id); selection();};
    label.append(cb, element('span','name',a.name)); const count=element('span','count',String(a.track_count));
    const exclude=element('button','exclude',a.excluded?'↩':'×'); exclude.type='button'; exclude.title=a.excluded?'Вернуть в проверку':'Исключить из проверки'; exclude.setAttribute('aria-label',`${exclude.title}: ${a.name}`);
    exclude.onclick=async()=>{if(await post('/api/exclude',{artist_id:a.id,excluded:!a.excluded})){selected.delete(a.id); await loadArtists(true);}};
    row.append(label,count,exclude); return row;
  }); list.replaceChildren(...rows); $('artistCount').textContent=String(artists.length); selection();
}
async function loadArtists(force=false) { const data=await get('/api/artists'); const encoded=JSON.stringify(data); if(force||encoded!==lastArtists){artists=data; lastArtists=encoded; const allowed=new Set(data.filter(a=>!a.excluded).map(a=>a.id)); for(const id of selected)if(!allowed.has(id))selected.delete(id); renderArtists();} }
for(const id of ['noSingles','noRemixes','since']){const field=$(id);try{const saved=localStorage.getItem('filter:'+id);if(saved!==null){if(field.type==='checkbox')field.checked=saved==='true';else field.value=saved;}}catch{}field.addEventListener('change',()=>{try{localStorage.setItem('filter:'+id,field.type==='checkbox'?String(field.checked):field.value);}catch{}});}
$('search').oninput=renderArtists;
$('selectVisible').onclick=()=>{visible().filter(a=>!a.excluded).forEach(a=>selected.add(a.id));renderArtists();};
$('clearSelection').onclick=()=>{selected.clear();renderArtists();};
$('scan').onclick=()=>post('/api/scan');
$('check').onclick=()=>post('/api/check',{artist_ids:[...selected],options:{no_singles:$('noSingles').checked,no_remixes:$('noRemixes').checked,since:$('since').value ? Number($('since').value) : null}});
$('openSettings').onclick=()=>$('settings').showModal(); $('openDownloads').onclick=()=>$('downloads').showModal();
$('saveToken').onclick=async()=>{const value=$('yandexToken').value;if(!value)return notify('Вставь токен',true);if(await post('/api/token',{token:value})){$('yandexToken').value='';notify('Токен сохранён');}};
$('previewOrder').onclick=async()=>{if(await post('/api/order-preview')){$('settings').close();notify('Сверка порядка запущена');}};
$('previewFixes').onclick=async()=>{if(await post('/api/fix-preview')){$('settings').close();notify('Проверка тегов запущена');}};
$('legacy').onclick=async()=>{if(await post('/api/legacy')){$('settings').close();notify('Перенос настроек запущен');}};
$('downloadLinks').onclick=async()=>{const result=await post('/api/downloads',{text:$('links').value});if(result){$('downloads').close();$('links').value='';notify(`В очереди: ${result.queued} из ${result.found}`);}};
$('saveMatch').onclick=async()=>{const id=Number($('matchId').value);if(!Number.isSafeInteger(id)||id<=0)return notify('Укажи числовой ID артиста',true);if(await post('/api/match',{artist_id:matchArtist,provider_id:id})){$('matchDialog').close();notify('Сопоставление проверяется');}};
function showResults(items) {
  currentResults=items; const container=$('results'); if(!items.length)return;
  const total=items.reduce((n,r)=>n+(r.missing?.length||0),0); $('resultCount').textContent=`· ${total}`;
  container.replaceChildren(...items.map(r=>{
    const group=element('div','result-group'), title=element('div','result-title'); title.append(element('strong','',r.name||`Артист ${r.id}`),element('small','',r.error?'Ошибка':r.found?`${r.missing.length} ${new Intl.PluralRules('ru').select(r.missing.length)==='one'?'релиз':new Intl.PluralRules('ru').select(r.missing.length)==='few'?'релиза':'релизов'}`:'Не найден'));
    const match=element('button','quiet','Сопоставить');match.onclick=()=>{matchArtist=r.id;$('matchName').textContent=r.name||'';$('matchId').value='';$('matchDialog').showModal();};title.append(match);group.append(title);
    if(r.error){group.append(element('div','release',r.error));return group;}
    for(const release of r.missing||[]){const row=element('div','release'), cb=document.createElement('input'), link=element('a','',release.title);cb.type='checkbox';cb.checked=picked.has(release.id);cb.setAttribute('aria-label','Выбрать '+release.title);cb.onchange=()=>{cb.checked?picked.set(release.id,release):picked.delete(release.id);updatePicked();};link.href=release.url;link.target='_blank';link.rel='noopener noreferrer';const button=element('button','quiet','Скачать');button.onclick=async()=>{if(await post('/api/download',{album_id:Number(release.id)}))notify('Добавлено в очередь');};row.append(cb,link,element('small','',release.date),element('small','',release.type||''),button);group.append(row);} return group;
  }));
}

function updatePicked(){ $('downloadSelected').disabled=!picked.size; $('downloadSelected').textContent=picked.size?`Скачать (${picked.size})`:'Скачать выбранные'; }
$('selectReleases').onclick=()=>{const releases=currentResults.flatMap(r=>r.missing||[]); if(releases.length&&releases.every(r=>picked.has(r.id)))picked.clear();else releases.forEach(r=>picked.set(r.id,r)); updatePicked();showResults(currentResults);};
$('exportReport').onclick=()=>{if(!currentResults.length)return notify('Нет результатов для отчёта',true);const lines=['# Недостающие релизы',''];for(const r of currentResults){lines.push(`## ${(r.name||String(r.id)).replace(/[\r\n]/g,' ')}`);if(r.error)lines.push(`Ошибка: ${r.error}`);else if(!r.found)lines.push('Артист не найден');else if(!r.missing.length)lines.push('Недостающих релизов не найдено');else for(const m of r.missing)lines.push(`- ${m.date} · [${m.title.replace(/[\[\]]/g,'')}](${m.url})`);lines.push('');}const blob=new Blob([lines.join('\n')],{type:'text/markdown;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='releases.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('copyLinks').onclick=async()=>{const links=currentResults.flatMap(r=>r.missing||[]).map(r=>r.url);if(!links.length)return notify('Нет ссылок для копирования',true);try{await navigator.clipboard.writeText(links.join('\n'));notify('Ссылки скопированы');}catch{notify('Не удалось скопировать ссылки',true);}};
$('downloadSelected').onclick=async()=>{const data=await post('/api/downloads',{text:[...picked.values()].map(r=>r.url).join('\n')});if(data){picked.clear();updatePicked();showResults(currentResults);notify(`В очереди: ${data.queued} из ${data.found}`);}};

function showJobs(jobs) {
  const scan=jobs.find(j=>j.kind==='scan'), check=jobs.find(j=>j.kind==='check');
  const status = j => j.status==='running'?`Выполнено ${j.progress.done||0} из ${j.progress.total||'…'}`:({queued:'В очереди',done:'Готово',error:'Ошибка',interrupted:'Прервано'}[j.status]||j.status);
  if(scan)$('scanStatus').textContent=scan.error||status(scan);
  if(check){$('checkStatus').textContent=check.error||status(check);if(check.result?.results){const key=JSON.stringify(check.result.results);if(key!==lastResults){lastResults=key;showResults(check.result.results);}}}
  const relevant=jobs.filter(j=>['download','match','import','legacy','fix_preview','fix_apply','order_preview','order_apply'].includes(j.kind)); $('queueCount').textContent=relevant.length?String(relevant.length):'';
  if(!relevant.length){$('queue').className='queue-empty';$('queue').textContent='Задач пока нет';return;}
  $('queue').className=''; $('queue').replaceChildren(...relevant.map(j=>{
    const row=element('div',`job ${j.status}`), details=element('div'), labels={download:'Загрузка альбома',match:'Сопоставление артиста',import:'Импорт в Apple Music',legacy:'Перенос настроек',fix_preview:'Проверка тегов',fix_apply:'Исправление тегов',order_preview:'Сверка порядка в Music',order_apply:'Изменение порядка в Music'};
    details.append(element('strong','',labels[j.kind]),element('small','',`${status(j)}${j.progress.current?' · '+j.progress.current:''}${j.error?' · '+j.error:''}${j.result?.errors?' · Ошибок: '+j.result.errors:''}`));
    if(j.kind==='legacy'&&j.result?.matches_added!==undefined)details.append(element('small','',`Исключений: ${j.result.excluded_added}, сопоставлений: ${j.result.matches_added}`));
    if(j.kind==='import'&&j.result?.files){const errs=j.result.files.filter(f=>f.error);for(const err of errs)details.append(element('small','',`${err.file}: ${err.error}`));}
    if(j.kind==='fix_preview'&&j.result?.changes){const changes=j.result.changes;details.append(element('small','',`Файлов: ${j.result.files}, изменений: ${changes.length}, ошибок: ${j.result.errors.length}`));if(changes.length){const more=document.createElement('details'),summary=element('summary','','Посмотреть изменения'),list=document.createElement('ul');for(const c of changes){list.append(element('li','',`${c.path}: ${c.fixes.join(', ')}`));}more.append(summary,list);details.append(more);}}
    if(j.kind==='fix_apply'&&j.result?.results){const more=document.createElement('details'),summary=element('summary','','Результаты'),list=document.createElement('ul');for(const c of j.result.results)list.append(element('li','',`${c.path}: ${c.error||'сохранена резервная копия '+c.backup}`));more.append(summary,list);details.append(more);}
    if(j.kind==='order_preview'&&j.result?.changes){const changes=j.result.changes;details.append(element('small','',`Альбомов: ${j.result.albums}, изменений: ${changes.length}, несовпадений: ${j.result.issues.length}`));if(changes.length){const more=document.createElement('details'),summary=element('summary','','Посмотреть изменения'),list=document.createElement('ul');for(const c of changes)list.append(element('li','',`${c.album} — ${c.title}: ${c.old.join('/')} → ${c.values.join('/')}`));more.append(summary,list);details.append(more);}}
    if(j.kind==='order_apply'&&j.result)details.append(element('small','',`Обновлено: ${j.result.updated}, ошибок: ${j.result.errors.length}`));
    row.append(details); if(j.kind==='order_preview'&&j.status==='done'&&j.result?.changes?.length){const b=element('button','secondary','Применить порядок');b.onclick=()=>post('/api/order-apply',{preview_id:j.id});row.append(b);} if(j.kind==='fix_preview'&&j.status==='done'&&j.result?.changes?.length){const b=element('button','secondary','Применить исправления');b.onclick=()=>post('/api/fix-apply',{preview_id:j.id});row.append(b);} if(j.kind==='download'&&j.status==='done'){const b=element('button','secondary','Добавить в Music'); b.onclick=()=>post('/api/import',{download_id:j.id});row.append(b);}return row;
  }));
}
async function refresh(){try{const jobs=await get('/api/jobs');const encoded=JSON.stringify(jobs);if(encoded!==lastJobs){lastJobs=encoded;showJobs(jobs);}if(jobs.some(j=>['running','queued'].includes(j.status)))timer=setTimeout(refresh,1200);else await loadArtists();}catch(e){notify('Сервис недоступен',true);}}
refresh();
