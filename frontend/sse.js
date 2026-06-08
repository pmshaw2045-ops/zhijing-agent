96|// ====== CHAT ======
97|function addMessage(role, content, isHTML) {
98|  const div = document.createElement('div');
99|  div.className = 'message ' + role;
100|  if (role === 'agent') {
101|    div.innerHTML = '<div class="msg-avatar agent">织</div><div class="msg-bubble">' + (isHTML ? content : content.replace(/\n/g,'<br>')) + '</div>';
102|  } else {
103|    div.innerHTML = '<div class="msg-avatar user">👤</div><div class="msg-bubble">' + content + '</div>';
104|  }
105|  chatMessages.appendChild(div);
106|  chatMessages.scrollTop = chatMessages.scrollHeight;
107|  return div;
108|}
109|
110|// 状态提示映射
111|const STATUS_TEXT = {
112|  'intent': '意图识别中...',
113|  'precheck': '分析中...',
114|  'decompose': '规划任务中...',
115|  'tool_mapping': '准备工具...',
116|  'execute': '数据采集中...',
117|  'report': '生成报告中...',
118|  'reflect': '初版评审中...',
119|  'reflect_retry': '修正中...',
120|  'reflect_v2': '修正版评审中...',
121|};
122|
123|function updateStatus(bubble, phase) {
124|  var text = STATUS_TEXT[phase] || '处理中...';
125|  // 文生图场景：执行阶段显示"生成图片中"
126|  if (phase === 'execute' && currentMode === 'image') {
127|    text = '生成图片中...';
128|  }
129|  var bubbleEl = bubble.querySelector('.msg-bubble');
130|  bubbleEl.innerHTML = '<div class="agent-status"><span class="dot-pulse"></span>' + text + '</div>';
131|}
132|
133|// ====== API CALL ======
134|let pendingSessionId = null;
135|
136|async function submitClarify(sid) {
137|  const input = document.getElementById('clarifyInput');
138|  if (!input) return;
139|  const answer = input.value.trim();
140|  if (!answer) return;
141|  addMessage('user', answer);
142|  pendingSessionId = sid;
143|  await sendMessageWithClarify(answer, sid);
144|}
145|
146|async function sendMessageWithClarify(answer, sid) {
147|  isProcessing = true;
148|  btnSend.disabled = true;
149|
150|  const reportBubble = addMessage('agent', '<div class="agent-status"><span class="dot-pulse"></span>准备中...</div>', true);
151|
152|  try {
153|    const response = await fetch(API_BASE + '/api/chat', {
154|      method: 'POST',
155|      headers: { 'Content-Type': 'application/json' },
156|      body: JSON.stringify({ message: answer, session_id: sid, mode: currentMode, clarify_answer: answer })
157|    });
158|
159|    if (!response.ok) throw new Error('HTTP ' + response.status);
160|    await _readSSEStream(response, reportBubble);
161|  } catch (err) {
162|    reportBubble.querySelector('.msg-bubble').innerHTML = '<span style="color:#c00">错误: ' + err.message + '</span>';
163|  } finally {
164|    isProcessing = false;
165|    btnSend.disabled = false;
166|  }
167|}
168|
169|// 公共 SSE 流读取函数
170|async function _readSSEStream(response, reportBubble) {
171|  const reader = response.body.getReader();
172|  const decoder = new TextDecoder();
173|  let buffer = '';
174|
175|  while (true) {
176|    const { done, value } = await reader.read();
177|    if (done) break;
178|    buffer += decoder.decode(value, { stream: true });
179|    const lines = buffer.split('\n');
180|    buffer = lines.pop() || '';
181|    for (const line of lines) {
182|      if (!line.startsWith('data: ')) continue;
183|      try {
184|        const event = JSON.parse(line.slice(6));
185|        handleSSEEvent(event, reportBubble);
186|      } catch(e) { console.warn('SSE parse warning:', e.message); }
187|    }
188|  }
189|}
190|
191|async function sendMessage() {
192|  const text = userInput.value.trim();
193|  if (!text || isProcessing) return;
194|
195|  userInput.value = '';
196|  userInput.style.height = 'auto';
197|  isProcessing = true;
198|  btnSend.disabled = true;
199|  clearConsole();
200|
201|  addMessage('user', text);
202|
203|  clog('', '══════════ AGENT PIPELINE 启动 ══════════');
204|  clog('info', '用户输入: "' + text.substring(0,80) + (text.length>80?'...':'') + '"');
205|  clog('info', '会话ID: ' + sessionId + ' | 模式: ' + currentMode);
206|
207|  const reportBubble = addMessage('agent', '<div class="agent-status"><span class="dot-pulse"></span>准备中...</div>', true);
208|
209|  const MAX_RETRIES = 3;
210|  let lastError = null;
211|
212|  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
213|    try {
214|      const response = await fetch(API_BASE + '/api/chat', {
215|        method: 'POST',
216|        headers: { 'Content-Type': 'application/json' },
217|        body: JSON.stringify({ message: text, session_id: sessionId, mode: currentMode })
218|      });
219|
220|      if (!response.ok) throw new Error('HTTP ' + response.status);
221|      await _readSSEStream(response, reportBubble);
222|      lastError = null;
223|      break;
224|    } catch (err) {
225|      lastError = err;
226|      if (attempt >= MAX_RETRIES) break;
227|      const delay = 2000 * (attempt + 1);
228|      updateStatus('连接中断，' + Math.round(delay/1000) + '秒后重试...(' + (attempt+1) + '/' + MAX_RETRIES + ')');
229|      await new Promise(r => setTimeout(r, delay));
230|    }
231|  }
232|
233|  if (lastError) {
234|    reportBubble.querySelector('.msg-bubble').innerHTML = '<span style="color:#c00">错误: ' + lastError.message + '</span>';
235|    clog('error', 'Pipeline失败: ' + lastError.message);
236|  }
237|
238|  isProcessing = false;
239|  btnSend.disabled = false;
240|}
241|