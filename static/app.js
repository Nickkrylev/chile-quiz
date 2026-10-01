'use strict';
const $ = (selector, root = document) => root.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const main = $('#main');
let sessionInfo, testInfo, state, ticker, syncing = false, preview = null, selected = null, filterPage = 1;
let clockAt = 0, remainingAt = 0, screen = '', toastTimer;
const date = value => value == null ? '—' : new Date(value * 1000).toLocaleString('ru-RU', {day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});

async function api(path, data) {
  const options = {credentials:'same-origin', headers:{'Accept':'application/json'}, cache:'no-store'};
  if (data !== undefined) {
    options.method = 'POST';
    options.headers['Content-Type'] = 'application/json';
    options.headers['X-CSRF-Token'] = sessionInfo?.csrf || '';
    options.body = JSON.stringify(data);
  }
  let response;
  try { response = await fetch(path, options); }
  catch { throw new Error('Нет связи с сервером. Проверьте интернет и повторите действие.'); }
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(result.error || 'Не удалось выполнить действие. Попробуйте ещё раз.');
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
  screen = name;
  main.innerHTML = html;
  window.scrollTo(0,0);
}
function errorBox(target, message) { target.textContent = message; target.classList.remove('hidden'); }
function account() {
  const user = sessionInfo.user;
  $('#account').innerHTML = user ? `<span class="account-email">${esc(user.email)}</span><button class="text-button" id="logout">Выйти</button>` : '<span class="tag">УО-6</span>';
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
    show(`<div class="panel content-narrow"><h1>Не удалось загрузить платформу</h1><p class="muted">${esc(error.message)}</p><button class="button" id="retry">Повторить</button></div>`, 'error');
    $('#retry').onclick = boot;
  }
}

function login() {
  const oauthError = new URLSearchParams(location.search).has('login_error');
  show(`<div class="login-layout">
    <section class="intro"><div class="eyebrow">Контроль знаний · УО-6</div><h1>Тест по<br>испанскому языку</h1><p class="lead">Сравнительные формы, глаголы и деловая коммуникация.</p>
      <div class="exam-facts"><div class="fact"><strong>20</strong><span>вопросов</span></div><div class="fact"><strong>20 сек.</strong><span>на каждый вопрос</span></div><div class="fact"><strong>1</strong><span>попытка</span></div></div>
      <p class="small-note">Перед началом проверьте подключение к интернету. Таймер запускается только после нажатия «Начать тест».</p>
    </section>
    <section class="panel login-card"><div class="eyebrow">Вход участника</div><h2>Учебный аккаунт</h2><p class="panel-subtitle">Войдите с почтой <strong>student.karazin.ua</strong></p>
      ${sessionInfo.google_enabled ? '<a class="button secondary full" href="auth/google"><span class="google-letter" aria-hidden="true">G</span> Войти через Google</a>' : '<button class="button secondary full" disabled><span class="google-letter" aria-hidden="true">G</span> Войти через Google</button><div class="notice">Вход студентов ещё не открыт. Преподаватель сообщит, когда можно будет начать тест.</div>'}
      ${oauthError ? '<div class="notice error">Не удалось подтвердить учебный аккаунт. Выберите почту student.karazin.ua или обратитесь к преподавателю.</div>' : ''}
      <p class="small-note">Имя и фамилию можно подтвердить перед началом. Результат будет доступен вам и преподавателю.</p>
      ${sessionInfo.local_teacher_enabled ? `<div class="divider"></div><details id="teacher-login"><summary>Тестовый вход преподавателя</summary><form id="login-form">
        <div class="field"><label for="email">Логин</label><input class="input" id="email" name="email" type="email" autocomplete="username" value="admin@student.karazin.ua" required></div>
        <div class="field"><label for="password">Пароль платформы</label><input class="input" id="password" name="password" type="password" autocomplete="current-password" required maxlength="256"></div>
        <p id="login-error" class="notice error hidden" role="alert"></p><button class="button full" type="submit">Войти в кабинет</button>
        <p class="field-hint">Отдельный тестовый аккаунт. Используйте пароль платформы.</p></form></details>` : ''}
    </section></div>`, 'login');
  $('#login-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    const button = $('button',event.currentTarget); button.disabled = true;
    try { await api('api/auth/local', {email:$('#email').value,password:$('#password').value}); await boot(); }
    catch (error) { errorBox($('#login-error'),error.message); button.disabled=false; }
  });
}

function rules() {
  const user = sessionInfo.user;
  show(`<section class="panel start-card"><div class="eyebrow">Перед началом</div><h1>Проверьте свои данные</h1><p class="muted">${esc(testInfo.title)}</p>
    <form id="start-form"><div class="row"><div class="field"><label for="last-name">Фамилия</label><input class="input" id="last-name" autocomplete="family-name" maxlength="80" required value="${esc(user.last_name)}"></div><div class="field"><label for="first-name">Имя</label><input class="input" id="first-name" autocomplete="given-name" maxlength="80" required value="${esc(user.first_name)}"></div></div>
    <div class="notice">${esc(user.email)} · Одна попытка на учебный аккаунт</div>
    <ol class="rules"><li>В каждом из 20 вопросов выберите один ответ и нажмите «Ответить».</li><li>На вопрос даётся <strong>20 секунд</strong>. Когда время закончится, откроется следующий.</li><li>Таймер продолжает идти при закрытии вкладки и потере интернета.</li><li>Вернуться к предыдущему вопросу или начать заново нельзя.</li></ol>
    <label class="check-label"><input type="checkbox" id="accept-rules" required><span>Данные верны, правила понятны. Я готов(а) начать.</span></label>
    ${!testInfo.is_open ? '<div class="notice warning">Приём ответов пока закрыт. Дождитесь указания преподавателя.</div>' : ''}
    <div class="notice error hidden" id="start-error" role="alert"></div><button class="button full" type="submit" ${testInfo.is_open?'':'disabled'}>Начать тест <span aria-hidden="true">→</span></button></form></section>`, 'rules');
  $('#start-form').onsubmit = async event => {
    event.preventDefault();
    const button = $('button',event.currentTarget);button.disabled=true;
    try { renderAttempt(await api('api/attempts',{first_name:$('#first-name').value.trim(),last_name:$('#last-name').value.trim()})); }
    catch (error) {errorBox($('#start-error'),error.message);button.disabled=false;}
  };
}

function renderAttempt(attempt) {
  state = attempt;
  if (attempt.status === 'completed') return result(attempt);
  selected = null;
  show(`<section class="quiz-shell">
    ${preview ? '<div class="preview-bar"><span>Предпросмотр преподавателя · Результат не сохраняется</span><button id="exit-preview" class="text-button">Закрыть</button></div>':''}
    <div class="quiz-status"><div><div class="quiz-label">Испанский язык · УО-6</div><div class="question-count">Вопрос ${attempt.question_index+1} <span class="muted">из ${attempt.total}</span></div></div>
      <div class="timer" id="timer"><span class="timer-caption">ОСТАЛОСЬ<br>НА ВОПРОС</span><span class="timer-number" id="time-value" role="timer" aria-label="Осталось секунд">00:20</span></div></div>
    <progress class="time-progress" id="time-progress" max="20" value="20" aria-label="Время на вопрос"></progress>
    <div class="notice warning hidden" id="connection-notice" role="status"></div><form class="panel question-card" id="answer-form">
      <div class="eyebrow">Выберите один ответ</div><h1 lang="es">${esc(attempt.question)}</h1><p class="question-text" lang="es">${esc(attempt.text)}</p>
      <fieldset class="choices" id="choices"><legend class="sr-only">Варианты ответа</legend>${attempt.choices.map((choice,i)=>`<label class="choice"><input type="radio" name="answer" value="${i}"><span class="choice-letter" aria-hidden="true">${'abcd'[i]}</span><span lang="es">${esc(choice)}</span></label>`).join('')}</fieldset>
      <div class="question-bottom"><p>Ответ можно изменить до подтверждения.</p><button class="button" id="answer-button" type="submit" disabled>${attempt.question_index===19?'Завершить тест':'Ответить'} <span aria-hidden="true">→</span></button></div>
    </form><div class="quiz-foot"><span>${preview ? 'Проверка интерфейса' : esc(attempt.last_name+' '+attempt.first_name)}</span><span>Без возврата к предыдущим вопросам</span></div></section>`, 'quiz');
  $('#exit-preview')?.addEventListener('click',()=>{preview=null;dashboard();});
  $('#answer-form').onchange = event => {selected=Number(event.target.value);$('#answer-button').disabled=false;};
  $('#answer-form').onsubmit = async event => {
    event.preventDefault();
    if(selected===null || syncing)return;
    $('#answer-button').disabled=true;$('#choices').disabled=true;
    if(preview)return previewAnswer(selected);
    syncing=true;
    try {renderAttempt(await api(`api/attempts/${state.id}/answers`,{question_index:state.question_index,choice:selected}));}
    catch(error){
      if(screen==='quiz')errorBox($('#connection-notice'),'Не удалось подтвердить ответ. Проверяем сохранённое состояние…');
      try { const saved=await api('api/attempts/current'); if(saved.attempt)renderAttempt(saved.attempt); }
      catch {if(screen==='quiz')errorBox($('#connection-notice'),error.message+' Время продолжает идти.');}
    } finally {syncing=false;}
  };
  clockAt=performance.now();
  remainingAt=Math.max(0,attempt.deadline-attempt.server_time);
  tick();ticker=setInterval(tick,100);
}

function tick() {
  if(screen!=='quiz')return;
  const left=Math.max(0,remainingAt-(performance.now()-clockAt)/1000);
  const seconds=Math.ceil(left);
  $('#time-value').textContent=`00:${String(seconds).padStart(2,'0')}`;
  $('#time-value').setAttribute('aria-label',`Осталось ${seconds} секунд`);
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
  try{
    const saved=await api('api/attempts/current');
    if(saved.attempt)renderAttempt(saved.attempt);
  }catch(error){
    nextSync=performance.now()+2000;
    if(screen==='quiz')errorBox($('#connection-notice'),error.message+' Время продолжает идти.');
    if(error.status===401)await boot();
  }finally{syncing=false;}
}
window.addEventListener('online',()=>syncAttempt(true));
document.addEventListener('visibilitychange',()=>{if(!document.hidden)syncAttempt(true);});

function result(attempt){
  const percent=Math.round(attempt.score/attempt.total*100);
  show(`<section class="panel result-panel"><span class="tag ${preview?'amber':'green'}">${preview?'Предпросмотр завершён':'Попытка сохранена'}</span><h1 class="result-title">Тест завершён</h1><p class="muted">${preview?'Результат предпросмотра не записан в базу.':esc(attempt.last_name+' '+attempt.first_name)}</p>
    <div class="result-score">${attempt.score}<span> / ${attempt.total}</span></div><p class="muted">правильных ответов</p><div class="result-meta"><div><strong>${percent}%</strong><span>Результат</span></div><div><strong>${attempt.total-attempt.answered}</strong><span>Пропущено</span></div></div>
    ${preview?'<button class="button full" id="back-dashboard">Вернуться в кабинет</button>':'<div class="notice">Результат доступен преподавателю. Повторное прохождение этого теста недоступно.</div>'}</section>`, 'result');
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
    show(`<div class="page-top"><div><div class="eyebrow">Кабинет преподавателя</div><h1>Результаты тестирования</h1><p>Испанский язык · УО-6 <span class="muted">/</span> 20 вопросов</p></div><div class="actions"><button class="button secondary" id="questions-button">Вопросы и ключи</button><button class="button" id="preview-button">Проверить тест <span aria-hidden="true">→</span></button></div></div>
      <div class="metrics"><div class="metric"><div class="metric-label">Всего участников</div><div class="metric-value">${overview.total}</div></div><div class="metric"><div class="metric-label">Завершили тест</div><div class="metric-value">${overview.completed}</div></div><div class="metric"><div class="metric-label">Проходят сейчас</div><div class="metric-value">${overview.active}</div></div><div class="metric"><div class="metric-label">Средний результат</div><div class="metric-value">${overview.average==null?'—':overview.average+'%'}</div></div></div>
      <section class="panel table-panel"><div class="section-head"><h2>Участники</h2><a class="button secondary small" href="api/teacher/export.csv" id="export-link">Скачать CSV ↓</a></div><form class="filters" id="filters"><label class="sr-only" for="search">Поиск по имени или почте</label><input class="input" id="search" type="search" placeholder="Поиск по имени или почте"><label class="sr-only" for="status">Статус</label><select class="input" id="status"><option value="">Все статусы</option value="completed">Завершён</option><option value="active">В процессе</option></select><button class="button secondary" type="submit">Найти</button></form><div id="participants" aria-live="polite"><div class="loading">Загрузка результатов…</div></div></section>
      <section class="panel settings-panel"><div class="settings-grid"><div><div class="section-head"><h2>Доступ к тесту</h2><span class="tag ${test.is_open?'green':'amber'}">${test.is_open?'Открыт':'Закрыт'}</span></div>
      ${!overview.google_enabled?'<div class="notice warning">Вход студентов через Google ещё не подключён. Пока можно проверить вопросы, таймер и интерфейс в предпросмотре.</div>':'<p>Студенты входят с учебной почтой student.karazin.ua.</p>'}
      ${!test.keys_approved?'<p>Перед открытием проверьте уточнения к ключам:</p><ul class="key-notes"><li>№7: принять b и c — обе формы допустимы.</li><li>№10: правильный ответ d — elegimos.</li><li>№16: правильный ответ b — La.</li></ul><label class="check-label"><input id="approve-keys" type="checkbox"><span>Я проверил(а) вопросы и принимаю эти уточнения.</span></label>':'<p class="notice success">Ключи проверены. Уточнения №7, №10 и №16 приняты.</p>'}
      <button class="button secondary" id="toggle-test" ${!overview.google_enabled&&!test.is_open?'disabled':''}>${test.is_open?'Закрыть приём новых попыток':'Открыть тест для студентов'}</button>
      ${!test.keys_approved?'<button class="text-button" id="save-keys">Сохранить проверенные ключи</button>':''}<p class="field-hint">Закрытие не прерывает уже начатые попытки.</p></div>
      <div><h2>Учётная запись</h2><p>${esc(sessionInfo.user.email)}</p><p>${sessionInfo.user.issuer==='local'?'Тестовый вход преподавателя. Пароль действует только на этой платформе.':'Вход через Google.'}</p>${sessionInfo.user.issuer==='local'?'<button class="button secondary" id="password-button">Изменить пароль</button>':''}</div></div></section>`, 'dashboard');
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
  try{await api('api/teacher/test/settings',{is_open:isOpen,approve_suggested_keys:$('#approve-keys')?.checked||false});await dashboard();toast('Настройки сохранены.');}
  catch(error){toast(error.message);}
}
async function loadParticipants(){
  try{
    const params=new URLSearchParams({search:$('#search').value,status:$('#status').value,page:filterPage});
    const data=await api('api/teacher/attempts?'+params);
    if(screen!=='dashboard')return;
    $('#export-link').href='api/teacher/export.csv?'+params;
    $('#participants').innerHTML=data.rows.length?`<div class="table-scroll"><table><thead><tr><th>Участник</th><th>Статус</th><th>Начало</th><th>Результат</th><th><span class="sr-only">Подробнее</span></th></tr></thead><tbody>${data.rows.map(row=>`<tr><td><strong>${esc(row.last_name+' '+row.first_name)}</strong><span class="person-email">${esc(row.email)}</span></td><td><span class="tag ${row.finished!=null?'green':'blue'}">${row.finished!=null?'Завершён':'В процессе'}</span></td><td>${date(row.started)}</td><td>${row.finished!=null?`<strong>${row.score}</strong><span class="muted"> / 20</span>`:'—'}</td><td><button class="text-button detail-button" data-id="${row.id}">Открыть</button></td></tr>`).join('')}</tbody></table></div><div class="pagination"><span>Всего: ${data.total}</span><div class="actions"><button class="button secondary small" id="previous-page" ${filterPage<=1?'disabled':''}>Назад</button><span>${filterPage}</span><button class="button secondary small" id="next-page" ${filterPage*50>=data.total?'disabled':''}>Далее</button></div></div>`:`<div class="empty-state"><strong>${params.get('search')||params.get('status')?'Участники не найдены':'Результатов пока нет'}</strong><p>${params.get('search')||params.get('status')?'Измените условия поиска.':'Когда студенты начнут тест, их попытки появятся здесь.'}</p></div>`;
    document.querySelectorAll('.detail-button').forEach(button=>button.onclick=()=>detailView(button.dataset.id));
    $('#previous-page')?.addEventListener('click',()=>{filterPage--;loadParticipants();});
    $('#next-page')?.addEventListener('click',()=>{filterPage++;loadParticipants();});
  }catch(error){if(screen==='dashboard')$('#participants').innerHTML=`<div class="notice error">${esc(error.message)}</div>`;}
}
function questionCards(questions,answers=null){
  return questions.map((q,i)=>{
    const a=answers?.find(x=>x.question_index===i);
    return `<article class="answer-card"><div class="section-head"><strong>Вопрос ${i+1}</strong>${answers?`<span class="tag ${a?.correct?'green':''}">${!a?'Не открыт':a.choice==null?'Пропущен':a.correct?'Верно':'Неверно'}</span>`:''}</div><h3 lang="es">${esc(q.prompt)}</h3><p lang="es">${esc(q.text)}</p><div class="answer-options" lang="es">${q.choices.map((choice,j)=>`<div class="${q.correct.includes(j)?'right':a?.choice===j?'wrong':''}"><strong>${'abcd'[j]})</strong> ${esc(choice)} ${q.correct.includes(j)?' — верный ответ':''}${a?.choice===j?' · выбран':''}</div>`).join('')}</div></article>`;
  }).join('');
}
async function questionsView(){
  try{
    const data=await api('api/teacher/preview');
    show(`<div class="content-narrow"><div class="page-top"><div><div class="eyebrow">Материалы теста</div><h1>Вопросы и ключи</h1><p>20 вопросов · Один ответ на вопрос</p></div><button class="button secondary" id="back">В кабинет</button></div><div class="notice">Показаны предлагаемые ключи с уточнениями №7, №10 и №16. Их принятие доступно в кабинете. В №7 засчитывается b или c.</div>${questionCards(data.questions)}</div>`,'questions');
    $('#back').onclick=dashboard;
  }catch(error){toast(error.message);}
}
async function detailView(id){
  try{
    const data=await api('api/teacher/attempts/'+id);
    show(`<div class="content-narrow"><div class="page-top"><div><div class="eyebrow">Карточка попытки</div><h1>${esc(data.last_name+' '+data.first_name)}</h1><p>${esc(data.email)}</p></div><button class="button secondary" id="back">В кабинет</button></div><div class="notice">Начало: ${date(data.started)} · ${data.finished!=null?'Завершение: '+date(data.finished)+' · Результат: '+data.score+' / 20':'Тест в процессе'}</div>${questionCards(data.questions,data.answers)}</div>`,'detail');$('#back').onclick=dashboard;
  }catch(error){toast(error.message);}
}
function passwordView(){
  show(`<div class="panel start-card"><div class="eyebrow">Учётная запись</div><h1>Изменить пароль</h1><p class="panel-subtitle">${esc(sessionInfo.user.email)}</p><form id="password-form"><div class="field"><label for="old-password">Текущий пароль</label><input class="input" id="old-password" type="password" autocomplete="current-password" required maxlength="256"></div><div class="field"><label for="new-password">Новый пароль</label><input class="input" id="new-password" type="password" autocomplete="new-password" minlength="20" maxlength="256" required><p class="field-hint">Не менее 20 символов. Можно использовать длинную фразу.</p></div><div class="field"><label for="confirm-password">Повторите новый пароль</label><input class="input" id="confirm-password" type="password" autocomplete="new-password" required></div><p class="notice">После смены пароля потребуется заново войти на других устройствах.</p><div class="notice error hidden" id="password-error" role="alert"></div><div class="actions"><button class="button" type="submit">Сохранить пароль</button><button class="button secondary" type="button" id="back">Отмена</button></div></form></div>`,'password');
  $('#back').onclick=dashboard;
  $('#password-form').onsubmit=async event=>{
    event.preventDefault();
    if($('#new-password').value!==$('#confirm-password').value)return errorBox($('#password-error'),'Пароли не совпадают.');
    const button=$('button[type=submit]',event.currentTarget);button.disabled=true;
    try{await api('api/auth/password',{current_password:$('#old-password').value,password:$('#new-password').value});sessionInfo=await api('api/session');await dashboard();toast('Пароль изменён.');}
    catch(error){errorBox($('#password-error'),error.message);button.disabled=false;}
  };
}
boot();
