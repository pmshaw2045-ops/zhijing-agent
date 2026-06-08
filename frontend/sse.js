// ====== CHAT ======
function addMessage(role, content, isHTML) {
  const div = document.createElement('div');
  div.className = 'message ' + role;
  if (role === 'agent') {
    div.innerHTML = '<div class="msg-avatar agent">织</div><div class="msg-bubble">' + (isHTML ? content : content.replace(/\n/g,'<br>')) + '</div>';
  } else {
    div.innerHTML = '<div class="msg-avatar user">👤</div><div class="msg-bubble">' + content + '</div>';
  }
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
  return div;
}

// 状态提示映射
const STATUS_TEXT = {
  'intent': '意图识别中...',
  'precheck': '分析中...',
  'decompose': '规划任务中...',
  'tool_mapping': '准备工具...',
  'execute': '数据采集中...',
  'report': '生成报告中...',
  'reflect': '初版评审中...',
  'reflect_retry': '修正中...',
  'reflect_v2': '修正版评审中...',
};

function updateStatus(bubble, phase) {
  var text = STATUS_TEXT[phase] || '处理中...';
  // 文生图场景：执行阶段显示"生成图片中"
  if (phase === 'execute' && currentMode === 'image') {
    text = '生成图片中...';
  }
  var bubbleEl = bubble.querySelector('.msg-bubble');
  bubbleEl.innerHTML = '<div class="agent-status"><span class="dot-pulse"></span>' + text + '</div>';
}

// ====== API CALL ======
let pendingSessionId = null;

async function submitClarify(sid) {
  const input = document.getElementById('clarifyInput');
  if (!input) return;
  const answer = input.value.trim();
  if (!answer) return;
  addMessage('user', answer);
  pendingSessionId = sid;
  await sendMessageWithClarify(answer, sid);
}

async function sendMessageWithClarify(answer, sid) {
  isProcessing = true;
  btnSend.disabled = true;

  const reportBubble = addMessage('agent', '<div class="agent-status"><span class="dot-pulse"></span>准备中...</div>', true);

  try {
    const response = await fetch(API_BASE + '/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: answer, session_id: sid, mode: currentMode, clarify_answer: answer })
    });

    if (!response.ok) throw new Error('HTTP ' + response.status);
    await _readSSEStream(response, reportBubble);
  } catch (err) {
    reportBubble.querySelector('.msg-bubble').innerHTML = '<span style="color:#c00">错误: ' + err.message + '</span>';
  } finally {
    isProcessing = false;
    btnSend.disabled = false;
  }
}

// 公共 SSE 流读取函数
async function _readSSEStream(response, reportBubble) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const event = JSON.parse(line.slice(6));
        handleSSEEvent(event, reportBubble);
      } catch(e) { console.warn('SSE parse warning:', e.message); }
    }
  }
}

async function sendMessage() {
  const text = userInput.value.trim();
  if (!text || isProcessing) return;

  userInput.value = '';
  userInput.style.height = 'auto';
  isProcessing = true;
  btnSend.disabled = true;
  clearConsole();

  addMessage('user', text);

  clog('', '══════════ AGENT PIPELINE 启动 ══════════');
  clog('info', '用户输入: "' + text.substring(0,80) + (text.length>80?'...':'') + '"');
  clog('info', '会话ID: ' + sessionId + ' | 模式: ' + currentMode);

  const reportBubble = addMessage('agent', '<div class="agent-status"><span class="dot-pulse"></span>准备中...</div>', true);

  const MAX_RETRIES = 3;
  let lastError = null;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    try {
      const response = await fetch(API_BASE + '/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, session_id: sessionId, mode: currentMode })
      });

      if (!response.ok) throw new Error('HTTP ' + response.status);
      await _readSSEStream(response, reportBubble);
      lastError = null;
      break;
    } catch (err) {
      lastError = err;
      if (attempt >= MAX_RETRIES) break;
      const delay = 2000 * (attempt + 1);
      updateStatus('连接中断，' + Math.round(delay/1000) + '秒后重试...(' + (attempt+1) + '/' + MAX_RETRIES + ')');
      await new Promise(r => setTimeout(r, delay));
    }
  }

  if (lastError) {
    reportBubble.querySelector('.msg-bubble').innerHTML = '<span style="color:#c00">错误: ' + lastError.message + '</span>';
    clog('error', 'Pipeline失败: ' + lastError.message);
  }

  isProcessing = false;
  btnSend.disabled = false;
}