96|<script src="/console.js"></script>
97|
98|  const phase = event.phase;
99|  const data = event.data;
100|  const status = event.status;
101|
102|  if (type === 'phase' && status === 'running') {
103|    const modelMap = {
104|      intent: 'deepseek-chat', precheck: 'rule_engine', decompose: 'deepseek-v4-pro',
105|      tool_mapping: 'rule_engine', execute: 'execution_engine', reflect: 'deepseek-v4-pro',
106|      reflect_retry: 'deepseek-v4-pro', reflect_v2: 'deepseek-v4-pro', report: 'deepseek-chat',
107|      conversation: 'rule_engine', router: 'rule_engine'
108|    };
109|    const model = event.model || modelMap[phase] || '';
110|    const phaseNames = {
111|      intent: 'Phase 1: 意图识别+路由', precheck: 'Phase 2: 前置校验',
112|      decompose: 'Phase 3: DAG拆解', tool_mapping: 'Phase 4: 工具映射',
113|      execute: 'Phase 5: 并行执行', reflect: 'Phase 7: 初版审查',
114|      reflect_retry: 'Phase 7b: 重试', reflect_v2: 'Phase 7b: 修正版审查', report: 'Phase 6: 报告',
115|      conversation: 'Phase 0: 多轮检测', router: 'Phase 0: 路由判定'
116|    };
117|    const modelColor = model.includes('v4-pro') ? '#e0c080' : model.includes('chat') ? '#80d0d0' : '#888';
118|    clog('model', phaseNames[phase] || phase + ' → <span style="color:' + modelColor + '">' + model + '</span>');
119|
120|    // 更新状态提示
121|    updateStatus(bubble, phase);
122|
123|    if (phase === 'reflect_retry' && data && data.fixes) {
124|      data.fixes.forEach(function(f) { clog('reflect', '  🔧 ' + f); });
125|    }
126|
127|  } else if (type === 'phase' && status === 'done' && data) {
128|    const phaseName = phase || '';
129|
130|    if (phaseName === 'intent') {
131|      const intentData = data.intent || data;
132|      clog('intent', '意图: ' + (intentData.intent_type || '?') + ' (置信度 ' + (intentData.confidence || '?') + ')');
133|      if (intentData.entities) {
134|        var e = intentData.entities;
135|        clog('intent', '实体: 主体="' + (e.subject||'') + '", 类目="' + (e.category||'') + '", 风格="' + (e.style||'') + '", 时间="' + (e.time||'') + '"');
136|      }
137|      if (data.auto_routed) {
138|        clog('intent', '自动路由 → ' + data.auto_routed);
139|        autoHighlightSidebar(data.auto_routed);
140|      }
141|      if (intentData.goal) {
142|        clogSection('结构化 GOAL', JSON.stringify(intentData.goal, null, 2));
143|      }
144|
145|    } else if (phaseName === 'conversation') {
146|      clog('', '📞 多轮检测: ' + (data.scenario || '新查询') + (data.enhanced ? ' (查询已增强)' : ''));
147|
148|    } else if (phaseName === 'router') {
149|      clog('', '🧭 路由判定: ' + (data.complexity || '标准') + ' | 反思:' + (data.include_reflection ? '✅' : '⏭️跳过') + ' | 重试上限:' + (data.max_retries||'?'));
150|
151|    } else if (phaseName === 'precheck') {
152|      var checks = data.checks || {};
153|      Object.entries(checks).forEach(function(entry) {
154|        var k = entry[0], v = entry[1];
155|        clog('precheck', k + ': ' + (v.passed ? '✅ PASS' : '⚠️ ' + (v.gaps||[]).length + '个缺口'));
156|        if (v.gaps) v.gaps.forEach(function(g) { clog('precheck', '  ↳ ' + g); });
157|      });
158|      if (data.confidence_matrix) {
159|        clogSection('置信度矩阵', JSON.stringify(data.confidence_matrix, null, 2));
160|      }
161|
162|    } else if (phaseName === 'decompose') {
163|      var tasks = data.tasks || [];
164|      var isLLM = data._llm_generated;
165|      var label = isLLM ? '✅ LLM 自主拆解' : (data._fallback ? '⚠️ 模板回退' : '');
166|      var taskSummary = tasks.map(function(t){return t.id + '→' + (t.tool||'?');}).join(' | ');
167|      clog('decompose', (label || '拆解完成') + ': ' + tasks.length + '个任务 — ' + taskSummary);
168|      if (data.rationale) clog('decompose', '设计理由: ' + data.rationale);
169|
170|    } else if (phaseName === 'tool_mapping') {
171|      var mappings = data.mappings || [];
172|      clog('tool', '工具绑定: ' + mappings.length + '个任务→工具映射');
173|      mappings.forEach(function(m) { clog('tool', '  ' + m.task_id + ' → ' + m.tool + (m.desc ? ': "' + m.desc + '"' : '')); });
174|
175|    } else if (phaseName === 'reflect') {
176|      if (data.skipped) {
177|        clog('reflect', '⏭️ 跳过反思: ' + (data.reason || ''));
178|      } else {
179|        var scores = data.scores || {};
180|        var overall = scores.overall || '?';
181|        var passed = data.passed !== false;
182|        clog('reflect', '初版审查: ' + (passed ? '✅ 通过' : '⚠️ 需关注') + ' (综合: ' + overall + '/10)');
183|        if (scores.data_consistency !== undefined) {
184|          clog('reflect', '  数据一致性: ' + scores.data_consistency + '/10 | 目标对齐: ' + scores.goal_alignment + '/10 | 可落地性: ' + scores.actionability + '/10');
185|        }
186|        if (data.issues && data.issues.length > 0) {
187|          data.issues.forEach(function(i) { clog('reflect', '  ⚠️ 问题: ' + i); });
188|        }
189|        if (data.warnings && data.warnings.length > 0) {
190|          data.warnings.forEach(function(w) { clog('reflect', '  💡 提示: ' + w); });
191|        }
192|        if (data.verdict) {
193|          clog('reflect', '  结论: ' + data.verdict);
194|        }
195|      }
196|
197|    } else if (phaseName === 'reflect_retry') {
198|      var retries = data.retries || 0;
199|      var final = data.final_score || '?';
200|      var target = data.target || 7;
201|      var passed = data.passed ? '✅ 达标' : '⚠️ 未达标';
202|      var trail = (data.score_trail || []).join(' → ');
203|      var selected = data.selected_version !== undefined ? ' (保留v' + data.selected_version + ')' : '';
204|      clog('reflect', '🔄 重试' + retries + '次完成: ' + passed + ' (最佳:' + final + '/10' + selected + ', 目标≥' + target + '/10)');
205|      if (trail) clog('reflect', '  评分轨迹: ' + trail);
206|
207|    } else if (phaseName === 'reflect_v2') {
208|      var scores2 = data.scores || {};
209|      var overall2 = scores2.overall || '?';
210|      var before = data.score_before || '?';
211|      var after = data.score_after || overall2;
212|      var label = data.label || '重试审查';
213|      clog('reflect', label + ': ' + after + '/10 (' + before + '→' + after + ') | 一致性:' + (scores2.data_consistency||'?') + ' 对齐:' + (scores2.goal_alignment||'?') + ' 落地:' + (scores2.actionability||'?'));
214|
215|    } else if (phaseName === 'report') {
216|      clog('success', '报告生成完成 ✅');
217|
218|    } else if (phaseName === 'execute') {
219|      var llmDriven = data.llm_driven_tools || 0;
220|      var total = data.total_tools || 0;
221|      clog('execute', '全部任务执行完成 ✅ (' + total + '个任务, ' + llmDriven + '个LLM驱动工具)');
222|    }
223|
224|  } else if (type === 'phase' && status === 'step' && data) {
225|    var tid = data.task_id;
226|    var desc = data.desc || (data.params && data.params.query) || '';
227|    clog('state', tid + ': ' + (data.state_before||'') + ' → ' + (data.state_after||'') + ' (' + data.tool + ')' + (desc ? ' — ' + desc : ''));
228|
229|  } else if (type === 'clarify') {
230|    var msg = event.message || '请补充以下信息';
231|    addMessage('agent', '<p>' + msg.replace(/\n/g,'<br>') + '</p><div style="margin-top:10px"><input type="text" id="clarifyInput" placeholder="输入补充信息..." style="width:100%;padding:8px 12px;border:1px solid var(--border-light);border-radius:8px;font-size:13px" onkeydown="if(event.key==\'Enter\')submitClarify(\'' + event.session_id + '\')"><button onclick="submitClarify(\'' + event.session_id + '\')" style="margin-top:6px;padding:6px 16px;background:var(--accent-rose);color:white;border:none;border-radius:6px;cursor:pointer;font-size:12px">补充并继续</button></div>', true);
232|    chatMessages.scrollTop = chatMessages.scrollHeight;
233|    isProcessing = false;
234|    btnSend.disabled = false;
235|
236|  } else if (type === 'image_result') {
237|    // 图片生成结果
238|    var url = event.url;
239|    var prompt = event.prompt || '';
240|    var bubbleEl = bubble.querySelector('.msg-bubble');
241|    bubbleEl.innerHTML = '<div style="text-align:center">' +
242|      '<img src="' + url + '" alt="生成的图片" style="max-width:100%;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.1)" onload="this.parentElement.parentElement.parentElement.scrollIntoView({behavior:\'smooth\'})">' +
243|      (prompt ? '<div style="margin-top:12px;font-size:12px;color:var(--text-light);text-align:left;line-height:1.6"><strong>生成Prompt:</strong> ' + prompt + '</div>' : '') +
244|      '<a href="' + url + '" download="织镜_文生图.png" target="_blank" style="display:inline-block;margin-top:12px;padding:6px 16px;border-radius:6px;border:1px solid var(--border-light);color:var(--text-secondary);font-size:11px;text-decoration:none;transition:all 0.2s" onmouseover="this.style.borderColor=\'var(--accent-rose)\';this.style.color=\'var(--accent-rose)\'" onmouseout="this.style.borderColor=\'var(--border-light)\';this.style.color=\'var(--text-secondary)\'">下载图片</a>' +
245|      '</div>';
246|    chatMessages.scrollTop = chatMessages.scrollHeight;
247|    clog('success', '图片生成完成 ✅ URL已渲染到对话区');
248|
249|  } else if (type === 'prompt') {
250|    var label = event.label || ('Phase: ' + (event.phase || '?'));
251|    var model = event.model || '?';
252|    var promptText = event.prompt || '';
253|    var id = 'prompt_' + Date.now() + '_' + Math.random().toString(36).substr(2,4);
254|    clog('prompt', '📝 注入Prompt: ' + label + ' → ' + model + ' (' + promptText.length + '字符)');
255|    clogSection('📝 PROMPT: ' + label + ' → ' + model,
256|      '<pre style="white-space:pre-wrap;word-break:break-all;max-height:300px;overflow-y:auto;font-size:10px">' + promptText.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</pre>');
257|
258|  } else if (type === 'summary') {
259|    var d = event.data || {};
260|    var r = d.requests || {};
261|    var t = d.tokens || {};
262|    var totalCost = (t.total_tokens || 0) * (2 / 1000000);  // 粗略按 ¥2/百万token
263|    
264|    clogSection('📊 任务汇总',
265|      '<div style="display:flex;gap:12px;flex-wrap:wrap;font-size:11px">' +
266|      '<span>⏱️ P50: <b>' + (r.latency_p50_ms || 0).toFixed(0) + 'ms</b></span>' +
267|      '<span>🔢 Token: <b style="color:#e0c080">' + (t.total_tokens || 0).toLocaleString() + '</b></span>' +
268|      '<span>📞 调用: <b>' + (t.total_calls || 0) + '次</b></span>' +
269|      '<span>💰 约 <b style="color:#80d080">¥' + totalCost.toFixed(3) + '</b></span>' +
270|      '</div>');
271|
272|  } else if (type === 'quality_review') {
273|    var q = event.data || {};
274|    var scores = q.scores || {};
275|    var sc = scores.overall || '?';
276|    var style = q.passed ? 'f0f7f0;border-left-color:#8b9d83;color:#5a7d5a' : 'fef9f0;border-left-color:#e0a060;color:#b07030';
277|    var html = '<div style="margin-top:20px;padding:14px 18px;background:#' + style.split(';')[0] + ';border-left:3px solid ' + style.split(';')[1].split(':')[1] + ';border-radius:6px;font-size:13px;color:' + style.split(';')[2].split(':')[1] + '">';
278|    html += '<h4 style="margin:0 0 8px">' + (q.passed ? '✅ 质量审查通过' : '📋 质量审查') + '</h4>';
279|    if (q.retried) html += '<p style="margin:4px 0;font-size:12px">🔄 本报告经自动修正' + (q.passed ? '后达标' : '，以下为修正后评分') + '</p>';
280|    html += '<p style="margin:4px 0"><strong>综合评分:</strong> ' + sc + '/10' + (q.verdict ? ' — ' + q.verdict : '') + '</p>';
281|    html += '<p style="margin:4px 0"><strong>数据一致性:</strong> ' + (scores.data_consistency||'?') + '/10 | <strong>目标对齐:</strong> ' + (scores.goal_alignment||'?') + '/10 | <strong>可落地性:</strong> ' + (scores.actionability||'?') + '/10</p>';
282|    if (q.warnings && q.warnings.length) html += '<p style="margin:4px 0;font-size:12px">' + q.warnings.map(function(w){return '· '+w;}).join('<br>') + '</p>';
283|    if (q.shortfall) html += '<p style="margin:4px 0;font-size:12px;color:#c06030">⚠️ 质量未达标，建议结合人工判断</p>';
284|    html += '</div>';
285|    var bubbleEl = bubble.querySelector('.msg-bubble');
286|    bubbleEl.insertAdjacentHTML('beforeend', html);
287|
288|  } else if (type === 'result') {
289|    var bubbleEl = bubble.querySelector('.msg-bubble');
290|    var content = event.content;
291|    // 检测 JSON 报告或 HTML 报告
292|    if (typeof content === 'string' && content.trim().startsWith('{')) {
293|      try {
294|        var json = JSON.parse(content);
295|        bubbleEl.innerHTML = renderReport(json);
296|        void bubbleEl.offsetHeight;
297|        bubbleEl.style.flex = '1';
298|      } catch(e) {
299|        console.warn('JSON parse failed, falling back to HTML:', e.message);
300|        // 非标准 JSON，回退到 HTML
301|        bubbleEl.innerHTML = content;
302|        fixReportLayout(bubbleEl);
303|      }
304|    } else {
305|      bubbleEl.innerHTML = content;
306|      fixReportLayout(bubbleEl);
307|    }
308|    chatMessages.scrollTop = chatMessages.scrollHeight;
309|    clog('success', '结果已渲染到对话区');
310|    injectDownloadBtn(bubbleEl);
311|
312|  } else if (type === 'done') {
313|    clog('', '══════════ PIPELINE 完成 ══════════');
314|    fetch(API_BASE + '/api/memory/' + sessionId)
315|      .then(function(r) { return r.json(); })
316|      .then(function(d) {
317|        document.getElementById('memDisplay').textContent =
318|          '短' + (d.stats?.short_term_count || 0) + '条 · 工作:' + (d.working_memory?.last_intent || '-');
319|      })
320|      .catch(function(e) { console.warn('Memory display fetch failed:', e); });
321|
322|  } else if (type === 'error') {
323|    clog('error', '错误: ' + event.message);
324|    bubble.querySelector('.msg-bubble').innerHTML = '<span style="color:#c00">执行错误: ' + event.message + '</span>';
325|  }
326|}
327|
328|// ====== UI EVENTS ======
329|btnSend.addEventListener('click', sendMessage);
330|userInput.addEventListener('keydown', function(e) {
331|  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
332|});
333|userInput.addEventListener('input', function() {
334|  userInput.style.height = 'auto';
335|  userInput.style.height = Math.min(userInput.scrollHeight, 120) + 'px';
336|});
337|
338|document.querySelectorAll('.quick-btn').forEach(function(btn) {
339|  btn.addEventListener('click', function() {
340|    userInput.value = btn.textContent.trim();
341|    userInput.style.height = 'auto';
342|    userInput.style.height = Math.min(userInput.scrollHeight, 120) + 'px';
343|    sendMessage();
344|  });
345|});
346|
347|function autoHighlightSidebar(mode) {
348|  var labels = { selection: '智能选品', competitive: '竞品分析', trend: '趋势洞察', copy: '商品文案', pricing: '定价策略', launch: '上新排期', image: '文生图' };
349|  currentMode = mode;
350|  headerTitle.textContent = (labels[mode] || '分析') + ' — LLM自动路由';
351|}
352|
353|function resetSidebarStatus() {
354|  headerTitle.textContent = '智能选品 — 真实LLM驱动';
355|}
356|
357|document.querySelectorAll('.console-tab').forEach(function(tab) {
358|  tab.addEventListener('click', function() {
359|    document.querySelectorAll('.console-tab').forEach(function(t) { t.classList.remove('active'); });
360|    tab.classList.add('active');
361|    var active = tab.dataset.tab;
362|    var pc = document.getElementById('pipelineContent');
363|    var mp = document.getElementById('memoryPanel');
364|
365|    // ── MEMORY: 显示面板，隐藏管道 ──
366|    if (active === 'memory') {
367|      pc.style.display = 'none'; mp.style.display = '';
368|      mp.innerHTML = '<div class="console-line"><span class="ts">' + ts() + '</span><span class="text dim">加载中...</span></div>';
369|      fetch(API_BASE + '/api/memory/' + sessionId)
370|        .then(function(r) { return r.json(); })
371|        .then(function(d) { buildMemoryPanel(mp, d); })
372|        .catch(function(e) { mp.innerHTML = '<div class="console-line"><span class="ts">' + ts() + '</span><span class="text" style="color:#c06050">获取失败</span></div>'; });
373|      return;
374|    }
375|
376|    // ── 其他 tab: 显示管道，隐藏面板 ──
377|    mp.style.display = 'none'; pc.style.display = '';
378|
379|    // PIPELINE/STATE: 按标签过滤管道内的行
380|    if (active !== 'all') {
381|      var children = pc.children;
382|      for (var i = 0; i < children.length; i++) {
383|        var tag = children[i].getAttribute('data-tag') || '';
384|        if (active === 'pipeline') {
385|          children[i].style.display = (tag === '' || tag === 'section' || filterByTab(tag, 'pipeline')) ? '' : 'none';
386|        } else if (active === 'state') {
387|          children[i].style.display = (tag === 'state') ? '' : 'none';
388|        }
389|      }
390|    } else {
391|      // ALL: 全部显示
392|      for (var i = 0; i < pc.children.length; i++) { pc.children[i].style.display = ''; }
393|    }
394|    consoleOutput.scrollTop = consoleOutput.scrollHeight;
395|  });
396|});
397|
398|// MEMORY 面板渲染（独立于 clog 系统）
399|function buildMemoryPanel(panel, d) {
400|  var html = '';
401|  function item(text) {
402|    html += '<div class="console-line"><span class="ts">' + ts() + '</span><span class="tag tag-memory">MEMORY</span><span class="text">' + text + '</span></div>';
403|  }
404|  function section(title, content) {
405|    html += '<div class="console-section"><div class="s-title">' + title + '</div><div class="console-json">' + content + '</div></div>';
406|  }
407|
408|  item('🧠 Session: ' + sessionId);
409|  var stats = d.stats || {};
410|  item('会话数: ' + (d.total_sessions || stats.total_sessions || '?') + ' | 短期记忆: ' + (stats.short_term_count || 0) + '条');
411|