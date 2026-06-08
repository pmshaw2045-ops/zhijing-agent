93|// ====== CONSOLE ======
94|function ts() { return new Date().toTimeString().substring(0,8); }
95|function clog(tag, text) {
96|  const div = document.createElement('div');
97|  div.className = 'console-line';
98|  div.setAttribute('data-tag', tag);
99|  div.innerHTML = '<span class="ts">' + ts() + '</span><span class="tag tag-' + tag + '">' + tag.toUpperCase() + '</span><span class="text">' + text + '</span>';
100|  document.getElementById('pipelineContent').appendChild(div);
101|  consoleOutput.scrollTop = consoleOutput.scrollHeight;
102|}
103|function filterByTab(tag, tab) {
104|  if (tab === 'all') return true;
105|  if (tab === 'pipeline') return ['', 'model', 'intent', 'precheck', 'decompose', 'dag', 'tool', 'execute', 'success', 'error', 'reflect', 'info'].includes(tag);
106|  if (tab === 'state') return tag === 'state';
107|  if (tab === 'memory') return tag === 'memory';
108|  return true;
109|}
110|function clogSection(title, content) {
111|  const div = document.createElement('div');
112|  div.className = 'console-section';
113|  div.setAttribute('data-tag', 'section');
114|  div.innerHTML = '<div class="s-title">' + title + '</div><div class="console-json">' + content + '</div>';
115|  document.getElementById('pipelineContent').appendChild(div);
116|  consoleOutput.scrollTop = consoleOutput.scrollHeight;
117|}
118|function clearConsole() { document.getElementById('pipelineContent').innerHTML = ''; }
119|