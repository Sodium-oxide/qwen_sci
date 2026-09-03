# B部分上下游接口需求与剩余差距说明

本文档给 A/C/D 三个部分对接使用。B 部分负责“电力方程与物理验证”，核心目标是：接收候选电力系统模型，转成统一 Equation IR，完成结构验证、数值验证、物理验证，并返回结构化 ValidationReport。

当前 B 部分已在 `part_b_xtl/` 下提供最小可运行版本，不调用 LLM。

---

## 1. B部分当前已完成内容

### 1.1 M02 电力系统本体 MVP

已完成文件：`power_b_ontology.py`

当前已包含 30+ 个核心变量/参数注册项，例如：

- `delta`：转子功角
- `omega`：转速
- `Pm`：机械功率
- `Pe`：电磁功率
- `H`：惯性常数
- `D`：阻尼系数
- `V/Vm`：电压幅值
- `theta/Va`：相角
- `P/Q`：有功/无功功率
- `P_load/Q_load`：负荷
- `P_gen/Q_gen`：发电
- `Ybus/G/B`：网络导纳相关量

每个变量包含：

- `name`
- `symbol`
- `unit`
- `per_unit`
- `coordinate`
- `role`
- `description`
- `dimension`

### 1.2 M04 Equation IR MVP

已完成文件：

- `power_b_equation_ir.py`
- `power_b_sympy_compiler.py`

当前支持：

- 变量引用 `VariableRef`
- 参数引用 `ParameterRef`
- 方程节点 `EquationNode`
- 候选模型 `CandidateModel`
- 方程中间表示 `EquationIR`
- 验证报告 `ValidationReport`
- 结构化错误 `ValidationError`
- 将 `d(delta)/dt`、`d(omega)/dt` 编译为内部符号
- 将 Equation IR 编译为 SymPy 残差表达式

### 1.3 M06 ANDES Adapter 壳子

已完成文件：`power_b_andes_adapter.py`

当前支持统一接口：

- `initialize(case_path)`
- `run(routine='TDS')`
- `extract(names)`

当前定位是适配层壳子：能检测 ANDES 是否可用，也能在初始化失败时返回结构化结果。完整仿真流程需要 C 部分提供标准 case 文件或 CaseManifest 后继续补齐。

### 1.4 M12 V1-V3 验证器 MVP

已完成文件：`power_b_validators.py`

当前实现：

- V1 结构验证：空方程、未知变量、ODE 左端不规范、简单单位不一致
- V2 数值验证：残差是否有限、残差范数是否超过阈值
- V3 物理验证：摆方程功率反项缺失、`Pe` 使用但无代数闭合、明显不稳定项初筛

当前已支持结构化错误码：

- `UNKNOWN_VARIABLE`
- `EMPTY_EQUATION_SET`
- `MISSING_DERIVATIVE_EQUATION`
- `UNIT_MISMATCH`
- `NONFINITE_RESIDUAL`
- `NUMERICAL_DIVERGENCE`
- `POWER_BALANCE_VIOLATION`
- `ALGEBRAIC_CLOSURE_MISSING`
- `EIGENVALUE_UNSTABLE`

### 1.5 SMIB 自检样例

已完成文件：

- `power_b_smib_examples.py`
- `power_b_selfcheck.py`

当前自检结果：

```text
[smib_correct] passed=True stage=physical
[smib_power_violation] passed=False stage=physical
  - POWER_BALANCE_VIOLATION
[smib_missing_closure] passed=False stage=physical
  - ALGEBRAIC_CLOSURE_MISSING
```

说明：B 部分当前已经具备最小演示能力：正确模型通过，错误模型被硬拒绝，并返回结构化报告。

---

## 2. 离要求还差什么

 B 部分的完整要求是：

> 对 SMIB 与 IEEE 9 节点，能自动判断“功率不守恒”或“代数闭合缺失”的候选模型并硬拒绝，且能生成带诊断的 ValidationReport。

当前距离完整要求还差以下内容。

### 2.1 变量注册表还需要扩展和统一命名

当前是 MVP 级变量表，已经覆盖摆方程和部分网络变量，但还需要和 A/C/D 统一：

- 变量命名到底用 `Vm/Va`，还是 `V/theta`
- 功率到底用 `Pe/Pm`，还是 `P_e/P_m`
- IEEE 9 多机变量如何编号，例如 `delta_g1`、`omega_g1`、`Vm_bus5`
- 标幺基准字段是否需要明确写 `S_base`、`V_base`、`omega_base`
- Lens 变换后单位字段如何保留

### 2.2 Equation IR 还不是最终契约版

当前 IR 是 B 部分自洽版本，能跑通自检，但还不是全队统一 Schema。

还缺：

- A 部分定义的正式 JSON Schema
- `EquationIR` 的 JSON 序列化/反序列化规范
- `CandidateModel` 从 D 部分传入时的字段约定
- `CaseManifest` 从 C 部分传入时的字段约定
- 方程 AST 更细粒度结构，目前表达式仍以字符串为主
- 代数变量、动态变量、观测变量、控制输入的正式区分

### 2.3 ANDES 适配层还没有接真实 case

当前 ANDES Adapter 是统一接口壳子，能导入 ANDES，能尝试加载 case 文件，但还没有和 C 部分的 B1/IEEE 9 真值库联调。

还缺：

- C 部分提供 ANDES 可加载的 SMIB/IEEE 9 case 文件路径
- C 部分提供 CaseManifest 到 ANDES case 的映射
- 统一仿真时间、步长、扰动设置、输出通道
- 仿真结果字段与变量注册表对齐

### 2.4 V2 数值验证还只是残差检查

当前 V2 能检查残差是否有限、残差范数是否过大，但还不是完整的电力系统数值验证。

还缺：

- 对仿真轨迹的误差评估
- 与 C 部分真值数据对齐的指标，例如 RMSE、MAE、最大偏差
- 拟合参数边界检查
- DAE 一致初值检查
- 仿真失败分类，例如初始化失败、积分发散、代数方程不收敛

### 2.5 V3 物理验证还需要增强

当前 V3 能识别最典型的功率反项缺失和代数闭合缺失，但还需要增强为论文级验证。

还缺：

- 严格功率平衡检查
- 能量函数/阻尼耗散检查
- 平衡点线性化与特征值分析
- 多机系统的网络约束检查
- IEEE 9 节点级别的潮流/动态一致性检查
- Lens 变换后单位与坐标一致性检查

### 2.6 IEEE 9 目前只是占位

当前 `power_b_ieee9_examples.py` 只是占位示例，不是完整 IEEE 9 验证。

还缺：

- IEEE 9 标准 CaseManifest
- IEEE 9 节点、支路、发电机、负荷字段
- IEEE 9 的 Ybus 或 ANDES case 文件
- 多机摆方程/网络代数方程
- IEEE 9 验证样例：正确模型、功率不守恒模型、代数闭合缺失模型

---

## 3. B部分需要 A 提供什么

A 部分负责科学内核与契约。B 部分需要 A 优先确定以下契约。

### 3.1 必需 Schema

A 需要提供正式 JSON Schema：

- `EquationIR`
- `CandidateModel`
- `CaseManifest`
- `LensSpec`
- `RunManifest`
- `ValidationReport`

B 当前已有 Python dataclass 版本，但最终应以 A 的 Schema 为准。

### 3.2 ValidationReport 标准字段

B 建议 A 将 `ValidationReport` 至少定义为：

```json
{
  "model_id": "string",
  "case_id": "string",
  "passed": true,
  "stage": "structure|numerical|physical",
  "errors": [
    {
      "code": "POWER_BALANCE_VIOLATION",
      "message": "string",
      "target": "string|null",
      "severity": "error|warning",
      "details": {}
    }
  ],
  "metrics": {},
  "artifacts": [],
  "created_at": "ISO-8601 string"
}
```

### 3.3 错误码枚举

A 需要统一错误码枚举，避免 B/D/C 各写各的。

B 建议第一批错误码：

- `UNKNOWN_VARIABLE`
- `UNIT_MISMATCH`
- `DIMENSION_MISMATCH`
- `MISSING_DERIVATIVE_EQUATION`
- `ALGEBRAIC_CLOSURE_MISSING`
- `POWER_BALANCE_VIOLATION`
- `INITIALIZATION_FAILED`
- `NUMERICAL_DIVERGENCE`
- `NONFINITE_RESIDUAL`
- `PARAMETER_OUT_OF_BOUNDS`
- `EIGENVALUE_UNSTABLE`
- `ENERGY_DISSIPATION_VIOLATION`

### 3.4 状态机对接点

A 的状态机需要告诉 B 在哪个阶段运行验证。

建议流程：

```text
CANDIDATE_PROPOSED
  -> B.V1_STRUCTURE_CHECK
  -> B.V2_NUMERICAL_CHECK
  -> B.V3_PHYSICAL_CHECK
  -> VALIDATION_ACCEPTED 或 VALIDATION_REJECTED
```

B 只返回结果，不决定全局状态跳转。

---

## 4. B部分需要 C 提供什么

C 部分负责数据透镜与基准案例。B 部分需要 C 提供可复算、带单位、带版本的算例数据。

### 4.1 CaseManifest

C 需要提供 B0/B1/B2 的 `CaseManifest`。

B 建议字段：

```json
{
  "case_id": "B1_SMIB_v1",
  "case_type": "B0|B1|B2",
  "system_name": "SMIB",
  "version": "1.0.0",
  "base": {
    "S_base_MVA": 100.0,
    "V_base_kV": 230.0,
    "frequency_Hz": 60.0
  },
  "files": {
    "andes_case": "cases/B1_SMIB/andes.xlsx",
    "truth_data": "cases/B1_SMIB/truth.parquet",
    "metadata": "cases/B1_SMIB/metadata.json"
  },
  "variables": [
    {
      "name": "delta",
      "unit": "rad",
      "coordinate": "generator",
      "sampling_rate_Hz": 100
    }
  ],
  "events": [],
  "expected_checks": ["power_balance", "algebraic_closure"]
}
```

### 4.2 Lens 输出数据

C 的 Lens 变换后，必须保留：

- 原始变量名
- 单位
- 坐标系
- 采样率
- 噪声强度
- 是否归一化/标幺化
- 变换矩阵或变换记录
- 随机种子

B 需要这些字段做 V3 物理验证，否则 Lens 变换后无法判断功率平衡是否仍成立。

### 4.3 真值数据

C 需要至少提供：

- B0 摆方程真值轨迹
- B1 SMIB 真值轨迹
- B2 IEEE 9 真值轨迹或 ANDES case
- 每个案例对应的平衡点参数
- 每个案例对应的合理参数范围

### 4.4 隐藏评估接口

如果 C 要做隐藏评估器，B 只需要暴露：

```python
validate_candidate_model(candidate_model, case_manifest, lens_spec) -> ValidationReport
```

C 不需要把真值方程暴露给 D，但需要给 B 足够的 case 元数据做验证。

---

## 5. B部分需要 D 提供什么

D 部分负责发现算法与拟合执行。B 需要 D 不要传自然语言模型描述，而要传结构化 `CandidateModel`。

### 5.1 CandidateModel 最小字段

D 传给 B 的候选模型至少包含：

```json
{
  "candidate_id": "sindy_pi_smib_001",
  "model_name": "SMIB candidate from SINDy-PI",
  "source": "known_structure_fit|sindy_pi|manual_baseline",
  "variables": [
    {"name": "delta", "unit": "rad"},
    {"name": "omega", "unit": "pu"}
  ],
  "parameters": [
    {"name": "H", "value": 3.5, "unit": "s"},
    {"name": "D", "value": 0.1, "unit": "pu"}
  ],
  "equations": [
    {
      "kind": "ode",
      "lhs": "d(delta)/dt",
      "rhs": "omega_b * (omega - 1)",
      "unit": "rate"
    },
    {
      "kind": "ode",
      "lhs": "d(omega)/dt",
      "rhs": "(Pm - Pe - D*(omega - 1)) / (2*H)",
      "unit": "rate"
    }
  ],
  "fit_metadata": {
    "training_lens": "lens_high_quality",
    "fit_loss": 0.001,
    "optimizer": "least_squares"
  }
}
```

### 5.2 D 必须接收 B 的错误码

D 收到 B 的 `ValidationReport` 后，应按错误码处理：

- `UNKNOWN_VARIABLE`：候选模型用了本体里不存在的变量，需要改名或注册变量
- `UNIT_MISMATCH`：单位不一致，不能继续拟合
- `ALGEBRAIC_CLOSURE_MISSING`：缺少代数闭合方程，需要补网络/功率表达式
- `POWER_BALANCE_VIOLATION`：摆方程缺少功率反项，候选模型应淘汰或重生成
- `NUMERICAL_DIVERGENCE`：数值残差过大，需要重新拟合或换初值
- `EIGENVALUE_UNSTABLE`：局部稳定性不合理，需要检查符号或参数

D 和 B 之间不要用自然语言传“这个模型不太对”。必须用错误码驱动修复。

---

## 6. B对外建议统一函数接口

B 对 A/C/D 暴露一个主入口：

```python
validate_candidate_model(candidate_model, case_manifest=None, lens_spec=None, context=None) -> ValidationReport
```

当前 MVP 版本已经有：

```python
validate_candidate_model(candidate, context=None, sample_points=None) -> ValidationReport
```

后续要扩展为兼容 A/C 的正式契约。

---

## 7. B部分当前测试方法

在父目录运行：

```powershell
cd E:\Projects\oneyear_project\qwen_ai_scientist_new\ai_scientist_qwen
python -m part_b_xtl.power_b_selfcheck
```

期望输出：

```text
[smib_correct] passed=True stage=physical
[smib_power_violation] passed=False stage=physical
  - POWER_BALANCE_VIOLATION
[smib_missing_closure] passed=False stage=physical
  - ALGEBRAIC_CLOSURE_MISSING
```

---

## 8. 下一步建议优先级

### P0：先和 A 对齐契约

必须先确定：

- `CandidateModel` Schema
- `EquationIR` Schema
- `ValidationReport` Schema
- 错误码枚举

否则 B/C/D 很容易各自写一套格式，后面联调会非常痛苦。

### P1：接 C 的 B0/B1 数据

先不要急着完整 IEEE 9。建议先联调：

```text
C 的 B0/B1 CaseManifest
  -> D 的已知结构拟合/SINDy-PI CandidateModel
  -> B 的 V1/V2/V3 ValidationReport
  -> A 的状态机记录结果
```

### P2：补完整 IEEE 9

等 B0/SMIB 跑通后，再补：

- IEEE 9 CaseManifest
- ANDES case 载入
- 多机变量编号
- 网络代数方程
- 特征值验证
- 跨 Lens 结构漂移验证

---

## 9. 给队长的简短状态汇报

B 部分当前已经完成 MVP：变量注册表、Equation IR、SymPy 残差编译、V1/V2/V3 验证器、SMIB 正确/错误样例、自检脚本和 ANDES Adapter 壳子。当前能对 SMIB 摆方程识别功率反项缺失和代数闭合缺失，并返回结构化 ValidationReport。

距离完整验收还差：A 的正式 Schema、C 的 B0/B1/B2 CaseManifest 与真值数据、D 的 CandidateModel 输入格式、真实 ANDES case 联调、IEEE 9 完整网络方程和更严格的 V3 物理验证。
