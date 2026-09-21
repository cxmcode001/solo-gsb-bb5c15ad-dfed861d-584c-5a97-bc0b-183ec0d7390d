"""元件敏感度分析（sensitivity）：中心差分 + 归一化敏感度。

请求体与 ``/api/solve`` 的网络 JSON 完全一致，另带一个 ``sensitivity`` 段：

    {
      ...网络...,
      "sensitivity": {
        "target": {"kind": "voltage", "id": "2"},   # 或 kind="current" + 支路编号
        "ratio": 0.01                                # 相对扰动比例（0.0001～0.1，即 0.01%～10%）
      }
    }

分析流程：

1. **基准求解**：在网络的深拷贝上调用一次 :func:`app.solver.solve`，得到基准
   目标值 ``f0`` 并确认网络有唯一解。基准失败时直接抛出带
   ``stage="baseline"`` 标记的结构化错误，不继续扰动。
2. **逐元件 ±δ 相对扰动**：对元件表中的每个 R / I / V 元件，参数原值为
   ``p0`` 时分别取 ``p0·(1±δ)``，在两个独立的网络副本上复用同一套 MNA
   求解与结构诊断，绝不改写调用方的电路表。
3. **中心差分**：

       导数      df/dp ≈ (f+ − f−) / (2·p0·δ)
       归一化敏感度 S = (df/dp)·(p0/f0)   （无量纲）

   基准目标值 ``f0`` 为 0 时归一化敏感度无定义（返回 ``null``，按导数绝对
   值排序）。

任一元件的任一扰动方向求解失败（结构矛盾 / 奇异 / 该取值非法）时，只把该
元件标记为 ``status:"error"`` 并原样保留错误分组（额外带
``stage="perturbation"`` 与 ``side:"plus"/"minus"`` 标记），**继续分析其余
元件**。元件基准参数为 0（0 A 电流源 / 0 V 电压源）时相对扰动步长为 0，
该元件直接记为 ``zero_parameter`` 失败项。

分析参数本身（缺少 ``sensitivity`` 段 / 目标类型非法 / 比例越界 / 目标不在
求解结果中）无法开工，抛出 :class:`CircuitError`（``sensitivity_validation``）。
"""

from __future__ import annotations

import copy
import math
from typing import Any

from .solver import CircuitError, solve

# 相对扰动比例（小数）：0.01% ～ 10%
SENSITIVITY_MIN_RATIO = 1e-4
SENSITIVITY_MAX_RATIO = 0.1
# 与 solver 的零电流 / 零电压截断保持一致：|f0| 不超过该值视为基准目标为 0
_ZERO_TARGET_TOL = 1e-12

TARGET_VOLTAGE = "voltage"
TARGET_CURRENT = "current"
STAGE_BASELINE = "baseline"
STAGE_PERTURBATION = "perturbation"
SIDE_MINUS = "minus"
SIDE_PLUS = "plus"

_UNIT = {"R": "Ω", "I": "A", "V": "V"}


def _reject(items: list[dict[str, str]]) -> CircuitError:
    return CircuitError(
        [{"code": "sensitivity_validation", "message": "敏感度分析参数未通过校验", "items": items}]
    )


def _tagged(exc: CircuitError, stage: str, side: str | None = None) -> CircuitError:
    """给既有错误分组补上阶段 / 扰动方向标记。"""
    groups: list[dict[str, Any]] = []
    for group in exc.errors:
        tagged = {**group, "stage": stage}
        if side is not None:
            tagged["side"] = side
        groups.append(tagged)
    return CircuitError(groups)


def _target_value(result: dict[str, Any], kind: str, target_id: str) -> float | None:
    """从一次 solve 结果中取出目标量；目标不存在时返回 None。"""
    if kind == TARGET_VOLTAGE:
        for row in result["node_voltages"]:
            if str(row["id"]) == target_id:
                return float(row["voltage"])
    else:
        for branch in result["branches"]:
            if str(branch["id"]) == target_id:
                return float(branch["current"])
    return None


def sensitivity(payload: dict[str, Any]) -> dict[str, Any]:
    """对全部元件做 ±相对扰动的中心差分敏感度分析。"""
    if not isinstance(payload, dict):
        raise _reject([{"ref": "-", "detail": "请求体应为对象"}])

    spec = payload.get("sensitivity")
    if not isinstance(spec, dict):
        raise _reject([{"ref": "-", "detail": "缺少 sensitivity 分析参数对象"}])

    # ------------------------------------------------------------- 分析目标
    problems: list[dict[str, str]] = []
    target = spec.get("target")
    kind = ""
    target_id = ""
    if not isinstance(target, dict):
        problems.append({"ref": "分析目标", "detail": "缺少 target 目标对象"})
    else:
        kind = str(target.get("kind") or "").strip().lower()
        target_id = str(target.get("id") or "").strip()
        if kind not in (TARGET_VOLTAGE, TARGET_CURRENT):
            problems.append(
                {"ref": "分析目标", "detail": f"目标类型“{kind}”非法，应为 voltage（节点电压）或 current（支路电流）"}
            )
        if not target_id:
            problems.append(
                {"ref": "分析目标", "detail": f"未指定目标{'节点' if kind == TARGET_VOLTAGE else '支路'}编号"}
            )

    # ------------------------------------------------------------- 扰动比例
    raw_ratio = spec.get("ratio")
    ratio: float | None = None
    if isinstance(raw_ratio, bool) or not isinstance(raw_ratio, (int, float)):
        problems.append(
            {"ref": "扰动比例", "detail": f"相对扰动比例必须是数字（当前：{raw_ratio!r}）"}
        )
    else:
        ratio = float(raw_ratio)
        if not math.isfinite(ratio):
            problems.append(
                {"ref": "扰动比例", "detail": f"相对扰动比例必须为有限实数（当前：{raw_ratio!r}）"}
            )
        elif not (SENSITIVITY_MIN_RATIO <= ratio <= SENSITIVITY_MAX_RATIO):
            problems.append(
                {
                    "ref": "扰动比例",
                    "detail": (
                        f"相对扰动比例必须在 {SENSITIVITY_MIN_RATIO * 100:g}%～"
                        f"{SENSITIVITY_MAX_RATIO * 100:g}% 之间（当前：{ratio * 100:g}%）"
                    ),
                }
            )

    if problems:
        raise _reject(problems)
    assert ratio is not None

    # ------------------------------------------------------------- 基准求解
    try:
        base_result = solve(copy.deepcopy(payload))
    except CircuitError as exc:
        # 基准网络本身无唯一解：无法定义任何敏感度，整次请求失败
        raise _tagged(exc, STAGE_BASELINE)

    f0 = _target_value(base_result, kind, target_id)
    if f0 is None:
        label = "节点" if kind == TARGET_VOLTAGE else "支路"
        raise _reject(
            [
                {
                    "ref": target_id,
                    "detail": (
                        f"目标{label}“{target_id}”不在基准求解结果中，"
                        f"请先成功求解并选择表中存在的{label}"
                    ),
                }
            ]
        )

    base_zero = abs(f0) <= _ZERO_TARGET_TOL
    elements = payload["elements"]

    # ------------------------------------------------- 逐元件 ±δ 扰动 + 差分
    records: list[dict[str, Any]] = []
    for element in elements:
        eid = str(element["id"])
        etype = str(element["type"]).strip().upper()
        p0 = float(element["value"])
        common = {
            "element_id": eid,
            "type": etype,
            "node_p": element["node_p"],
            "node_n": element["node_n"],
            "value": p0,
            "target_base": 0.0 if base_zero else f0,
        }

        # 基准参数为 0：p0·δ = 0，正负扰动都等于原值，中心差分为 0/0
        if p0 == 0.0:
            records.append(
                {
                    **common,
                    "status": "error",
                    "value_minus": 0.0,
                    "value_plus": 0.0,
                    "errors": [
                        {
                            "code": "zero_parameter",
                            "stage": STAGE_PERTURBATION,
                            "side": None,
                            "message": "元件基准参数值为 0，相对扰动步长为 0，无法用中心差分计算敏感度",
                            "items": [
                                {
                                    "ref": eid,
                                    "detail": (
                                        f"元件 {eid} 的基准参数为 0 {_UNIT.get(etype, '')}，"
                                        "正负相对扰动均不改变其值；请先在元件表中给出非零参数"
                                    ),
                                }
                            ],
                        }
                    ],
                }
            )
            continue

        value_minus = p0 * (1.0 - ratio)
        value_plus = p0 * (1.0 + ratio)
        step = p0 * ratio  # 单侧扰动量，中心差分分母为 2·step

        side_errors: list[dict[str, Any]] = []
        targets: dict[str, float] = {}
        for side, perturbed_value in ((SIDE_MINUS, value_minus), (SIDE_PLUS, value_plus)):
            trial = copy.deepcopy(payload)
            # 元件编号经 solve 校验唯一，按 id 定位要扰动的那一行
            for row in trial["elements"]:
                if str(row.get("id")) == eid:
                    row["value"] = perturbed_value
                    break
            try:
                trial_result = solve(trial)
            except CircuitError as exc:
                side_errors.extend(_tagged(exc, STAGE_PERTURBATION, side).errors)
                continue
            f_side = _target_value(trial_result, kind, target_id)
            if f_side is None or not math.isfinite(f_side):
                side_errors.append(
                    {
                        "code": "target_lost",
                        "stage": STAGE_PERTURBATION,
                        "side": side,
                        "message": "扰动后无法从求解结果中读取目标量",
                        "items": [
                            {"ref": eid, "detail": f"{eid} 的{('＋' if side == SIDE_PLUS else '－')}扰动解中目标缺失或非有限值"}
                        ],
                    }
                )
                continue
            targets[side] = f_side

        if side_errors:
            # 任一扰动方向失败：该元件不出差分结果，但不影响其它元件
            records.append(
                {
                    **common,
                    "status": "error",
                    "value_minus": value_minus,
                    "value_plus": value_plus,
                    "target_minus": targets.get(SIDE_MINUS),
                    "target_plus": targets.get(SIDE_PLUS),
                    "errors": side_errors,
                }
            )
            continue

        f_minus = targets[SIDE_MINUS]
        f_plus = targets[SIDE_PLUS]
        derivative = (f_plus - f_minus) / (2.0 * step)
        sensitivity_value = None if base_zero else derivative * p0 / f0

        records.append(
            {
                **common,
                "status": "ok",
                "value_minus": value_minus,
                "value_plus": value_plus,
                "target_minus": f_minus,
                "target_plus": f_plus,
                "derivative": derivative,
                "sensitivity": sensitivity_value,
            }
        )

    # ----------------- 排序：有限归一化敏感度 → 基准为 0 时按导数 → 失败项 --
    def sort_key(rec: dict[str, Any]) -> tuple[int, float]:
        if rec["status"] != "ok":
            return (2, 0.0)  # 稳定排序：失败项保持元件表顺序沉底
        if rec["sensitivity"] is None:
            return (1, -abs(rec["derivative"]))
        return (0, -abs(rec["sensitivity"]))

    records.sort(key=sort_key)

    rank = 0
    any_finite = False
    for rec in records:
        if rec["status"] == "ok":
            rank += 1
            rec["rank"] = rank
            if rec["sensitivity"] is not None:
                any_finite = True
        else:
            rec["rank"] = None

    ok_count = sum(1 for rec in records if rec["status"] == "ok")
    fail_count = len(records) - ok_count

    return {
        "ok": True,
        "target": {"kind": kind, "id": target_id},
        "ratio": ratio,
        "ratio_percent": ratio * 100.0,
        "target_base": 0.0 if base_zero else f0,
        "ranking": "derivative" if base_zero or not any_finite else "sensitivity",
        "counts": {"total": len(records), "ok": ok_count, "error": fail_count},
        "elements": records,
        "warnings": base_result.get("warnings", []),
    }
