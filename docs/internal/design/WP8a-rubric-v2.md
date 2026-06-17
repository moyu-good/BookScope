# WP8a 设计稿 · rubric_v2（字段语义钉死 + 综述题错配 + rubric 版本指针）

**日期**：2026-06-10
**状态**：过闸执行中（作者授权高速开发；自审通过，作者保留否决权）
**上游**：exp-004 第 9 节两个 follow-up（overall/total 字段语义跨 provider 漂移；综述题与 actionability 结构性错配）

## 目的

评分卡是整个改进回路的测量仪器，但它的输出 schema 没钉死（DeepSeek 把 overall 当文字总评、total 当分数，minimax 相反）、对综述题结构性压分（zhinei q1 三 run actionability 1/2/2）、且 rubric 文件指针硬编码 v1——和 WP0 修过的 prompt 冻结是同一类隐患。

**成功标准**：① rubric_v2 输出 schema 字段唯一语义（`total`=25 制数字必填 / `overall_comment`=文字总评），reviewer 解析两版皆兼容；② 综述题有显式评分指引，actionability 不再错配压分；③ rubric 版本进 `LoopTrace`/batch 元数据 + 指针常量 + 哨兵测试（复制 WP0 模式）；④ 全套零回归。

## 方法论锚

**测量仪器先于实验**（本人沉淀，WP0 同款）——仪器自身的版本、输出格式、适用范围必须先于下一轮实验钉死。

## 方案概要

1. **rubric_v2.md**（PE 起草，v1 原样保留）：输出 schema 节重写——`total` 数字必填、`overall_comment` 文字、禁用裸 `overall` 字段；新增"题型感知"节：综述/概括类问题的 actionability 评"是否给出可跟进的定位与阅读指引"而非"修改处方"，并要求 reviewer 在输出里标注 `question_type_detected`
2. **reviewer 兼容解析**：`total` 优先，缺则尝试 `overall` 数字化（v1 时代数据兼容）；解析出的字段标准化后再入库
3. **rubric 版本指针**：`CURRENT_RUBRIC_VERSION` 常量 + 路径拼接 + env override + trace/batch 元数据记录 + 哨兵测试——完全照抄 WP0 的模子
4. **生效与对照**：rubric 是仪器不是被测物，切 v2 后历史分数不可直接比——batch 元数据有 rubric 版本即可追溯，不做 v1/v2 对照实验（仪器校准靠 WP8 主体的人机一致率，不靠仪器自比）

## 影响范围

`prompts/reviewer_rubric_v2.md`（新）/ `reviewer.py`（解析标准化 + 指针）/ batch 脚本元数据 / 新测试

## 不做什么

- 不改 5 维度本身与 25 分制（量纲稳定）
- 不做 v1/v2 评分对照（理由见方案 4）
- 人机一致率校准（WP8 主体，需作者盲评 1 小时，另排）

## 验证方法

schema 解析单测（v1/v2 两形态 + 字段漂移用例）；哨兵；全套回归。

## 自审

字段唯一语义 ✓ 直接答 exp-004 follow-up；照抄 WP0 模子 ✓ 不发明第二套版本机制；砍掉 v1/v2 对照 ✓ 仪器不自比。
