/**
 * 前端报告渲染引擎测试
 *
 * 直接加载 render.js 文件，在 jsdom 中执行后测试 renderReport 函数。
 */
const fs = require('fs');
const path = require('path');

// 直接读取 render.js（定义 var R = {...} 和 function renderReport(json)）
const renderJs = fs.readFileSync(path.resolve(__dirname, '../render.js'), 'utf-8');

describe('renderReport', () => {
  let renderReport;

  beforeAll(() => {
    // 在 jsdom 中执行 render.js — var R 和 renderReport 挂到 window
    const fn = new Function(renderJs + '; return renderReport;');
    renderReport = fn();
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

  test('renders table section', () => {
    const result = renderReport({
      sections: [{ type: 'table', data: {
        headers: ['品牌', '价格'],
        rows: [['品牌A', '¥299'], ['品牌B', '¥399']]
      }}]
    });
    expect(result).toContain('rc-table');
    expect(result).toContain('品牌A');
    expect(result).toContain('¥299');
  });

  test('renders brand_card section', () => {
    const result = renderReport({
      sections: [{ type: 'brand_card', data: {
        name: '法式茶歇裙', brand: 'a',
        rows: [{ k: '建议价格', v: '¥199-299' }, { k: '风险', v: '季节性强' }]
      }}]
    });
    expect(result).toContain('rc-brand-card');
    expect(result).toContain('法式茶歇裙');
    expect(result).toContain('¥199-299');
  });

  test('renders compare section', () => {
    const result = renderReport({
      sections: [{ type: 'compare', data: { brands: [
        { name: '太平鸟', rows: [{ k: '定位', v: '中高端' }] },
        { name: '伊芙丽', rows: [{ k: '定位', v: '中端' }] }
      ]}}]
    });
    expect(result).toContain('rc-compare');
    expect(result).toContain('太平鸟');
    expect(result).toContain('伊芙丽');
  });

  test('renders swot section', () => {
    const result = renderReport({
      sections: [{ type: 'swot', data: {
        brand: 'a', name: '品牌A',
        s: ['款式经典'], w: ['季节性强'],
        o: ['直播红利'], t: ['价格战']
      }}]
    });
    expect(result).toContain('rc-swot');
    expect(result).toContain('优势');
    expect(result).toContain('劣势');
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
    expect(result).toContain('rc-insight');
    expect(result).toContain('注意风险');
  });

  test('renders section_title', () => {
    const result = renderReport({
      sections: [{ type: 'section_title', data: { text: '价格带分析', style: 'gold' } }]
    });
    expect(result).toContain('rc-section-title');
    expect(result).toContain('价格带分析');
  });

  test('renders text section', () => {
    const result = renderReport({
      sections: [{ type: 'text', data: { content: '纯文本段落' } }]
    });
    expect(result).toContain('纯文本段落');
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
