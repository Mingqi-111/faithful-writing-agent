# 用宿主模型运行 benchmark

本包不调用 API。宿主模型执行生成/审校，脚本分配任务、保存实际结果并计算门槛。运行命令返回任务清单并不代表测试已经完成。

## 1. 离线检查器

```text
python3 scripts/agent.py benchmark --mode offline
```

40 条固定原稿/改稿样本只验证确定性检查器是否按预期工作，包括常见数字/单位等值写法、链接、代码与引语。四条语义盲区样本会故意让本地检查不报错，提醒必须另做语义审校。不能将 40/40 写成 Agent 写作质量或人类作者概率。

## 2. 公开生成开发集

```text
python3 scripts/agent.py benchmark --mode prepare --limit 3 --host codex/unknown
```

返回 benchmark 的 `id` 和每条 run_id/task。宿主逐条按 runtime.md 完成 `draft → review`，全部完成后：

```text
python3 scripts/agent.py benchmark --mode report --id BENCHMARK_ID
```

20 条公开用例含原文、场景、必须保留/禁止新增的语义约束，部分还有表达改善目标。`style_goals` 不是授权删除作者独立观点。逐稿评审必须实际核对这些条件，未满足的具体问题写进 issues 并请求修正。

遗漏的稿、没审完的稿不能算通过；fallback 也不能冒充成功改写。记录 review_mode 和 reviewer：同一上下文自审不算独立评测。另一个上下文也可能共享基础模型偏差，所以结果仍需要人工校准。

这个宿主版目前提供固定策略的公开集测试与个性化新旧对比；旧 API 工程中的 plain/skill/agent 自动三路调用不直接移植为“宿主已实测”。要做三路研究，应由宿主独立构建各组输出，保证相同题目与评审规则，再记录实际结果。

## 3. 个人偏好候选

```text
python3 scripts/agent.py benchmark --mode prepare --candidate CANDIDATE_ID --host codex/unknown
```

固定为 3 篇留存稿和 2 条公开用例，每条生成基础偏好与候选偏好两份，共 10 个 run。不得通过 --limit 缩短启用门槛。

每个生成任务只带其原文、场景、偏好及必要约束，不含用户的留存终稿。最好为每份输出使用独立上下文；若使用同一上下文，生成者可能看到另一份结果，不能在报告中称作严格隔离实验。

所有 run 完成后调用 report。若仍待处理，则继续完成；若任何稿失败则不能升级。内容检查通过后返回 A/B 比较任务，仅此时显示用户留存终稿作为风格参考。

把返回的比较任务交给没有参与两组生成的上下文，不传原 run_id、候选偏好或版本身份。由真实审校者填写每题的 a_pass、b_pass、winner、reason、review_mode、reviewer，按返回 submission_format 写成 JSON：

```text
python3 scripts/agent.py benchmark-review --id BENCHMARK_ID --json-file /工作目录/work/comparisons.json
```

每题必须恰好一条，缺项、重复或未知题目被拒绝。相同输出强制平局。基线或候选出现内容错误、候选有败项或全部平局都不能启用；只做自审时保留降级状态。

同一上下文提取偏好时，即便后续审稿独立，仍不能声称留存终稿对提取者未见；报告会整体降级。脚本只知道宿主提交了什么，无法证明宿主确实调用了另一模型或提供了完整人工审评。禁止生成看似合理但未实际执行的报告。

## 4. 可解释的结论

报告应说明测试数量、完成率、内容失败、胜负平局、审校方式和宿主标识。不能只报“通过率高”而隐去没完成或回退的稿。

公开开发集可被实现者看到，不是隐藏验收集。个人留存材料只通过接口隔离，有权限读取整个状态库的宿主仍能看到，因此需要诚实执行协议；测试技巧不能冒充学习收益。更大样本、真实用户盲评、长期跨文章重复率等留待产品验证。
