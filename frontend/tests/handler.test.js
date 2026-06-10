/**
 * handler.js 关键路径测试
 */
const fs = require('fs');
const path = require('path');

const handlerJs = fs.readFileSync(path.resolve(__dirname, '../handler.js'), 'utf-8');
const renderJs = fs.readFileSync(path.resolve(__dirname, '../render.js'), 'utf-8');

function setupHandlerEnv() {
  document.body.innerHTML = '';

  // handler.js eval 时直接引用的 DOM 元素
  const els = {
    chatMessages: 'div', btnSend: 'button', headerTitle: 'div', userInput: 'textarea',
    memDisplay: 'div', sidDisplay: 'div', modelTag: 'span',
    btnToggleConsole: 'button', consoleOutput: 'div', pipelineContent: 'div', memoryPanel: 'div',
  };
  Object.keys(els).forEach(id => {
    const el = document.createElement(els[id]);
    el.id = id;
    document.body.appendChild(el);
  });

  // console-panel 通过 class 访问
  const cp = document.createElement('div');
  cp.className = 'console-panel';
  document.body.appendChild(cp);

  // 映射 handler.js 期望的全局变量
  global.API_BASE = '';
  global.chatMessages = document.getElementById('chatMessages');
  global.btnSend = document.getElementById('btnSend');
  global.headerTitle = document.getElementById('headerTitle');
  global.userInput = document.getElementById('userInput');
  global.sessionId = 'sess_test';
  global.currentMode = 'selection';
  global.isProcessing = false;

  // Mock 跨文件函数
  global.clog = jest.fn();
  global.clogSection = jest.fn();
  global.ts = jest.fn(() => '10:00:00');
  global.addMessage = jest.fn(() => document.createElement('div'));
  global.updateStatus = jest.fn();
  global.fixReportLayout = jest.fn();
  global.injectDownloadBtn = jest.fn();
  global.sendMessage = jest.fn();
  global.submitClarify = jest.fn();
  global.clearConsole = jest.fn();

  // 加载依赖文件（用 global.eval 让函数定义在全局作用域）
  global.eval(renderJs);

  // 用 var 声明将全局变量注入 eval 作用域，再执行 handler.js
  // handler.js 期望的全局变量来自 index.html inline script 的 const 声明
  let varDecls = Object.keys(els).map(id => 'var ' + id + ' = document.getElementById("' + id + '");').join('\n');

  // 加上其他全局函数和变量
  varDecls += '\nvar API_BASE = "";';
  varDecls += '\nvar clog = global.clog; var clogSection = global.clogSection; var ts = global.ts;';
  varDecls += '\nvar addMessage = global.addMessage; var updateStatus = global.updateStatus;';
  varDecls += '\nvar fixReportLayout = global.fixReportLayout; var injectDownloadBtn = global.injectDownloadBtn;';
  varDecls += '\nvar sendMessage = global.sendMessage; var submitClarify = global.submitClarify;';
  varDecls += '\nvar clearConsole = global.clearConsole; var sessionId = global.sessionId;';
  varDecls += '\nvar currentMode = global.currentMode; var isProcessing = global.isProcessing;';

  global.eval(varDecls + '\n' + handlerJs);
}

describe('handleSSEEvent', () => {
  let bubble, bubbleEl, clog, clogSection, fixReportLayout, addMessage;

  beforeEach(() => {
    setupHandlerEnv();

    bubbleEl = document.createElement('div');
    bubbleEl.className = 'msg-bubble';
    bubble = document.createElement('div');
    bubble.appendChild(bubbleEl);
    bubble.classList = [];

    clog = global.clog;
    clogSection = global.clogSection;
    fixReportLayout = global.fixReportLayout;
    addMessage = global.addMessage;
  });

  test('phase running: logs model info', () => {
    handleSSEEvent({
      type: 'phase', phase: 'intent', status: 'running', model: 'deepseek-chat'
    }, bubble);
    expect(clog).toHaveBeenCalledWith('model', expect.stringContaining('Phase 1'));
    expect(global.updateStatus).toHaveBeenCalledWith(bubble, 'intent');
  });

  test('phase running: reflect_retry with fixes', () => {
    handleSSEEvent({
      type: 'phase', phase: 'reflect_retry', status: 'running',
      data: { fixes: ['修复A'] }
    }, bubble);
    expect(clog).toHaveBeenCalledWith('reflect', expect.stringContaining('🔧'));
  });

  test('phase done intent: logs type and entities', () => {
    handleSSEEvent({
      type: 'phase', phase: 'intent', status: 'done',
      data: {
        intent: { intent_type: '单品选品分析', confidence: 0.85,
          entities: { subject: '茶歇裙' }, goal: { 品类: '连衣裙' } },
        auto_routed: 'selection'
      }
    }, bubble);
    expect(clog).toHaveBeenCalledWith('intent', expect.stringContaining('单品选品分析'));
    expect(clogSection).toHaveBeenCalled();
  });

  test('phase done decompose: logs LLM generated', () => {
    handleSSEEvent({
      type: 'phase', phase: 'decompose', status: 'done',
      data: { _llm_generated: true, tasks: [{ id: 'T1', tool: 'bocha_search' }] }
    }, bubble);
    expect(clog).toHaveBeenCalledWith('decompose', expect.stringContaining('LLM'));
  });

  test('phase done reflect: logs passed', () => {
    handleSSEEvent({
      type: 'phase', phase: 'reflect', status: 'done',
      data: { passed: true, scores: { overall: 8 }, verdict: '合格' }
    }, bubble);
    expect(clog).toHaveBeenCalledWith('reflect', expect.stringContaining('✅'));
  });

  test('phase step: logs state transition', () => {
    handleSSEEvent({
      type: 'phase', phase: 'execute', status: 'step',
      data: { task_id: 'T1', tool: 'bocha_search', state_before: 'PENDING', state_after: 'COMPLETED' }
    }, bubble);
    expect(clog).toHaveBeenCalledWith('state', expect.stringContaining('T1'));
  });

  test('result: renders JSON report', () => {
    handleSSEEvent({
      type: 'result',
      content: JSON.stringify({ title: '测试报告', sections: [{ type: 'insight', data: { style: 'tip', body: '内容' } }] })
    }, bubble);
    expect(bubbleEl.innerHTML).toContain('测试报告');
    expect(bubble.classList.contains('print-report')).toBe(true);
  });

  test('result: falls back to HTML', () => {
    handleSSEEvent({ type: 'result', content: '<div>纯HTML</div>' }, bubble);
    expect(bubbleEl.innerHTML).toContain('纯HTML');
    expect(fixReportLayout).toHaveBeenCalled();
  });

  test('clarify: renders form', () => {
    handleSSEEvent({ type: 'clarify', message: '请明确', session_id: 'sess_123' }, bubble);
    expect(addMessage).toHaveBeenCalled();
  });

  test('image_result: renders image', () => {
    handleSSEEvent({ type: 'image_result', url: 'http://example.com/img.png' }, bubble);
    expect(bubbleEl.innerHTML).toContain('img');
  });

  test('prompt: logs prompt', () => {
    handleSSEEvent({ type: 'prompt', label: 'Phase 1', model: 'flash', prompt: 'xxx' }, bubble);
    expect(clog).toHaveBeenCalledWith('prompt', expect.stringContaining('Phase 1'));
    expect(clogSection).toHaveBeenCalled();
  });

  test('summary: logs metrics', () => {
    handleSSEEvent({ type: 'summary', data: { requests: { latency_p50_ms: 3200 }, tokens: { total_tokens: 15000 } } }, bubble);
    expect(clogSection).toHaveBeenCalledWith('📊 任务汇总', expect.stringContaining('15,000'));
  });

  test('quality_review: renders card', () => {
    handleSSEEvent({ type: 'quality_review', data: { passed: true, scores: { overall: 8 } } }, bubble);
    expect(bubbleEl.innerHTML).toContain('8/10');
  });

  test('error: shows message', () => {
    handleSSEEvent({ type: 'error', message: 'API超时' }, bubble);
    expect(bubbleEl.innerHTML).toContain('API超时');
  });

  test('done: logs completion', () => {
    global.fetch = jest.fn(() => Promise.resolve({ json: () => Promise.resolve({}) }));
    handleSSEEvent({ type: 'done' }, bubble);
    expect(clog).toHaveBeenCalledWith('', expect.stringContaining('PIPELINE 完成'));
  });
});

describe('autoHighlightSidebar', () => {
  beforeEach(() => setupHandlerEnv());

  test('sets mode and updates header', () => {
    autoHighlightSidebar('trend');
    expect(global.currentMode).toBe('trend');
    expect(global.headerTitle.textContent).toContain('趋势洞察');
  });

  test('resetSidebarStatus restores default', () => {
    autoHighlightSidebar('pricing');
    resetSidebarStatus();
    expect(global.headerTitle.textContent).toContain('智能选品');
  });
});

describe('injectDownloadBtn', () => {
  let bubbleEl;

  beforeEach(() => {
    setupHandlerEnv();
    bubbleEl = document.createElement('div');
    document.body.appendChild(bubbleEl);
  });

  test('creates button', () => {
    injectDownloadBtn(bubbleEl);
    expect(bubbleEl.querySelector('.btn-download-pdf')).not.toBeNull();
    expect(bubbleEl.style.paddingBottom).toBe('48px');
  });

  test('deduplicates style', () => {
    injectDownloadBtn(bubbleEl);
    injectDownloadBtn(bubbleEl);
    expect(document.querySelectorAll('#_pdfDownloadStyle').length).toBe(1);
  });
});
