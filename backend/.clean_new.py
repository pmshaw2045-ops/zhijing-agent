def _clean(text: str) -> str:
    """清理LLM输出：markdown + HTML包裹"""
    import re
    text = text.strip()

    # 1. 移除 markdown 代码块包裹
    if '```html' in text:
        start = text.find('```html')
        end = text.rfind('```')
        if start != -1 and end != -1 and end > start:
            text = text[start+7:end].strip()
    elif text.startswith('```'):
        lines = text.split('\n')
        text = '\n'.join(lines[1:-1] if lines and lines[-1].strip() == '```' else lines[1:])
    text = text.replace('```html', '').replace('```', '')

    # 2. 移除残余 markdown 语法 — 这是新增的！
    # 移除 markdown 标题 (# ## ### 等，但保留HTML中的#)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # 移除 markdown 粗体 **text** → <strong>text</strong>（在非HTML上下文中）
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    # 移除 markdown 分隔线 ---（独立成行）
    text = re.sub(r'^\s*---\s*$', '<hr style="border:none;border-top:1px dashed #ddd;margin:16px 0">', text, flags=re.MULTILINE)
    # 移除 markdown 列表标记 - 或 * 开头（但保留HTML中的）
    # 移除 markdown 斜体 *text*
    text = re.sub(r'(?<!\w)\*([^*]+)\*(?!\w)', r'<em>\1</em>', text)

    # 3. 移除 HTML 文档包裹
    lt_pos = text.find('<')
    if lt_pos > 0:
        text = text[lt_pos:]
    text = re.sub(r'<!DOCTYPE\s+html[^>]*>', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'^<html[^>]*>', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'</html>\s*$', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'<head[^>]*>.*?</head>', '', text, flags=re.IGNORECASE | re.DOTALL).strip()
    text = re.sub(r'<body[^>]*>', '', text, count=1, flags=re.IGNORECASE).strip()
    text = re.sub(r'</body>', '', text, flags=re.IGNORECASE).strip()

    return text.strip()
