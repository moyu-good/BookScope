# `prompts/fast_path/` —— fast 路径子类 prompt 模板

本目录原有 4 份 prompt（Sprint 5.5 PE 落地）：

- `fast_path_general_v1.md` —— 通识题
- `fast_path_review_v1.md` —— 评论题
- `fast_path_summary_v1.md` —— 摘要题
- `fast_path_rating_v1.md` —— 评分题

## 当前状态（fast_path 砍 5 类到 2 类后）

`bookscope.agent.fast_path._route_question` 重构成"字数主信号 + 诊断词
兜底"，**只会产生 2 个路由值**：

- `fast_general` —— 短题且无诊断词
- `agent_loop` —— 长题或含诊断词

即——当前路由**不再命中** `fast_review` / `fast_summary` / `fast_rating`
三类，由 agent_loop 接管这部分题。

## 为什么三份 prompt 还留着

1. **chapter-06 案例研究**有引文用——`docs/internal/case-study/chapter-06-prompt-architecture/`
   里把这四份当架构演进史的素材
2. **后续 sprint 可能复用**——比如把"评分题"重新接成单独的卡片产品
3. 不动文件 = `_FAST_PATH_PROMPT_PATHS` / `_load_subroute_prompt` 行为
   100% 等价，``test_fast_path_subroute.py::TestSubroutePromptLoading``
   仍全过

## 不要做

- 不要从代码里删 `_FAST_PATH_PROMPT_PATHS` —— contract 是
  ``"subroute=fast_review"`` 调用方可以静态指定 subroute，``run_fast_path``
  会按这份表加载对应 prompt
- 不要把这三份 prompt 内容合并到 `fast_path_general_v1.md` ——日后想
  恢复分流时找不到原版
