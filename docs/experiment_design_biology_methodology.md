# ExperimentDesign 生物研究的方法细节策略

非人体生物研究默认允许 `FULL_METHODOLOGY_PLAN`。植物病理、微生物、动物模型、
遗传改造和非人体临床前研究的审核标记保留，但这些标记本身不再限制方法细节，
也不再导致测量、对照、分析、实验步骤或模板细节被恢复为受限默认内容。

人体参与信号（例如 `human_participants: true`、`human participant`、
`human subject`、`patient`、`clinical trial`、`volunteers`、`受试者`、
`志愿者`、`人体实验`）仍会触发
`RESTRICTED_HIGH_RISK_PLAN` 和 `BLOCKED_BY_RISK_REVIEW`。临床或健康学科标签
本身只添加专家、伦理和数据审核要求；是否限制方法细节取决于实际人体参与信号。
危险化学品、高压、高温和高能设备的独立方法限制继续生效。

方案生成与证据卡抽取采用相同策略。完整方法仍须区分来源证据、设计假设和
待补输入，不能虚构来源或观测结果。所有 ExperimentDesign 产物保持
`DESIGN_ONLY`，最终方法学、动物伦理、生物安全及设施审核要求仍保留。

例如，Chenopodium pallidicaule 植物免疫与病原系统课题中的 `pathogen`
会记录病原相关审核，但不会仅因这一关键词限制模型选择、筛选逻辑、测量、
对照或分析计划。若同一课题包含人体参与或独立危险条件，则仍按对应限制处理。

策略与提示词进入现有缓存身份：方案缓存包含 scope gate，证据卡缓存包含方法
策略和提示词摘要。更新后重新运行会使用新策略；旧产物不会自动改写，已运行的
进程需要重启才能加载新代码。
