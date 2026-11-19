'use strict';
const $ = (selector, root=document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const main = $('#main');
const scriptUrl = new URL(document.querySelector('script[src*="app.js"]').src);
const basePath = scriptUrl.pathname.replace(/\/static\/app\.js$/, '').replace(/\/$/, '');
const apiUrl = path => `${basePath}/${String(path).replace(/^\/+/, '')}`;
const publicCode = main.dataset.publicCode || (location.pathname.match(/\/t\/([^/]+)$/)?.[1] ?? '');
let sessionInfo, testInfo, state, ticker, syncing=false, preview=null, selected=null, filterPage=1;
let editorModel=null, editorWasOpen=false, resultTestId=null, clockAt=0, remainingAt=0, screen='', toastTimer, viewEpoch=0;
const date = value => value==null ? '—' : new Date(value*1000).toLocaleString('uk-UA',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
const secondsLabel = value => value==null ? 'Без таймера' : `${value} с / запитання`;

async function api(path,data,method='POST') {
  const options={credentials:'same-origin',headers:{'Accept':'application/json'},cache:'no-store'};
  if(data!==undefined){options.method=method;options.headers['Content-Type']='application/json';options.headers['X-CSRF-Token']=sessionInfo?.csrf||'';options.body=JSON.stringify(data);}
  const controller=new AbortController(), timeout=setTimeout(()=>controller.abort(),5000), startedAt=performance.now();
  options.signal=controller.signal;
  let response,result;
  try{response=await fetch(apiUrl(path),options);result=await response.json();}
  catch(error){throw new Error(error.name==='AbortError'?'Сервер не відповів вчасно. Повторіть дію.':'Немає зв’язку із сервером. Перевірте інтернет і повторіть дію.');}
  finally{clearTimeout(timeout);}
  for(const candidate of [result,result?.attempt]) if(candidate&&typeof candidate.server_time==='number') candidate._requestStarted=startedAt;
  if(!response.ok){const error=new Error(result.error||'Не вдалося виконати дію. Спробуйте ще раз.');error.status=response.status;throw error;}
  return result;
}
function toast(message){$('#toast').textContent=message;$('#toast').classList.remove('hidden');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.add('hidden'),5500);}
function show(html,name){clearInterval(ticker);viewEpoch++;screen=name;main.innerHTML=html;window.scrollTo(0,0);}
function errorBox(target,message){if(target){target.textContent=message;target.classList.remove('hidden');}}
function closeSiteMenu(){
  const toggle=$('#menu-toggle'),menu=$('#site-menu');
  if(!toggle||!menu)return;
  menu.hidden=true;toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-label','Відкрити меню');
}
function toggleSiteMenu(){
  const toggle=$('#menu-toggle'),menu=$('#site-menu');
  if(!toggle||!menu)return;
  menu.hidden=!menu.hidden;toggle.setAttribute('aria-expanded',String(!menu.hidden));
  toggle.setAttribute('aria-label',menu.hidden?'Відкрити меню':'Закрити меню');
}
$('#menu-toggle').addEventListener('click',toggleSiteMenu);
$('#site-menu').addEventListener('click',event=>{
  const button=event.target.closest('[data-menu-action]');
  if(!button)return;
  closeSiteMenu();
  if(button.dataset.menuAction==='tests')library();
  if(button.dataset.menuAction==='create')createTest(button);
});
document.addEventListener('pointerdown',event=>{if(!event.target.closest('#site-menu')&&!event.target.closest('#menu-toggle'))closeSiteMenu();});
document.addEventListener('keydown',event=>{if(event.key==='Escape')closeSiteMenu();});
function account(){
  const user=sessionInfo.user;
  const menu=$('#site-menu'),toggle=$('#menu-toggle');
  const isTeacher=user?.role==='teacher';
  toggle.hidden=!isTeacher;
  if(isTeacher){
    menu.innerHTML='<button type="button" data-menu-action="tests">Мої тести</button><button type="button" data-menu-action="create">Створити тест</button>';
    closeSiteMenu();
  }else{menu.innerHTML='';closeSiteMenu();}
  $('#account').innerHTML=user?`<span class="account-email">${esc(user.email)}</span>${user.role==='teacher'?'<button class="text-button" id="account-password">Пароль</button>':''}<button class="text-button" id="logout">Вийти</button>`:'<span class="tag">Навчальне тестування</span>';
  $('#account-password')?.addEventListener('click',passwordView);
  $('#logout')?.addEventListener('click',async()=>{try{await api('api/auth/logout',{});preview=null;await boot();}catch(error){toast(error.message);}});
}
async function boot(){
  try{
    sessionInfo=await api('api/session');account();
    if(sessionInfo.user?.role==='teacher')return library();
    testInfo=publicCode?await api(`api/tests/${encodeURIComponent(publicCode)}`):await api('api/test');
    if(!sessionInfo.user)return login();
    const current=publicCode?await api(`api/tests/${encodeURIComponent(publicCode)}/attempts/current`):await api('api/attempts/current');
    if(current.attempt)renderAttempt(current.attempt);else rules();
  }catch(error){
    show(`<div class="panel content-narrow"><h1>Не вдалося завантажити платформу</h1><p class="muted">${esc(error.message)}</p><button class="button" id="retry">Повторити</button></div>`,'error');
    $('#retry').onclick=boot;
  }
}

function login(){
  const title=testInfo?.title||'Навчальне тестування';
  show(`<div class="login-layout"><section class="panel login-card">
    <div class="eyebrow">${esc(title)}</div><h1>Вхід учасника</h1>
    ${testInfo?.description?`<p class="lead">${esc(testInfo.description)}</p>`:''}
    <form id="student-login-form">
      <div class="field"><label for="student-email">Email учасника</label><input class="input" id="student-email" type="email" autocomplete="email" inputmode="email" placeholder="name@example.com" maxlength="254" required></div>
      <div class="row"><div class="field"><label for="last-name">Прізвище</label><input class="input" id="last-name" autocomplete="family-name" maxlength="80" required></div><div class="field"><label for="first-name">Ім’я</label><input class="input" id="first-name" autocomplete="given-name" maxlength="80" required></div></div>
      <p class="notice error hidden" id="student-login-error" role="alert"></p><button class="button full" type="submit">Продовжити <span aria-hidden="true">→</span></button>
    </form>
    ${sessionInfo.local_teacher_enabled&&!publicCode?`<div class="divider"></div><details id="teacher-login"><summary>Вхід викладача</summary><form id="login-form"><div class="field"><label for="teacher-email">Логін</label><input class="input" id="teacher-email" name="email" type="email" autocomplete="username" value="admin@student.karazin.ua" required></div><div class="field"><label for="password">Пароль</label><input class="input" id="password" name="password" type="password" autocomplete="current-password" required maxlength="256"></div><p id="login-error" class="notice error hidden" role="alert"></p><button class="button full" type="submit">До кабінету</button></form></details>`:''}
  </section></div>`,'login');
  $('#student-login-form').onsubmit=async event=>{
    event.preventDefault();const button=$('button[type=submit]',event.currentTarget);button.disabled=true;
    try{
      await api('api/auth/student',{email:$('#student-email').value,first_name:$('#first-name').value,last_name:$('#last-name').value,...(publicCode?{public_code:publicCode}:{})});
      sessionInfo=await api('api/session');account();
      const current=publicCode?await api(`api/tests/${encodeURIComponent(publicCode)}/attempts/current`):await api('api/attempts/current');
      if(current.attempt)renderAttempt(current.attempt);else rules();
    }catch(error){errorBox($('#student-login-error'),error.message);button.disabled=false;}
  };
  $('#login-form')?.addEventListener('submit',async event=>{event.preventDefault();const button=$('button',event.currentTarget);button.disabled=true;try{await api('api/auth/local',{email:$('#teacher-email').value,password:$('#password').value});await boot();}catch(error){errorBox($('#login-error'),error.message);button.disabled=false;}});
}

function rules(){
  const user=sessionInfo.user, open=publicCode?testInfo.is_open:testInfo.is_open;
  const timer=testInfo.seconds_per_question??testInfo.seconds;
  show(`<section class="panel start-card"><div class="eyebrow">${esc(testInfo.title)}</div><h1>Умови проходження</h1>
    <p class="lead">Перед початком перевірте кількість запитань, час на відповідь і ліміт спроб.</p>
    ${testInfo.description?`<p class="muted">${esc(testInfo.description)}</p>`:''}
    <div class="exam-facts"><div class="fact"><strong>${testInfo.total}</strong><span>запитань</span></div><div class="fact"><strong>${timer??'—'}</strong><span>${timer==null?'без таймера':'секунд на відповідь'}</span></div><div class="fact"><strong>1</strong><span>спроба</span></div></div>
    <div class="notice warning"><strong>Доступна лише одна спроба.</strong> Після початку тесту розпочати нову спробу буде неможливо.</div>
    <div class="notice">${timer==null?'Час на проходження не обмежено.':`На кожне запитання дається ${timer} секунд. Відлік почнеться після запуску тесту.`}</div>
    <p class="muted">${esc(user.last_name+' '+user.first_name)} · ${esc(user.email)}</p>
    ${!open?'<div class="notice warning">Приймання нових спроб закрито. Якщо ви вже почали тест, оновіть сторінку, щоб продовжити.</div>':''}
    <p class="notice error hidden" id="start-error" role="alert"></p><button class="button full" id="start-test" ${open?'':'disabled'}>Розпочати тест <span aria-hidden="true">→</span></button></section>`,'rules');
  $('#start-test').onclick=async event=>{
    const button=event.currentTarget;button.disabled=true;
    try{const route=publicCode?`api/tests/${encodeURIComponent(publicCode)}/attempts`:'api/attempts';renderAttempt(await api(route,{first_name:user.first_name,last_name:user.last_name}));}
    catch(error){errorBox($('#start-error'),error.message);button.disabled=false;}
  };
}

function renderAttempt(attempt){
  state=attempt;
  if(attempt.status==='completed')return result(attempt);
  selected=null;
  const qtype=attempt.type||'single_choice', timed=attempt.seconds_per_question!=null;
  let inputs='';
  if(qtype==='short_text'){
    const value=preview?.draftText||'';
    inputs=`<label class="field answer-text-field"><span class="field-label">Ваша відповідь</span><textarea class="input" id="short-answer" rows="3" maxlength="2000" required>${esc(value)}</textarea></label>`;
  }else{
    const multi=qtype==='multiple_choice';
    inputs=`<fieldset class="choices" id="choices"><legend class="sr-only">Варіанти відповіді</legend>${attempt.choices.map((choice,i)=>`<label class="choice"><input type="${multi?'checkbox':'radio'}" name="answer" value="${i}"><span class="choice-letter" aria-hidden="true">${String.fromCharCode(97+i)})</span><span lang="es">${esc(choice)}</span></label>`).join('')}</fieldset>`;
  }
  show(`<section class="quiz-shell">
    ${preview?'<div class="preview-bar"><span>Попередній перегляд · Спроба не зберігається</span><button id="exit-preview" class="text-button">Закрити</button></div>':''}
    <div class="quiz-status"><div><div class="quiz-label">${esc(testInfo?.title||preview?.title||'Навчальне тестування')}</div><div class="question-count">Запитання ${attempt.question_index+1} <span class="muted">з ${attempt.total}</span></div></div>
    ${timed?`<div class="timer" id="timer"><span class="timer-caption">ЗАЛИШИЛОСЯ<br>НА ЗАПИТАННЯ</span><span class="timer-number" id="time-value" role="timer">00:20</span></div>`:'<span class="tag blue">Без таймера</span>'}</div>
    ${timed?`<progress class="time-progress" id="time-progress" max="${attempt.seconds_per_question}" value="${attempt.seconds_per_question}" aria-label="Час на запитання"></progress>`:''}
    <div class="notice warning hidden" id="connection-notice" role="status"></div><form class="panel question-card" id="answer-form">
      <div class="eyebrow">${qtype==='short_text'?'Введіть коротку відповідь':qtype==='multiple_choice'?'Оберіть усі правильні відповіді':'Оберіть одну відповідь'}</div>
      <h1 lang="es">${esc(attempt.question)}</h1>${attempt.text?`<p class="question-text" lang="es">${esc(attempt.text)}</p>`:''}${inputs}
      <div class="question-bottom"><p>${qtype==='multiple_choice'?'Можна обрати кілька варіантів.':'Відповідь можна змінити до підтвердження.'}</p><button class="button" id="answer-button" type="submit" disabled>${attempt.question_index===attempt.total-1?'Завершити тест':'Відповісти'} <span aria-hidden="true">→</span></button></div>
    </form><div class="quiz-foot"><span>${preview?'Перевірка інтерфейсу':esc(attempt.last_name+' '+attempt.first_name)}</span><span>Без повернення до попередніх запитань</span></div></section>`,'quiz');
  $('#exit-preview')?.addEventListener('click',()=>{preview=null;if(editorModel)renderEditor();else library();});
  $('#answer-form').onchange=()=>{selected=readAnswer(qtype);$('#answer-button').disabled=!hasAnswer(selected);};
  $('#short-answer')?.addEventListener('input',event=>{selected={text:event.target.value};$('#answer-button').disabled=!event.target.value.trim();if(preview)preview.draftText=event.target.value;});
  $('#answer-form').onsubmit=async event=>{
    event.preventDefault();selected=readAnswer(qtype);if(!hasAnswer(selected)||syncing)return;
    $('#answer-button').disabled=true;$('#choices')?.setAttribute('disabled','');syncing=true;const epoch=viewEpoch;
    if(preview){const answer=selected;previewAnswer(answer);syncing=false;return;}
    try{
      const updated=await api(`api/attempts/${state.id}/answers`,{question_index:state.question_index,...selected});if(epoch===viewEpoch)renderAttempt(updated);
    }catch(error){
      if(epoch!==viewEpoch)return;
      errorBox($('#connection-notice'),'Не вдалося підтвердити відповідь. Перевіряємо збережений стан…');
      try{const saved=publicCode?await api(`api/tests/${encodeURIComponent(publicCode)}/attempts/current`):await api('api/attempts/current');if(saved.attempt&&epoch===viewEpoch)renderAttempt(saved.attempt);}
      catch{if(screen==='quiz')errorBox($('#connection-notice'),error.message+' Час продовжує спливати.');}
    }finally{syncing=false;}
  };
  clockAt=performance.now();
  remainingAt=timed?Math.max(0,attempt.deadline-attempt.server_time-(performance.now()-(attempt._requestStarted??performance.now()))/1000):0;
  if(timed){tick();ticker=setInterval(tick,100);}
}
function readAnswer(type){
  if(type==='short_text')return {text:$('#short-answer')?.value||''};
  const selectedValues=[...document.querySelectorAll('input[name="answer"]:checked')].map(input=>Number(input.value));
  return type==='multiple_choice'?{choices:selectedValues}:{choice:selectedValues[0]};
}
function hasAnswer(answer){return 'text' in answer?Boolean(answer.text.trim()):'choices' in answer?answer.choices.length>0:Number.isInteger(answer.choice);}
function tick(){
  if(screen!=='quiz'||!state?.seconds_per_question)return;
  const left=Math.max(0,remainingAt-(performance.now()-clockAt)/1000),seconds=Math.ceil(left);
  const mins=Math.floor(seconds/60),secs=seconds%60;
  $('#time-value').textContent=`${String(mins).padStart(2,'0')}:${String(secs).padStart(2,'0')}`;
  $('#time-value').setAttribute('aria-label',`Залишилося ${seconds} секунд`);$('#time-progress').value=left;
  $('#timer').classList.toggle('urgent',seconds<=5);
  if(left===0){$('#answer-button').disabled=true;$('#choices')?.setAttribute('disabled','');if(preview)previewTimeout();else syncAttempt();}
}
async function syncAttempt(){
  if(syncing||preview||screen!=='quiz')return;syncing=true;const epoch=viewEpoch;
  try{const saved=publicCode?await api(`api/tests/${encodeURIComponent(publicCode)}/attempts/current`):await api('api/attempts/current');if(saved.attempt&&epoch===viewEpoch)renderAttempt(saved.attempt);}
  catch(error){if(screen==='quiz')errorBox($('#connection-notice'),error.message+' Час продовжує спливати.');if(error.status===401)await boot();}
  finally{syncing=false;}
}
window.addEventListener('online',syncAttempt);document.addEventListener('visibilitychange',()=>{if(!document.hidden)syncAttempt();});

function previewAnswer(answer){
  const q=preview.questions[preview.index];let correct=false;
  if(q.type==='short_text')correct=(q.correct_texts||[]).some(value=>normalizeClientText(value)===normalizeClientText(answer.text));
  else if(q.type==='multiple_choice')correct=JSON.stringify([...answer.choices].sort((a,b)=>a-b) )===JSON.stringify([...(q.correct||[])].sort((a,b)=>a-b));
  else correct=(q.correct||[]).includes(answer.choice);
  preview.answered++;if(correct)preview.score++;preview.index++;preview.draftText='';
  if(preview.seconds!=null)preview.deadline=performance.now()+preview.seconds*1000;
  previewRender();
}
function normalizeClientText(value){return String(value||'').trim().replace(/\s+/g,' ').toLowerCase().replace(/[ßẞ]/g,'ss').replace(/ς/g,'σ');}
function previewTimeout(){
  if(!preview||preview.seconds==null)return;
  while(preview.index<preview.questions.length&&performance.now()>=preview.deadline){preview.index++;preview.deadline+=preview.seconds*1000;}
  previewRender();
}
function previewRender(){
  if(preview.index>=preview.questions.length)return result({score:preview.score,total:preview.questions.length,answered:preview.answered,status:'completed'});
  const question=preview.questions[preview.index],server=performance.now()/1000;
  renderAttempt({id:0,status:'active',question_index:preview.index,total:preview.questions.length,type:question.type||'single_choice',question:question.prompt,text:question.text||'',choices:question.choices||[],seconds_per_question:preview.seconds,deadline:preview.deadline==null?null:preview.deadline/1000,server_time:server,first_name:'',last_name:''});
}
function startPreview(testId,draft=null){
  const source=draft?Promise.resolve({title:draft.title,questions:JSON.parse(JSON.stringify(draft.questions)),seconds_per_question:draft.seconds_per_question}):api(`api/teacher/tests/${testId}/preview`);
  source.then(data=>{preview={questions:data.questions,index:0,score:0,answered:0,seconds:data.seconds_per_question,title:data.title,deadline:data.seconds_per_question==null?null:performance.now()+data.seconds_per_question*1000,draftText:''};testInfo={title:data.title,total:data.questions.length,seconds_per_question:data.seconds_per_question};previewRender();}).catch(error=>toast(error.message));
}
function result(attempt){
  const percent=Math.round(attempt.score/attempt.total*100);
  const hasReview=!preview&&attempt.review;
  show(`<section class="panel result-panel"><span class="tag ${preview?'amber':'green'}">${preview?'Перегляд завершено':'Спробу збережено'}</span><h1 class="result-title">Тест завершено</h1><p class="muted">${preview?'Результат перегляду не записано до бази.':esc(attempt.last_name+' '+attempt.first_name)}</p>
    <div class="result-score">${attempt.score}<span> / ${attempt.total}</span></div><p class="muted">правильних відповідей</p><div class="result-meta"><div><strong>${percent}%</strong><span>Результат</span></div><div><strong>${attempt.total-attempt.answered}</strong><span>Пропущено</span></div></div>
    ${preview?'<button class="button full" id="back-dashboard">Повернутися до тестів</button>':'<div class="notice">Результат збережено. Повторне проходження цього тесту недоступне.</div>'}
    ${hasReview?`<button class="button secondary full" id="toggle-review" aria-expanded="false">Переглянути відповіді</button><section class="answer-review hidden" id="student-review" aria-label="Правильні відповіді">${questionCards(attempt.review.questions,attempt.review.answers)}</section>`:''}</section>`,'result');
  $('#back-dashboard')?.addEventListener('click',()=>{preview=null;if(editorModel)renderEditor();else library();});
  $('#toggle-review')?.addEventListener('click',event=>{
    const panel=$('#student-review'),expanded=event.currentTarget.getAttribute('aria-expanded')==='true';
    panel.classList.toggle('hidden',expanded);event.currentTarget.setAttribute('aria-expanded',String(!expanded));
    event.currentTarget.textContent=expanded?'Переглянути відповіді':'Сховати відповіді';
  });
}

// Teacher library, editor and per-test reports.
async function library(){
  try{
    preview=null;editorModel=null;const data=await api('api/teacher/tests');
    show(`<div class="page-top"><div><div class="eyebrow">Кабінет викладача</div><h1>Мої тести</h1><p>Створюйте тести, діліться посиланнями та переглядайте результати.</p></div><button class="button" id="create-test">Створити тест <span aria-hidden="true">＋</span></button></div>
      <div class="test-library">${data.tests.length?data.tests.map(test=>testCard(test)).join(''):'<section class="panel empty-state"><strong>Тестів поки немає</strong><p>Створіть перший тест, щоб поділитися посиланням зі студентами.</p></section>'}</div>`,'library');
    $('#create-test').onclick=createTest;
    document.querySelectorAll('[data-edit]').forEach(button=>button.onclick=()=>editTest(Number(button.dataset.edit)));
    document.querySelectorAll('[data-results]').forEach(button=>button.onclick=()=>testResults(Number(button.dataset.results)));
    document.querySelectorAll('[data-preview]').forEach(button=>button.onclick=()=>startPreview(Number(button.dataset.preview)));
    document.querySelectorAll('[data-state]').forEach(button=>button.onclick=()=>changeState(Number(button.dataset.state),button.dataset.next));
    document.querySelectorAll('[data-delete]').forEach(button=>button.onclick=()=>deleteTest(Number(button.dataset.delete),button.dataset.title,Number(button.dataset.attemptCount)));
    document.querySelectorAll('[data-copy]').forEach(button=>button.onclick=()=>copyLink(button.dataset.copy));
  }catch(error){toast(error.message);}
}
function testCard(test){
  const open=test.status==='open',stateLabel=test.status==='draft'?'Чернетка':open?'Відкрито':'Закрито';
  return `<article class="panel test-card"><div class="test-card-top"><div><span class="tag ${test.status==='draft'?'amber':open?'green':''}">${stateLabel}</span><h2>${esc(test.title)}</h2><p>${esc(test.description||'Опис поки не доданий.')}</p></div><div class="test-card-stats"><strong>${test.question_count}</strong><span>запитань</span><strong>${test.attempt_count}</strong><span>спроб</span></div></div>
    <div class="share-row"><label class="field-label" for="share-${test.id}">Посилання для студентів</label><div class="copy-field"><input class="input" id="share-${test.id}" value="${esc(test.public_url)}" readonly><button class="button secondary small" data-copy="${esc(test.public_url)}">Копіювати</button></div></div>
    <div class="test-card-actions"><button class="button secondary small" data-edit="${test.id}">Редагувати</button><button class="button secondary small" data-preview="${test.id}">Перегляд</button><button class="button secondary small" data-results="${test.id}">Результати (${test.completed_count} завершено)</button><button class="button ${open?'danger-button':'small'} ${open?'small':''}" data-state="${test.id}" data-next="${open?'closed':'open'}">${open?'Закрити тест':'Відкрити тест'}</button><button class="button danger-button small" data-delete="${test.id}" data-title="${esc(test.title)}" data-attempt-count="${test.attempt_count}">Видалити</button></div>
  </article>`;
}
async function createTest(button=$('#create-test')){
  if(button)button.disabled=true;
  try{const test=await api('api/teacher/tests',{});await editTest(test.id);}
  catch(error){toast(error.message);}
  finally{if(button)button.disabled=false;}
}
async function copyLink(value){
  try{
    if(navigator.clipboard&&window.isSecureContext)await navigator.clipboard.writeText(value);
    else{const input=document.createElement('textarea');input.value=value;input.style.position='fixed';input.style.opacity='0';document.body.append(input);input.select();document.execCommand('copy');input.remove();}
    toast('Посилання скопійовано.');
  }catch{toast('Не вдалося скопіювати посилання. Скопіюйте його з поля вручну.');}
}
async function changeState(testId,next){
  const test=await api(`api/teacher/tests/${testId}`);
  let body={status:next};
  if(next==='open'){
    if(!window.confirm(`Відкрити «${test.title}» для нових спроб? Переконайтеся, що перевірили всі ключі відповідей.`))return;
    body.confirm_keys=true;
    if(testId===1&&!test.keys_approved)body.approve_suggested_keys=true;
  }else if(!window.confirm(`Закрити «${test.title}» для нових спроб? Уже розпочаті спроби продовжаться.`))return;
  try{await api(`api/teacher/tests/${testId}/state`,body);await library();toast(next==='open'?'Тест відкрито для студентів.':'Приймання нових спроб закрито.');}
  catch(error){toast(error.message);}
}

async function deleteTest(testId,title,attemptCount){
  const remainder=attemptCount%100,unit=attemptCount%10;
  const attempts=attemptCount===1?'1 спробу':`${attemptCount} ${unit>=2&&unit<=4&&(remainder<12||remainder>14)?'спроби':'спроб'}`;
  if(!window.confirm(`Видалити тест «${title}» і його посилання назавжди? Також буде видалено ${attempts} та всі результати. Цю дію не можна скасувати.`))return;
  try{
    await api(`api/teacher/tests/${testId}`,{},'DELETE');
    await library();
    toast(`Тест «${title}» видалено.`);
  }catch(error){toast(error.message);}
}

function defaultQuestion(){return {type:'single_choice',prompt:'Нове запитання',text:'',choices:['Варіант 1','Варіант 2'],correct:[0]};}
async function editTest(testId){
  try{editorModel=await api(`api/teacher/tests/${testId}`);editorWasOpen=editorModel.status==='open';renderEditor();}
  catch(error){toast(error.message);}
}
function renderEditor(message='',{scrollY=window.scrollY,focus=null}={}){
  const test=editorModel;
  show(`<div class="page-top"><div><div class="eyebrow">Конструктор тесту</div><h1>Редагування тесту</h1><p>Збереження закриває тест для нових спроб. Уже розпочаті спроби продовжаться.</p></div><button class="button secondary" id="editor-back">До списку тестів</button></div>
    <form id="editor-form"><section class="panel editor-settings"><div class="field"><label for="test-title">Назва тесту</label><input class="input" id="test-title" maxlength="200" required value="${esc(test.title)}"></div>
      <div class="field"><label for="test-description">Опис</label><textarea class="input" id="test-description" maxlength="3000" rows="3">${esc(test.description||'')}</textarea></div>
      <div class="timer-setting"><label class="check-label"><input type="checkbox" id="timer-enabled" ${test.seconds_per_question==null?'':'checked'}><span>Обмежити час на відповідь</span></label><div class="field"><label for="timer-seconds">Секунд на запитання</label><input class="input" id="timer-seconds" type="number" min="5" max="3600" step="1" value="${test.seconds_per_question??20}" ${test.seconds_per_question==null?'disabled':''}></div></div>
      <div class="field"><label class="check-label"><input type="checkbox" id="show-answers" ${test.show_answers?'checked':''}><span>Дозволити учасникам перегляд відповідей після завершення</span></label><p class="muted">Якщо вимкнено, правильні відповіді залишаться прихованими.</p></div>
      ${test.id===1&&!test.keys_approved?'<div class="notice warning">У старому тесті треба повторно підтвердити ключі. Перед відкриттям перевірте уточнення №7 (b і c), №10 (d) та №16 (b).</div>':''}
    </section><div class="section-head editor-question-head"><div><h2>Запитання</h2><span class="muted">${test.questions.length} запитань · максимум 100</span></div></div>
    <div id="editor-questions">${test.questions.map((question,index)=>questionEditor(question,index,test.questions.length)).join('')}</div>
    <div class="editor-add-question"><button class="button secondary" type="button" id="add-question">Додати запитання ＋</button></div>
    <p class="notice error ${message?'':'hidden'}" id="editor-error" role="alert">${esc(message)}</p><div class="editor-footer"><button class="button" type="submit" id="save-test">Зберегти зміни</button><button class="button secondary" type="button" id="editor-preview">Переглянути як студент</button><span class="muted">Стан: ${test.status==='draft'?'чернетка':test.status==='open'?'відкрито':'закрито'}</span></div></form>`,'editor');
  window.scrollTo(0,scrollY);
  if(typeof focus==='function')focus()?.focus({preventScroll:true});else if(focus)$(focus)?.focus({preventScroll:true});
  $('#editor-back').onclick=library;
  $('#timer-enabled').onchange=event=>{$('#timer-seconds').disabled=!event.target.checked;};
  $('#editor-form').onsubmit=saveTest;
  $('#add-question').onclick=()=>{editorModel=readEditor();editorModel.questions.push(defaultQuestion());renderEditor('',{scrollY:window.scrollY,focus:`.editor-question[data-question-index="${editorModel.questions.length-1}"] [data-question-prompt]`});document.querySelector('.editor-question:last-child')?.scrollIntoView({block:'center'});};
  $('#editor-questions').onclick=editorQuestionAction;
  $('#editor-questions').onchange=editorQuestionChange;
  $('#editor-preview').onclick=()=>{editorModel=readEditor();startPreview(test.id,editorModel);};
}
function questionEditor(question,index,total){
  const q={...question,type:question.type||'single_choice'};
  const opts=['single_choice','multiple_choice','short_text'];
  const typeLabels={single_choice:'Одна відповідь',multiple_choice:'Кілька відповідей',short_text:'Коротка текстова відповідь'};
  const fields=q.type==='short_text'?`<div class="editor-answers"><div class="field-label">Допустимі відповіді (ігноруються регістр і зайві пробіли)</div>${(q.correct_texts||['']).map((answer,i)=>`<div class="editor-option"><input class="input" data-accepted-text value="${esc(answer)}" maxlength="1000" aria-label="Допустима відповідь ${i+1}"><button class="icon-button" type="button" data-action="remove-answer" aria-label="Видалити відповідь">×</button></div>`).join('')}<button class="text-button" type="button" data-action="add-answer">Додати допустиму відповідь</button></div>`:`<div class="editor-answers"><div class="field-label">Варіанти та ключ відповіді</div>${(q.choices||[]).map((choice,i)=>`<div class="editor-option"><input class="input" data-choice-text value="${esc(choice)}" maxlength="500" aria-label="Варіант ${i+1}"><label class="key-toggle"><input type="checkbox" data-correct ${q.correct?.includes(i)?'checked':''}><span>Правильний</span></label><button class="icon-button" type="button" data-action="remove-choice" aria-label="Видалити варіант">×</button></div>`).join('')}<button class="text-button" type="button" data-action="add-choice">Додати варіант</button></div>`;
  return `<article class="panel editor-question" data-question-index="${index}"><div class="editor-question-top"><strong>Запитання ${index+1}</strong><div class="actions"><button class="icon-button" type="button" data-action="up" ${index===0?'disabled':''} aria-label="Перемістити вгору">↑</button><button class="icon-button" type="button" data-action="down" ${index===total-1?'disabled':''} aria-label="Перемістити вниз">↓</button><button class="icon-button delete" type="button" data-action="delete" aria-label="Видалити запитання">Видалити</button></div></div>
    <div class="field"><label>Формат відповіді</label><select class="input" data-question-type>${opts.map(type=>`<option value="${type}" ${q.type===type?'selected':''}>${typeLabels[type]}</option>`).join('')}</select></div>
    <div class="field"><label>Формулювання запитання</label><input class="input" data-question-prompt maxlength="1200" required value="${esc(q.prompt)}"></div><div class="field"><label>Додатковий текст (необов’язково)</label><textarea class="input" data-question-text maxlength="4000" rows="2">${esc(q.text||'')}</textarea></div>${fields}</article>`;
}
function readEditor(){
  if(!editorModel)return editorModel;
  const title=$('#test-title'),description=$('#test-description'),timer=$('#timer-enabled'),seconds=$('#timer-seconds'),showAnswers=$('#show-answers');
  if(title)editorModel.title=title.value;if(description)editorModel.description=description.value;
  if(timer)editorModel.seconds_per_question=timer.checked?Number(seconds.value):null;
  if(showAnswers)editorModel.show_answers=showAnswers.checked;
  const cards=[...document.querySelectorAll('.editor-question')];
  if(cards.length)editorModel.questions=cards.map(card=>{
    const old=editorModel.questions[Number(card.dataset.questionIndex)]||{},type=$('[data-question-type]',card).value;
    const q={...old,type,prompt:$('[data-question-prompt]',card).value,text:$('[data-question-text]',card).value};
    if(type==='short_text')q.correct_texts=[...card.querySelectorAll('[data-accepted-text]')].map(input=>input.value);
    else{q.choices=[...card.querySelectorAll('[data-choice-text]')].map(input=>input.value);q.correct=[...card.querySelectorAll('[data-correct]')].map((input,i)=>input.checked?i:-1).filter(i=>i>=0);delete q.correct_texts;}
    return q;
  });
  return editorModel;
}
function editorQuestionChange(event){
  if(!event.target.matches('[data-question-type]'))return;
  editorModel=readEditor();const index=Number(event.target.closest('.editor-question').dataset.questionIndex),q=editorModel.questions[index],type=event.target.value;
  if(type==='short_text'){q.correct_texts=[''];delete q.choices;delete q.correct;}
  else{q.choices=['Варіант 1','Варіант 2'];q.correct=[0];delete q.correct_texts;}
  renderEditor();document.querySelectorAll('.editor-question')[index]?.scrollIntoView({block:'center'});
}
function editorQuestionAction(event){
  const button=event.target.closest('[data-action]');if(!button)return;
  const scrollY=window.scrollY;
  editorModel=readEditor();const card=button.closest('.editor-question'),index=Number(card.dataset.questionIndex),action=button.dataset.action,q=editorModel.questions[index];
  if(action==='up'&&index>0)[editorModel.questions[index-1],editorModel.questions[index]]=[editorModel.questions[index],editorModel.questions[index-1]];
  if(action==='down'&&index<editorModel.questions.length-1)[editorModel.questions[index+1],editorModel.questions[index]]=[editorModel.questions[index],editorModel.questions[index+1]];
  if(action==='delete')editorModel.questions.splice(index,1);
  if(action==='add-choice')q.choices.push(`Варіант ${q.choices.length+1}`);
  if(action==='remove-choice'){const choiceIndex=[...card.querySelectorAll('[data-choice-text]')].indexOf(button.parentElement.querySelector('[data-choice-text]'));q.choices.splice(choiceIndex,1);q.correct=(q.correct||[]).filter(value=>value!==choiceIndex).map(value=>value>choiceIndex?value-1:value);}
  if(action==='add-answer')q.correct_texts.push('');
  if(action==='remove-answer'){const answerIndex=[...card.querySelectorAll('[data-accepted-text]')].indexOf(button.parentElement.querySelector('[data-accepted-text]'));q.correct_texts.splice(answerIndex,1);}
  const focus=action==='add-choice'?()=>document.querySelectorAll(`.editor-question[data-question-index="${index}"] [data-choice-text]`)[q.choices.length-1]:action==='add-answer'?()=>document.querySelectorAll(`.editor-question[data-question-index="${index}"] [data-accepted-text]`)[q.correct_texts.length-1]:null;
  renderEditor('',{scrollY,focus});
}
async function saveTest(event){
  event.preventDefault();editorModel=readEditor();const button=$('#save-test');button.disabled=true;
  try{
    const wasOpen=editorWasOpen;
    editorModel=await api(`api/teacher/tests/${editorModel.id}`,editorModel,'PUT');editorWasOpen=false;
    renderEditor();toast(wasOpen?'Зміни збережено. Тест закрито для нових спроб.':'Зміни збережено.');
  }catch(error){errorBox($('#editor-error'),error.message);button.disabled=false;}
}
function questionCards(questions,answers=null){
  return questions.map((q,i)=>{
    const a=answers?.find(item=>item.question_index===i),type=q.type||'single_choice';
    const expected=type==='short_text'?q.correct_texts||[]:[];
    const correctIndices=type==='short_text'?[]:(q.correct||[]);
    const studentAnswer=a?(a.choice!=null?q.choices[a.choice]:a.selection?a.selection.map(index=>q.choices[index]).join(', '):a.text_response||'Пропущено'):'';
    const choices=type==='short_text'?`<div class="answer-options"><div class="right"><strong>Допустимі відповіді:</strong> ${expected.map(esc).join(' · ')}</div>${a?`<div class="${a.correct?'right':'wrong'}"><strong>Відповідь студента:</strong> ${esc(studentAnswer||'Пропущено')}</div>`:''}</div>`:`<div class="answer-options" lang="es">${(q.choices||[]).map((choice,j)=>`<div class="${correctIndices.includes(j)?'right':(a?.choice===j||a?.selection?.includes(j))?'wrong':''}"><strong>${String.fromCharCode(97+j)})</strong> ${esc(choice)} ${correctIndices.includes(j)?' — правильна відповідь':''}${a?.choice===j||a?.selection?.includes(j)?' · обрано':''}</div>`).join('')}${a&&a.choice==null&&!a.selection&&!a.text_response?'<div class="muted">Пропущено</div>':''}</div>`;
    return `<article class="answer-card"><div class="section-head"><strong>Запитання ${i+1}</strong>${answers?`<span class="tag ${a?.correct?'green':''}">${!a?'Не відкрито':a.choice==null&&!a.selection&&!a.text_response?'Пропущено':a.correct?'Правильно':'Неправильно'}</span>`:`<span class="tag">${type==='short_text'?'Короткий текст':type==='multiple_choice'?'Кілька відповідей':'Одна відповідь'}</span>`}</div><h3 lang="es">${esc(q.prompt)}</h3>${q.text?`<p lang="es">${esc(q.text)}</p>`:''}${choices}</article>`;
  }).join('');
}
async function testResults(testId){
  try{
    resultTestId=testId;const overview=await api(`api/teacher/tests/${testId}/overview`);
    show(`<div class="page-top"><div><div class="eyebrow">Результати · ${esc(overview.test.title)}</div><h1>Спроби учасників</h1><p>${overview.test.question_count} запитань · ${overview.test.status==='open'?'Тест відкритий':'Тест закритий'}</p></div><div class="actions"><button class="button secondary" id="results-back">До списку тестів</button><a class="button secondary" href="${apiUrl(`api/teacher/tests/${testId}/export.csv`)}" id="export-link">Завантажити CSV ↓</a></div></div>
      <div class="metrics"><div class="metric"><div class="metric-label">Усього учасників</div><div class="metric-value">${overview.total}</div></div><div class="metric"><div class="metric-label">Завершили тест</div><div class="metric-value">${overview.completed}</div></div><div class="metric"><div class="metric-label">Проходять зараз</div><div class="metric-value">${overview.active}</div></div><div class="metric"><div class="metric-label">Середній результат</div><div class="metric-value">${overview.average==null?'—':overview.average+'%'}</div></div></div>
      <section class="panel table-panel"><div class="section-head"><h2>Учасники</h2></div><form class="filters" id="filters"><label class="sr-only" for="search">Пошук за ім’ям або поштою</label><input class="input" id="search" type="search" placeholder="Пошук за ім’ям або поштою"><label class="sr-only" for="status">Статус</label><select class="input" id="status"><option value="">Усі статуси</option><option value="completed">Завершено</option><option value="active">У процесі</option></select><button class="button secondary" type="submit">Знайти</button></form><div id="participants" aria-live="polite"><div class="loading">Завантаження результатів…</div></div></section>`,'results');
    $('#results-back').onclick=library;$('#filters').onsubmit=event=>{event.preventDefault();filterPage=1;loadParticipants();};$('#status').onchange=()=>{filterPage=1;loadParticipants();};filterPage=1;await loadParticipants();
  }catch(error){toast(error.message);}
}
async function loadParticipants(){
  try{
    const params=new URLSearchParams({search:$('#search').value,status:$('#status').value,page:filterPage}),data=await api(`api/teacher/tests/${resultTestId}/attempts?${params}`);
    if(screen!=='results')return;
    $('#participants').innerHTML=data.rows.length?`<div class="table-scroll"><table><thead><tr><th>Учасник</th><th>Статус</th><th>Початок</th><th>Результат</th><th><span class="sr-only">Докладніше</span></th></tr></thead><tbody>${data.rows.map(row=>`<tr><td><strong>${esc(row.last_name+' '+row.first_name)}</strong><span class="person-email">${esc(row.email)}</span></td><td><span class="tag ${row.finished!=null?'green':'blue'}">${row.finished!=null?'Завершено':'У процесі'}</span></td><td>${date(row.started)}</td><td>${row.finished!=null?`<strong>${row.score}</strong><span class="muted"> / ${row.max_score} (${row.percent}%)</span>`:'—'}</td><td><button class="text-button detail-button" data-id="${row.id}">Відкрити</button></td></tr>`).join('')}</tbody></table></div><div class="pagination"><span>Усього: ${data.total}</span><div class="actions"><button class="button secondary small" id="previous-page" ${filterPage<=1?'disabled':''}>Назад</button><span>${filterPage}</span><button class="button secondary small" id="next-page" ${filterPage*50>=data.total?'disabled':''}>Далі</button></div></div>`:`<div class="empty-state"><strong>${params.get('search')||params.get('status')?'Учасників не знайдено':'Результатів поки немає'}</strong><p>${params.get('search')||params.get('status')?'Змініть умови пошуку.':'Коли студенти розпочнуть тест, їхні спроби з’являться тут.'}</p></div>`;
    document.querySelectorAll('.detail-button').forEach(button=>button.onclick=()=>attemptDetail(Number(button.dataset.id)));
    $('#previous-page')?.addEventListener('click',()=>{filterPage--;loadParticipants();});$('#next-page')?.addEventListener('click',()=>{filterPage++;loadParticipants();});
  }catch(error){if(screen==='results')$('#participants').innerHTML=`<div class="notice error">${esc(error.message)}</div>`;}
}
async function attemptDetail(attemptId){
  try{
    const data=await api(`api/teacher/tests/${resultTestId}/attempts/${attemptId}`);
    show(`<div class="content-narrow"><div class="page-top"><div><div class="eyebrow">Картка спроби · ${esc(data.test_title)}</div><h1>${esc(data.last_name+' '+data.first_name)}</h1><p>${esc(data.email)}</p></div><button class="button secondary" id="back">До результатів</button></div><div class="notice">Початок: ${date(data.started)} · ${data.finished!=null?'Завершення: '+date(data.finished)+' · Результат: '+data.score+' / '+data.max_score:'Тест триває'}</div>${questionCards(data.questions,data.answers)}</div>`,'detail');$('#back').onclick=()=>testResults(resultTestId);
  }catch(error){toast(error.message);}
}
function passwordView(){
  show(`<div class="panel start-card"><div class="eyebrow">Обліковий запис</div><h1>Змінити пароль</h1><p class="panel-subtitle">${esc(sessionInfo.user.email)}</p><form id="password-form"><div class="field"><label for="old-password">Поточний пароль</label><input class="input" id="old-password" type="password" autocomplete="current-password" required maxlength="256"></div><div class="field"><label for="new-password">Новий пароль</label><input class="input" id="new-password" type="password" autocomplete="new-password" minlength="20" maxlength="256" required><p class="field-hint">Щонайменше 20 символів. Можна використати довгу фразу.</p></div><div class="field"><label for="confirm-password">Повторіть новий пароль</label><input class="input" id="confirm-password" type="password" autocomplete="new-password" required></div><p class="notice">Після зміни пароля потрібно буде знову ввійти на інших пристроях.</p><div class="notice error hidden" id="password-error" role="alert"></div><div class="actions"><button class="button" type="submit">Зберегти пароль</button><button class="button secondary" type="button" id="back">Скасувати</button></div></form></div>`,'password');
  $('#back').onclick=library;$('#password-form').onsubmit=async event=>{event.preventDefault();if($('#new-password').value!==$('#confirm-password').value)return errorBox($('#password-error'),'Паролі не збігаються.');const button=$('button[type=submit]',event.currentTarget);button.disabled=true;try{await api('api/auth/password',{current_password:$('#old-password').value,password:$('#new-password').value});sessionInfo=await api('api/session');await library();toast('Пароль змінено.');}catch(error){errorBox($('#password-error'),error.message);button.disabled=false;}};
}
boot();
