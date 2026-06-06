# 竞品对标报告 — 验证模板

本文件记录竞品对标报告的关键检查项，用于后续验证报告渲染质量。

## Prompt
太平鸟和伊芙丽2026夏季连衣裙在天猫的竞品对标，对比价格带、面料策略和设计风格

## 检查清单
- [✅] rc-metrics 指标卡片（无 rc-metric-card 残留）
- [✅] rc-bar-chart 柱状图（含 rc-bar-row/rc-bar-track/rc-bar-fill）
- [✅] rc-table 对比表格
- [✅] rc-swot-cell SWOT矩阵（含 .cell-head / .cell-body / ul>li）
- [✅] rc-brand-card 品牌概览卡片
- [✅] rc-insight 洞察框
- [✅] 无 markdown 残留（#标题/**粗体/---分隔线）
- [✅] 质量审查块独立于正文末尾

## 原始HTML
tests/competitive_raw.html

## 转换后HTML（前端 fixReportLayout 效果）
tests/competitive_converted.html
