# 量化参数证据工作流

本工作流为独立的 `Q1/Q2` 数学建模与数值仿真支线服务。它不修改
`idea_result_v5`，不改变 `ExperimentDesign` 的主线输入；只有主线完成
`ExperimentDesign` 后，量化支线才允许物化模型。它只向 Author 提供合格数值
仿真结果、参数来源摘要和必要的迭代谱系。

## 运行前配置

在本机 `.env` 中配置学术资料发现所需的凭据：

```dotenv
OPENALEX_API_KEY=
OPENALEX_EMAIL=
UNPAYWALL_EMAIL=
SEMANTIC_SCHOLAR_API_KEY=
```

`OPENALEX` 和 `Semantic Scholar` 只用于发现与元数据交叉核验；它们的搜索
结果、摘要和网页片段不能直接成为数值参数。`Unpaywall` 仅定位 DOI 对应的
合法开放获取位置。API key 不写入工作流 JSON、日志、PDF 或 Author handoff。

## 标准命令序列

以下 `<RUN>` 是已有 science run 目录，`<IDEAS_MANIFEST>` 是该 run 已验证的
`quantitative_ideas_manifest.json`。

如果要在同一个命令中先完成 Survey → Idea → ExperimentDesign，并暂停 Author
等待量化支线，使用：

```powershell
python -m src.cli science `
  --topic "<TOPIC>" `
  --discipline-id <DISCIPLINE_ID> `
  --allow-quantitative-modeling `
  --defer-author `
  --until author
```

这里的 `--allow-quantitative-modeling` 把量化模式设为 `required`。当前命令中
显式保留 `--defer-author` 以表达暂停意图；即使省略它，只要是新建 run 且目标
为 `author`，系统也会在 `ExperimentDesign` 完成后自动暂停，不会在量化 handoff
之前生成主 Author。普通 `--quantitative-mode optional` 不触发这个暂停。

量化支线完成并生成 handoff 后，再恢复主线：

```powershell
python -m src.cli science `
  --resume <RUN> `
  --until author
```

如果 sidecar 已明确记录 `NO_ELIGIBLE_IDEAS`，required 模式允许这次恢复直接
进入 Author；只要存在一个 Q1/Q2 候选，就必须先完成全部候选的终版、独立数学
建模 PDF 和 Author handoff。

主线必须先完成 `ExperimentDesign`。可以用下面的命令查看独立支线状态；它会
从已验证产物重建状态，因此中断后可继续：

```powershell
python -m src.cli quantitative status --run-dir <RUN>
python -m src.cli quantitative continue --run-dir <RUN>
```

如果希望由一个可暂停的高层入口负责恢复量化支线，并在 handoff 完成后自动
回接 Science Author，可以使用：

```powershell
python -m src.cli science `
  --resume <RUN> `
  --continue-quantitative `
  --until author
```

该入口会在安全边界内连续推进 sidecar 恢复、ExperimentDesign 补跑、blueprint、
获批参数后的模型物化、数学建模 PDF 发布和 Author handoff；遇到参数证据发现、
人工候选选择、参数批准、仿真执行、结果合格化或 v1/v2 修订接受时立即返回，
并在 `quantitative_state.next_actions` 给出下一条命令。它绝不会代替用户加入
`--execute --plan-identity`，也不会自动接受参数或修订决定。

对于历史上已经完成 `Idea`、但当时没有启用量化模式的 run，可以从已有 Idea
直接启动量化支线。该命令不会重跑 Survey 或已完成的 Idea；如果
`ExperimentDesign` 尚未完成，它只会先把主线续跑到 `exp_design`，随后在原 Idea
attempt 目录生成独立的 `quantitative_ideas.json` 和
`quantitative_ideas_manifest.json`。这两个文件生成后，命令返回正常的量化状态机
边界，下一步通常是生成 blueprint：

```powershell
python -m src.cli quantitative resume-from-idea `
  --run-dir <RUN> `
  --config src/config/default.yaml

python -m src.cli quantitative continue `
  --run-dir <RUN> `
  --config src/config/default.yaml
```

`resume-from-idea` 要求已有 Idea manifest 可验证，并且不会覆盖已存在的量化
sidecar；如果发现不完整或不可信的同名文件，会停止并要求人工处理。它同样不
执行参数联网检索、参数批准或数值仿真；每次仿真仍必须单独使用显式
`--execute --plan-identity`。

`continue` 每次只推进一个不涉及求解器执行的安全动作（生成蓝图、在参数获批
后物化模型、发布 PDF 或生成 Author handoff）。遇到参数检索、候选选择、参数
批准、结果合格化、修订接受或最终化时会返回 `next_actions`，这些步骤仍需要
用户显式执行。遇到仿真时只返回精确 `plan_identity`，不会代替用户添加
`--execute`。

```powershell
# 1. 让 LLM 定义符号模型、参数、单位、适用条件和检索式；不产生参数数值。
python -m src.cli quantitative blueprint `
  --run-dir <RUN> `
  --quantitative-ideas-manifest <IDEAS_MANIFEST> `
  --idea-id Q1 --version 0

# 2. 显式授权学术元数据检索。此命令不执行数值仿真。
python -m src.cli quantitative parameters discover `
  --run-dir <RUN> --idea-id Q1 --version 0 --fetch

# 3. 显式授权下载提供方声明为开放获取的 PDF；不会绕过订阅、登录或付费墙。
python -m src.cli quantitative parameters fetch-fulltext `
  --run-dir <RUN> --idea-id Q1 --version 0 --fetch

# 4a. 可选：把用户明确提供的 PDF/TXT/MD/CSV 纳入受控证据树。
python -m src.cli quantitative parameters import-document `
  --run-dir <RUN> --idea-id Q1 --version 0 `
  --document <LOCAL_DOCUMENT> --document-id UPD-001 `
  --title "Source title" --doi "" --year 2026

# 4b. 从一个已受控的文档抽取候选值。文中 quote 必须真实存在才会被接受。
python -m src.cli quantitative parameters extract `
  --run-dir <RUN> --idea-id Q1 --version 0 --document-id UPD-001
```

当全文清单中有多篇相互独立的论文时，可以批量并行抽取。每个文档使用独立的
模型请求；科学运行锁只在读取清单和提交结果时持有，因此不会把远程 LLM 调用
串行化。候选 ID 在提交阶段重新分配，多个 worker 不会产生重复 ID：

```powershell
python -m src.cli quantitative parameters extract-batch `
  --run-dir <RUN> --idea-id Q1 --version 0 `
  --document-ids PFD-001,PFD-002,PFD-003 --workers 3

# 或处理全文清单及用户导入目录中的全部受控文档
python -m src.cli quantitative parameters extract-batch `
  --run-dir <RUN> --idea-id Q1 --version 0 --all --workers 3
```

抽取器先按参数符号、含义、单位、适用条件和检索词定位页面，只向模型发送命中
页面及少量前后文，而不是整篇 PDF；没有任何命中时会直接写入空候选集合，不
调用模型。页面文本按文档 SHA-256 缓存，后续重试会复用解析结果。默认的
`extraction_workers=3`、`fulltext_workers=4`、`fulltext_per_host_concurrency=2`、
每参数最多三个页面片段和 6000 字符上下文都可在
`quantitative_modeling.parameter_evidence` 中调整；`minimum_keyword_hits` 可提高
局部检索门槛（默认 `minimum_keyword_hits=2`）以减少常见词误命中。并发数应
全文下载默认每篇最多尝试两个声明的 PDF URL，并对临时 HTTP 失败重试一次。并发数应
结合模型服务和学术提供方的速率限制设置；并行不会绕过人工候选审阅、参数批准
或仿真执行授权。

若模型注册表声明支持原生 JSON Schema，抽取请求会优先使用严格的
`quantitative_parameter_evidence` schema；不支持时自动退回 `json_object`，并仍
由本地契约、单位检查和原文 quote 校验兜底。章节窗口和结构化 LLM 响应分别按
窗口内容与 prompt/model identity 缓存，缓存损坏只会触发重新计算，不会改变证据
边界。

抽取后的候选会保存在：

```text
<RUN>/quantitative/Q1/parameter_evidence/v0/extractions/extract-001.json
```

每一个候选都必须有数值、目标单位、适用条件、不确定性、来源类型、来源文件、
页面/表格/章节定位和原文 quote。模型要求的适用条件（例如 `temperature_K`、
材料成分、几何尺度）缺失时，候选不可被批准。

## 人工审阅与批准

候选不会被系统自动选为模型参数。审阅者创建显式选择 JSON；候选型选择的
`selected_value` 若提供，必须严格等于候选已抽取的 `normalized_value`。

```powershell
python -m src.cli quantitative parameters propose `
  --run-dir <RUN> --idea-id Q1 --version 0 `
  --selections-json '[
    {
      "parameter_id": "k",
      "candidate_id": "PEC-Q1-k-001",
      "selection_rationale": "Temperature and material conditions match the baseline."
    }
  ]'

# 审阅 proposal 后才可冻结参数集；本命令不会启动仿真。
python -m src.cli quantitative parameters approve `
  --run-dir <RUN> --idea-id Q1 --version 0 --approve
```

输出的 `approved_parameter_set.json` 和
`approved_parameter_set_manifest.json` 是不可变的。它们的 identity 覆盖数值、
单位、条件、不确定性、转换、来源定位和选择理由。`MODEL_ASSUMPTION` 只在
蓝图明确允许时可用，并在 PDF 与 Author 中明确标记为非文献/非实测参数。

## 模型物化与仿真

只有参数集获批后才能生成带数值的 MathIR：

```powershell
python -m src.cli quantitative materialize `
  --run-dir <RUN> `
  --quantitative-ideas-manifest <IDEAS_MANIFEST> `
  --idea-id Q1 --version 0
```

物化会拒绝以下情况：

- `MathIR.parameters` 漏少、增加或改写任何获批参数；
- 参数集、模型蓝图、谱系或版本不匹配；
- 非 `SCENARIO_INPUT` 参数出现在情景 override 中；
- 参数集 manifest 与内容 hash 不匹配。

物化后的 `simulation_run_plan.json` 绑定 `parameter_set_identity`。参数、条件、
模型或情景任一改变都会改变 `plan_identity`。每一轮数值仿真仍需重新显式授权：

```powershell
python -m src.cli quantitative simulate `
  --run-dir <RUN> --idea-id Q1 --version 0 `
  --execute --plan-identity <EXACT_PLAN_IDENTITY>
```

LLM 不会获得运行任意 Python、shell 或 notebook 的权限。仿真仅使用受审计的
MathIR 和固定求解器适配器。

## v1/v2 迭代

每个 Q 最多从 `v0` 迭代到 `v2`。合格仿真结果生成 refinement proposal 后，必须
先显式接受：

```powershell
python -m src.cli quantitative propose-refinement ...
python -m src.cli quantitative accept-revision --run-dir <RUN> --idea-id Q1 --parent-version 0 --accept
```

新版本的 `hypothesis_delta`、`model_delta`、
`parameter_or_boundary_delta`、预期区分结果和证伪条件会注入下一版蓝图和模型
提示词。若模型、参数或边界变化，新增/改变的参数需要重新发现、抽取、审阅和
批准，并使用新的 `--execute --plan-identity`。这不会回写 `idea_result_v5`。

## 发布与 Author

完成 `qualify` 与 `finalize` 后，`publish` 生成独立的数学建模 PDF。其
`Parameter Provenance and Applicability` 章节包含参数集 identity、来源状态、
定位、适用条件、不确定性和模型假设披露。随后 `author-handoff` 只传递：

- `NUMERICAL_SIMULATION / SIMULATED / NOT_EMPIRICAL` 的合格终版结果；
- 压缩参数来源摘要；
- 全部必要的 v0→v1→v2 结果谱系（包括非正向结果）。

旧的 `quantitative model` 命令为兼容历史产物保留，生成内容会标记为
`LEGACY_INLINE_ASSUMPTIONS`。新研究应使用本页的 `blueprint → parameters →
materialize` 路径。

数模支线完成 handoff 后，使用主线恢复命令把它 late-bind 到 Author。若 run 的
Author 需要正式主文章 PDF，命令会自动生成只包含两份正式 PDF 引用的 bundle
manifest，不会合并两个 PDF：

```powershell
python -m src.cli science `
  --resume <RUN> `
  --quantitative-handoff-manifest <RUN>/quantitative/author/quantitative_author_handoff_manifest.json `
  --until author
```

该命令会校验 handoff manifest、数学建模 PDF、Author 文档中的数值仿真披露，
并将两个 PDF 绑定到：

```text
<RUN>/quantitative/publication/publication_bundle_manifest.json
```
