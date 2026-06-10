/**
 * console.js 测试 — ts, clog, filterByTab, clogSection, clearConsole
 */
const fs = require('fs');
const path = require('path');

const consoleJs = fs.readFileSync(path.resolve(__dirname, '../console.js'), 'utf-8');

function setupEnv() {
  document.body.innerHTML = '';
  const pc = document.createElement('div');
  pc.id = 'pipelineContent';
  document.body.appendChild(pc);
  const co = document.createElement('div');
  co.id = 'consoleOutput';
  document.body.appendChild(co);
  global.consoleOutput = co;
  global.eval(consoleJs);
}

describe('ts()', () => {
  beforeEach(setupEnv);

  test('returns HH:MM:SS format', () => {
    const result = ts();
    expect(result).toMatch(/^\d{2}:\d{2}:\d{2}$/);
  });
});

describe('clog(tag, text)', () => {
  beforeEach(setupEnv);

  test('appends a console line with tag and text', () => {
    clog('model', 'Phase 1: done');
    const pc = document.getElementById('pipelineContent');
    expect(pc.children.length).toBe(1);
    const line = pc.children[0];
    expect(line.className).toBe('console-line');
    expect(line.getAttribute('data-tag')).toBe('model');
    expect(line.innerHTML).toContain('Phase 1: done');
  });

  test('multiple calls append in order', () => {
    clog('a', 'first');
    clog('b', 'second');
    const pc = document.getElementById('pipelineContent');
    expect(pc.children.length).toBe(2);
    expect(pc.children[0].innerHTML).toContain('first');
    expect(pc.children[1].innerHTML).toContain('second');
  });
});

describe('filterByTab(tag, tab)', () => {
  beforeEach(setupEnv);

  test('all tab returns true for any tag', () => {
    expect(filterByTab('', 'all')).toBe(true);
    expect(filterByTab('state', 'all')).toBe(true);
    expect(filterByTab('unknown', 'all')).toBe(true);
  });

  test('pipeline tab includes expected tags', () => {
    expect(filterByTab('', 'pipeline')).toBe(true);
    expect(filterByTab('model', 'pipeline')).toBe(true);
    expect(filterByTab('intent', 'pipeline')).toBe(true);
    expect(filterByTab('success', 'pipeline')).toBe(true);
    expect(filterByTab('error', 'pipeline')).toBe(true);
    expect(filterByTab('reflect', 'pipeline')).toBe(true);
    expect(filterByTab('state', 'pipeline')).toBe(false);
  });

  test('state tab only shows state tags', () => {
    expect(filterByTab('state', 'state')).toBe(true);
    expect(filterByTab('model', 'state')).toBe(false);
    expect(filterByTab('', 'state')).toBe(false);
  });
});

describe('clogSection(title, content)', () => {
  beforeEach(setupEnv);

  test('appends a section with title and content', () => {
    clogSection('📊 任务汇总', '<div>内容</div>');
    const pc = document.getElementById('pipelineContent');
    expect(pc.children.length).toBe(1);
    const sec = pc.children[0];
    expect(sec.className).toBe('console-section');
    expect(sec.getAttribute('data-tag')).toBe('section');
    expect(sec.innerHTML).toContain('📊 任务汇总');
    expect(sec.innerHTML).toContain('内容');
  });
});

describe('clearConsole()', () => {
  beforeEach(setupEnv);

  test('clears all pipeline content', () => {
    clog('a', 'line1');
    clog('b', 'line2');
    expect(document.getElementById('pipelineContent').children.length).toBe(2);
    clearConsole();
    expect(document.getElementById('pipelineContent').innerHTML).toBe('');
  });
});
