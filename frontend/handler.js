function handleSSEEvent(event, bubble) {
  const type = event.type;
  const phase = event.phase;
  const data = event.data;
  const status = event.status;

  if (type === 'phase' && status === 'running') {
    const modelMap = {
      intent: 'flash', precheck: 'rule_engine', decompose: 'pro',
      tool_mapping: 'rule_engine', execute: 'execution_engine', reflect: 'pro',
      reflect_retry: 'pro', reflect_v2: 'pro', report: 'chat',
      conversation: 'rule_engine', router: 'rule_engine'
    };
    const model = event.model || modelMap[phase] || '';
    const phaseNames = {
      intent: 'Phase 1: 意图识别+路由', precheck: 'Phase 2: 前置校验',
      decompose: 'Phase 3: DAG拆解', tool_mapping: 'Phase 4: 工具映射',
      execute: 'Phase 5: 并行执行', reflect: 'Phase 7: 初版审查',
      reflect_retry: 'Phase 7b: 重试', reflect_v2: 'Phase 7b: 修正版审查', report: 'Phase 6: 报告',
      conversation: 'Phase 0: 多轮检测', router: 'Phase 0: 路由判定'
    };
    const modelColor = model === 'pro' ? '#e0c080' : model === 'chat' || model === 'flash' ? '#80d0d0' : model.includes('pro') ? '#e0c080' : model.includes('chat') || model.includes('mini') ? '#80d0d0' : '#888';
    clog('model', phaseNames[phase] || phase + ' → <span style="color:' + modelColor + '">' + model + '</span>');

    // 更新状态提示
    updateStatus(bubble, phase);

    if (phase === 'reflect_retry' && data && data.fixes) {
      data.fixes.forEach(function(f) { clog('reflect', '  🔧 ' + f); });
    }

  } else if (type === 'phase' && status === 'done' && data) {
    const phaseName = phase || '';

    if (phaseName === 'intent') {
      const intentData = data.intent || data;
      clog('intent', '意图: ' + (intentData.intent_type || '?') + ' (置信度 ' + (intentData.confidence || '?') + ')');
      if (intentData.entities) {
        var e = intentData.entities;
        clog('intent', '实体: 主体="' + (e.subject||'') + '", 类目="' + (e.category||'') + '", 风格="' + (e.style||'') + '", 时间="' + (e.time||'') + '"');
      }
      if (data.auto_routed) {
        clog('intent', '自动路由 → ' + data.auto_routed);
        autoHighlightSidebar(data.auto_routed);
      }
      if (intentData.goal) {
        clogSection('结构化 GOAL', JSON.stringify(intentData.goal, null, 2));
      }

    } else if (phaseName === 'conversation') {
      clog('', '📞 多轮检测: ' + (data.scenario || '新查询') + (data.enhanced ? ' (查询已增强)' : ''));

    } else if (phaseName === 'router') {
      clog('', '🧭 路由判定: ' + (data.complexity || '标准') + ' | 反思:' + (data.include_reflection ? '✅' : '⏭️跳过') + ' | 重试上限:' + (data.max_retries||'?'));

    } else if (phaseName === 'precheck') {
      var checks = data.checks || {};
      Object.entries(checks).forEach(function(entry) {
        var k = entry[0], v = entry[1];
        clog('precheck', k + ': ' + (v.passed ? '✅ PASS' : '⚠️ ' + (v.gaps||[]).length + '个缺口'));
        if (v.gaps) v.gaps.forEach(function(g) { clog('precheck', '  ↳ ' + g); });
      });
      if (data.confidence_matrix) {
        clogSection('置信度矩阵', JSON.stringify(data.confidence_matrix, null, 2));
      }

    } else if (phaseName === 'decompose') {
      var tasks = data.tasks || [];
      var isLLM = data._llm_generated;
      var label = isLLM ? '✅ LLM 自主拆解' : (data._fallback ? '⚠️ 模板回退' : '');
      var taskSummary = tasks.map(function(t){return t.id + '→' + (t.tool||'?');}).join(' | ');
      clog('decompose', (label || '拆解完成') + ': ' + tasks.length + '个任务 — ' + taskSummary);
      if (data.rationale) clog('decompose', '设计理由: ' + data.rationale);

    } else if (phaseName === 'tool_mapping') {
      var mappings = data.mappings || [];
      clog('tool', '工具绑定: ' + mappings.length + '个任务→工具映射');
      mappings.forEach(function(m) { clog('tool', '  ' + m.task_id + ' → ' + m.tool + (m.desc ? ': "' + m.desc + '"' : '')); });

    } else if (phaseName === 'reflect') {
      if (data.skipped) {
        clog('reflect', '⏭️ 跳过反思: ' + (data.reason || ''));
      } else {
        var scores = data.scores || {};
        var overall = scores.overall || '?';
        var passed = data.passed !== false;
        clog('reflect', '初版审查: ' + (passed ? '✅ 通过' : '⚠️ 需关注') + ' (综合: ' + overall + '/10)');
        if (scores.data_consistency !== undefined) {
          clog('reflect', '  数据一致性: ' + scores.data_consistency + '/10 | 目标对齐: ' + scores.goal_alignment + '/10 | 可落地性: ' + scores.actionability + '/10');
        }
        if (data.issues && data.issues.length > 0) {
          data.issues.forEach(function(i) { clog('reflect', '  ⚠️ 问题: ' + i); });
        }
        if (data.warnings && data.warnings.length > 0) {
          data.warnings.forEach(function(w) { clog('reflect', '  💡 提示: ' + w); });
        }
        if (data.verdict) {
          clog('reflect', '  结论: ' + data.verdict);
        }
      }

    } else if (phaseName === 'reflect_retry') {
      var retries = data.retries || 0;
      var final = data.final_score || '?';
      var target = data.target || 7;
      var passed = data.passed ? '✅ 达标' : '⚠️ 未达标';
      var trail = (data.score_trail || []).join(' → ');
      var selected = data.selected_version !== undefined ? ' (保留v' + data.selected_version + ')' : '';
      clog('reflect', '🔄 重试' + retries + '次完成: ' + passed + ' (最佳:' + final + '/10' + selected + ', 目标≥' + target + '/10)');
      if (trail) clog('reflect', '  评分轨迹: ' + trail);

    } else if (phaseName === 'reflect_v2') {
      var scores2 = data.scores || {};
      var overall2 = scores2.overall || '?';
      var before = data.score_before || '?';
      var after = data.score_after || overall2;
      var label = data.label || '重试审查';
      clog('reflect', label + ': ' + after + '/10 (' + before + '→' + after + ') | 一致性:' + (scores2.data_consistency||'?') + ' 对齐:' + (scores2.goal_alignment||'?') + ' 落地:' + (scores2.actionability||'?'));

    } else if (phaseName === 'report') {
      clog('success', '报告生成完成 ✅');

    } else if (phaseName === 'execute') {
      var llmDriven = data.llm_driven_tools || 0;
      var total = data.total_tools || 0;
      clog('execute', '全部任务执行完成 ✅ (' + total + '个任务, ' + llmDriven + '个LLM驱动工具)');
    }

  } else if (type === 'phase' && status === 'step' && data) {
    var tid = data.task_id;
    var desc = data.desc || (data.params && data.params.query) || '';
    clog('state', tid + ': ' + (data.state_before||'') + ' → ' + (data.state_after||'') + ' (' + data.tool + ')' + (desc ? ' — ' + desc : ''));

  } else if (type === 'clarify') {
    var msg = event.message || '请补充以下信息';
    addMessage('agent', '<p>' + msg.replace(/\n/g,'<br>') + '</p><div style="margin-top:10px"><input type="text" id="clarifyInput" placeholder="输入补充信息..." style="width:100%;padding:8px 12px;border:1px solid var(--border-light);border-radius:8px;font-size:13px" onkeydown="if(event.key==\'Enter\')submitClarify(\'' + event.session_id + '\')"><button onclick="submitClarify(\'' + event.session_id + '\')" style="margin-top:6px;padding:6px 16px;background:var(--accent-rose);color:white;border:none;border-radius:6px;cursor:pointer;font-size:12px">补充并继续</button></div>', true);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    isProcessing = false;
    btnSend.disabled = false;

  } else if (type === 'image_result') {
    // 图片生成结果
    var url = event.url;
    var prompt = event.prompt || '';
    var bubbleEl = bubble.querySelector('.msg-bubble');
    bubbleEl.innerHTML = '<div style="text-align:center">' +
      '<img src="' + url + '" alt="生成的图片" style="max-width:100%;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,0.1)" onload="this.parentElement.parentElement.parentElement.scrollIntoView({behavior:\'smooth\'})">' +
      (prompt ? '<div style="margin-top:12px;font-size:12px;color:var(--text-light);text-align:left;line-height:1.6"><strong>生成Prompt:</strong> ' + prompt + '</div>' : '') +
      '<a href="' + url + '" download="织镜_文生图.png" target="_blank" style="display:inline-block;margin-top:12px;padding:6px 16px;border-radius:6px;border:1px solid var(--border-light);color:var(--text-secondary);font-size:11px;text-decoration:none;transition:all 0.2s" onmouseover="this.style.borderColor=\'var(--accent-rose)\';this.style.color=\'var(--accent-rose)\'" onmouseout="this.style.borderColor=\'var(--border-light)\';this.style.color=\'var(--text-secondary)\'">下载图片</a>' +
      '</div>';
    chatMessages.scrollTop = chatMessages.scrollHeight;
    clog('success', '图片生成完成 ✅ URL已渲染到对话区');

  } else if (type === 'history_comparison') {
    // 同类目历史对比展示
    var d = event.data || {};
    var current = d.current || {};
    var previous = d.previous || [];
    if (previous.length) {
      var html = '<div style="margin-top:16px;padding:12px 16px;background:#f8f6f0;border-left:3px solid #c0a878;border-radius:6px;font-size:12px;color:#665533">';
      html += '<div style="font-weight:600;margin-bottom:8px">📊 历史分析对比</div>';
      html += '<div style="margin-bottom:6px"><strong>本次：</strong>' + (current.title || '当前报告') + '</div>';
      html += '<div style="font-size:11px;color:#887744">此前相关分析：</div>';
      previous.forEach(function(h) {
        html += '<div style="margin:4px 0 4px 8px;padding:4px 8px;background:rgba(255,255,255,0.6);border-radius:4px">';
        html += '<span style="color:#998855;font-size:10px">[' + h.timestamp + ']</span> ';
        html += '<strong>' + (h.title || '') + '</strong>';
        html += '<div style="color:#776644;font-size:11px;margin-top:2px">' + (h.summary || '') + '</div>';
        html += '</div>';
      });
      html += '</div>';
      bubble.querySelector('.msg-bubble').insertAdjacentHTML('beforeend', html);
    }

  } else if (type === 'prompt') {
    var label = event.label || ('Phase: ' + (event.phase || '?'));
    var model = event.model || '?';
    var promptText = event.prompt || '';
    var id = 'prompt_' + Date.now() + '_' + Math.random().toString(36).substr(2,4);
    clog('prompt', '📝 注入Prompt: ' + label + ' → ' + model + ' (' + promptText.length + '字符)');
    clogSection('📝 PROMPT: ' + label + ' → ' + model,
      '<pre style="white-space:pre-wrap;word-break:break-all;max-height:300px;overflow-y:auto;font-size:10px">' + promptText.replace(/</g,'&lt;').replace(/>/g,'&gt;') + '</pre>');

  } else if (type === 'summary') {
    var d = event.data || {};
    var r = d.requests || {};
    var t = d.tokens || {};
    var totalCost = (t.total_tokens || 0) * (2 / 1000000);  // 粗略按 ¥2/百万token
    
    clogSection('📊 任务汇总',
      '<div style="display:flex;gap:12px;flex-wrap:wrap;font-size:11px">' +
      '<span>⏱️ P50: <b>' + (r.latency_p50_ms || 0).toFixed(0) + 'ms</b></span>' +
      '<span>🔢 Token: <b style="color:#e0c080">' + (t.total_tokens || 0).toLocaleString() + '</b></span>' +
      '<span>📞 调用: <b>' + (t.total_calls || 0) + '次</b></span>' +
      '<span>💰 约 <b style="color:#80d080">¥' + totalCost.toFixed(3) + '</b></span>' +
      '</div>');

  } else if (type === 'quality_review') {
    var q = event.data || {};
    var scores = q.scores || {};
    var sc = scores.overall || '?';
    var style = q.passed ? 'f0f7f0;border-left-color:#8b9d83;color:#5a7d5a' : 'fef9f0;border-left-color:#e0a060;color:#b07030';
    var html = '<div style="margin-top:20px;padding:14px 18px;background:#' + style.split(';')[0] + ';border-left:3px solid ' + style.split(';')[1].split(':')[1] + ';border-radius:6px;font-size:13px;color:' + style.split(';')[2].split(':')[1] + '">';
    html += '<h4 style="margin:0 0 8px">' + (q.passed ? '✅ 质量审查通过' : '📋 质量审查') + '</h4>';
    if (q.retried) html += '<p style="margin:4px 0;font-size:12px">🔄 本报告经自动修正' + (q.passed ? '后达标' : '，以下为修正后评分') + '</p>';
    html += '<p style="margin:4px 0"><strong>综合评分:</strong> ' + sc + '/10' + (q.verdict ? ' — ' + q.verdict : '') + '</p>';
    html += '<p style="margin:4px 0"><strong>数据一致性:</strong> ' + (scores.data_consistency||'?') + '/10 | <strong>目标对齐:</strong> ' + (scores.goal_alignment||'?') + '/10 | <strong>可落地性:</strong> ' + (scores.actionability||'?') + '/10</p>';
    if (q.warnings && q.warnings.length) html += '<p style="margin:4px 0;font-size:12px">' + q.warnings.map(function(w){return '· '+w;}).join('<br>') + '</p>';
    if (q.shortfall) html += '<p style="margin:4px 0;font-size:12px;color:#c06030">⚠️ 质量未达标，建议结合人工判断</p>';
    html += '</div>';
    var bubbleEl = bubble.querySelector('.msg-bubble');
    bubbleEl.insertAdjacentHTML('beforeend', html);

  } else if (type === 'result') {
    var bubbleEl = bubble.querySelector('.msg-bubble');
    var content = event.content;
    // 检测 JSON 报告或 HTML 报告
    if (typeof content === 'string' && content.trim().startsWith('{')) {
      try {
        var json = JSON.parse(content);
        bubbleEl.innerHTML = renderReport(json);
        void bubbleEl.offsetHeight;
        bubbleEl.style.flex = '1';
      } catch(e) {
        console.warn('JSON parse failed, falling back to HTML:', e.message);
        // 非标准 JSON，回退到 HTML
        bubbleEl.innerHTML = content;
        fixReportLayout(bubbleEl);
      }
    } else {
      bubbleEl.innerHTML = content;
      fixReportLayout(bubbleEl);
    }
    chatMessages.scrollTop = chatMessages.scrollHeight;
    clog('success', '结果已渲染到对话区');
    injectDownloadBtn(bubbleEl);
    // 标记当前报告气泡（打印时只显示这个）
    bubble.classList.add('print-report');

  } else if (type === 'done') {
    clog('', '══════════ PIPELINE 完成 ══════════');
    fetch(API_BASE + '/api/memory/' + sessionId)
      .then(function(r) { return r.json(); })
      .then(function(d) {
        document.getElementById('memDisplay').textContent =
          '短' + (d.stats?.short_term_count || 0) + '条 · 工作:' + (d.working_memory?.last_intent || '-');
      })
      .catch(function(e) { console.warn('Memory display fetch failed:', e); });

  } else if (type === 'error') {
    clog('error', '错误: ' + event.message);
    bubble.querySelector('.msg-bubble').innerHTML = '<span style="color:#c00">执行错误: ' + event.message + '</span>';
  }
}

// ====== UI EVENTS ======
btnSend.addEventListener('click', sendMessage);
userInput.addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
});
userInput.addEventListener('input', function() {
  userInput.style.height = 'auto';
  userInput.style.height = Math.min(userInput.scrollHeight, 120) + 'px';
});

document.querySelectorAll('.quick-btn').forEach(function(btn) {
  btn.addEventListener('click', function() {
    userInput.value = btn.textContent.trim();
    userInput.style.height = 'auto';
    userInput.style.height = Math.min(userInput.scrollHeight, 120) + 'px';
    sendMessage();
  });
});

function autoHighlightSidebar(mode) {
  var labels = { selection: '智能选品', competitive: '竞品分析', trend: '趋势洞察', copy: '商品文案', pricing: '定价策略', launch: '上新排期', image: '文生图' };
  currentMode = mode;
  headerTitle.textContent = (labels[mode] || '分析') + ' — LLM自动路由';
}

function resetSidebarStatus() {
  headerTitle.textContent = '智能选品 — 真实LLM驱动';
}

document.querySelectorAll('.console-tab').forEach(function(tab) {
  tab.addEventListener('click', function() {
    document.querySelectorAll('.console-tab').forEach(function(t) { t.classList.remove('active'); });
    tab.classList.add('active');
    var active = tab.dataset.tab;
    var pc = document.getElementById('pipelineContent');
    var mp = document.getElementById('memoryPanel');

    // ── MEMORY: 显示面板，隐藏管道 ──
    if (active === 'memory') {
      pc.style.display = 'none'; mp.style.display = '';
      mp.innerHTML = '<div class="console-line"><span class="ts">' + ts() + '</span><span class="text dim">加载中...</span></div>';
      fetch(API_BASE + '/api/memory/' + sessionId)
        .then(function(r) { return r.json(); })
        .then(function(d) { buildMemoryPanel(mp, d); })
        .catch(function(e) { mp.innerHTML = '<div class="console-line"><span class="ts">' + ts() + '</span><span class="text" style="color:#c06050">获取失败</span></div>'; });
      return;
    }

    // ── 其他 tab: 显示管道，隐藏面板 ──
    mp.style.display = 'none'; pc.style.display = '';

    // PIPELINE/STATE: 按标签过滤管道内的行
    if (active !== 'all') {
      var children = pc.children;
      for (var i = 0; i < children.length; i++) {
        var tag = children[i].getAttribute('data-tag') || '';
        if (active === 'pipeline') {
          children[i].style.display = (tag === '' || tag === 'section' || filterByTab(tag, 'pipeline')) ? '' : 'none';
        } else if (active === 'state') {
          children[i].style.display = (tag === 'state') ? '' : 'none';
        }
      }
    } else {
      // ALL: 全部显示
      for (var i = 0; i < pc.children.length; i++) { pc.children[i].style.display = ''; }
    }
    consoleOutput.scrollTop = consoleOutput.scrollHeight;
  });
});

// MEMORY 面板渲染（独立于 clog 系统）
function buildMemoryPanel(panel, d) {
  var html = '';
  function item(text) {
    html += '<div class="console-line"><span class="ts">' + ts() + '</span><span class="tag tag-memory">MEMORY</span><span class="text">' + text + '</span></div>';
  }
  function section(title, content) {
    html += '<div class="console-section"><div class="s-title">' + title + '</div><div class="console-json">' + content + '</div></div>';
  }

  item('🧠 Session: ' + sessionId);
  var stats = d.stats || {};
  item('会话数: ' + (d.total_sessions || stats.total_sessions || '?') + ' | 短期记忆: ' + (stats.short_term_count || 0) + '条');

  var wm = d.working_memory || {};
  if (Object.keys(wm).length) {
    section('📌 工作记忆', '<pre style="white-space:pre-wrap;font-size:11px;color:#aaa">' + JSON.stringify(wm, null, 2).replace(/</g,'&lt;') + '</pre>');
  }
  var tc = d.topic_context || {};
  if (Object.keys(tc).length) {
    section('📂 主题上下文', '<pre style="white-space:pre-wrap;font-size:11px;color:#aaa">' + JSON.stringify(tc, null, 2).replace(/</g,'&lt;') + '</pre>');
  }
  var hist = d.analysis_history || [];
  if (hist.length) {
    section('📊 分析历史（近5条）', hist.slice(-5).map(function(h) {
      return '· [' + (h.timestamp || '?') + '] ' + (h.intent || '') + ': ' + ((h.summary || '').substring(0, 80));
    }).join('<br>'));
  }
  var lt = d.long_term || {};
  if (Object.keys(lt).length) {
    section('🗄️ 长期记忆', '<pre style="white-space:pre-wrap;font-size:11px;color:#aaa">' + JSON.stringify(lt, null, 2).replace(/</g,'&lt;') + '</pre>');
  }
  var conv = d.conversation || [];
  if (conv.length) {
    section('💬 对话记录（近10条）', conv.slice(-10).map(function(m) {
      return (m.role === 'user' ? '👤 ' : '🤖 ') + ((m.content || '').substring(0, 100));
    }).join('<br>'));
  }
  panel.innerHTML = html;
}

// Console 展开/收起
var btnToggleConsole = document.getElementById('btnToggleConsole');
var consolePanel = document.querySelector('.console-panel');
if (btnToggleConsole && consolePanel) {
  btnToggleConsole.addEventListener('click', function() {
    consolePanel.classList.toggle('collapsed');
    btnToggleConsole.textContent = consolePanel.classList.contains('collapsed') ? '◀' : '☰';
  });
}

// ====== PDF 下载 ======
function injectDownloadBtn(bubbleEl) {
  var old = bubbleEl.querySelector('.btn-download-pdf');
  if (old) old.remove();
  var btn = document.createElement('button');
  btn.className = 'btn-download-pdf';
  btn.title = '下载PDF报告';
  btn.innerHTML = '下载PDF';
  btn.addEventListener('click', function(e) {
    e.stopPropagation();
    downloadPDF(bubbleEl);
  });
  bubbleEl.appendChild(btn);
  // 为按钮留出底部空间
  bubbleEl.style.paddingBottom = '48px';
  // 添加样式（纯文本PDF下载按钮）
  if (!document.getElementById('_pdfDownloadStyle')) {
    var s = document.createElement('style');
    s.id = '_pdfDownloadStyle';
    s.textContent = '.btn-download-pdf{position:absolute;bottom:12px;left:50%;transform:translateX(-50%);padding:6px 18px;border:1px solid var(--border-light,#ddd);border-radius:8px;background:var(--bg-card,#fff);color:var(--text-secondary,#666);font-size:12px;cursor:pointer;transition:all .2s;z-index:10;white-space:nowrap}.btn-download-pdf:hover{border-color:var(--accent-rose,#c47);color:var(--accent-rose,#c47);background:var(--bg-secondary,#faf8f5)}';
    document.head.appendChild(s);
  }
}

function downloadPDF(bubbleEl) {
  var clone = bubbleEl.cloneNode(true);
  var btn = clone.querySelector('.btn-download-pdf');
  if (btn) btn.remove();
  var title = (document.querySelector('.header-title') && document.querySelector('.header-title').textContent) || '织镜报告';
  var cssText = '';
  // 收集 inline <style>
  document.querySelectorAll('style').forEach(function(s) { cssText += s.textContent + '\n'; });
  // fetch <link> 样式表
  var linkPromises = [];
  document.querySelectorAll('link[rel=stylesheet]').forEach(function(link) {
    linkPromises.push(fetch(link.href).then(function(r) { return r.text(); }).catch(function() { return ''; }));
  });
  Promise.all(linkPromises).then(function(linkCss) {
    cssText += linkCss.filter(Boolean).join('\n');
    var html = '<!DOCTYPE html><html lang=zh-CN><head><meta charset=UTF-8><title>' + title + '</title>' +
      '<style>' +
      '*{box-sizing:border-box}body{margin:0;padding:32px 48px;background:#fff;font-family:-apple-system,BlinkMacSystemFont,PingFang SC,Microsoft YaHei,sans-serif;color:#2c2416;font-size:13px;line-height:1.7}' +
      '.btn-download-pdf{display:none!important}' +
      cssText +
      '</style></head><body>' + clone.outerHTML + '</body></html>';
    var win = window.open('', '_blank', 'width=900,height=700');
    if (win) {
      win.document.write(html);
      win.document.close();
      // 双重 requestAnimationFrame 确保渲染完成
      requestAnimationFrame(function() {
        requestAnimationFrame(function() {
          win.print();
        });
      });
    } else {
      var iframe = document.createElement('iframe');
      iframe.style.display = 'none';
      document.body.appendChild(iframe);
      var doc = iframe.contentDocument || iframe.contentWindow.document;
      doc.open(); doc.write(html); doc.close();
      iframe.onload = function() {
        requestAnimationFrame(function() {
          requestAnimationFrame(function() {
            iframe.contentWindow.print();
            document.body.removeChild(iframe);
          });
        });
      };
    }
  });
}