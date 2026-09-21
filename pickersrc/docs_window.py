# -*- coding: utf-8 -*-
"""**在窗口里看使用说明**：左侧目录、右侧正文，可调字号、可"用浏览器打开"。

版式与课题组的 SHKit / SHSynth 一致（它们是 `docs/使用说明.html` + 一个预览窗口）。

为什么不用系统浏览器直接打开：
  · 用户正在对着界面操作，说明书弹在自己窗口里能边看边点，不切窗口；
  · 目录能点着跳、字号能调（现场屏幕大小差别很大）；
  · 说明书是随包的 `docs/使用说明.html`，窗口渲染不依赖外网。

Qt 的富文本引擎（QTextBrowser）只认 CSS 2.1 的一个子集（没有 flex/sticky），
所以那份 HTML 只用 标题 + 段落 + 表格 + 代码块 + 锚点排版，在浏览器里也好看。
"""
from __future__ import annotations

import os
import re

from PySide6.QtCore import QEvent, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSplitter, QTextBrowser, QVBoxLayout,
)

from . import appinfo

__all__ = ["GuideDialog", "open_guide"]


class GuideDialog(QDialog):
    """窗口内使用说明（目录 + 正文 + 缩放）。"""

    def __init__(self, parent=None, html_path=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{appinfo.APP_NAME} 使用说明")
        self.resize(1060, 780)
        self.setMinimumSize(700, 470)

        self._html_path = str(html_path or appinfo.guide_html_path() or "")
        self._zoom = 0
        self._img_size: dict[str, tuple[int, int]] = {}   # 原图尺寸缓存
        self._img_cap: dict[str, int] = {}                # HTML 里写的宽度（缩放上限）

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # ---------------------------------------------------------- 顶部工具条
        bar = QHBoxLayout()
        title = QLabel(f"<b style='font-size:14pt;'>{appinfo.APP_NAME} 使用说明</b>"
                       f"<span style='color:#666;'>　{appinfo.APP_NAME_CN}</span>")
        bar.addWidget(title)
        bar.addStretch(1)
        self.btn_smaller = QPushButton("A−")
        self.btn_smaller.setFixedWidth(46)
        self.btn_smaller.setToolTip("缩小正文字号")
        self.btn_smaller.clicked.connect(lambda: self._zoom_by(-1))
        self.btn_bigger = QPushButton("A+")
        self.btn_bigger.setFixedWidth(46)
        self.btn_bigger.setToolTip("放大正文字号")
        self.btn_bigger.clicked.connect(lambda: self._zoom_by(1))
        self.btn_reset = QPushButton("默认字号")
        self.btn_reset.clicked.connect(self._zoom_reset)
        self.btn_browser = QPushButton("用浏览器打开")
        self.btn_browser.setToolTip("在系统默认浏览器里打开同一份使用说明")
        self.btn_browser.clicked.connect(self._open_in_browser)
        for b in (self.btn_smaller, self.btn_bigger, self.btn_reset,
                  self.btn_browser):
            b.setMinimumHeight(28)
            bar.addWidget(b)
        root.addLayout(bar)

        # ---------------------------------------------------------- 目录 + 正文
        split = QSplitter(Qt.Orientation.Horizontal)
        self.toc = QListWidget()
        self.toc.setMaximumWidth(320)
        self.toc.setMinimumWidth(170)
        self.toc.setToolTip("点一条跳到对应章节")
        self.toc.itemClicked.connect(self._goto_item)
        split.addWidget(self.toc)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setOpenLinks(False)          # 内部锚点自己处理，外部链接交给系统
        self.view.anchorClicked.connect(self._on_anchor)
        # 视口一变宽就重新按宽度缩图（否则拉大/缩小窗口后图还是老的尺寸）
        self._vp = self.view.viewport()
        self._vp.installEventFilter(self)
        split.addWidget(self.view)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([250, 810])
        root.addWidget(split, 1)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        box.rejected.connect(self.reject)
        root.addWidget(box)

        self._load()

    # ------------------------------------------------------------------ 加载
    def _load(self) -> None:
        path = self._html_path
        if not path or not os.path.exists(path):
            self.view.setHtml(
                "<h2>没有找到使用说明</h2>"
                f"<p>预期文件：<code>{path or 'docs/使用说明.html'}</code></p>"
                "<p>安装版应位于程序目录的 <code>_internal\\docs\\"
                "使用说明.html</code>。</p>")
            return
        with open(path, encoding="utf-8") as fh:
            html = fh.read()
        # QTextBrowser 不会去磁盘找相对路径图片 —— 给它一个基地址
        base = QUrl.fromLocalFile(os.path.dirname(os.path.abspath(path)) + os.sep)
        self.view.document().setBaseUrl(base)
        self.view.setHtml(html)
        self._build_toc(html)
        self._fit_images()                 # 图片按窗口宽度等比缩放（Qt 不会自己缩）

    # ------------------------------------------------------------------ 图片自适应
    def _image_fragments(self):
        """遍历正文里所有图片片段（`(fragment, image_format)`）。"""
        doc = self.view.document()
        blk = doc.begin()
        while blk.isValid():
            it = blk.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    fmt = frag.charFormat().toImageFormat()
                    if fmt.isValid() and fmt.name():
                        yield frag, fmt
                it += 1
            blk = blk.next()

    def _natural_size(self, name: str) -> tuple[int, int]:
        """图片原始像素尺寸（缓存；按 HTML 目录解析相对路径）。"""
        if name not in self._img_size:
            p = name
            if not os.path.isabs(p) and self._html_path:
                p = os.path.join(os.path.dirname(self._html_path), name)
            img = QImage(p)
            self._img_size[name] = (img.width(), img.height())
        return self._img_size[name]

    def _fit_images(self) -> None:
        """把正文里的图片**按窗口宽度等比缩小**。

        为什么必须自己做：`QTextBrowser` 不会给图片做自适应 —— HTML 里写了
        `width="760"` 它就按 760 排，窗口窄了右边被裁掉、下面还留一大片空白
        （用户实测："图片下有大片空白，另外，图片没有自适应宽度"）。
        规则：`显示宽 = min(原图宽, HTML 里写的宽度, 视口宽 - 边距)`，
        高度按原比例一起算（★ 只给宽度、`setHeight(0)` 会让 Qt 把图排成 0 高 ——
        实测图直接"消失"、只剩一大片空白）。
        """
        avail = max(160, self.view.viewport().width() - 16)
        changed = False
        for frag, fmt in list(self._image_fragments()):
            name = fmt.name()
            nw, nh = self._natural_size(name)
            if nw <= 0:
                continue
            # HTML 里写的宽度当作**上限**记一次（之后按窗口缩放时不再变）
            cap = self._img_cap.get(name)
            if cap is None:
                cap = int(fmt.width()) or nw
                self._img_cap[name] = cap
            want = max(60, min(nw, cap, avail))
            want_h = max(20, int(round(nh * want / nw))) if nh else 0
            if int(fmt.width()) == want and int(fmt.height()) == want_h:
                continue
            fmt.setWidth(want)
            fmt.setHeight(want_h)          # ★ 高度要显式给（0 = 排成 0 高）
            cur = QTextCursor(self.view.document())
            cur.setPosition(frag.position())
            cur.setPosition(frag.position() + frag.length(),
                            QTextCursor.MoveMode.KeepAnchor)
            cur.setCharFormat(fmt)
            changed = True
        if changed:
            doc = self.view.document()
            doc.markContentsDirty(0, max(1, doc.characterCount()))

    def _build_toc(self, html: str) -> None:
        """从 HTML 的 h2/h3 生成目录（h3 缩进一级）。"""
        self.toc.clear()
        for m in re.finditer(r"<h([23])\s+id=\"([^\"]+)\"[^>]*>(.*?)</h\1>",
                             html, re.S | re.I):
            lvl, sid, text = m.group(1), m.group(2), m.group(3)
            text = re.sub(r"<[^>]+>", "", text).replace("↑", "").strip()
            item = QListWidgetItem(("　" if lvl == "3" else "") + text)
            item.setData(Qt.ItemDataRole.UserRole, sid)
            if lvl == "2":
                f = item.font()
                f.setBold(True)
                item.setFont(f)
            self.toc.addItem(item)
        if self.toc.count():
            self.toc.setCurrentRow(0)

    # ------------------------------------------------------------------ 动作
    def _goto_item(self, item: QListWidgetItem) -> None:
        sid = item.data(Qt.ItemDataRole.UserRole)
        if sid:
            self.view.scrollToAnchor(str(sid))

    def _on_anchor(self, url: QUrl) -> None:
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
        elif url.hasFragment() or (url.toString() or "").startswith("#"):
            self.view.scrollToAnchor(url.fragment())
        else:
            QDesktopServices.openUrl(url)

    def _zoom_by(self, step: int) -> None:
        self._zoom = max(-4, min(8, self._zoom + step))
        self.view.zoomIn(1 if step > 0 else -1)

    def _zoom_reset(self) -> None:
        while self._zoom > 0:
            self.view.zoomOut(1)
            self._zoom -= 1
        while self._zoom < 0:
            self.view.zoomIn(1)
            self._zoom += 1

    def _open_in_browser(self) -> None:
        if self._html_path and os.path.exists(self._html_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._html_path))

    def eventFilter(self, obj, ev) -> bool:               # noqa: N802（Qt 命名）
        """正文视口变宽变窄 → 图片重新按宽度缩放（拖动分隔条也走这里）。"""
        if obj is self._vp and ev.type() == QEvent.Type.Resize:
            self._fit_images()
        return super().eventFilter(obj, ev)

    def resizeEvent(self, ev) -> None:                   # noqa: N802（Qt 命名）
        super().resizeEvent(ev)
        self._fit_images()


def open_guide(parent=None) -> bool:
    """打开使用说明窗口；找到说明书文件返回 True。"""
    path = appinfo.guide_html_path()
    dlg = GuideDialog(parent, html_path=path)
    dlg.exec()
    return bool(path)
