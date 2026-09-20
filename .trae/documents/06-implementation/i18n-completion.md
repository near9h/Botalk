# 国际化（语言跟随）

> 实现记录 — commits `ee78cf1` + `8eea475` (2026-09-20)
> 历史方案在 [../history/](../history/)（i18n-completion-plan.md）

---

## 1. 目标

bot 回复**跟随用户输入语言**（中 / 英 / 日），总结（📋 总结）也跟随。

## 2. 关键设计

### 2.1 启发式检测

`backend/app/services/language_detect.py`：

```
detect_response_language(text) -> "zh" | "en"
规则：
  CJK 字符（U+4E00–U+9FFF + U+3400–U+4DBF）占比 ≥ 30% → "zh"
  否则 "en"
latin_floor=4：拉丁字符少于 4 个时不判定（避免噪声）
```

> 不上 NLP 库，纯启发式足够；CJK 占比分母包含 latin 也可（保守）。

### 2.2 系统指令注入

`backend/app/orchestrator/msghub.py`：

- `_generate_agent`：在构造 system prompt 时追加 `[回复语言]` directive
- `_summarize`：用双语 system 模板（中文场景用中文指令、英文场景用英文指令）

### 2.3 测试

- `tests/test_language_detect.py` — 8 个用例（纯中 / 纯英 / 混合 / 日文 / 数字）
- `tests/test_msghub_lang_directive.py` — bot + summary 注入正确

## 3. 已知边界

- **日文**（平假名 / 片假名）不计入 CJK 正则 → 默认 "zh"。业务场景目前只有中 / 英，先容忍
- **混合文本**：以占比为主，未引入 token 级加权

## 4. 后续

- 引入 fasttext language-id 替换启发式（如多语言用户增长）