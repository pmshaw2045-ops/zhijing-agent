var R = {
  esc: function(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); },
  metrics: function(items) {
    return '<div class="rc-metrics">' + items.map(function(i) {
      var cls = 'rc-metric' + (i.accent ? ' accent-' + i.accent : '');
      return '<div class="' + cls + '"><div class="val">' + R.esc(i.value) + '</div><div class="lbl">' + R.esc(i.label) + '</div></div>';
    }).join('') + '</div>';
  },
  bar_chart: function(items) {
    return '<div class="rc-bar-chart">' + items.map(function(i) {
      return '<div class="rc-bar-row"><span class="rc-bar-label">' + R.esc(i.label) + '</span><div class="rc-bar-track"><div class="rc-bar-fill ' + (i.color||'c1') + '" style="width:' + (i.value||0) + '%">' + R.esc(String(i.value)) + (i.suffix||'%') + '</div></div></div>';
    }).join('') + '</div>';
  },
  table: function(headers, rows) {
    var h = '<thead><tr>' + headers.map(function(h) { return '<th>' + R.esc(h) + '</th>'; }).join('') + '</tr></thead>';
    var b = '<tbody>' + rows.map(function(r) { return '<tr>' + r.map(function(c) { return '<td>' + R.esc(c) + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody>';
    return '<div class="rc-table"><table>' + h + b + '</table></div>';
  },
  brand_card: function(name, rows, brand) {
    brand = brand || 'a';
    return '<div class="rc-brand-card brand-' + brand + '"><div class="brand-header">' + R.esc(name) + '</div><div class="brand-body">' + rows.map(function(r) { return '<div class="row"><span class="k">' + R.esc(r.k) + '</span><span class="v">' + R.esc(r.v) + '</span></div>'; }).join('') + '</div></div>';
  },
  compare: function(brands) {
    return '<div class="rc-compare">' + brands.map(function(b, i) { return R.brand_card(b.name, b.rows, i===0?'a':'b'); }).join('') + '</div>';
  },
  swot: function(data) {
    var brand = data.brand || 'a';
    return '<div class="rc-swot-wrap brand-' + brand + '"><div class="rc-swot-title"><span class="brand-tag ' + brand + '">' + R.esc(data.name) + '</span> SWOT</div><div class="rc-swot">' +
      R._swot_cell('s', '优势', data.s, '💪') +
      R._swot_cell('w', '劣势', data.w, '⚠️') +
      R._swot_cell('o', '机会', data.o, '🚀') +
      R._swot_cell('t', '威胁', data.t, '⚡') +
    '</div></div>';
  },
  _swot_cell: function(type, title, items, icon) {
    return '<div class="rc-swot-cell ' + type + '"><div class="cell-head">' + icon + ' ' + title + ' ' + type.toUpperCase() + '</div><div class="cell-body"><ul>' + (items||[]).map(function(i) { return '<li>' + R.esc(i) + '</li>'; }).join('') + '</ul></div></div>';
  },
  insight: function(style, title, body) {
    return '<div class="rc-insight ' + (style||'tip') + '"><strong>' + R.esc(title) + '</strong>' + R.esc(body) + '</div>';
  },
  section_title: function(text, style) {
    return '<div class="rc-section-title' + (style?' '+style:'') + '">' + R.esc(text) + '</div>';
  },
  text: function(content) {
    return '<p>' + R.esc(content) + '</p>';
  }
};

// 顶层渲染：JSON → HTML
function renderReport(json) {
  if (!json || !json.sections) return '';
  var html = '';
  if (json.title) html += '<h3>' + R.esc(json.title) + '</h3>';
  json.sections.forEach(function(sec) {
    var d = sec.data || {};
    switch (sec.type) {
      case 'metrics':     html += R.metrics(d.items||[]); break;
      case 'bar_chart':   html += R.bar_chart(d.items||[]); break;
      case 'table':       html += R.table(d.headers||[], d.rows||[]); break;
      case 'brand_card':  html += R.brand_card(d.name, d.rows||[], d.brand); break;
      case 'compare':     html += R.compare(d.brands||[]); break;
      case 'swot':        html += R.swot(d); break;
      case 'insight':     html += R.insight(d.style, d.title, d.body); break;
      case 'section_title': html += R.section_title(d.text, d.style); break;
      case 'text':        html += R.text(d.content); break;
    }
  });
  return html;
}