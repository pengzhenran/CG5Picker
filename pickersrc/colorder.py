"""列顺序 / 列显示设置。

用户要求"列的排序也可以自己设定"，所以这里把"显示哪些列、按什么顺序"
做成一个可保存、可一键恢复默认的纯数据对象（`ColOrder`），
界面层只负责呈现 —— 便于无 GUI 单测。

默认顺序（用户指定）：线号、点号、观测值、观测时长、时间、日期……
这里的"观测值"在 CG-5 里就是 `GRAV.` → `读数(mGal)`；"时间"= `时刻`。
其余原始列按文件原顺序接在后面。
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "REASON_COL", "DEFAULT_HEAD", "ColOrder", "default_visible", "step",
]

#: 表格最前面附加的"为什么剔除"列（不属于原始文件列，导出时可选带出）
REASON_COL = "处理理由"

#: 表格**第一列**：勾选框（勾上 = 保留）。置顶且不参与排序，复核时不用横向滚动。
#: 真正定义在 `table_model.CHK_COL`；这里复制一份常量避免循环 import。
CHK_COL = "☑"

#: 用户指定的默认表头顺序（前缀）。找不到的列自动跳过。
DEFAULT_HEAD: tuple[str, ...] = ("线号", "点号", "读数(mGal)", "观测时长(s)", "时刻", "日期")


@dataclass
class ColOrder:
    """列显示顺序：`order` 给"真实列"，`reason` 决定是否附理由列。"""

    order: list[str] = field(default_factory=list)
    reason: bool = True

    def visible(self, available: list[str]) -> list[str]:
        """按 `order` 排列；未列进 `order` 的列接在后面（保证不丢列）。"""
        avail = list(available)
        seen = [c for c in self.order if c in avail]
        rest = [c for c in avail if c not in seen]
        return seen + rest

    def export_columns(self) -> list[str]:
        """导出用列序（只含真实数据列；勾选框/理由列不是数据）。"""
        return [c for c in self.order if c not in (CHK_COL, REASON_COL)]

    def display_columns(self, available: list[str]) -> list[str]:
        """界面用列序：**勾选框在最前，处理理由紧随其后**，再接真实数据列。

        理由：复核时要一眼看到"打勾没打勾"和"为什么剔"，所以这两列固定在左边；
        真实列的先后由用户拖动表头或列设置决定。
        """
        cols = self.visible(available)
        if not self.reason:
            return [CHK_COL] + cols
        return [CHK_COL, REASON_COL] + cols

    def copy_columns(self, available: list[str]) -> list[str]:
        """复制到剪贴板用的列：真实数据列 + （可选）处理理由。

        勾选框列没有可复制的文字，所以排除；理由列有意义，跟 `reason` 开关走。
        """
        cols = self.visible(available)
        return cols + [REASON_COL] if self.reason else cols


def default_visible(available: list[str]) -> list[str]:
    """默认列序：用户指定的前 6 列优先，其余按原文件顺序。"""
    head = [c for c in DEFAULT_HEAD if c in available]
    return head + [c for c in available if c not in head]


def step(order: list[str], row: int, delta: int) -> list[str]:
    """把 `order[row]` 上/下移 `delta` 位，返回新的列表（越界则原样返回）。"""
    out = list(order)
    j = row + delta
    if not (0 <= row < len(out)) or not (0 <= j < len(out)):
        return out
    out[row], out[j] = out[j], out[row]
    return out
