function ts() { return new Date().toTimeString().substring(0,8); }
function clog(tag, text) {
  const div = document.createElement('div');
  div.className = 'console-line';
  div.setAttribute('data-tag', tag);
  div.innerHTML = '<span class="ts">' + ts() + '</span><span class="tag tag-' + tag + '">' + tag.toUpperCase() + '</span><span class="text">' + text + '</span>';
  document.getElementById('pipelineContent').appendChild(div);
  consoleOutput.scrollTop = consoleOutput.scrollHeight;
}
function filterByTab(tag, tab) {
  if (tab === 'all') return true;
  if (tab === 'pipeline') return ['', 'model', 'intent', 'precheck', 'decompose', 'dag', 'tool', 'execute', 'success', 'error', 'reflect', 'info'].includes(tag);
  if (tab === 'state') return tag === 'state';
  if (tab === 'memory') return tag === 'memory';
  if (tab === 'eval') return tag === 'eval';
  return true;
}
function clogSection(title, content) {
  const div = document.createElement('div');
  div.className = 'console-section';
  div.setAttribute('data-tag', 'section');
  div.innerHTML = '<div class="s-title">' + title + '</div><div class="console-json">' + content + '</div>';
  document.getElementById('pipelineContent').appendChild(div);
  consoleOutput.scrollTop = consoleOutput.scrollHeight;
}
function clearConsole() { document.getElementById('pipelineContent').innerHTML = ''; }
