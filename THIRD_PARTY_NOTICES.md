# 来源与许可

本版沿用 0.1 版逐份审阅后的保义规则与检查器，改为由宿主应用进行模型推理。运行时不调用五个上游项目的可选 CLI 或检测器。

| 来源 | 主 Skill 的 Git blob SHA | 保留许可 |
|---|---|---|
| [op7418/Humanizer-zh](https://github.com/op7418/Humanizer-zh) | ef07b54da21a41d4a7e4fe0b0afb928f597eb684 | [MIT](licenses/op7418-Humanizer-zh.txt) |
| [blader/humanizer](https://github.com/blader/humanizer) | 19fc634208e8cc6ae55d4ff287152583216fd244 | [MIT](licenses/blader-humanizer.txt) |
| [syw2039/humanizer-zh](https://github.com/syw2039/humanizer-zh) | 333e9e916109bd7a2774316dc94a752f1f079246 | [MIT](licenses/syw2039-humanizer-zh.txt) |
| [LifelongLazyLearner/qu-ai-wei](https://github.com/LifelongLazyLearner/qu-ai-wei) | 72e8c39686f60c46b15c8243d6d7583b761d78bd | [MIT](licenses/LifelongLazyLearner-qu-ai-wei.txt) |
| [Aboudjem/humanizer-skill](https://github.com/Aboudjem/humanizer-skill) | 574e4cd95e0d35fca569d5eed207e8a087ab7995 | [MIT](licenses/Aboudjem-humanizer-skill.txt) |

采纳信息锁定、全文关系检查、结构诊断、场景差异和有限修正。拒绝编造经历或数字、强行注入立场、删除必要不确定性、固定句长和标点禁令，也不继承 AI 作者概率或检测器通过率。规则与案例冲突时以内容保真为准。

这些 SHA 标识审阅时的文件内容，不是仓库 commit。上表链接用于访问各上游仓库；本仓库不分发历史完整快照。此标准 Skill 包只保留一个 SKILL.md，避免宿主误将五个参考 Skill 注册为可执行技能。

上游版权声明和授权条款按原样保存在 licenses/。本版原始代码许可见根目录 LICENSE。引用不代表上游作者为本项目背书。

## v0.3 文章研究来源

100 篇具名媒体文章的标题、作者、出版信息、来源链与原文链接见 [媒体清单](evidence/corpus/media-sources.jsonl)。文章托管于人民日报电子报与新华网，部分为注明来源的转载；版权归相应权利人。个人署名不证明文章完全没有 AI 参与。

85 篇 AI 来源研究记录来自 [HeraldofLight/C-ReD](https://github.com/HeraldofLight/C-ReD)，固定 commit `b90072cd218b6ebdbd1d1478ce6e439677f18192`。本轮查看的固定仓库树未找到 LICENSE/LICENCE/COPYING 文件，不推定其文章可以再分发。生成身份依据发布者标签，非独立核验的生成日志。

分发内容仅含来源定位、哈希、统计、自写分析及原创合成测试，不含文章正文、CSV 或生成提示。研究元数据中的模型判断不代表来源作者、媒体或数据集发布者的观点，也不构成人工质量金标。研究方法和局限见 [RESEARCH.md](RESEARCH.md)。本项目 MIT 许可不扩展至上述第三方内容。
