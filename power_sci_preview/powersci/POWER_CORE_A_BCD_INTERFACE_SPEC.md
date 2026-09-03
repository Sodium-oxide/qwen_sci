# A 部分与 B/C/D 的统一接口说明

版本：2026-08-26（基于 `ai_scientist_qwen-B_part.zip` 实际代码核对）  
维护方：A 部分（M00、M01、M15、M17）

## 1. 结论

A 的原有 v1 契约、B0 无 LLM 垂直切片和状态机继续保留，不做破坏性修改。跨组联调使用新增的版本化契约。任何跨组数据必须先通过 A 的 JSON Schema 和语义校验，不传递任意字典。

B 分支中的说明文档只作为接口需求来源，不自动视为代码修改命令。本次适配以 B 分支真实 Python 类型和真实验证函数为准：

- 输入：`CandidateModel`，内部包含 `VariableRef`、`ParameterRef`、`EquationNode`；
- 入口：`part_b_xtl.validate_candidate_model(candidate, context=None, sample_points=None)`；
- 输出：B 自己的 `ValidationReport`；
- A 负责将公共 JSON 契约转换为上述对象，并将 B 报告规范化、校验和落盘；
- B 不得直接推进 A 的全局状态机。

## 2. 公共契约

| 公共名称 | `schema_version` | 发送方 → 接收方 | 用途 |
|---|---|---|---|
| `CandidateModelV1` | `candidate_model_v1` | D → A → B | 候选模型、变量、参数、字符串方程和固定拟合元数据 |
| `EquationIRV2` | `equation_ir_v2` | B → A，或 D → A → B | 可持久化 AST、单位、量纲、坐标和绝对量/偏差量语义 |
| `CaseManifestV2` | `case_manifest_v2` | C → A → B/D | B0/B1/B2 算例、基准值、变量、事件、资源和预期验证项 |
| `LensSpecV2` | `lens_spec_v2` | C → A → B/D | 确定性数据透镜；强制保留单位、坐标和参考量语义 |
| `TaskEnvelopeV2` | `task_envelope_v2` | A → B | 冻结协议后的候选验证任务和输入产物引用 |
| `ValidationReportV2` | `validation_report_v2` | B → A → D | 完整 V1/V2/V3 结果、哈希、硬拒绝结论和结构化错误 |
| `StructuredErrorV2` | `structured_error_v2` | B/A → D | 机器可处理错误；禁止仅返回自然语言 |
| `RunManifest` | `run_manifest_v1` | A → 全组 | 一次运行的输入、输出及冻结协议哈希 |

Schema 文件位于 `power_core_a/schemas/`，注册名必须使用表中“公共名称”，不能直接拿 `schema_version` 当注册名。

旧名称 `EquationIR`、`CaseManifest`、`LensSpec`、`ValidationReport`、`TaskEnvelope` 和 `StructuredError` 仍表示 v1，供已有 B0 验收和兼容代码使用。

## 3. 必须统一的电力语义

B 当前 SMIB 示例把 `omega` 定义为绝对标幺转速，稳态值为 `1.0 pu`：

```text
d(delta)/dt = omega_b * (omega - 1)
```

A 原 B0 固定样例把 `omega` 定义为转速偏差，稳态值为 `0.0 pu`：

```text
d(delta)/dt = omega_b * omega
```

两者都可成立，但不能混用。因此公共变量必须携带：

- `unit`：物理单位；
- `coordinate`：坐标/物理位置语义；
- `reference_mode`：`ABSOLUTE`、`DEVIATION` 或 `NOT_APPLICABLE`；
- 当 `reference_mode=ABSOLUTE` 时必须有 `nominal_value`。

A 的适配器不会按变量名猜测这些字段。C 提供算例和透镜时必须保留它们，D 生成候选时必须继承它们，B 做物理验证时必须按它们解释方程。

## 4. 标准联调数据流

1. A 的全局状态机先完成 `BRIEF_DRAFT → ... → PROTOCOL_FROZEN`。
2. C 提交 `CaseManifestV2`、`LensSpecV2` 及其引用的数据产物；A 校验并存入 M15。
3. D 提交 `CandidateModelV1`；A 校验并存入 M15。
4. A 创建 `TaskEnvelopeV2(task_type=VALIDATE_CANDIDATE, target_module=M12)`。
5. A 适配器将严格契约转换成 B 当前 dataclass 图；开放的 B `metadata` 不跨越接口。
6. B 将候选编译成其内部 `EquationIR`，执行结构、数值、物理验证，返回结构化错误码。
7. A 将 B 结果规范化为 `ValidationReportV2`，再次校验并追加写入 M15。
8. D 只根据 `errors[].code` 修复或淘汰候选；自然语言 `message` 仅用于诊断展示。
9. A 在组装最终 Result Bundle 时，将候选、任务和验证报告描述符加入 `RunManifest.output_artifacts`，不覆盖任何旧版本。

候选验证是冻结协议后的子流程，不新增全局终态。B/C/D 都不得直接修改 A 的状态日志。

## 5. B 同学接入方法

合并时应保证仓库根目录可直接导入：

```python
import part_b_xtl
```

A 的真实调用入口为：

```python
from power_core_a.validation_workflow import run_part_b_candidate_validation

result = run_part_b_candidate_validation(
    store_root=store_path,
    run_id="run-smib-001",
    current_state="PROTOCOL_FROZEN",
    candidate_contract=candidate_json,
    case_manifest=case_json,
    lens_spec=lens_json,
    part_b_api=part_b_xtl,
    created_at="2026-08-26T08:00:00Z",
)
```

结果中的 `candidate`、`case`、`lens`、`task`、`validation_report` 都是已校验且带内容哈希的 ArtifactDescriptor。相同 `run_id + candidate_id + 相同输入` 再次执行会从 M15 恢复，`resumed=True`，不会重复调用 B。

B 当前代码有一个需要后续修正但不阻塞本次接入的执行顺序：`validate_candidate_model` 在数值采样前先做物理预检查。因此若物理预检查失败，A 会如实记录 `V1=PASS, V2=NOT_RUN, V3=FAIL`，不会虚构 V2 已通过。建议 B 最终将执行顺序固定为 V1 → V2 → V3，并在报告中直接返回三个阶段的明细。

## 6. C 同学必须提供的内容

- `CaseManifestV2` 中每个变量的单位、坐标、参考模式和归一化方式；
- 系统基准 `s_base_mva`、`frequency_hz`；
- 事件发生时间必须落在 `time_domain` 内；
- 资源必须有 SHA-256 内容哈希；
- `LensSpecV2` 的变换顺序从 0 连续递增；
- 噪声必须明确 `noise_std` 和 `noise_unit`；
- 单位、坐标、绝对量/偏差量元数据在 Lens 后必须保留；
- 随机变换必须带固定 `seed`。

C 不向 B 发送未登记列名，也不把经过标准化的数据冒充物理量。

## 7. D 同学必须提供和处理的内容

D 提交 `CandidateModelV1`，其中：

- `source` 只能是 `KNOWN_STRUCTURE_FIT`、`SINDY_PI`、`MANUAL_BASELINE`、`OTHER`；
- 方程类型只能是 `ode`、`algebraic`、`residual`；
- ODE 左端采用 `d(name)/dt`；
- 变量名、参数名不能重名；
- `fit_metadata` 使用固定字段，不能塞任意字典；
- 参数、变量和方程必须带单位；
- 变量的坐标和参考模式必须来自 C/公共 IR，不能自行猜测。

D 必须处理以下结构化错误码：

```text
UNKNOWN_VARIABLE
EMPTY_EQUATION_SET
UNIT_MISMATCH
DIMENSION_MISMATCH
MISSING_DERIVATIVE_EQUATION
STRUCTURE_INVALID
ALGEBRAIC_CLOSURE_MISSING
POWER_BALANCE_VIOLATION
INITIALIZATION_FAILED
NUMERICAL_DIVERGENCE
NONFINITE_RESIDUAL
PARAMETER_OUT_OF_BOUNDS
EIGENVALUE_UNSTABLE
ENERGY_DISSIPATION_VIOLATION
```

未知的 B 错误码会由 A 映射为 `INTERNAL_ERROR`，原始码保存在 `diagnostics`，结论为 `BLOCKED` 而不是错误地硬拒绝科学模型。

## 8. 依赖与环境责任

A 的离线契约、状态机、Artifact Store 和 B0 验收仍只使用 A 自己的轻量依赖，不需要 Qwen、API Key、ANDES、pandapower 或 LaTeX。

真实调用 B 代码的联调环境需要安装 B 的依赖。根据 B 分支实际源码：

- 候选编译/当前 V1-V3 入口至少直接需要 `sympy` 和 `numpy`；
- M06 ANDES 适配器及完整电力仿真再安装 B 的 `docker/requirements-power.txt`；
- B 的 requirements 当前没有显式列出源码直接导入的 `sympy`，建议 B 补为直接依赖，不能只依赖传递安装。

A 不保存、读取或要求 Qwen/文献检索 API Key。密钥不得写入契约、测试、日志或 GitHub。

## 9. 验证命令

A 的全量测试：

```powershell
python -m pytest tests_power_core_a -q -p no:cacheprovider
```

该测试覆盖：

- 20 份 Schema 自校验；
- 原有 B0 无 LLM Result Bundle 验收；
- B dataclass 的精确边界适配；
- `omega` 参考模式缺失时硬拒绝；
- B 物理错误映射为 V3 结构化硬拒绝；
- 候选验证产物落盘、哈希校验和断点恢复；
- `PROTOCOL_FROZEN` 前禁止调用 B。

当前仓库测试使用与 B 真实签名完全一致的轻量 test double，因此不会强迫只开发 A 的成员安装整套电力环境。合并 B 分支后，再在 B 的依赖环境运行一次上面第 5 节的真实 smoke test。

## 10. 可直接发给 B/C/D 的简短通知

> A 已发布版本化公共契约和 M15 接口。D 请按 `CandidateModelV1` 提交候选；C 请按 `CaseManifestV2/LensSpecV2` 保留单位、坐标、归一化及 ABSOLUTE/DEVIATION 语义；B 保持 `part_b_xtl.validate_candidate_model` 入口并返回结构化错误。所有输入先由 A 校验并以 ArtifactDescriptor 传递，B/C/D 不直接改全局状态或传任意 dict。完整字段、错误码、调用示例和测试命令见 `POWER_CORE_A_BCD_INTERFACE_SPEC.md`。
