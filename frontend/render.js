267|// 报告渲染引擎 — JSON → HTML（100% 正确的CSS类名，不再依赖LLM）
268|// =====================================================================
269|var R = {
270|  esc: function(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); },
271|  metrics: function(items) {
272|    return '<div class="rc-metrics">' + items.map(function(i) {
273|      var cls = 'rc-metric' + (i.accent ? ' accent-' + i.accent : '');
274|      return '<div class="' + cls + '"><div class="val">' + R.esc(i.value) + '</div><div class="lbl">' + R.esc(i.label) + '</div></div>';
275|    }).join('') + '</div>';
276|  },
277|  bar_chart: function(items) {
278|    return '<div class="rc-bar-chart">' + items.map(function(i) {
279|      return '<div class="rc-bar-row"><span class="rc-bar-label">' + R.esc(i.label) + '</span><div class="rc-bar-track"><div class="rc-bar-fill ' + (i.color||'c1') + '" style="width:' + (i.value||0) + '%">' + R.esc(String(i.value)) + (i.suffix||'%') + '</div></div></div>';
280|    }).join('') + '</div>';
281|  },
282|  table: function(headers, rows) {
283|    var h = '<thead><tr>' + headers.map(function(h) { return '<th>' + R.esc(h) + '</th>'; }).join('') + '</tr></thead>';
284|    var b = '<tbody>' + rows.map(function(r) { return '<tr>' + r.map(function(c) { return '<td>' + R.esc(c) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody>';
285|    return '<div class="rc-table"><table>' + h + b + '</table></div>';
286|  },
287|  brand_card: function(name, rows, brand) {
288|    brand = brand || 'a';
289|    return '<div class="rc-brand-card brand-' + brand + '"><div class="brand-header">' + R.esc(name) + '</div><div class="brand-body">' + rows.map(function(r) { return '<div class="row"><span class="k">' + R.esc(r.k) + '</span><span class="v">' + R.esc(r.v) + '</span></div>'; }).join('') + '</div></div>';
290|  },
291|  compare: function(brands) {
292|    return '<div class="rc-compare">' + brands.map(function(b, i) { return R.brand_card(b.name, b.rows, i===0?'a':'b'); }).join('') + '</div>';
293|  },
294|  swot: function(data) {
295|    var brand = data.brand || 'a';
296|    return '<div class="rc-swot-wrap brand-' + brand + '"><div class="rc-swot-title"><span class="brand-tag ' + brand + '">' + R.esc(data.name) + '</span> SWOT</div><div class="rc-swot">' +
297|      R._swot_cell('s', '优势', data.s, '💪') +
298|      R._swot_cell('w', '劣势', data.w, '⚠️') +
299|      R._swot_cell('o', '机会', data.o, '🚀') +
300|      R._swot_cell('t', '威胁', data.t, '⚡') +
301|    '</div></div>';
302|  },
303|  _swot_cell: function(type, title, items, icon) {
304|    return '<div class="rc-swot-cell ' + type + '"><div class="cell-head">' + icon + ' ' + title + ' ' + type.toUpperCase() + '</div><div class="cell-body"><ul>' + (items||[]).map(function(i) { return '<li>' + R.esc(i) + '</li>'; }).join('') + '</ul></div></div>';
305|  },
306|  insight: function(style, title, body) {
307|    return '<div class="rc-insight ' + (style||'tip') + '"><strong>' + R.esc(title) + '</strong>' + R.esc(body) + '</div>';
308|  },
309|  section_title: function(text, style) {
310|    return '<div class="rc-section-title' + (style?' '+style:'') + '">' + R.esc(text) + '</div>';
311|  },
312|  text: function(content) {
313|    return '<p>' + R.esc(content) + '</p>';
314|  }
315|};
316|
317|// 顶层渲染：JSON → HTML
318|function renderReport(json) {
319|  if (!json || !json.sections) return '';
320|  var html = '';
321|  if (json.title) html += '<h3>' + R.esc(json.title) + '</h3>';
322|  json.sections.forEach(function(sec) {
323|    var d = sec.data || {};
324|    switch (sec.type) {
325|      case 'metrics':     html += R.metrics(d.items||[]); break;
326|      case 'bar_chart':   html += R.bar_chart(d.items||[]); break;
327|      case 'table':       html += R.table(d.headers||[], d.rows||[]); break;
328|      case 'brand_card':  html += R.brand_card(d.name, d.rows||[], d.brand); break;
329|      case 'compare':     html += R.compare(d.brands||[]); break;
330|      case 'swot':        html += R.swot(d); break;
331|      case 'insight':     html += R.insight(d.style, d.title, d.body); break;
332|      case 'section_title': html += R.section_title(d.text, d.style); break;
333|      case 'text':        html += R.text(d.content); break;
334|    }
335|  });
336|  return html;
337|}
338|