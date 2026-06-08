/**
 * 前端报告渲染引擎测试
 *
 * 测试策略：从 index.html 提取 renderReport 和 R 对象进行独立测试，
 * 不修改生产代码。
 */

// Helper: 读取 index.html 中的 R 对象和 renderReport 函数
const fs = require('fs');
const path = require('path');
const html = fs.readFileSync(path.resolve(__dirname, '../index.html'), 'utf-8');

// 提取 renderReport + R 对象
function extractRenderFunctions(html) {
  const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
  if (!scriptMatch) throw new Error('No script tag found');
  const js = scriptMatch[1];

  // 提取 R 对象定义
  const rStart = js.indexOf('var R = {');
  if (rStart === -1) throw new Error('R object not found');
  
  // 找到 R 对象的结尾（匹配花括号）
  let depth = 0;
  let rEnd = rStart;
  // 找到第一个 {
  const braceStart = js.indexOf('{', rStart);
  for (let i = braceStart; i < js.length; i++) {
    if (js[i] === '{') depth++;
    else if (js[i] === '}') {
      depth--;
      if (depth === 0) { rEnd = i + 1; break; }
    }
  }

  // 提取 renderReport 函数
  const rrStart = js.indexOf('function renderReport(');
  if (rrStart === -1) throw new Error('renderReport not found');

  depth = 0;
  let rrEnd = rrStart;
  for (let i = rrStart; i < js.length; i++) {
    if (js[i] === '{') depth++;
    else if (js[i] === '}') {
      depth--;
      if (depth === 0) { rrEnd = i + 1; break; }
    }
  }

  const rCode = js.slice(rStart, rEnd);
  const rrCode = js.slice(rrStart, rrEnd);

  // 还要提取 R.esc 等工具函数
  const escMatch = js.match(/R\.esc\s*=\s*function[^}]+}/);
  const escCode = escMatch ? escMatch[0] : '';

  const combined = rCode + '\n' + escCode + '\n' + rrCode + '\n;';
  return combined;
}

describe('renderReport', () => {
  let renderReport;

  beforeAll(() => {
    const code = extractRenderFunctions(html);
    // 在 jsdom 环境中执行代码
    const fn = new Function('R', code + '; return renderReport;');
    // 创建模拟的 R 对象
    const R = {
      esc: (s) => String(s || '').replace(/[<>&"']/g, ''),
      metrics: (items) => '<div class="rc-metrics">' + (items || []).map(function(it) {
        return '<span class="rc-metric' + (it.accent ? ' accent-' + it.accent : '') + '"><b>' + R.esc(it.value || '') + '</b>' + R.esc(it.label || '') + '</span>';
      }).join('') + '</div>',
      bar_chart: (items) => '<div class="rc-bar-chart">' + (items || []).map(function(it) {
        return '<div class="rc-bar-item"><span class="bar-label">' + R.esc(it.label || '') + '</span><div class="bar-track"><div class="bar-fill color-' + (it.color || 'c1') + '" style="width:' + (it.value || 0) + '%"></div></div><span class="bar-value">' + R.esc(it.value + (it.suffix || '')) + '</span></div>';
      }).join('') + '</div>',
      insight: (d) => '<div class="rc-insight' + (d.style === 'warn' ? ' warn' : ' tip') + '">' + (d.title ? '<strong>' + R.esc(d.title) + '</strong>' : '') + '<p>' + (d.body || '') + '</p></div>',
    };
    renderReport = fn(R);
  });

  test('returns empty string for null input', () => {
    expect(renderReport(null)).toBe('');
  });

  test('returns empty string for input without sections', () => {
    expect(renderReport({})).toBe('');
    expect(renderReport({ title: '测试' })).toBe('');
  });

  test('renders title', () => {
    const result = renderReport({
      title: '测试报告',
      sections: [{ type: 'insight', data: { style: 'tip', body: '内容' } }]
    });
    expect(result).toContain('测试报告');
    expect(result).toContain('rc-insight');
  });

  test('renders metrics section', () => {
    const result = renderReport({
      sections: [{ type: 'metrics', data: { items: [
        { label: '热度', value: '85', accent: 'gold' }
      ]}}]
    });
    expect(result).toContain('rc-metrics');
    expect(result).toContain('accent-gold');
    expect(result).toContain('85');
    expect(result).toContain('热度');
  });

  test('renders bar chart section', () => {
    const result = renderReport({
      sections: [{ type: 'bar_chart', data: { items: [
        { label: '¥0-199', value: 30, color: 'c1', suffix: '%' }
      ]}}]
    });
    expect(result).toContain('rc-bar-chart');
    expect(result).toContain('¥0-199');
    expect(result).toContain('30%');
  });

  test('renders insight (tip)', () => {
    const result = renderReport({
      sections: [{ type: 'insight', data: { style: 'tip', title: '建议', body: '值得切入' } }]
    });
    expect(result).toContain('rc-insight');
    expect(result).toContain('建议');
    expect(result).toContain('值得切入');
  });

  test('renders insight (warn)', () => {
    const result = renderReport({
      sections: [{ type: 'insight', data: { style: 'warn', body: '注意风险' } }]
    });
    expect(result).toContain('rc-insight warn');
    expect(result).toContain('注意风险');
  });

  test('handles unknown section type gracefully', () => {
    const result = renderReport({
      sections: [{ type: 'unknown_type', data: {} }]
    });
    expect(result).not.toContain('undefined');
  });

  test('renders multiple sections in order', () => {
    const result = renderReport({
      title: '综合报告',
      sections: [
        { type: 'metrics', data: { items: [{ label: '热度', value: '90' }] } },
        { type: 'insight', data: { style: 'tip', body: '结论' } }
      ]
    });
    // title first
    const titleIdx = result.indexOf('综合报告');
    const metricsIdx = result.indexOf('rc-metrics');
    const insightIdx = result.indexOf('rc-insight');
    expect(titleIdx).toBeLessThan(metricsIdx);
    expect(metricsIdx).toBeLessThan(insightIdx);
  });

  test('escapes HTML in labels', () => {
    const result = renderReport({
      sections: [{ type: 'insight', data: { style: 'tip', body: '<script>alert("xss")</script>' } }]
    });
    expect(result).not.toContain('<script>');
    expect(result).toContain('&lt;script&gt;');
  });
});
