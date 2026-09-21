# 直流网络校核器

一个用于直流电阻网络建模与校核的 Web 应用。前端为原生 HTML/CSS/JS，后端使用
**Python FastAPI + NumPy**，通过**改进节点分析（Modified Nodal Analysis, MNA）**
组装并求解线性方程。

## 功能

- 最多录入 **30 个节点**，以及电阻（R）、独立电流源（I）、独立电压源（V）三类元件，
  可指定任意节点为接地（电位 0 V）。
- 服务端组装 MNA 增广矩阵并求解，返回：
  - 各**节点电压**（含接地节点）；
  - 各**支路方向电流**（支路正方向取 `p → n`，负值时前端反色并标出实际方向）；
  - 全网**功率平衡**信息：总发出 / 总吸收功率、绝对与相对误差，达标时高亮“校核通过”。
- 对无法得到唯一解的网络**不崩溃**，而是区分并列出相关节点 / 元件：
  - **无接地**或接地节点不在节点表中；
  - **浮置子网**：与接地之间仅通过电流源连接（或完全悬空）的连通片，列出其中节点；
  - **理想电压源互相矛盾**：如不同电压的理想电压源并联，列出冲突元件。
- 前端提供三个示例一键载入（正常网络 / 浮置子网 / 电压源冲突）、表格化编辑、
  提交前输入校验、结果与问题行高亮。
- **单参数扫描**：从元件表选择一个元件，给出起值、止值与采样点数（2～101），
  后端在网络副本上逐点等间距替换该元件参数，复用同一套 MNA 求解与结构诊断。
  - 扫描**不会改写当前电路表**；单个采样点求解失败时保留该点的错误原因，
    不中断整次扫描（曲线在失败点处断开）。
  - 结果区用折线图展示指定**节点电压**或**支路电流**随参数的变化，
    图下逐点列出采样值、观测值与成功 / 失败状态。
  - 一次请求返回全部点的全部节点电压与支路电流，切换观测量 / 目标只做本地重绘，
    **不会重复请求**后端。
  - 非法范围（起值或止值不是有限数、起值与止值相同）、电阻起值或止值非正、
    采样点数不在 2～101、扫描元件不存在或编号重复等，均在前后端给出明确提示。
- **两节点端口等效（戴维南）**：从现有节点表选择两个不同节点作为端口的
  正端 `p` 与负端 `n`，后端分两阶段计算并返回：
  - **开路电压 V_oc**：直接求解原网络（端口不挂元件，天然开路），
    取 `V_oc = V(p) − V(n)`；
  - **等效电阻 R_eq**：在网络副本上将独立电压源置零（0 V，短路）、
    独立电流源置零（0 A，开路），再**从 n 向 p 注入 1 A 测试电流**
    （向 p 注入 +1 A、从 n 抽出 1 A），取 `R_eq = V(p) − V(n)`（Ω）。
  - 结果卡显示**端口方向（p → n）、开路电压与等效电阻**及等效电路说明；
    等效结果与接地节点的选择无关。
  - 任一步出现**浮置子网 / 电压源冲突 / 奇异 / 无接地**时，错误分组原样返回
    并带上 `stage`（`open_circuit` 或 `equivalent_resistance`）标记，
    前端按阶段展示，**不展示任何半截伪结果**。
  - 计算在网络副本上进行，不改写元件表；**节点表发生变更（增删 / 改名）后，
    旧的端口等效结果自动失效隐藏**，需重新计算。
- **元件敏感度分析**：求解成功后，选择一个**节点电压**或**支路电流**目标与
  **相对扰动比例**（0.01%～10%），后端对元件表中的**每个 R / I / V 元件**
  在两个独立的网络副本上分别施加 `p₀·(1±δ)` 的正负同幅相对扰动，复用同一套
  MNA 求解与结构诊断，以**中心差分**计算
  - 原始导数 `∂f/∂p ≈ (f₊ − f₋) / (2·p₀·δ)`；
  - **归一化敏感度** `S =（∂f/∂p）·（p/f₀）`（无量纲，>0 同向、<0 反向）。
  - 结果**按 |S| 从大到小排名**，逐元件列出正负扰动参数值、正负扰动目标值、
    导数与归一化敏感度；基准目标值为 0 时 S 无定义（记为 —），改按导数排序。
  - **基准网络求解失败**时整次请求返回 `422`（错误分组带
    `stage:"baseline"`）；**任一元件的任一扰动方向失败**（0 参数元件步长为 0、
    结构矛盾 / 奇异等）时，只把该元件标记为失败并保留带
    `stage:"perturbation"`、`side:"plus"/"minus"` 的结构化错误，
    **继续分析其它元件**。
  - 分析在**深拷贝**上进行，不改写元件表；**节点表发生变更后旧结果自动失效隐藏**。

## 元件方向约定

| 类型 | 参数含义 | 方向 / 极性 |
| ---- | -------- | ----------- |
| `R` 电阻 | 电阻值（Ω，> 0） | 支路正方向 `p → n` |
| `I` 电流源 | 电流（A） | 正值表示电流由 `p` 流向 `n` |
| `V` 电压源 | 电动势（V） | `p` 为正极、`n` 为负极，支路电流正方向 `p → n` |

支路功率按**关联参考方向**计算：`P = (V_p − V_n)·I`。`P > 0` 为吸收功率，
`P < 0` 为发出功率；全网吸收功率之和应接近 0。

## 快速启动

需要已安装 Docker（含 Compose 插件）。在项目根目录执行：

```bash
docker compose up --build
```

启动后用浏览器访问：

- **http://localhost:8000**

API：

- `GET  /api/meta`：容量与元件类型元信息（含 `sweep_min_points` /
  `sweep_max_points`，即 2 / 101，以及 `sensitivity_min_ratio` /
  `sensitivity_max_ratio`，即 0.0001 / 0.1）；
- `POST /api/solve`：请求体为网络 JSON（见下），成功返回 `200`，
  输入或结构问题返回 `422`，错误按 `no_ground / floating_subnet / voltage_conflict / validation`
  分组列出；
- `POST /api/sweep`：单参数扫描。请求体与 `/api/solve` 相同，另加一个 `sweep` 段
  （见下）；**扫描参数本身非法**（元件缺失 / 重复、范围非法、电阻范围含非正值、
  点数越界等）时整体返回 `422` 且错误码为 `sweep_validation`；扫描可以开始时
  恒返回 `200`，各采样点的失败以 `status: "error"` 内联在结果中，不影响其它点。
- `POST /api/thevenin`：两节点端口戴维南等效。请求体与 `/api/solve` 相同，
  另加一个 `port` 段（见下）。**端口参数本身非法**（缺少 `port` 段、端点不在
  节点表、p 与 n 相同等）时返回 `422` 且错误码为 `port_validation`；端口合法时，
  开路电压（`open_circuit`）或等效电阻（`equivalent_resistance`）任一阶段求解
  失败，同样返回 `422`，错误分组沿用 `/api/solve` 的
  `no_ground / floating_subnet / voltage_conflict / singular / validation` 编码，
  并额外带 `stage` 字段标明失败阶段；成功返回 `200`。
- `POST /api/sensitivity`：元件敏感度分析。请求体与 `/api/solve` 相同，另加一个
  `sensitivity` 段（见下）。**分析参数非法**（缺少 `sensitivity` 段、目标类型
  非 `voltage` / `current`、目标编号缺失、扰动比例不在 0.0001～0.1 等）时返回
  `422` 且错误码为 `sensitivity_validation`；**基准网络求解失败**同样返回 `422`，
  原错误分组带 `stage:"baseline"`。基准可解后恒返回 `200`：每个元件的正负扰动
  独立求解，单个元件失败以 `status:"error"` 内联在结果中（错误分组带
  `stage:"perturbation"` 与 `side:"plus"/"minus"`），**不影响其它元件**。

停止服务：

```bash
docker compose down
```

## 配置

- 容器内固定监听 **8000** 端口，compose 将宿主机同号端口映射进去。
  若宿主机 8000 被占用，可修改 `compose.yaml`：

  ```yaml
  ports:
    - "8080:8000"   # 宿主机端口:容器端口
  ```

- 无其它外部依赖：不使用数据库，数据只存在浏览器页面中，刷新即重置。

## 请求示例

```bash
curl -s -X POST http://localhost:8000/api/solve \
  -H 'Content-Type: application/json' \
  -d '{
    "ground": "0",
    "nodes": ["0", "1"],
    "elements": [
      {"id": "V1", "type": "V", "node_p": "1", "node_n": "0", "value": 10},
      {"id": "R1", "type": "R", "node_p": "1", "node_n": "0", "value": 10}
    ]
  }'
```

## 单参数扫描

### 页面操作

1. 按常规录入网络（可先“载入示例①”），在左下「单参数扫描」卡片的
   「扫描元件」下拉中选择元件表中的一个元件；
2. 填写**起值**、**止值**与**采样点数**（整数，2～101；电阻两端点都必须为正，
   起值与止值不能相同），点击「开始参数扫描」；
3. 右侧出现扫描结果：
   - 顶部下拉可在「节点电压 / 支路电流」之间切换，并选择具体节点 / 支路，
     折线图与明细表即时重绘，**不会重新发起请求**；
   - 折线仅连接成功点，失败采样点在图底以红色 ✕ 标出；
   - 下方明细表逐点给出扫描参数值、当前观测量数值与状态，失败点同时列出
     该点的错误原因（与 `/api/solve` 的错误分组一致）。

扫描期间元件表保持原样；修改电路后需重新点击「开始参数扫描」。

### 请求体与返回结构

在网络 JSON 中追加 `sweep` 段即可：

```bash
curl -s -X POST http://localhost:8000/api/sweep \
  -H 'Content-Type: application/json' \
  -d '{
    "ground": "0",
    "nodes": ["0", "1"],
    "elements": [
      {"id": "V1", "type": "V", "node_p": "1", "node_n": "0", "value": 10},
      {"id": "R1", "type": "R", "node_p": "1", "node_n": "0", "value": 10}
    ],
    "sweep": {"element_id": "R1", "start": 10, "end": 100, "points": 11}
  }'
```

返回（`200`）：

```json
{
  "ok": true,
  "sweep": {"element_id": "R1", "type": "R", "unit": "Ω",
            "start": 10.0, "end": 100.0, "points": 11},
  "nodes": ["0", "1"],
  "branches": [{"id": "V1", "type": "V", "node_p": "1", "node_n": "0"}, ...],
  "points": [
    {"index": 0, "value": 10.0, "status": "ok",
     "voltages": [0.0, 10.0], "currents": [-1.0, 1.0]},
    {"index": 5, "value": 55.0, "status": "error",
     "errors": [{"code": "...", "message": "...", "items": []}]}
  ]
}
```

- `points[].voltages` / `points[].currents` 分别与顶层 `nodes` / `branches`
  **按下标对齐**，因此前端切换观测量无需再次请求；失败点只有 `errors`，
  不含这两个数组。
- 当所有采样点都失败时（例如基准网络无接地），`nodes` / `branches`
  由请求体兜底推导，便于前端仍能切换查看目标。
- 扫描参数非法时返回 `422`：

```json
{"ok": false,
 "errors": [{"code": "sweep_validation",
             "message": "扫描参数未通过校验",
             "items": [{"ref": "采样点数", "detail": "采样点数必须在 2～101 之间（当前：102）"}]}]}
```

### 校验规则汇总

| 情形 | 处理 |
| ---- | ---- |
| 扫描元件为空 / 不在元件表 / 编号重复 | 拒绝成扫（`422 sweep_validation`） |
| 起值或止值不是有限实数 | 拒绝成扫 |
| 起值与止值相同 | 拒绝成扫 |
| 扫描电阻且起值或止值 ≤ 0（含跨零区间） | 拒绝成扫 |
| 采样点数不是整数或不在 2～101 | 拒绝成扫 |
| 基准网络或某个取值点结构矛盾 / 数值奇异 | 该点 `status:"error"` 并保留错误，其余点照常求解 |

## 两节点端口等效（戴维南）

### 页面操作

1. 按常规录入网络（可先“载入示例①”），在左下「两节点端口等效（戴维南）」卡片的
   两个下拉中分别选择端口**正端 p** 与**负端 n**（必须是节点表中两个不同节点）；
2. 点击「计算端口等效」，右侧结果卡显示：
   - **端口方向** `p → n`；
   - **开路电压 V_oc (V)**：原网络在该端口的开路电位差 `V(p) − V(n)`；
   - **等效电阻 R_eq (Ω)**：独立源全部置零后，从 n 向 p 注入 1 A 测试电流
     （电流方向 n→p，即向 p 注入 +1 A、从 n 抽出 1 A）
     得到的端口电位差 `V(p) − V(n)`；
   - 一行等效电路文字说明（理想电压源串联等效电阻）。
3. 开路或测试阶段任一阶段失败（无接地、浮置子网、电压源冲突、矩阵奇异）时，
   结果卡不出现，反馈面板按**阶段**（阶段 1 开路电压 / 阶段 2 等效电阻）
   展示与 `/api/solve` 一致的结构化错误，不会给出伪结果。
4. **节点表一旦变更**（添加 / 删除节点、修改节点编号、载入示例、清空），
   旧结果立即失效隐藏；仅修改元件参数 / 接地不影响已选端口，可直接重新计算。

### 请求体与返回结构

在网络 JSON 中追加 `port` 段：

```bash
curl -s -X POST http://localhost:8000/api/thevenin \
  -H 'Content-Type: application/json' \
  -d '{
    "ground": "0",
    "nodes": ["0", "1", "2"],
    "elements": [
      {"id": "V1", "type": "V", "node_p": "1", "node_n": "0", "value": 10},
      {"id": "R1", "type": "R", "node_p": "1", "node_n": "2", "value": 10},
      {"id": "R2", "type": "R", "node_p": "2", "node_n": "0", "value": 20}
    ],
    "port": {"node_p": "2", "node_n": "0"}
  }'
```

返回（`200`）：

```json
{
  "ok": true,
  "port": {"node_p": "2", "node_n": "0"},
  "open_circuit_voltage": 6.666666666666667,
  "equivalent_resistance": 6.666666666666664,
  "test_current": 1.0,
  "warnings": []
}
```

（上例：开路为 10 V 在 10 Ω + 20 Ω 上的分压 20/3 V；独立源置零后 V1 短路，
R_eq 为 10 Ω ∥ 20 Ω = 20/3 Ω。）

- 交换 p、n 会使 `open_circuit_voltage` 反号，`equivalent_resistance` 不变。
- 端口取在理想电压源两端时，`equivalent_resistance` 为 `0`。
- 计算在**深拷贝**上进行：原网络中的独立源数值不会被置零，1 A 测试电流源
  （内部编号 `__port_Itest__`，与用户元件撞号时自动避让）也不会残留在元件表中。
- 开路电压阶段的数值警告（如条件数过大）经 `warnings` 返回。

端口参数非法时返回 `422 port_validation`：

```json
{"ok": false,
 "errors": [{"code": "port_validation",
             "message": "端口参数未通过校验",
             "items": [{"ref": "2", "detail": "端口的 p、n 端必须选择不同节点（不能对同一节点取等效）"}]}]}
```

网络在某个阶段无唯一解时，错误分组与 `/api/solve` 完全相同，只是多了 `stage`：

```json
{"ok": false,
 "errors": [{"code": "floating_subnet",
             "stage": "open_circuit",
             "message": "检测到未通过电阻或电压源与接地节点连通的浮置子网……",
             "items": [{"nodes": ["2", "3"]}]}]}
```

### 校验 / 失败规则汇总

| 情形 | 处理 |
| ---- | ---- |
| 缺少 `port` 段 / p 或 n 为空 | 拒绝计算（`422 port_validation`） |
| p 或 n 不在节点表 | 拒绝计算（`port_validation`，指名缺失节点） |
| p 与 n 为同一节点 | 拒绝计算（`port_validation`） |
| 原网络无接地 / 浮置子网 / 电压源冲突 / 奇异 / 输入非法 | `422`，原错误分组 + `stage:"open_circuit"` |
| 置零加测试源后的网络无唯一解（防御性，正常无源网络应可解） | `422`，原错误分组 + `stage:"equivalent_resistance"` |

## 元件敏感度分析

### 页面操作

1. 先按常规录入网络并点击「校核求解」，求解成功后页面会记住节点电压 / 支路电流
   清单作为可选目标；
2. 在左下「元件敏感度分析」卡片中：
   - **目标量**选择「节点电压 (V)」或「支路电流 (A)」，并在相邻下拉中选择具体
     节点 / 支路；
   - 填写**相对扰动比例**（百分比，0.01%～10%，默认 1%）；
3. 点击「计算元件敏感度」，右侧结果表逐元件给出：
   - **排名**（按归一化敏感度绝对值从大到小，失败项无排名并排到末尾）；
   - 元件编号 / 类型 / 支路方向，以及基准参数 `p₀` 与 `＋δ / －δ` 后的参数值；
   - `＋δ / －δ` 两次扰动求解得到的目标值 `f₊ / f₋`；
   - 中心差分**导数 ∂f/∂p** 与**归一化敏感度 S**（带表示 |S| 相对大小的横条，
     负值反色，表示参数增大时目标反而减小）；
   - 成功 / 失败状态；失败元件逐项列出失败方向（＋δ / －δ）与结构化错误原因。
4. 基准目标值为 0（例如对接地节点求电压敏感度）时，归一化敏感度因除以 0 无定义，
   表中记为 —，并在表头提示“改按导数绝对值排序”。
5. **节点表一旦变更**（添加 / 删除节点、修改节点编号、载入示例、清空），旧结果
   立即失效隐藏，需重新求解后再分析；修改元件参数后也应先重新求解。

### 计算方法

对元件表中的每个元件（基准参数 `p₀`、目标基准值 `f₀`），在两个独立的网络
**深拷贝**上把该元件参数分别替换为 `p₀·(1−δ)` 与 `p₀·(1+δ)`，各自复用
`/api/solve` 的完整 MNA 求解与结构诊断，然后：

```
∂f/∂p ≈ (f₊ − f₋) / (2·p₀·δ)                 # 中心差分（二阶精度）
S     = (∂f/∂p) · (p₀ / f₀)                   # 归一化（对数）敏感度，无量纲
```

`S = 0.5` 表示该元件参数相对变化 1% 时，目标约同向变化 0.5%；`S = −2` 表示
参数增大 1% 时目标约减小 2%。中心差分的步长就是相对扰动比例 δ：δ 越小截断
误差通常越小，但过小会放大浮点舍入误差，故限制在 0.01%～10%。

### 请求体与返回结构

在网络 JSON 中追加 `sensitivity` 段（`ratio` 为小数：0.0001～0.1）：

```bash
curl -s -X POST http://localhost:8000/api/sensitivity \
  -H 'Content-Type: application/json' \
  -d '{
    "ground": "0",
    "nodes": ["0", "1", "2"],
    "elements": [
      {"id": "V1", "type": "V", "node_p": "1", "node_n": "0", "value": 10},
      {"id": "R1", "type": "R", "node_p": "1", "node_n": "2", "value": 10},
      {"id": "R2", "type": "R", "node_p": "2", "node_n": "0", "value": 20}
    ],
    "sensitivity": {"target": {"kind": "voltage", "id": "2"}, "ratio": 0.01}
  }'
```

返回（`200`，节选）：

```json
{
  "ok": true,
  "target": {"kind": "voltage", "id": "2"},
  "ratio": 0.01,
  "ratio_percent": 1.0,
  "target_base": 6.666666666666666,
  "ranking": "sensitivity",
  "counts": {"total": 3, "ok": 3, "error": 0},
  "elements": [
    {
      "element_id": "V1", "type": "V", "node_p": "1", "node_n": "0",
      "value": 10.0, "target_base": 6.666666666666666,
      "status": "ok", "rank": 1,
      "value_minus": 9.9, "value_plus": 10.1,
      "target_minus": 6.6, "target_plus": 6.733333333333333,
      "derivative": 0.6666666666666643,
      "sensitivity": 0.9999999999999966
    }
  ],
  "warnings": []
}
```

- `elements` 已按 `|sensitivity|` 降序排列（基准目标为 0 时按
  `|derivative|` 降序，`ranking` 字段相应为 `"derivative"`），失败元件沉底且
  `rank` 为 `null`。
- 成功元件含 `value_minus/value_plus`、`target_minus/target_plus`、
  `derivative`、`sensitivity`（基准目标为 0 时为 `null`）；失败元件不含
  `derivative / sensitivity`，改为携带 `errors`，例如 0 A 电流源：

```json
{
  "element_id": "I1", "type": "I", "status": "error", "rank": null,
  "value_minus": 0.0, "value_plus": 0.0,
  "target_minus": null, "target_plus": null,
  "errors": [{
    "code": "zero_parameter", "stage": "perturbation", "side": null,
    "message": "元件基准参数值为 0，相对扰动步长为 0，无法用中心差分计算敏感度",
    "items": [{"ref": "I1", "detail": "元件 I1 的基准参数为 0 A ……"}]
  }]
}
```

基准网络本身无唯一解时返回 `422`，错误分组与 `/api/solve` 相同但带
`stage:"baseline"`：

```json
{"ok": false,
 "errors": [{"code": "no_ground", "stage": "baseline",
             "message": "未指定接地节点：节点电压缺少参考点，无法求解", "items": []}]}
```

分析参数非法时返回 `422 sensitivity_validation`：

```json
{"ok": false,
 "errors": [{"code": "sensitivity_validation",
             "message": "敏感度分析参数未通过校验",
             "items": [{"ref": "扰动比例",
                        "detail": "相对扰动比例必须在 0.01%～10% 之间（当前：50%）"}]}]}
```

### 校验 / 失败规则汇总

| 情形 | 处理 |
| ---- | ---- |
| 缺少 `sensitivity` 段 / `target` 段 | 拒绝分析（`422 sensitivity_validation`） |
| 目标 `kind` 非 `voltage` / `current`，或目标编号为空 | 拒绝分析 |
| 扰动比例不是有限数或不在 0.0001～0.1（0.01%～10%） | 拒绝分析 |
| 基准网络无接地 / 浮置子网 / 电压源冲突 / 奇异 / 输入非法 | `422`，原错误分组 + `stage:"baseline"`，不做任何扰动 |
| 目标节点 / 支路不在基准求解结果中 | `422 sensitivity_validation` |
| 元件基准参数为 0（0 A / 0 V），相对扰动步长为 0 | 该元件 `status:"error"`（`zero_parameter`），其余元件照常 |
| 某元件 ＋δ 或 －δ 扰动求解失败 | 该元件失败，错误分组带 `stage:"perturbation"`、`side:"plus"/"minus"`，继续其它元件 |
| 基准目标值为 0 | 分析正常返回，`sensitivity` 为 `null`，按导数绝对值排序 |

## 本地开发（不使用 Docker）

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## 目录结构

```
.
├── app/
│   ├── main.py            # FastAPI 路由（/api/solve、/api/sweep、/api/thevenin、/api/sensitivity）与静态文件
│   ├── solver.py          # MNA 组装、结构诊断与求解
│   ├── sweep.py           # 单参数扫描：校验 + 逐点复用 solve
│   ├── thevenin.py        # 两节点端口戴维南等效：开路电压 + 置零注入测试电流
│   ├── sensitivity.py     # 元件敏感度：逐元件 ±δ 扰动 + 中心差分归一化敏感度
│   └── static/
│       ├── index.html     # 页面结构（含扫描、敏感度、端口等效表单与结果区）
│       ├── style.css      # 样式与高亮（含扫描曲线、敏感度、端口等效样式）
│       └── app.js         # 表格编辑、校验、单次求解、扫描 / 敏感度 / 端口等效交互
├── test_solver.py         # 求解器冒烟测试：python3 test_solver.py
├── test_sweep.py          # 扫描冒烟测试：python3 test_sweep.py
├── test_thevenin.py       # 端口等效冒烟测试：python3 test_thevenin.py
├── test_sensitivity.py    # 敏感度分析冒烟测试：python3 test_sensitivity.py
├── Dockerfile
├── compose.yaml
└── requirements.txt
```
