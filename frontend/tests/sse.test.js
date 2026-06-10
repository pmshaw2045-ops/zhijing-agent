/**
 * sse.js 测试 — addMessage, STATUS_TEXT, updateStatus, _readSSEStream
 */
const fs = require('fs');
const path = require('path');

const sseJs = fs.readFileSync(path.resolve(__dirname, '../sse.js'), 'utf-8');

function setupEnv() {
  document.body.innerHTML = '';

  // Polyfill TextEncoder and TextDecoder for jsdom
  if (typeof TextEncoder === 'undefined') {
    global.TextEncoder = require('util').TextEncoder;
  }
  if (typeof TextDecoder === 'undefined') {
    global.TextDecoder = require('util').TextDecoder;
  }

  // sse.js 依赖的 DOM 元素和全局变量
  const ids = ['chatMessages', 'userInput', 'btnSend', 'pipelineContent', 'consoleOutput'];
  const tags = { btnSend: 'button', userInput: 'textarea', chatMessages: 'div', pipelineContent: 'div', consoleOutput: 'div' };
  ids.forEach(id => {
    const el = document.createElement(tags[id] || 'div');
    el.id = id;
    document.body.appendChild(el);
  });

  // Console DOM 依赖
  const cp = document.createElement('div');
  cp.className = 'console-panel';
  document.body.appendChild(cp);

  global.API_BASE = '';
  global.sessionId = 'sess_test';
  global.currentMode = 'selection';
  global.isProcessing = false;
  global.chatMessages = document.getElementById('chatMessages');
  global.btnSend = document.getElementById('btnSend');
  global.userInput = document.getElementById('userInput');
  global.consoleOutput = document.getElementById('consoleOutput');

  // Mock handler.js / console.js 函数（sse.js 引用它们）
  global.clog = jest.fn();
  global.clogSection = jest.fn();
  global.clearConsole = jest.fn();
  global.handleSSEEvent = jest.fn();
  global.autoHighlightSidebar = jest.fn();

  global.eval(sseJs);
}

describe('addMessage(role, content, isHTML)', () => {
  beforeEach(setupEnv);

  test('adds a user message bubble', () => {
    const result = addMessage('user', '帮我分析连衣裙');
    expect(result.className).toBe('message user');
    expect(result.innerHTML).toContain('帮我分析连衣裙');
    expect(document.getElementById('chatMessages').children.length).toBe(1);
  });

  test('adds an agent message with avatar', () => {
    const result = addMessage('agent', '分析完成');
    expect(result.className).toBe('message agent');
    expect(result.innerHTML).toContain('织');
    expect(result.innerHTML).toContain('分析完成');
  });

  test('handles isHTML=true by not escaping newlines', () => {
    const result = addMessage('agent', '<div>HTML内容</div>', true);
    expect(result.innerHTML).toContain('HTML内容');
  });
});

describe('STATUS_TEXT', () => {
  test('has mapping for all major phases', () => {
    // 直接从源码读取 STATUS_TEXT（const 在 global.eval 中不挂到 global 上）
    const src = fs.readFileSync(path.resolve(__dirname, '../sse.js'), 'utf-8');
    const match = src.match(/STATUS_TEXT\s*=\s*({[^}]+})/);
    expect(match).not.toBeNull();
    const obj = eval('(' + match[1] + ')');
    expect(obj.intent).toBe('意图识别中...');
    expect(obj.precheck).toBe('分析中...');
    expect(obj.decompose).toBe('规划任务中...');
    expect(obj.execute).toBe('数据采集中...');
    expect(obj.report).toBe('生成报告中...');
    expect(obj.reflect).toBe('初版评审中...');
  });
});

describe('updateStatus(bubble, phase)', () => {
  beforeEach(setupEnv);

  test('updates bubble text with running indicator', () => {
    const bubble = document.createElement('div');
    const bubbleEl = document.createElement('div');
    bubbleEl.className = 'msg-bubble';
    bubble.appendChild(bubbleEl);

    updateStatus(bubble, 'intent');
    expect(bubbleEl.innerHTML).toContain('意图识别中...');
    expect(bubbleEl.innerHTML).toContain('dot-pulse');
  });

  test('uses image-specific text for image mode', () => {
    global.currentMode = 'image';
    const bubble = document.createElement('div');
    const bubbleEl = document.createElement('div');
    bubbleEl.className = 'msg-bubble';
    bubble.appendChild(bubbleEl);

    updateStatus(bubble, 'execute');
    expect(bubbleEl.innerHTML).toContain('生成图片中...');
  });
});

describe('_readSSEStream(response, reportBubble)', () => {
  beforeEach(setupEnv);

  test('parses SSE data lines and dispatches to handleSSEEvent', async () => {
    const mockReader = {
      read: jest.fn()
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('data: {"type":"phase","phase":"intent","status":"done"}\n\n') })
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('data: {"type":"result","content":"{}"}\n\n') })
        .mockResolvedValueOnce({ done: true, value: undefined })
    };
    const response = { body: { getReader: () => mockReader } };
    const reportBubble = document.createElement('div');

    await _readSSEStream(response, reportBubble);

    expect(handleSSEEvent).toHaveBeenCalledTimes(2);
    expect(handleSSEEvent).toHaveBeenCalledWith(
      { type: 'phase', phase: 'intent', status: 'done' },
      reportBubble
    );
    expect(handleSSEEvent).toHaveBeenCalledWith(
      { type: 'result', content: '{}' },
      reportBubble
    );
  });

  test('handles fragmented SSE chunks', async () => {
    // Simulate a single event split across two chunks
    const mockReader = {
      read: jest.fn()
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('data: {"type":"ph') })
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('ase","phase":"intent"}\n\n') })
        .mockResolvedValueOnce({ done: true, value: undefined })
    };
    const response = { body: { getReader: () => mockReader } };

    await _readSSEStream(response, document.createElement('div'));

    expect(handleSSEEvent).toHaveBeenCalledTimes(1);
    expect(handleSSEEvent).toHaveBeenCalledWith(
      { type: 'phase', phase: 'intent' },
      expect.any(HTMLElement)
    );
  });

  test('skips non-data lines', async () => {
    const mockReader = {
      read: jest.fn()
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode(':comment\n\ndata: {"type":"result","content":"{}"}\n\n') })
        .mockResolvedValueOnce({ done: true, value: undefined })
    };
    const response = { body: { getReader: () => mockReader } };

    await _readSSEStream(response, document.createElement('div'));

    expect(handleSSEEvent).toHaveBeenCalledTimes(1);
  });

  test('handles malformed JSON gracefully', async () => {
    const mockReader = {
      read: jest.fn()
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode('data: 不是JSON\n\n') })
        .mockResolvedValueOnce({ done: true, value: undefined })
    };
    const response = { body: { getReader: () => mockReader } };

    // Should not throw
    await expect(
      _readSSEStream(response, document.createElement('div'))
    ).resolves.toBeUndefined();
  });
});
