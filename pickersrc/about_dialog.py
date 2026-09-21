# -*- coding: utf-8 -*-
"""「关于 / 作者信息」对话框 —— 与课题组 SHKit / SHSynth 同一版式。

左侧是联系方式表（作者 / 单位 / 邮箱 / 电话 / 公众号 / 版本），
右侧直接显示**公众号二维码**（不用再点开二级窗口），底部有：
  发邮件 / 放大二维码 / 打开说明（README）/ 配置文件在哪。
底下一段 credit 说明依赖与许可（PySide6 LGPL、matplotlib BSD、openpyxl MIT），
以及"仅供科研与教学使用"。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

from . import appinfo
from .settings import Settings

__all__ = ["AboutDialog"]


class AboutDialog(QDialog):
    """关于 / 作者信息（含公众号二维码与快速上手）。"""

    def __init__(self, parent=None, settings: Settings | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle(f"关于 {appinfo.APP_NAME} / About")
        self.resize(860, 720)
        self.setMinimumSize(620, 460)
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(18, 16, 18, 16)

        header = QLabel(
            f"<h2>{appinfo.APP_NAME} {appinfo.version()} — "
            f"{appinfo.APP_NAME_CN}</h2>"
            f"<p>{appinfo.APP_TAGLINE}<br>"
            "<small>与大软件 GravProc 分工：这里只做"
            "<b>按日期 / Survey / 条件挑选 + 图形确认 + 按原格式导出</b>。</small></p>")
        header.setWordWrap(True)
        root.addWidget(header)

        root.addWidget(self._author_group())
        root.addWidget(self._quick_start_group())
        root.addWidget(self._credit_label())
        root.addStretch(1)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        box.rejected.connect(self.reject)
        root.addWidget(box)

    # ------------------------------------------------------------- 子部件
    def _author_group(self) -> QGroupBox:
        grp = QGroupBox("作者信息  /  Author")
        outer = QHBoxLayout(grp)
        outer.setSpacing(16)

        left = QWidget()
        grid = QGridLayout(left)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        rows = [
            ("作者  Author",
             f"{appinfo.AUTHOR_NAME_CN}  （{appinfo.AUTHOR_NAME_EN}）"),
            ("单位  Affiliation",
             f"{appinfo.AUTHOR_AFFILIATION_CN}<br>{appinfo.AUTHOR_AFFILIATION_EN}"),
            ("邮箱  E-mail",
             f'<a href="mailto:{appinfo.AUTHOR_EMAIL}">{appinfo.AUTHOR_EMAIL}</a>'),
            ("电话  Phone", appinfo.AUTHOR_PHONE),
            ("公众号  WeChat",
             f"{appinfo.WECHAT_ACCOUNT}（{appinfo.WECHAT_ACCOUNT_EN}）"),
            ("版本  Version", f"v{appinfo.version()}"),
        ]
        for r, (key, value) in enumerate(rows):
            k = QLabel(f"<b>{key}</b>")
            k.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            v = QLabel(value)
            v.setWordWrap(True)
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                      | Qt.TextInteractionFlag.LinksAccessibleByMouse)
            v.setOpenExternalLinks(True)
            grid.addWidget(k, r, 0)
            grid.addWidget(v, r, 1)
        grid.setColumnStretch(1, 1)

        btns = QHBoxLayout()
        b_mail = QPushButton("发邮件  (E-mail)")
        b_mail.setMinimumHeight(30)
        b_mail.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl(f"mailto:{appinfo.AUTHOR_EMAIL}")))
        b_wx = QPushButton("放大二维码")
        b_wx.setMinimumHeight(30)
        b_wx.clicked.connect(self._show_wechat)
        b_guide = QPushButton("使用说明（F1）")
        b_guide.setMinimumHeight(30)
        b_guide.setToolTip("打开随包的 HTML 使用说明（窗口内预览，也能用浏览器打开）")
        b_guide.clicked.connect(self._open_guide)
        b_cfg = QPushButton("配置文件位置")
        b_cfg.setMinimumHeight(30)
        b_cfg.setToolTip("参数设置的记忆文件（settings.json）与条件组合（presets.json）")
        b_cfg.clicked.connect(self._show_config)
        b_lic = QPushButton("许可与第三方声明")
        b_lic.setMinimumHeight(30)
        b_lic.setToolTip("本软件 MIT 全文 + 随包组件的许可声明"
                         "（PySide6/Qt LGPLv3、matplotlib、NumPy、openpyxl）")
        b_lic.clicked.connect(self._show_licenses)
        for b in (b_mail, b_wx, b_guide, b_cfg, b_lic):
            btns.addWidget(b)
        btns.addStretch(1)
        grid.addLayout(btns, len(rows), 0, 1, 2)
        outer.addWidget(left, stretch=1)
        outer.addWidget(self._qr_panel(), stretch=0)
        return grp

    def _qr_panel(self) -> QWidget:
        """二维码小面板：有图就显示，没图就说明该把文件放哪儿。"""
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        cap = QLabel(f"<b>{appinfo.WECHAT_ACCOUNT}</b><br>"
                     f"<small style='color:#666;'>{appinfo.WECHAT_ACCOUNT_EN} · "
                     "微信扫一扫</small>")
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(cap)

        path = appinfo.qr_image_path()
        pix = QPixmap(str(path)) if path else QPixmap()
        if not pix.isNull():
            img = QLabel()
            img.setPixmap(pix.scaled(170, 170, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation))
            img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img.setToolTip("点击放大二维码")
            img.setCursor(Qt.CursorShape.PointingHandCursor)
            img.mousePressEvent = lambda _e: self._show_wechat()   # noqa: ARG005
            lay.addWidget(img)
        else:
            miss = QLabel(f"<small style='color:#b45309;'>未找到二维码图片<br>"
                          f"（{appinfo.WECHAT_QR_FILENAME}）</small>")
            miss.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(miss)
        return panel

    def _quick_start_group(self) -> QGroupBox:
        grp = QGroupBox("快速上手  /  Quick start")
        lay = QVBoxLayout(grp)
        steps = [
            "① 打开 CG-5 手簿 —— 一个 .txt 里通常有多天 / 多个 Survey，会全部解析出来；",
            "② 选日期（左边）与 Survey（右边）—— 两条线是<b>且</b>的关系，"
            "缺一边就是 0 条；",
            "③ 调条件栈（勾选立即生效）——「连接」列决定角色：首要 / 或 / 且；"
            "「最终取值」每轮留一条，「分段间隔」定「多少分钟算新的一轮」；",
            "④ 结果表里复核 —— 表格勾选/取消 = 人工保留/剔除；"
            "「取消选中 / 勾选选中 / 取消勾选」作用于选中的行；",
            "⑤ 对图形 —— 单击=选中、Ctrl+单击=取反、拖动=平移、滚轮=缩放、"
            "Shift+拖动=框选、Ctrl+拖动=框选取反、R=复位；",
            "⑥ 导出 xlsx —— <b>默认附 Survey 文件头</b>，可选附处理理由；"
            "日期/时刻写真日期时间，数值列写真数值。",
            "⑦ 界面习惯会<b>记住</b>（窗口大小/分栏/视图/列序/导出选项/条件栈）—— "
            "下次打开还是上次的样子；想回出厂就在「筛选条件」里选第一个内置组合。",
        ]
        for s in steps:
            it = QLabel(s)
            it.setWordWrap(True)
            lay.addWidget(it)
        return grp

    def _credit_label(self) -> QLabel:
        lab = QLabel(
            f"<small><b>{appinfo.copyright_line()}</b><br>"
            "本软件自身代码采用 <b>MIT</b> 许可（全文 <code>LICENSE.txt</code>）。"
            "随包分发的第三方组件：图形界面 Qt for Python(<b>PySide6</b>，"
            "GNU LGPL v3) —— 动态链接、未修改；绘图 <b>matplotlib</b>(PSF/BSD 风格)；"
            "数值 <b>NumPy</b>(BSD-3)；xlsx 读写 <b>openpyxl</b>(MIT)。"
            "逐条声明与 LGPLv3 义务见 <code>licenses/NOTICE.txt</code>"
            "（LGPLv3/GPLv3 全文在 <code>licenses/</code>）。<br>"
            "本软件不使用任何 GPL-only 的 Qt 模块；界面中文用系统字体，"
            "不随包分发字体。<br>"
            f"配置文件：<code>{self._cfg_text()}</code><br>"
            "本软件仅供科研与教学使用。</small>")
        lab.setWordWrap(True)
        lab.setStyleSheet("color:#666;")
        return lab

    # ------------------------------------------------------------- 动作
    def _cfg_text(self) -> str:
        """配置文件位置（**在软件安装目录的 config/ 下**；不可写才退到用户目录）。"""
        try:
            cfg = (self._settings.path if self._settings is not None
                   else appinfo.settings_path())
            where = ("软件安装目录" if appinfo.config_dir_is_install_dir()
                     else "用户目录（安装目录不可写，自动退到这里）")
            return f"{cfg}　｜　条件组合：{appinfo.presets_path()}　（{where}）"
        except Exception:                                  # noqa: BLE001
            return "<安装目录>\\config\\"

    def _show_wechat(self) -> None:
        path = appinfo.qr_image_path()
        pix = QPixmap(str(path)) if path else QPixmap()
        if pix.isNull():
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"公众号二维码 —— {appinfo.WECHAT_ACCOUNT}")
        lay = QVBoxLayout(dlg)
        lab = QLabel()
        lab.setPixmap(pix.scaled(420, 420, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation))
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(lab)
        tip = QLabel(f"{appinfo.WECHAT_ACCOUNT}（{appinfo.WECHAT_ACCOUNT_EN}）")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(tip)
        dlg.exec()

    def _open_guide(self) -> None:
        """打开 HTML 使用说明（窗口内预览；找不到文件就退回 README）。"""
        from .docs_window import GuideDialog

        if appinfo.guide_html_path() is None:
            p = appinfo.readme_path()
            if p is not None:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
            return
        GuideDialog(self).exec()

    def _show_config(self) -> None:
        """配置文件位置：默认在**软件安装目录的 config/ 下**（用户口径：别放 C 盘系统里）。"""
        p = (self._settings.path if self._settings is not None
             else appinfo.settings_path())
        dlg = QDialog(self)
        dlg.setWindowTitle("配置文件位置")
        lay = QVBoxLayout(dlg)
        where = ("软件安装目录（跟着程序走，拷到别的机器也带着）"
                 if appinfo.config_dir_is_install_dir()
                 else "用户目录 —— 安装目录不可写（例如装在 C:\\Program Files），"
                      "自动退到这里")
        tip = QLabel(f"<b>配置文件放在：</b>{where}")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        for title, path in (("参数设置（记忆）", p),
                            ("条件参数组合", appinfo.presets_path())):
            lab = QLabel(f"<b>{title}</b><br><code>{path}</code>")
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            lay.addWidget(lab)
            b = QPushButton("打开所在文件夹")
            b.clicked.connect(lambda _c=False, _p=path: QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(_p.parent))))
            lay.addWidget(b)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.rejected.connect(dlg.reject)
        lay.addWidget(box)
        dlg.exec()

    def _show_licenses(self) -> None:
        """许可与第三方声明：本软件 MIT 全文 + 随包组件的逐条声明。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("许可与第三方声明 / Licenses")
        dlg.resize(880, 720)
        lay = QVBoxLayout(dlg)

        head = QLabel(
            f"<b>{appinfo.APP_NAME} {appinfo.version()} —— {appinfo.APP_NAME_CN}</b><br>"
            f"{appinfo.copyright_line()}<br>"
            "<small>本软件自身代码采用 <b>MIT</b> 许可（全文见 <code>LICENSE.txt</code>）。"
            "随发行包一起分发的第三方组件各自适用其许可，逐条声明见下 —— "
            "其中 Qt for Python(PySide6) 为 <b>LGPLv3</b>，随附 LGPLv3 / GPLv3 全文。</small>")
        head.setWordWrap(True)
        lay.addWidget(head)

        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        p = appinfo.notice_path()
        try:
            text = p.read_text(encoding="utf-8") if p is not None else ""
        except OSError:
            text = ""
        view.setPlainText(text or "（未找到 licenses/NOTICE.txt —— 请重新安装一次）")
        lay.addWidget(view, 1)

        row = QHBoxLayout()
        for text_, tip, path in (
                ("MIT 全文（LICENSE.txt）", "用系统默认程序打开本软件的 MIT 许可全文",
                 appinfo.license_path()),
                ("第三方许可全文（licenses/）",
                 "LGPL-3.0 / GPL-3.0 全文所在目录", (p.parent if p else None))):
            if path is None:
                continue
            b = QPushButton(text_)
            b.setToolTip(tip)
            b.clicked.connect(
                lambda _c=False, _p=path: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(_p))))
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        box.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        box.rejected.connect(dlg.reject)
        lay.addWidget(box)
        dlg.exec()
