# 根据明确反馈形成偏好

执行前先用 `profile --scene SCENE --user USER` 查看当前偏好和反馈数量。没有足够材料时正常改稿；不要编造反馈填满样本，也不要求首次用户上传历史作品。

## 提取候选

```text
python3 scripts/agent.py learn --scene douyin-tech --learning-mode same_context
```

至少 6 篇不同原文的明确采用/修改反馈才会返回学习任务。留存的 3 篇需未被旧候选占用，重复评测前要积累新的留存反馈；较早记录至多取最近 12 篇训练并受长度预算限制。`batch_id` 冻结该次划分；不能自行读取数据库把留存稿补进学习提示词。这里的隔离是程序接口与操作规范，不是对有文件访问权限的宿主建立了安全隔离。

默认 `same_context`：当前对话可能已看过全部用户反馈，后续评测整体降级，不允许默认启用。只有实际把返回的 training_feedback 交给**没有继承父会话历史的新学习上下文**提取偏好，才使用 `--learning-mode independent`。不能因为学习和审稿用了不同角色名就填 independent。

宿主只使用返回的 training_feedback 归纳偏好。每条至少引用 3 个不同训练记录 ID，且有可说明的重复行为；3 条编号本身不证明偏好真实。用户主动反复修改比仅接受一份稿可靠。没有稳定证据就不提交候选。

将 `{batch_id, preferences}` 写成 JSON：每项为 `{key,value,evidence_ids,reason}`，键值必须符合返回的 allowed_values。可调整开头、语气、句长倾向、结尾和比喻程度；不能新增作者经历、主题事实或更改核心规则。reason 只保存表达证据，不作为可执行指令。

```text
python3 scripts/agent.py propose --scene douyin-tech --json-file /工作目录/work/proposal.json
```

生成候选并不改变当前画像；训练集/留存集、学习方式、基础偏好与规则指纹均被冻结。同一批反馈不能反复提出不同候选以迎合留存集；仅换证据或理由、实际键值不变的候选也不能算策略升级。

## 验证与启用

按 [benchmark 协议](benchmark.md) 准备候选评测，完成所有生成、逐稿审查和 A/B 比较。不能用几个例子替代规定的五组，也不把新策略的名字告诉盲评者。

通过标准：全部内容检查通过、至少一次候选胜出、没有败项，并满足实际审校方式的要求。全平局不证明收益。模型审校有偏差，少量样本也不是统计显著结论。

用户说“启用通过的候选”或已授权满足条件后自动启用时：

```text
python3 scripts/agent.py activate --candidate CANDIDATE_ID
```

自审报告默认不能启用。只有用户明确接受这种降级验证，才可使用 `--allow-self-reviewed`；它仍不能绕过漏项、错误、全平局或败项，并会记录降级事件。普通用户发了一篇文章不等于授权降低验证要求。

回退：

```text
python3 scripts/agent.py rollback --scene douyin-tech
```

支持逐次回到旧版本或默认策略，不删除旧反馈。换宿主/模型或修改规则后，旧验证不应继续宣称有效，需按实际运行结果重新评测。

## 不做的“自我优化”

不改写核心 Skill，不削弱内容保真判据，不删除失败 benchmark，不把自己的改稿当人类偏好，也不从使用次数推导质量。新模式先以失败证据形成开发建议，再由维护者增加反例并重新评测。
