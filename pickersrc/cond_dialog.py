"""筛选条件参数对话框 —— 按条件类型自动生成表单。"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel,
    QSpinBox, QVBoxLayout, QWidget,
)

from .rules import COND_KINDS, PARAM_CN

__all__ = ["CondDialog"]

#: 整数型参数（用 SpinBox）
_INT_PARAMS = {"n"}
#: 参数单位后缀 —— 单位已写进标签，这里留空避免重复
_SUFFIX: dict[str, str] = {}
#: 下拉型参数：参数名 → [(值, 显示文字), …]（值不是数字的参数走这里）
_CHOICES: dict[str, list[tuple[str, str]]] = {
    "mode": [("latest", "最新（默认，取最后一个）"),
             ("min_dev", "最小距平（离合格读数均值最近；只有两个读数时取最新）")],
}


class CondDialog(QDialog):
    """按条件类型生成参数表单，返回参数字典。"""

    def __init__(self, kind: str, params: dict, parent=None) -> None:
        super().__init__(parent)
        meta = COND_KINDS[kind]
        self.setWindowTitle(f"条件参数 —— {meta.cn}")
        self._kind = kind
        self._edits: dict[str, QWidget] = {}

        lay = QVBoxLayout(self)
        info = QLabel(f"<b>{meta.desc}</b><br>"
                      f"<span style='color:#6b7280'>依据：{meta.basis}</span>")
        info.setWordWrap(True)
        lay.addWidget(info)

        form = QFormLayout()
        for key, default in meta.params.items():
            cur = params.get(key, default)
            if key in _CHOICES:                       # 非数值参数 → 下拉框
                vals = [v for v, _t in _CHOICES[key]]
                w: QWidget = QComboBox()
                for value, text in _CHOICES[key]:
                    w.addItem(text, value)
                w.setCurrentIndex(vals.index(cur) if cur in vals else 0)
                w.setMinimumWidth(300)
                self._edits[key] = w
                form.addRow(meta.params_cn.get(key) or PARAM_CN.get(key, key), w)
                continue
            try:
                cur_f = float(cur)
            except (TypeError, ValueError):
                cur_f = float(default)
            if key in _INT_PARAMS:
                w = QSpinBox()
                w.setRange(1, 100)
                w.setValue(int(cur_f))
                w.setSuffix(_SUFFIX.get(key, ""))
            else:
                w = QDoubleSpinBox()
                w.setDecimals(2)
                w.setRange(-1e6, 1e6)
                w.setValue(cur_f)
                w.setSuffix(_SUFFIX.get(key, ""))
            w.setMinimumWidth(160)
            self._edits[key] = w
            form.addRow(meta.params_cn.get(key) or PARAM_CN.get(key, key), w)
        lay.addLayout(form)

        if kind == "duration":
            hint = QLabel("<span style='color:#6b7280'>"
                          "提示：最长时长填 0 表示只卡下限（默认）。</span>")
            hint.setWordWrap(True)
            lay.addWidget(hint)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self) -> dict:
        out: dict = {}
        for key, w in self._edits.items():
            if isinstance(w, QComboBox):              # 下拉型（如「最终取值」的方式）
                out[key] = str(w.currentData())
            elif isinstance(w, QSpinBox):
                out[key] = int(w.value())
            else:
                v = float(w.value())
                out[key] = int(v) if abs(v - round(v)) < 1e-9 else v
        return out
