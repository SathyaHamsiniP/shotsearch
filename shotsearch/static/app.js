const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name=csrf-token]').content;
let page = 1, total = 0, selected = null, searching = false, polling = false, working = false;
let requestVersion = 0, collectionScroll = 0;
async function api(url, options = {}) {
  const response = await fetch(url, {...options, headers: {'Content-Type':'application/json', 'X-Shotsearch-Token':token, ...options.headers}});
  let data;
  try { data = await response.json(); } catch { throw Error('Could not contact the app. Check that it is still running.'); }
  if (!response.ok) throw Error(data.error || `Request failed (${response.status})`);
  return data;
}
function notice(message = '') { $('notice').textContent = message; }
function filename(path) { return path.split(/[\\/]/).pop(); }
function highlight(element, text) {
  const words = $('query').value.match(/\w+/g) || [];
  if (!words.length) { element.textContent = text; return; }
  const pattern = new RegExp(`(${words.join('|')})`, 'gi');
  for (const part of text.split(pattern)) {
    if (words.some(w => w.toLowerCase() === part.toLowerCase())) {
      const mark = document.createElement('mark'); mark.textContent = part; element.append(mark);
    } else element.append(document.createTextNode(part));
  }
}
function render(items) {
  $('grid').replaceChildren();
  if (!items.length) {
    const empty = document.createElement('div'); empty.className = 'empty';
    empty.textContent = searching ? 'No matches found. Try different words or check whether text was read from your images.' : 'Add your first folder using Manage collection. Your images stay on this computer.';
    $('grid').append(empty); return;
  }
  for (const item of items) {
    const card = document.createElement('button'); card.type = 'button'; card.className = 'card';
    const img = document.createElement('img'); img.className = 'preview'; img.loading = 'lazy';
    img.src = `/api/images/${item.id}/file`; img.alt = filename(item.path);
    img.onerror = () => { img.alt = 'Original image unavailable'; img.removeAttribute('src'); };
    const wrap = document.createElement('div'); wrap.className = 'cardtext';
    const title = document.createElement('strong'); title.textContent = filename(item.path); wrap.append(title);
    if (searching) { const snippet = document.createElement('p'); highlight(snippet, item.snippet || ''); wrap.append(snippet); }
    const tag = document.createElement('span'); tag.className = 'tag';
    tag.textContent = item.match_reason || ({ready:'Text available', empty:'No readable text found', error:'Couldn’t process'}[item.status]) || '';
    wrap.append(tag); card.append(img, wrap); card.onclick = () => view(item.id); $('grid').append(card);
  }
}
async function status() {
  const data = await api('/api/status'); $('stats').replaceChildren();
  for (const [label, n] of [['Ready to search', data.prepared], ['No readable text', data.counts.empty || 0], ['Couldn’t process', data.counts.error || 0]]) {
    const box = document.createElement('div'); box.className = 'stat'; const value = document.createElement('strong'); value.textContent = n;
    box.append(value, document.createTextNode(label)); $('stats').append(box);
  }
  const ready = data.prepared === (data.counts.ready || 0) && (!(data.counts.ready || 0) || data.model_loaded);
  $('retrybutton').hidden = ready;
  $('modelstatus').textContent = ready ? '● Search ready' : 'Meaning search needs preparation — Keyword search is available';
  $('setup').textContent = data.tesseract ? 'Text reader available.' : 'Tesseract is missing. See the setup instructions in README.';
  $('dbpath').textContent = 'Collection data: ' + data.database;
  return data;
}
async function browse() {
  const version = ++requestVersion;
  try {
    let data = await api('/api/images?page=' + page);
    if (version !== requestVersion) return;
    if (page > 1 && !data.items.length) { page = Math.max(1, Math.ceil(data.total / 30)); data = await api('/api/images?page=' + page); }
    if (version !== requestVersion) return;
    searching = false; total = data.total; render(data.items);
    $('heading').textContent = 'Your collection'; $('summary').textContent = total + ' images';
    $('pagination').hidden = false; $('page').textContent = `Page ${page} of ${Math.max(1, Math.ceil(total / 30))}`;
    $('prev').disabled = page <= 1; $('next').disabled = page * 30 >= total;
  } catch (error) { notice(error.message); }
}
async function clearSearch() {
  $('query').value = ''; $('clear').hidden = true; notice();
  await browse(); window.scrollTo(0, collectionScroll);
}
$('query').oninput = () => { $('clear').hidden = !$('query').value; if (!$('query').value && searching) clearSearch(); };
$('clear').onclick = clearSearch; $('browse').onclick = clearSearch;
$('searchform').onsubmit = async event => {
  event.preventDefault(); if (working) return;
  if (!searching) collectionScroll = window.scrollY;
  const version = ++requestVersion; $('searchbutton').disabled = true; notice('Searching…');
  try {
    const data = await api('/api/search', {method:'POST', body:JSON.stringify({query:$('query').value, mode:$('mode').value})});
    if (version !== requestVersion) return;
    searching = true; render(data.items); $('heading').textContent = 'Search results';
    $('summary').textContent = `${data.total ?? data.items.length} results · All shown, most relevant first · ${data.seconds.toFixed(2)} seconds`; $('pagination').hidden = true; notice();
  } catch (error) { if (version === requestVersion) notice(error.message); }
  finally { $('searchbutton').disabled = working; }
};
async function view(id) {
  try { const data = await api('/api/images/' + id); selected = id; $('viewtitle').textContent = filename(data.path);
    $('viewimage').src = `/api/images/${id}/file`; $('viewtext').textContent = data.text || data.error || 'No readable text found. Handwriting and blurry images may not work.';
    $('viewpath').textContent = data.path; $('viewer').showModal();
  } catch (error) { notice(error.message); }
}
$('removebutton').onclick = async () => {
  if (!confirm('Remove this image from your collection? The original file will be kept.')) return;
  try { await api('/api/images/' + selected, {method:'DELETE'}); $('viewer').close(); await status(); await clearSearch(); notice('Removed. Adding its folder again will restore it.'); }
  catch (error) { notice(error.message); }
};
$('manage').onclick = async () => { $('settings').showModal(); if (!working) { try { await status(); } catch (error) { $('setup').textContent = error.message; } } };
$('closesettings').onclick = () => $('settings').close(); $('closeviewer').onclick = () => $('viewer').close();
$('prev').onclick = () => { page--; browse(); }; $('next').onclick = () => { page++; browse(); };
function busy(on) { working = on; for (const id of ['searchbutton','indexbutton','retrybutton','browse','clear','prev','next']) $(id).disabled = on; }
async function poll() {
  if (polling) return; polling = true;
  try {
    const data = await api('/api/job');
    if (data.state === 'running') {
      busy(true); $('jobbox').hidden = false; $('jobtitle').textContent = 'Preparing your collection'; $('jobmessage').textContent = data.message;
      if (data.total) { $('progress').max = data.total; $('progress').value = data.done; } else $('progress').removeAttribute('value');
      setTimeout(poll, 800);
    } else {
      busy(false); $('jobbox').hidden = true;
      if (data.state === 'error') notice('Preparation stopped: ' + data.message + ' You can retry in Manage collection. Keyword search remains available for readable images.');
      if (data.state === 'complete') notice('Your collection is ready.' + (data.result?.failed ? ` ${data.result.failed} images could not be processed.` : ''));
      await status(); await browse();
    }
  } catch (error) { notice(error.message); busy(false); } finally { polling = false; }
}
$('indexform').onsubmit = async event => {
  event.preventDefault();
  try { await api('/api/folders', {method:'POST', body:JSON.stringify({directory:$('directory').value, language:$('language').value, force:$('force').checked})}); $('settings').close(); notice(); requestVersion++; poll(); }
  catch (error) { $('setup').textContent = error.message; }
};
$('retrybutton').onclick = async () => {
  try { await api('/api/prepare', {method:'POST', body:'{}'}); $('settings').close(); notice(); poll(); }
  catch (error) { $('setup').textContent = error.message; }
};
poll();
