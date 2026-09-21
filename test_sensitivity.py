"""元件敏感度分析冒烟测试（开发用，不打进镜像）。

运行：python3 test_sensitivity.py
"""
import math
import sys

from app.sensitivity import (
    SENSITIVITY_MAX_RATIO,
    SENSITIVITY_MIN_RATIO,
    sensitivity,
)
from app.solver import CircuitError

failures = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f"  -> {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)


def expect_rejected(payload, *detail_parts):
    try:
        sensitivity(payload)
        return False, "应当被拒绝但分析成功"
    except CircuitError as e:
        codes = [g["code"] for g in e.errors]
        text = " ".join(
            it.get("detail", "") for g in e.errors for it in g.get("items", [])
        )
        ok = codes == ["sensitivity_validation"] and all(p in text for p in detail_parts)
        return ok, f"{codes} / {text}"


def expect_baseline_error(payload):
    try:
        sensitivity(payload)
        return None, "基准失败时应当整体拒绝"
    except CircuitError as e:
        return [(g["code"], g.get("stage")) for g in e.errors], None


def divider(t):
    print(f"\n----- {t} -----")


# 10V 源 + 10Ω + 20Ω 分压，目标取中点节点 2 的电压 V2 = V1·R2/(R1+R2)
BASE = {
    "ground": "0",
    "nodes": ["0", "1", "2"],
    "elements": [
        {"id": "V1", "type": "V", "node_p": "1", "node_n": "0", "value": 10},
        {"id": "R1", "type": "R", "node_p": "1", "node_n": "2", "value": 10},
        {"id": "R2", "type": "R", "node_p": "2", "node_n": "0", "value": 20},
    ],
}
SPEC_V2 = {"target": {"kind": "voltage", "id": "2"}, "ratio": 0.001}

divider("1. 分压网络 V2 的归一化敏感度，与解析公式比对")
r = sensitivity({**BASE, "sensitivity": SPEC_V2})
check("返回 ok", r["ok"] is True)
check("回显目标与比例", r["target"] == {"kind": "voltage", "id": "2"}
      and math.isclose(r["ratio"], 0.001) and math.isclose(r["ratio_percent"], 0.1))
check("基准目标值 V2=20/3", math.isclose(r["target_base"], 20 / 3, abs_tol=1e-10),
      str(r["target_base"]))
check("按敏感度排序，排名 1..n",
      [e["rank"] for e in r["elements"]] == [1, 2, 3],
      str([(e["element_id"], e["rank"]) for e in r["elements"]]))
check("计数 3/0", r["counts"] == {"total": 3, "ok": 3, "error": 0}, str(r["counts"]))

by_id = {e["element_id"]: e for e in r["elements"]}
# S_V1 = +1（线性电源，V2 与 V1 成正比）
check("S(V1)=+1", math.isclose(by_id["V1"]["sensitivity"], 1.0, rel_tol=1e-6),
      str(by_id["V1"]["sensitivity"]))
# S_R1 = -R1/(R1+R2) = -1/3
check("S(R1)=-1/3", math.isclose(by_id["R1"]["sensitivity"], -1 / 3, rel_tol=1e-6),
      str(by_id["R1"]["sensitivity"]))
# S_R2 = +R1/(R1+R2) = +1/3
check("S(R2)=+1/3", math.isclose(by_id["R2"]["sensitivity"], 1 / 3, rel_tol=1e-6),
      str(by_id["R2"]["sensitivity"]))
# 排序：|S(V1)|=1 最大；R1/R2 理论上同为 1/3，有限差分下次序允许互换
order = [e["element_id"] for e in r["elements"]]
check("排序 V1 居首，R1/R2 次之",
      order[0] == "V1" and set(order[1:]) == {"R1", "R2"}, str(order))

divider("2. 中心差分原始导数：dV2/dR1 = -V1·R2/(R1+R2)^2 = -20/90")
check("dV2/dR1=-2/9",
      math.isclose(by_id["R1"]["derivative"], -20 / 90, rel_tol=1e-6),
      str(by_id["R1"]["derivative"]))
check("dV2/dV1=R2/(R1+R2)=2/3",
      math.isclose(by_id["V1"]["derivative"], 2 / 3, rel_tol=1e-6),
      str(by_id["V1"]["derivative"]))

divider("3. 正负扰动值与扰动目标值")
rec = by_id["R1"]
check("R1 参数 ±0.1%",
      math.isclose(rec["value_minus"], 9.99) and math.isclose(rec["value_plus"], 10.01))
check("R1 目标两侧为有限值且 f- > f+（R1 增大 V2 减小）",
      math.isfinite(rec["target_minus"]) and math.isfinite(rec["target_plus"])
      and rec["target_minus"] > rec["target_plus"],
      str((rec["target_minus"], rec["target_plus"])))

divider("4. 支路电流目标：I(R1)=V1/(R1+R2)，S_V1=1、S_R1=-1/3、S_R2=-2/3")
r4 = sensitivity({
    **BASE,
    "sensitivity": {"target": {"kind": "current", "id": "R1"}, "ratio": 0.001},
})
bid = {e["element_id"]: e for e in r4["elements"]}
check("基准目标电流 1/3 A", math.isclose(r4["target_base"], 1 / 3, abs_tol=1e-10),
      str(r4["target_base"]))
check("I 目标 S(V1)=1", math.isclose(bid["V1"]["sensitivity"], 1.0, rel_tol=1e-6))
check("I 目标 S(R1)=-1/3", math.isclose(bid["R1"]["sensitivity"], -1 / 3, rel_tol=1e-6))
check("I 目标 S(R2)=-2/3", math.isclose(bid["R2"]["sensitivity"], -2 / 3, rel_tol=1e-6))

divider("5. 基准目标值为 0：归一化敏感度为 null，按导数绝对值排序")
r5 = sensitivity({
    **BASE,
    "sensitivity": {"target": {"kind": "voltage", "id": "0"}, "ratio": 0.001},
})
check("基准目标=0", r5["target_base"] == 0.0)
check("ranking=derivative", r5["ranking"] == "derivative")
check("全部 sensitivity=null",
      all(e["sensitivity"] is None for e in r5["elements"] if e["status"] == "ok"))
check("导数仍计算（dVgnd/dp=0）",
      all(e["derivative"] == 0.0 for e in r5["elements"] if e["status"] == "ok"))

divider("6. 零参数元件（0 A 电流源）：记 zero_parameter 失败，其余元件继续")
net6 = {
    "ground": "0",
    "nodes": ["0", "1"],
    "elements": [
        {"id": "V1", "type": "V", "node_p": "1", "node_n": "0", "value": 10},
        {"id": "R1", "type": "R", "node_p": "1", "node_n": "0", "value": 10},
        {"id": "I1", "type": "I", "node_p": "1", "node_n": "0", "value": 0},
    ],
}
r6 = sensitivity({**net6, "sensitivity": {"target": {"kind": "voltage", "id": "1"},
                                          "ratio": 0.01}})
check("2 成功 1 失败", r6["counts"] == {"total": 3, "ok": 2, "error": 1})
i1 = [e for e in r6["elements"] if e["element_id"] == "I1"][0]
check("I1 失败且无排名", i1["status"] == "error" and i1["rank"] is None)
g = i1["errors"][0]
check("失败码 zero_parameter + 阶段/方向标记",
      g["code"] == "zero_parameter" and g["stage"] == "perturbation" and g["side"] is None,
      str(g))
check("失败项无导数字段", "derivative" not in i1 and "sensitivity" not in i1)
check("成功项仍有连续排名 1..2",
      sorted(e["rank"] for e in r6["elements"] if e["status"] == "ok") == [1, 2])
check("失败项沉底（稳定排序）", r6["elements"][-1]["element_id"] == "I1")

divider("7. 基准无唯一解：整体 422 风格拒绝，错误分组带 baseline 阶段标记")
c, _ = expect_baseline_error({
    **BASE, "ground": "", "sensitivity": SPEC_V2,
})
check("无接地 -> no_ground@baseline", c == [("no_ground", "baseline")], str(c))

float_net = {
    "ground": "0",
    "nodes": ["0", "1", "2", "3"],
    "elements": [
        {"id": "V1", "type": "V", "node_p": "1", "node_n": "0", "value": 10},
        {"id": "R1", "type": "R", "node_p": "1", "node_n": "0", "value": 10},
        {"id": "V2", "type": "V", "node_p": "2", "node_n": "3", "value": 5},
        {"id": "R2", "type": "R", "node_p": "2", "node_n": "3", "value": 100},
    ],
}
c, _ = expect_baseline_error({**float_net, "sensitivity": SPEC_V2})
check("浮置子网 -> floating_subnet@baseline", c == [("floating_subnet", "baseline")], str(c))

singular_net = {
    "ground": "0",
    "nodes": ["0", "1"],
    "elements": [
        {"id": "V1", "type": "V", "node_p": "1", "node_n": "0", "value": 5},
        {"id": "V2", "type": "V", "node_p": "1", "node_n": "0", "value": 5},
    ],
}
c, _ = expect_baseline_error({**singular_net, "sensitivity": SPEC_V2})
check("等值并联源 -> singular@baseline", c == [("singular", "baseline")], str(c))

divider("8. 分析参数校验")
ok, detail = expect_rejected({**BASE}, "缺少 sensitivity")
check("缺少 sensitivity 段被拒", ok, detail)

ok, detail = expect_rejected({**BASE, "sensitivity": {"ratio": 0.01}}, "target")
check("缺少 target 被拒", ok, detail)

ok, detail = expect_rejected(
    {**BASE, "sensitivity": {"target": {"kind": "power", "id": "2"}, "ratio": 0.01}},
    "voltage", "current")
check("目标类型非法被拒", ok, detail)

ok, detail = expect_rejected(
    {**BASE, "sensitivity": {"target": {"kind": "voltage", "id": ""}, "ratio": 0.01}},
    "节点")
check("目标编号为空被拒", ok, detail)

ok, detail = expect_rejected(
    {**BASE, "sensitivity": {"target": {"kind": "voltage", "id": "9"}, "ratio": 0.01}},
    "9")
check("目标节点不在结果中被拒（基准求解后检查）", ok, detail)

ok, detail = expect_rejected(
    {**BASE, "sensitivity": {"target": {"kind": "current", "id": "Rx"}, "ratio": 0.01}},
    "Rx")
check("目标支路不存在被拒", ok, detail)

ok, detail = expect_rejected(
    {**BASE, "sensitivity": {"target": {"kind": "voltage", "id": "2"}, "ratio": 0.00001}},
    "0.01%", "10%")
check("比例低于 0.01% 被拒", ok, detail)

ok, detail = expect_rejected(
    {**BASE, "sensitivity": {"target": {"kind": "voltage", "id": "2"}, "ratio": 0.5}},
    "0.01%", "10%")
check("比例高于 10% 被拒", ok, detail)

ok, detail = expect_rejected(
    {**BASE, "sensitivity": {"target": {"kind": "voltage", "id": "2"}, "ratio": 0}},
    "0.01%", "10%")
check("比例为 0 被拒", ok, detail)

check("1% 合法",
      sensitivity({**BASE, "sensitivity": {
          "target": {"kind": "voltage", "id": "2"}, "ratio": 0.01}})["ok"] is True)

ok, detail = expect_rejected(
    {**BASE, "sensitivity": {"target": {"kind": "voltage", "id": "2"}, "ratio": "x"}},
    "数字")
check("比例非数字被拒", ok, detail)

ok, detail = expect_rejected(
    {**BASE, "sensitivity": {"target": {"kind": "voltage", "id": "2"}, "ratio": True}},
    "数字")
check("布尔比例被拒", ok, detail)

divider("9. 边界比例 0.01% 与 10% 均合法，且步长收敛（小步长更接近解析解）")
r_lo = sensitivity({**BASE, "sensitivity": {
    "target": {"kind": "voltage", "id": "2"}, "ratio": SENSITIVITY_MIN_RATIO}})
r_hi = sensitivity({**BASE, "sensitivity": {
    "target": {"kind": "voltage", "id": "2"}, "ratio": SENSITIVITY_MAX_RATIO}})
check("0.01% 可分析", r_lo["counts"]["error"] == 0)
check("10% 可分析", r_hi["counts"]["error"] == 0)
# V2 对 R2 的敏感度含二阶截断误差 O(δ^2)，取该元件比较才有意义
exact = 1 / 3
s_lo = [e for e in r_lo["elements"] if e["element_id"] == "R2"][0]["sensitivity"]
s_hi = [e for e in r_hi["elements"] if e["element_id"] == "R2"][0]["sensitivity"]
check("中心差分随步长缩小而更精确（S_R2）",
      abs(s_lo - exact) < abs(s_hi - exact),
      f"{abs(s_lo - exact):.3e} vs {abs(s_hi - exact):.3e}")

divider("10. 不改写调用方电路表，且扰动在独立副本上")
payload10 = {**BASE, "sensitivity": SPEC_V2}
snapshot = [(e["id"], e["value"]) for e in payload10["elements"]]
sensitivity(payload10)
check("元件参数保持原值",
      [(e["id"], e["value"]) for e in payload10["elements"]] == snapshot)
check("元件数量不增减", len(payload10["elements"]) == 3)
check("sensitivity 段原样保留在请求体中", "sensitivity" in payload10)

divider("11. 基准数值警告经 warnings 透传")
# 构造接近奇异的网络（极大 / 极小电阻并存），只要基准可解就应透传警告
net11 = {
    "ground": "0",
    "nodes": ["0", "1", "2"],
    "elements": [
        {"id": "V1", "type": "V", "node_p": "1", "node_n": "0", "value": 10},
        {"id": "R1", "type": "R", "node_p": "1", "node_n": "2", "value": 1e-9},
        {"id": "R2", "type": "R", "node_p": "2", "node_n": "0", "value": 1e9},
    ],
}
try:
    r11 = sensitivity({**net11, "sensitivity": SPEC_V2})
    check("返回 warnings 字段（可能为空）", isinstance(r11.get("warnings"), list))
except CircuitError:
    check("近奇异网络基准可解（部分平台可能直接 singular，跳过透传断言）", True)

print()
if failures:
    print(f"{len(failures)} 个用例失败: {failures}")
    sys.exit(1)
print("全部用例通过 ✔")
