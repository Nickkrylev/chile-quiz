'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const main = $('#main');
let sessionInfo, testInfo, state, ticker, syncing = false, preview = null, selected = null, filterPage = 1;
let clockAt = 0, remainingAt = 0, screen = '', toastTimer, viewEpoch = 0;
const date = value => value == null ? '—' : new Date(value * 1000).toLocaleString('uk-UA', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});

async function api(path, data) {
  const options = {credentials:'same-origin', headers:{'Accept':'application/json'}, cache:'no-store'};
  if (data !== undefined) {
    options.method = 'POST';
    options.headers['Content-Type'] = 'application/json';
    options.headers['X-CSRF-Token'] = sessionInfo?.csrf || '';
    options.body = JSON.stringify(data);
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  const startedAt = performance.now();
  options.signal = controller.signal;
  let response, result;
  try {
    response = await fetch(path, options);
    result = await response.json();
  } catch (error) {
    throw new Error(error.name === 'AbortError' ? 'Сервер не відповів вчасно. Перевіряємо стан тесту.' : 'Немає зв’язку із сервером. Перевірте інтернет і повторіть дію.');
  } finally { clearTimeout(timeout); }
  // Conservatively include transit time; a delayed response must not grant extra displayed time.
  for (const candidate of [result, result?.attempt]) {
    if (candidate && typeof candidate.server_time === 'number') candidate._requestStarted = startedAt;
  }
  if (!response.ok) {
    const error = new Error(result.error || 'Не вдалося виконати дію. Спробуйте ще раз.');
    error.status = response.status;
    throw error;
  }
  return result;
}

function toast(message) {
  $('#toast').textContent = message;
  $('#toast').classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').classList.add('hidden'), 5500);
}
function show(html, name) {
  clearInterval(ticker);
  viewEpoch++;
  screen = name;
  main.innerHTML = html;
  window.scrollTo(0,0);
}
function errorBox(target, message) { target.textContent = message; target.classList.remove('hidden'); }
function account() {
  const user = sessionInfo.user;
  $('#account').innerHTML = user ? `<span class="account-email">${esc(user.email)}</span><button class="text-button" id="logout">Вийти</button>` : '<span class="tag">УО-6</span>';
  $('#logout')?.addEventListener('click', async () => {
    try { await api('api/auth/logout', {}); preview=null; await boot(); }
    catch (error) { toast(error.message); }
  });
}
async function boot() {
  try {
    sessionInfo = await api('api/session');
    testInfo = await api('api/test');
    account();
    if (!sessionInfo.user) return login();
    if (sessionInfo.user.role === 'teacher') return dashboard();
    const current = await api('api/attempts/current');
    if (current.attempt) renderAttempt(current.attempt);
    else rules();
  } catch (error) {
    show(`<div class="panel content-narrow"><h1>Не вдалося завантажити платформу</h1><p class="muted">${esc(error.message)}</p><button class="button" id="retry">Повторити</button></div>`, 'error');
    $('#retry').onclick = boot;
  }
}

function login() {
  show(`<div class="login-layout"><section class="panel login-card">
    <div class="eyebrow">УО-6 · Іспанська мова</div>
    <h1>Навчальне тестування</h1>
    <p class="notice exam-notice">Вам надається одна спроба. На кожне запитання — 20 секунд.</p>
    <form id="student-login-form">
      <div class="field"><label for="student-email">Студентська пошта</label><input class="input" id="student-email" type="email" autocomplete="email" inputmode="email" placeholder="name@student.karazin.ua" maxlength="254" required></div>
      <div class="row"><div class="field"><label for="last-name">Прізвище</label><input class="input" id="last-name" autocomplete="family-name" maxlength="80" required></div><div class="field"><label for="first-name">Ім’я</label><input class="input" id="first-name" autocomplete="given-name" maxlength="80" required></div></div>
      <p class="notice error hidden" id="student-login-error" role="alert"></p>
      <button class="button full" type="submit">Продовжити <span aria-hidden="true">→</span></button>
    </form>
    ${sessionInfo.local_teacher_enabled ? `<div class="divider"></div><details id="teacher-login"><summary>Вхід викладача</summary><form id="login-form">
      <div class="field"><label for="teacher-email">Логін</label><input class="input" id="teacher-email" name="email" type="email" autocomplete="username" value="admin@student.karazin.ua" required></div>
      <div class="field"><label for="password">Пароль</label><input class="input" id="password" name="password" type="password" autocomplete="current-password" required maxlength="256"></div>
      <p id="login-error" class="notice error hidden" role="alert"></p><button class="button full" type="submit">До кабінету</button>
    </form></details>` : ''}
  </section></div>`, 'login');
  $('#student-login-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button=$('button[type=submit]',event.currentTarget);button.disabled=true;
    try {
      await api('api/auth/student',{email:$('#student-email').value,first_name:$('#first-name').value,last_name:$('#last-name').value});
      sessionInfo=await api('api/session');testInfo=await api('api/test');account();
      const current=await api('api/attempts/current');
      if(current.attempt)renderAttempt(current.attempt);else rules();
    } catch(error){errorBox($('#student-login-error'),error.message);button.disabled=false;}
  });
  $('#login-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const button = $('button',event.currentTarget); button.disabled = true;
    try { await api('api/auth/local', {email:$('#teacher-email').value,password:$('#password').value}); await boot(); }
    catch (error) { errorBox($('#login-error'),error.message); button.disabled=false; }
  });
}
function rules() {
  const user=sessionInfo.user;
  show(`<section class="panel start-card"><div class="eyebrow">Іспанська мова · УО-6</div><h1>Готові розпочати?</h1>
    <p class="notice exam-notice">Вам надається одна спроба. На кожне запитання — 20 секунд.</p>
    <p class="muted">${esc(user.first_name+' '+user.last_name)} · ${esc(user.email)}</p>
    ${!testInfo.is_open?'<div class="notice warning">Тест поки закритий. Зверніться до викладача.</div>':''}
    <p class="notice error hidden" id="start-error" role="alert"></p>
    <button class="button full" id="start-test" ${testInfo.is_open?'':'disabled'}>Розпочати тест <span aria-hidden="true">→</span></button></section>`, 'rules');
  $('#start-test').onclick=async event=>{
    const button=event.currentTarget;button.disabled=true;
    try {renderAttempt(await api('api/attempts',{first_name:user.first_name,last_name:user.last_name}));}
    catch(error){errorBox($('#start-error'),error.message);button.disabled=false;}
  };
}
function renderAttempt(attempt) {
  state = attempt;
  if (attempt.status === 'completed') return result(attempt);
  selected = null;
  show(`<section class="quiz-shell">
    ${preview ? '<div class="preview-bar"><span>Перегляд викладача · Результат не зберігається</span><button id="exit-preview" class="text-button">Закрити</button></div>':''}
    <div class="quiz-status"><div><div class="quiz-label">Іспанська мова · УО-6</div><div class="question-count">Запитання ${attempt.question_index+1} <span class="muted">з ${attempt.total}</span></div></div>
      <div class="timer" id="timer"><span class="timer-caption">ЗАЛИШИЛОСЯ<br>НА ЗАПИТАННЯ</span><span class="timer-number" id="time-value" role="timer" aria-label="Залишилося секунд">00:20</span></div></div>
    <progress class="time-progress" id="time-progress" max="20" value="20" aria-label="Час на запитання"></progress>
    <div class="notice warning hidden" id="connection-notice" role="status"></div><form class="panel question-card" id="answer-form">
      <div class="eyebrow">Оберіть одну відповідь</div><h1 lang="es">${esc(attempt.question)}</h1><p class="question-text" lang="es">${esc(attempt.text)}</p>
      <fieldset class="choices" id="choices"><legend class="sr-only">Варіанти відповіді</legend>${attempt.choices.map((choice,i)=>`<label class="choice"><input type="radio" name="answer" value="${i}"><span class="choice-letter" aria-hidden="true">${'abcd'[i]}</span><span lang="es">${esc(choice)}</span></label>`).join('')}</fieldset>
      <div class="question-bottom"><p>Відповідь можна змінити до підтвердження.</p><button class="button" id="answer-button" type="submit" disabled>${attempt.question_index===19?'Завершити тест':'Відповісти'} <span aria-hidden="true">→</span></button></div>
    </form><div class="quiz-foot"><span>${preview ? 'Перевірка інтерфейсу' : esc(attempt.last_name+' '+attempt.first_name)}</span><span>Без повернення до попередніх запитань</span></div></section>`, 'quiz');
  $('#exit-preview')?.addEventListener('click',()=>{preview=null;dashboard();});
  $('#answer-form').onchange = event => {selected=Number(event.target.value);$('#answer-button').disabled=false;};
  $('#answer-form').onsubmit = async event => {
    event.preventDefault();
    if(selected===null || syncing)return;
    $('#answer-button').disabled=true;$('#choices').disabled=true;
    if(preview)return previewAnswer(selected);
    syncing=true;
    const epoch=viewEpoch;
    try {const updated=await api(`api/attempts/${state.id}/answers`,{question_index:state.question_index,choice:selected});if(epoch===viewEpoch)renderAttempt(updated);}
    catch(error){
      if(epoch!==viewEpoch)return;
      if(screen==='quiz')errorBox($('#connection-notice'),'Не вдалося підтвердити відповідь. Перевіряємо збережений стан…');
      try { const saved=await api('api/attempts/current'); if(saved.attempt&&epoch===viewEpoch)renderAttempt(saved.attempt); }
      catch {if(screen==='quiz')errorBox($('#connection-notice'),error.message+' Час продовжує спливати.');}
    } finally {syncing=false;}
  };
  clockAt=performance.now();
  remainingAt=Math.max(0,attempt.deadline-attempt.server_time-(performance.now()-(attempt._requestStarted ?? performance.now()))/1000);
  tick();ticker=setInterval(tick,100);
}

function tick() {
  if(screen!=='quiz')return;
  const left=Math.max(0,remainingAt-(performance.now()-clockAt)/1000);
  const seconds=Math.ceil(left);
  $('#time-value').textContent=`00:${String(seconds).padStart(2,'0')}`;
  $('#time-value').setAttribute('aria-label',`Залишилося ${seconds} секунд`);
  $('#time-progress').value=left;
  $('#timer').classList.toggle('urgent',seconds<=5);
  if(left===0){
    $('#answer-button').disabled=true;$('#choices').disabled=true;
    if(preview) previewTimeout(); else syncAttempt();
  }
}
let nextSync=0;
async function syncAttempt(force=false){
  if(syncing||preview||screen!=='quiz'||(!force&&performance.now()<nextSync))return;
  syncing=true;
  const epoch=viewEpoch;
  try{
    const saved=await api('api/attempts/current');
    if(saved.attempt&&epoch===viewEpoch)renderAttempt(saved.attempt);
  }catch(error){
    nextSync=performance.now()+2000;
    if(screen==='quiz')errorBox($('#connection-notice'),error.message+' Час продовжує спливати.');
    if(error.status===401)await boot();
  }finally{syncing=false;}
}
window.addEventListener('online',()=>syncAttempt(true));
document.addEventListener('visibilitychange',()=>{if(!document.hidden)syncAttempt(true);});

function result(attempt){
  const percent=Math.round(attempt.score/attempt.total*100);
  show(`<section class="panel result-panel"><span class="tag ${preview?'amber':'green'}">${preview?'Перегляд завершено':'Спробу збережено'}</span><h1 class="result-title">Тест завершено</h1><p class="muted">${preview?'Результат перегляду не записано до бази.':esc(attempt.last_name+' '+attempt.first_name)}</p>
    <div class="result-score">${attempt.score}<span> / ${attempt.total}</span></div><p class="muted">правильних відповідей</p><div class="result-meta"><div><strong>${percent}%</strong><span>Результат</span></div><div><strong>${attempt.total-attempt.answered}</strong><span>Пропущено</span></div></div>
    ${preview?'<button class="button full" id="back-dashboard">Повернутися в кабінет</button>':'<div class="notice">Результат доступний викладачеві. Повторне проходження цього тесту недоступне.</div>'}</section>`, 'result');
  $('#back-dashboard')?.addEventListener('click',()=>{preview=null;dashboard();});
}

async function startPreview(){
  try{
    const data=await api('api/teacher/preview');
    preview={questions:data.questions,index:0,score:0,answered:0,deadline:performance.now()+20000};
    previewRender();
  }catch(error){toast(error.message);}
}
function previewRender(){
  if(preview.index>=20)return result({score:preview.score,total:20,answered:preview.answered,status:'completed'});
  const q=preview.questions[preview.index];
  renderAttempt({id:0,question_index:preview.index,total:20,status:'active',question:q.prompt,text:q.text,choices:q.choices,server_time:performance.now()/1000,deadline:preview.deadline/1000});
}
function previewAnswer(choice){
  if(performance.now()>=preview.deadline)return previewTimeout();
  preview.answered++; if(preview.questions[preview.index].correct.includes(choice))preview.score++;
  preview.index++;preview.deadline=performance.now()+20000;previewRender();
}
function previewTimeout(){
  while(preview.index<20&&performance.now()>=preview.deadline){preview.index++;preview.deadline+=20000;}
  previewRender();
}

async function dashboard(){
  try{
    preview=null;
    const overview=await api('api/teacher/overview');
    const test=overview.test;
    show(`<div class="page-top"><div><div class="eyebrow">Кабінет викладача</div><h1>Результати тестування</h1><p>Іспанська мова · УО-6 <span class="muted">/</span> 20 запитань</p></div><div class="actions"><button class="button secondary" id="questions-button">Запитання та ключі</button><button class="button" id="preview-button">Перевірити тест <span aria-hidden="true">→</span></button></div></div>
      <div class="metrics"><div class="metric"><div class="metric-label">Усього учасників</div><div class="metric-value">${overview.total}</div></div><div class="metric"><div class="metric-label">Завершили тест</div><div class="metric-value">${overview.completed}</div></div><div class="metric"><div class="metric-label">Проходять зараз</div><div class="metric-value">${overview.active}</div></div><div class="metric"><div class="metric-label">Середній результат</div><div class="metric-value">${overview.average==null?'—':overview.average+'%'}</div></div></div>
      <section class="panel table-panel"><div class="section-head"><h2>Учасники</h2><a class="button secondary small" href="api/teacher/export.csv" id="export-link">Завантажити CSV ↓</a></div><form class="filters" id="filters"><label class="sr-only" for="search">Пошук за ім’ям або поштою</label><input class="input" id="search" type="search" placeholder="Пошук за ім’ям або поштою"><label class="sr-only" for="status">Статус</label><select class="input" id="status"><option value="">Усі статуси</option value="completed">Завершено</option><option value="active">У процесі</option></select><button class="button secondary" type="submit">Знайти</button></form><div id="participants" aria-live="polite"><div class="loading">Завантаження результатів…</div></div></section>
      <section class="panel settings-panel"><div class="settings-grid"><div><div class="section-head"><h2>Доступ до тесту</h2><span class="tag ${test.is_open?'green':'amber'}">${test.is_open?'Відкрито':'Закрито'}</span></div>
      <p>Студенти вводять адресу <strong>@student.karazin.ua</strong>. Спроба закріплюється за введеною поштою. Адреса не перевіряється листом або входом в університетський акаунт.</p>
      ${!test.keys_approved?'<p>Перед відкриттям перевірте уточнення до ключів:</p><ul class="key-notes"><li>№7: прийняти b і c — обидві форми допустимі.</li><li>№10: правильна відповідь d — elegimos.</li><li>№16: правильна відповідь b — La.</li></ul><label class="check-label"><input id="approve-keys" type="checkbox"><span>Я перевірив / перевірила запитання та приймаю ці уточнення.</span></label>':'<p class="notice success">Ключі перевірено. Уточнення №7, №10 та №16 прийнято.</p>'}
      <button class="button secondary" id="toggle-test" >${test.is_open?'Закрити приймання нових спроб':'Відкрити тест для студентів'}</button>
      ${!test.keys_approved?'<button class="text-button" id="save-keys">Зберегти перевірені ключі</button>':''}<p class="field-hint">Закриття не перериває вже розпочаті спроби.</p></div>
      <div><h2>Обліковий запис</h2><p>${esc(sessionInfo.user.email)}</p><p>${sessionInfo.user.issuer==='local'?'Тестовий вхід викладача. Пароль діє лише на цій платформі.':'Вхід викладача через локальний обліковий запис.'}</p>${sessionInfo.user.issuer==='local'?'<button class="button secondary" id="password-button">Змінити пароль</button>':''}</div></div></section>`, 'dashboard');
    $('#preview-button').onclick=startPreview;
    $('#questions-button').onclick=questionsView;
    $('#password-button')?.addEventListener('click',passwordView);
    $('#filters').onsubmit=event=>{event.preventDefault();filterPage=1;loadParticipants();};
    $('#status').onchange=()=>{filterPage=1;loadParticipants();};
    $('#toggle-test').onclick=()=>updateSettings(!test.is_open);
    $('#save-keys')?.addEventListener('click',()=>updateSettings(false));
    filterPage=1;await loadParticipants();
  }catch(error){toast(error.message);}
}
async function updateSettings(isOpen){
  try{await api('api/teacher/test/settings',{is_open:isOpen,approve_suggested_keys:$('#approve-keys')?.checked||false});await dashboard();toast('Налаштування збережено.');}
  catch(error){toast(error.message);}
}
async function loadParticipants(){
  try{
    const params=new URLSearchParams({search:$('#search').value,status:$('#status').value,page:filterPage});
    const data=await api('api/teacher/attempts?'+params);
    if(screen!=='dashboard')return;
    $('#export-link').href='api/teacher/export.csv?'+params;
    $('#participants').innerHTML=data.rows.length?`<div class="table-scroll"><table><thead><tr><th>Учасник</th><th>Статус</th><th>Початок</th><th>Результат</th><th><span class="sr-only">Докладніше</span></th></tr></thead><tbody>${data.rows.map(row=>`<tr><td><strong>${esc(row.last_name+' '+row.first_name)}</strong><span class="person-email">${esc(row.email)}</span></td><td><span class="tag ${row.finished!=null?'green':'blue'}">${row.finished!=null?'Завершено':'У процесі'}</span></td><td>${date(row.started)}</td><td>${row.finished!=null?`<strong>${row.score}</strong><span class="muted"> / 20</span>`:'—'}</td><td><button class="text-button detail-button" data-id="${row.id}">Відкрити</button></td></tr>`).join('')}</tbody></table></div><div class="pagination"><span>Усього: ${data.total}</span><div class="actions"><button class="button secondary small" id="previous-page" ${filterPage<=1?'disabled':''}>Назад</button><span>${filterPage}</span><button class="button secondary small" id="next-page" ${filterPage*50>=data.total?'disabled':''}>Далі</button></div></div>`:`<div class="empty-state"><strong>${params.get('search')||params.get('status')?'Учасників не знайдено':'Результатів поки немає'}</strong><p>${params.get('search')||params.get('status')?'Змініть умови пошуку.':'Коли студенти розпочнуть тест, їхні спроби з’являться тут.'}</p></div>`;
    document.querySelectorAll('.detail-button').forEach(button=>button.onclick=()=>detailView(button.dataset.id));
    $('#previous-page')?.addEventListener('click',()=>{filterPage--;loadParticipants();});
    $('#next-page')?.addEventListener('click',()=>{filterPage++;loadParticipants();});
  }catch(error){if(screen==='dashboard')$('#participants').innerHTML=`<div class="notice error">${esc(error.message)}</div>`;}
}
function questionCards(questions,answers=null){
  return questions.map((q,i)=>{
    const a=answers?.find(x=>x.question_index===i);
    return `<article class="answer-card"><div class="section-head"><strong>Запитання ${i+1}</strong>${answers?`<span class="tag ${a?.correct?'green':''}">${!a?'Не відкрито':a.choice==null?'Пропущено':a.correct?'Правильно':'Неправильно'}</span>`:''}</div><h3 lang="es">${esc(q.prompt)}</h3><p lang="es">${esc(q.text)}</p><div class="answer-options" lang="es">${q.choices.map((choice,j)=>`<div class="${q.correct.includes(j)?'right':a?.choice===j?'wrong':''}"><strong>${'abcd'[j]})</strong> ${esc(choice)} ${q.correct.includes(j)?' — правильна відповідь':''}${a?.choice===j?' · обрано':''}</div>`).join('')}</div></article>`;
  }).join('');
}
async function questionsView(){
  try{
    const data=await api('api/teacher/preview');
    show(`<div class="content-narrow"><div class="page-top"><div><div class="eyebrow">Матеріали тесту</div><h1>Запитання та ключі</h1><p>20 запитань · Одна відповідь на запитання</p></div><button class="button secondary" id="back">До кабінету</button></div><div class="notice">Наведено запропоновані ключі з уточненнями №7, №10 та №16. Підтвердити їх можна в кабінеті. У №7 зараховується b або c.</div>${questionCards(data.questions)}</div>`,'questions');
    $('#back').onclick=dashboard;
  }catch(error){toast(error.message);}
}
async function detailView(id){
  try{
    const data=await api('api/teacher/attempts/'+id);
    show(`<div class="content-narrow"><div class="page-top"><div><div class="eyebrow">Картка спроби</div><h1>${esc(data.last_name+' '+data.first_name)}</h1><p>${esc(data.email)}</p></div><button class="button secondary" id="back">До кабінету</button></div><div class="notice">Початок: ${date(data.started)} · ${data.finished!=null?'Завершення: '+date(data.finished)+' · Результат: '+data.score+' / 20':'Тест триває'}</div>${questionCards(data.questions,data.answers)}</div>`,'detail');$('#back').onclick=dashboard;
  }catch(error){toast(error.message);}
}
function passwordView(){
  show(`<div class="panel start-card"><div class="eyebrow">Обліковий запис</div><h1>Змінити пароль</h1><p class="panel-subtitle">${esc(sessionInfo.user.email)}</p><form id="password-form"><div class="field"><label for="old-password">Поточний пароль</label><input class="input" id="old-password" type="password" autocomplete="current-password" required maxlength="256"></div><div class="field"><label for="new-password">Новий пароль</label><input class="input" id="new-password" type="password" autocomplete="new-password" minlength="20" maxlength="256" required><p class="field-hint">Щонайменше 20 символів. Можна використати довгу фразу.</p></div><div class="field"><label for="confirm-password">Повторіть новий пароль</label><input class="input" id="confirm-password" type="password" autocomplete="new-password" required></div><p class="notice">Після зміни пароля потрібно буде знову ввійти на інших пристроях.</p><div class="notice error hidden" id="password-error" role="alert"></div><div class="actions"><button class="button" type="submit">Зберегти пароль</button><button class="button secondary" type="button" id="back">Скасувати</button></div></form></div>`,'password');
  $('#back').onclick=dashboard;
  $('#password-form').onsubmit=async event=>{
    event.preventDefault();
    if($('#new-password').value!==$('#confirm-password').value)return errorBox($('#password-error'),'Паролі не збігаються.');
    const button=$('button[type=submit]',event.currentTarget);button.disabled=true;
    try{await api('api/auth/password',{current_password:$('#old-password').value,password:$('#new-password').value});sessionInfo=await api('api/session');await dashboard();toast('Пароль змінено.');}
    catch(error){errorBox($('#password-error'),error.message);button.disabled=false;}
  };
}
boot();
