"""自检套件（非产品代码）：离屏装配界面，逐项核对功能。

先跑产品自带的无界面自检产出基准 xlsx，再跑本脚本：
    cd CG5Picker
    ..\\GravProc\\.venv\\Scripts\\python.exe main.py --selftest "<CG5手簿>" --out _selfcheck
    ..\\GravProc\\.venv\\Scripts\\python.exe _selfcheck\\verify_gui.py

覆盖：导出保真 / 线号显示规则 / 范围两条线 / 参数组合 / 条件栈内联操作 /
      结果表显示模式 / 手动筛选与表格↔图形同步 / 图形交互（缩放平移框选） / 四种视图
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CG5Picker"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

DATA = (ROOT / "GravProc" / "examples" / "示例数据" / "宁夏"
        / "01_每日导出的重力仪原始数据")
SRC = DATA / "0701" / "914" / "914_20250701.txt"      # 6 天 / 单 Survey
MULTI = DATA / "0711" / "914" / "914_20250711.txt"    # 15 天，含多 Survey 的一天
XLSX = ROOT / "CG5Picker" / "_selfcheck" / "原始格式.xlsx"

_fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> bool:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}" + (f"　{detail}" if detail else ""))
    if not cond:
        _fails.append(label)
    return bool(cond)


def head(t: str) -> None:
    print(f"\n{'=' * 72}\n{t}\n{'=' * 72}")


# =====================================================================
def _ensure_baseline_xlsx() -> None:
    """没有基准导出文件就先跑一遍产品的无界面自检生成它（本套件自洽，不依赖手工步骤）。"""
    if XLSX.exists():
        return
    print(f"  （未找到 {XLSX.name}，先跑一遍产品自检生成基准…）")
    from pickersrc.selftest import run_selftest

    run_selftest([str(SRC), "--out", str(XLSX.parent)])


def test_export() -> None:
    print("\n[1] 导出：表头 / 数值类型 / 编号去零 / 文本逐字")
    from openpyxl import load_workbook

    from pickersrc.cg5 import read_file
    from pickersrc.display import format_id_cell, is_numeric_text as _is_num_text

    _ensure_baseline_xlsx()
    if not XLSX.exists():
        check("基准导出文件存在", False, str(XLSX))
        return
    wb = load_workbook(XLSX, read_only=True)
    rows = [r for r in wb.active.iter_rows(values_only=True)]
    wb.close()
    hdr, body = rows[0], rows[1:]
    print(f"      {len(body)} 行 × {len(hdr)} 列；表头 {' '.join(str(x) for x in hdr)}")

    f = read_file(str(SRC))
    cols = list(f.columns)
    ci = {c: i for i, c in enumerate(cols)}

    check("表头无前导空格", all(not str(c).startswith(" ") for c in hdr))
    check("单元格无多余首尾空格",
          all(str(c) == str(c).strip() for r in body for c in r))

    # ---- 用一份"行号已知"的导出核对类型与格式 ----
    # （基准 xlsx 是产品自检写的，行号跟源行对不上，没法逐格比；这里自己导一份）
    from pickersrc.colorder import ColOrder
    from pickersrc.exporter import export_xlsx, survey_headers

    # 两条线求交集 → 日期与 Survey 都要给（空集 = 0 条）
    idx = f.filter_scope({"2025-07-01"},
                         set(f.surveys_on({"2025-07-01"})))[:6]
    tmp = XLSX.parent / "类型校验.xlsx"
    export_xlsx(f, idx, ColOrder(order=list(cols)), tmp, mode="verbatim",
                include_survey_header=True)
    wb2 = load_workbook(tmp)
    rows2 = [list(r) for r in wb2.active.iter_rows(values_only=True)]
    # Survey 文件头写在最上面：找到数据表头所在行，下面才是数据
    hdr_row = next(i for i, r in enumerate(rows2)
                   if r and str(r[0]) == f.colsource[0])
    head_block = rows2[:hdr_row]
    hdr2, body2 = rows2[hdr_row], rows2[hdr_row + 1:]
    nfmt = {}
    for j, name in enumerate(f.columns):
        nfmt[name] = wb2.active.cell(row=hdr_row + 2, column=j + 1).number_format
    # 时刻 / 日期：**真时间 / 真日期**（用户："WPS 提示该数据未识别为日期"）
    ws2 = wb2.active
    _dc = ws2.cell(row=hdr_row + 2, column=ci.get("日期", 0) + 1)
    _tc = ws2.cell(row=hdr_row + 2, column=ci.get("时刻", 0) + 1)
    dt_cell = (_dc.value, _dc.data_type, _dc.number_format)
    tm_cell = (_tc.value, _tc.data_type, _tc.number_format)
    # Survey 文件头块的字段类型：`Instrument S/N:` / `ZONE:` / `GMT DIFF.:` / `Date:` / `Time:`
    kv_cells = {}
    for r in range(1, hdr_row + 1):
        a = ws2.cell(row=r, column=1).value
        b = ws2.cell(row=r, column=2)
        if a:
            kv_cells[str(a).rstrip("：:").strip()] = (b.value, b.data_type,
                                                      b.number_format)
    wb2.close()

    check("自己导的那份行数对得上", len(body2) == len(idx),
          f"{len(body2)} 行 / 选了 {len(idx)} 条")
    check("Survey 文件头写在数据表头**上面**", hdr_row > 0,
          f"数据表头在第 {hdr_row + 1} 行，上面 {hdr_row} 行是文件头")
    flat = " ".join(str(x) for r in head_block for x in r if x is not None)
    check("文件头里有 Survey name / S/N / 经纬度",
          "Survey name:" in flat and "Instrument S/N:" in flat
          and "LONG:" in flat and "LAT:" in flat,
          f"第 1 行 = {[x for x in head_block[0] if x is not None] if head_block else '—'}")
    check("文件头用的是这些观测所属的 Survey",
          f.rows[idx[0]].survey in flat, f"survey={f.rows[idx[0]].survey}")
    check("经纬度按原文写（114.4000000 E 这种不被改成小数）",
          "114.4000000 E" in flat or "106.6000000 E" in flat,
          [x for r in head_block for x in r if isinstance(x, str) and "LONG" in x][:1])

    def src_of(k: int) -> list[str]:
        return list(f.rows[idx[k]].cells)

    # ★ 回归：**没有** Survey 文件头时，数据表头必须就在第 1 行
    #   （踩过的坑：`ws.max_row + 1` 在空表上算成 2 —— 多出一个空行，
    #    表头样式与 freeze_panes 全部错位）
    tmp2 = XLSX.parent / "无文件头.xlsx"
    export_xlsx(f, idx, ColOrder(order=list(cols)), tmp2, mode="verbatim")
    wb_n = load_workbook(tmp2)
    ws_n = wb_n.active
    check("没有 Survey 文件头时，数据表头就在第 1 行（不多空行）",
          str(ws_n.cell(row=1, column=1).value) == f.colsource[0]
          and ws_n.max_row == len(idx) + 1,
          f"A1={ws_n.cell(row=1, column=1).value!r}，max_row={ws_n.max_row}（应 {len(idx) + 1}）")
    check("第 1 行是加粗的表头（样式没加错行）",
          bool(ws_n.cell(row=1, column=1).font.bold))
    check("冻结窗格停在数据行（A2）", ws_n.freeze_panes == "A2",
          f"{ws_n.freeze_panes}")
    wb_n.close()

    # ① 数值列**写成数值**（用户："除了时间和日期都是文本类型，不方便"）
    num_cols = ("读数(mGal)", "观测时长(s)", "标准差(mGal)", "倾斜X(arcsec)")
    ok_num, bad_num = 0, []
    for k, r in enumerate(body2):
        raw = src_of(k)
        for name in num_cols:
            j = ci.get(name, -1)
            if j < 0 or j >= len(raw):
                continue
            want = float(raw[j])
            got = r[j] if j < len(r) else None
            if isinstance(got, (int, float)) and abs(float(got) - want) < 1e-9:
                ok_num += 1
            else:
                bad_num.append(f"{name}={got!r}(源 {raw[j]})")
    check("数值列写成数值（Excel 里能直接算）", not bad_num,
          f"{ok_num} 个数值单元格"
          + ("；异常 " + "，".join(bad_num[:3]) if bad_num else ""))

    # ② 编号列：去零后是纯数值 → 写**数值**，并用数字格式保留原文长度
    id_bad, id_num, id_txt = [], 0, 0
    for k, r in enumerate(body2):
        raw = src_of(k)
        for name in ("线号", "点号"):
            j = ci.get(name, -1)
            if j < 0 or j >= len(raw):
                continue
            want = format_id_cell(raw[j])
            got = r[j] if j < len(r) else None
            if want and _is_num_text(want):
                id_num += 1
                if not isinstance(got, (int, float)) or abs(float(got) - float(want)) > 1e-9:
                    id_bad.append(f"{name} {got!r} 不是数值（应 {want}）")
            else:
                id_txt += 1
                if str(got) != want:
                    id_bad.append(f"{name} {got!r} ≠ {want!r}")
    check("编号列是纯数字时写成数值、含字母时仍是文本", not id_bad,
          f"数值 {id_num} 个 / 文本 {id_txt} 个"
          + ("；" + "；".join(id_bad[:3]) if id_bad else ""))
    check("点号列不再出现 .0000000",
          all(".0000000" not in str(r[ci["点号"]]) for r in body2
              if ci.get("点号", -1) >= 0))
    check("点号的数字格式保留了原文长度（整数去零后为 0 位小数）",
          nfmt.get("点号", "") in ("0", "General", ""), f"格式 {nfmt.get('点号')!r}")

    # ②b 单元格取值规则（不需要造数据文件，直接测函数）
    from pickersrc.exporter import _cell_value
    for col, raw, want, why in [
        ("点号", "15.0000000", (15.0, "0"), "整数编号 → 数值 + 格式 0（不再是一串 0）"),
        ("点号", "12.5000000", (12.5, "0.0000000"),
         "带小数编号 → 数值 + 保留原长度 0.0000000"),
        ("线号", "0.0000000", (0.0, "0"), "0 → 数值 0"),
        ("点号", "1A", "1A", "含字母 → 原样文本"),
        ("点号", "1,000", "1,000", "千分位不是纯数值 → 文本"),
        ("读数(mGal)", "7432.742", 7432.742, "数值列 → 数值"),
        ("高程(m)", "30.3221", 30.3221, "数值列 → 数值"),
        ("时刻", "19:43:18", (_dt.time(19, 43, 18), "hh:mm:ss"), "时刻 → 真时间"),
        ("日期", "2025/06/23", (_dt.date(2025, 6, 23), "yyyy/mm/dd"), "日期 → 真日期"),
        ("日期", "2025/ 7/ 1", (_dt.date(2025, 7, 1), "yyyy/mm/dd"),
         "手簿里的 `2025/ 7/ 1` 也能认成日期"),
        ("时刻", "不是时间", "不是时间", "认不出来的原样留着，不许崩"),
        ("日期", "2025/13/45", "2025/13/45", "非法日期原样留文本"),
    ]:
        got = _cell_value(col, raw)
        check(f"{col} {raw!r} → {want!r}（{why}）", got == want, f"实得 {got!r}")

    # ②c Survey 文件头的字段类型（用户："SN 应该是数值，整数。Date 也提示未识别为日期。
    #     ZONE 和 GMT DIFF 也应该是数值，非文本"）
    from pickersrc.exporter import _kv_value
    for label, raw, want, why in [
        ("Instrument S/N", "41465", 41465, "S/N → 整数（不带 .0）"),
        ("ZONE", "0", 0, "ZONE → 数值"),
        ("GMT DIFF.", "-8.0", (-8.0, "0.0"), "GMT DIFF. → 数值 + 保留原文 1 位小数"),
        ("Date", "2025/ 7/ 1", (_dt.date(2025, 7, 1), "yyyy/mm/dd"), "Date → 真日期"),
        ("Time", "09:26:27", (_dt.time(9, 26, 27), "hh:mm:ss"), "Time → 真时间"),
        ("LONG", "106.6000000 E", "106.6000000 E", "LONG 带方向 → 仍是原文文本"),
        ("LAT", "37.4000000 N", "37.4000000 N", "LAT 带方向 → 仍是原文文本"),
        ("Survey name", "nx1465", "nx1465", "Survey 名 → 文本"),
    ]:
        got = _kv_value(label, raw)
        check(f"文件头 {label}: {raw!r} → {want!r}（{why}）", got == want, f"实得 {got!r}")

    # 真导一份，确认小数编号在文件里的格式确实是「保留原长度」
    t2 = XLSX.parent / "小数编号.xlsx"
    export_xlsx(f, idx[:1], ColOrder(order=list(cols)), t2, mode="parsed")
    wb3 = load_workbook(t2)
    ws3 = wb3.active
    dec_ok = True
    for j, name in enumerate(list(cols)):
        cell = ws3.cell(row=2, column=j + 1)
        if name in ("线号", "点号") and isinstance(cell.value, (int, float)):
            if "." in str(cell.value) and cell.number_format == "0":
                dec_ok = False
    wb3.close()
    check("编号带小数时用「0.000…」格式保留原长度", dec_ok)

    # ③ 时刻 / 日期写**真时间 / 真日期**（用户："WPS 提示该数据未识别为日期"）
    #    data_type 'd' = Excel 认它是日期/时间；显示靠数字格式保持原样。
    d_val, d_type, d_fmt = dt_cell
    t_val, t_type, t_fmt = tm_cell
    check("日期列是真日期（Excel 认日期，不再打绿三角）",
          d_type == "d" and isinstance(d_val, (_dt.date, _dt.datetime)),
          f"{d_val!r} type={d_type!r} fmt={d_fmt!r}")
    check("日期的显示格式还是 yyyy/mm/dd（显示不变）", d_fmt == "yyyy/mm/dd",
          f"fmt={d_fmt!r}")
    check("时刻列是真时间（'d' 类型）",
          t_type == "d" and isinstance(t_val, (_dt.time, _dt.datetime)),
          f"{t_val!r} type={t_type!r} fmt={t_fmt!r}")
    check("时刻的显示格式还是 hh:mm:ss（显示不变）", t_fmt == "hh:mm:ss",
          f"fmt={t_fmt!r}")
    #   逐行核对：日期/时刻的"显示形态"必须与源文件逐字一致
    dt_bad = []
    for k, r in enumerate(body2):
        raw_d = src_of(k)[ci["日期"]]
        raw_t = src_of(k)[ci["时刻"]]
        got_d, got_t = r[ci["日期"]], r[ci["时刻"]]
        if not isinstance(got_d, (_dt.date, _dt.datetime)):
            dt_bad.append(f"日期 {got_d!r} 不是日期")
        elif got_d.strftime("%Y/%m/%d") != raw_d.strip():
            dt_bad.append(f"日期 {got_d.strftime('%Y/%m/%d')} ≠ {raw_d!r}")
        if not isinstance(got_t, (_dt.time, _dt.datetime)):
            dt_bad.append(f"时刻 {got_t!r} 不是时间")
        elif got_t.strftime("%H:%M:%S") != raw_t.strip():
            dt_bad.append(f"时刻 {got_t.strftime('%H:%M:%S')} ≠ {raw_t!r}")
    check("每一行的日期/时刻显示形态都与源文件逐字一致", not dt_bad,
          "；".join(dt_bad[:3]) if dt_bad else f"{len(body2)} 行全部通过")

    # ③b Survey 文件头块里的字段类型（用户："SN 应该是数值，整数。Date 也提示未识别
    #     为日期。ZONE 和 GMT DIFF 也应该是数值，非文本"）
    def _kv(label: str):
        return kv_cells.get(label, (None, None, None))

    raw_kv = dict(survey_headers(f, idx)[0][1])          # 原文里这几个字段的样子

    sn_v, sn_t, sn_f = _kv("Instrument S/N")
    check("文件头 S/N 写成数值（整数）",
          sn_t == "n" and isinstance(sn_v, (int, float))
          and float(sn_v) == float(raw_kv["Instrument S/N"])
          and float(sn_v).is_integer(),
          f"S/N = {sn_v!r}（原文 {raw_kv['Instrument S/N']!r}）type={sn_t!r} fmt={sn_f!r}")
    z_v, z_t, _z_f = _kv("ZONE")
    check("文件头 ZONE 写成数值", z_t == "n" and isinstance(z_v, (int, float)),
          f"ZONE = {z_v!r}（原文 {raw_kv['ZONE']!r}）type={z_t!r}")
    g_v, g_t, _g_f = _kv("GMT DIFF.")
    check("文件头 GMT DIFF. 写成数值",
          g_t == "n" and isinstance(g_v, (int, float))
          and abs(float(g_v) - float(raw_kv["GMT DIFF."])) < 1e-9,
          f"GMT DIFF. = {g_v!r}（原文 {raw_kv['GMT DIFF.']!r}）type={g_t!r}")
    hd_v, hd_t, hd_f = _kv("Date")
    check("文件头 Date 是真日期（WPS 不再提示未识别）", hd_t == "d",
          f"Date = {hd_v!r}（原文 {raw_kv['Date']!r}）type={hd_t!r} fmt={hd_f!r}")
    ht_v, ht_t, _ht_f = _kv("Time")
    check("文件头 Time 是真时间", ht_t == "d",
          f"Time = {ht_v!r}（原文 {raw_kv['Time']!r}）type={ht_t!r}")
    lo_v, lo_t, _ = _kv("LONG")
    la_v, la_t, _ = _kv("LAT")
    check("文件头 LONG / LAT 仍是原文文本（带方向，不能被数值化）",
          lo_t == "s" and la_t == "s"
          and lo_v == raw_kv["LONG"].strip() and la_v == raw_kv["LAT"].strip()
          and (" E" in lo_v and " N" in la_v),
          f"LONG={lo_v!r} LAT={la_v!r}")
    nm_v, nm_t, _ = _kv("Survey name")
    check("文件头 Survey name / Client / Operator 仍是文本",
          nm_t == "s" and _kv("Client")[1] == "s" and _kv("Operator")[1] == "s",
          f"Survey name={nm_v!r}")

    # ⑤ 「处理理由」列只在**勾了**「附「处理理由」列」时才写
    #   （用户报："处理理由 / 最终取值 这一列为什么又加上了" —— 是他没勾却出现了？不是：
    #    对话框默认不勾，导出也就没有这列。这里把两头都钉住。）
    from pickersrc.colorder import REASON_COL
    from pickersrc.window import ExportDialog

    check("没勾「附处理理由列」时，导出的表头里没有「处理理由」",
          REASON_COL not in [str(x) for x in hdr2] and len(hdr2) == len(f.columns),
          f"表头 {len(hdr2)} 列（源文件 {len(f.columns)} 列）：{hdr2[-3:]}")
    dlg = ExportDialog(n_scope=len(idx), n_keep=len(idx))
    check("导出对话框默认不勾「附「处理理由」列」", not dlg.with_reason())
    # ★ 用户口径（本轮）："导出时默认勾选包含 survey" → 默认**勾上**
    check("导出对话框默认**勾上**「附 Survey 文件头」", dlg.with_survey_header())
    dlg.deleteLater()


# =====================================================================
def test_display_rule() -> None:
    print("\n[2] 线号/点号显示规则（整数去零 / 小数原样 / 含字母符号原样）")
    from pickersrc.display import format_id_cell as f

    for raw, want, why in [
        ("0.0000000", "0", "整数 → 去零"),
        ("1110.0000000", "1110", "整数 → 去零"),
        ("12.5000000", "12.5000000", "有小数 → 原样保留，不截断"),
        ("0.5", "0.5", "有小数 → 原样"),
        ("-2.000", "-2", "负整数 → 去零"),
        ("1A", "1A", "含字母 → 原样"),
        ("L-3", "L-3", "含字母+符号 → 原样"),
        ("2+3", "2+3", "含符号 → 原样"),
        ("1e5", "1e5", "科学计数法不算纯数值 → 原样"),
        ("1,000", "1,000", "千分位 → 原样"),
        ("", "", "空串 → 原样"),
    ]:
        got = f(raw)
        check(f"{raw!r} → {want!r}（{why}）", got == want, f"实得 {got!r}")


# =====================================================================
def test_scope(app) -> None:
    print("\n[3] 范围：先选主线（日期 / Survey），另一条线在右侧自动跟随")
    from pickersrc.scope_widget import MODE_DATE, MODE_SURVEY
    from pickersrc.window import MainWindow

    win = MainWindow()
    win.show()
    win.load_file(str(MULTI))
    sw, f = win.scope_widget, win.f

    # ---- 默认：按日期、最新一天；右边自动是那天里的 Survey（全选） ----
    check("默认主线 = 按日期", sw.mode() == MODE_DATE, sw.mode())
    check("主线（左）是日期、跟随线（右）是 Survey",
          sw.primary() is sw.dates and sw.secondary() is sw.surveys)
    check("日期列表列全", sw.dates.count() == len(f.dates),
          f"{sw.dates.count()} 项 = {len(f.dates)} 天")
    check("默认只勾最新一天", sw.selected_dates() == {f.dates[0]},
          str(sorted(sw.selected_dates())))
    check("右侧 Survey = 最新一天里的那些（不是整个文件的）",
          sw.selected_surveys() == set(f.surveys_on({f.dates[0]})),
          f"{sorted(sw.selected_surveys())} / 全部 {f.survey_names()}")
    check("右侧 Survey 默认全选（列出来的都勾上）",
          len(sw.selected_surveys()) == sw.surveys.count(),
          f"{len(sw.selected_surveys())}/{sw.surveys.count()}")
    check("右侧条数按左侧勾选统计（不是整份文件的条数）",
          sw.surveys.count() == len(f.surveys_on({f.dates[0]})),
          f"列了 {sw.surveys.count()} 个 Survey")
    # 用户要求："survey 列表后面加上经纬度的显示"
    items = [sw.surveys.list.item(i).text() for i in range(sw.surveys.count())]
    check("Survey 列表项带经纬度",
          bool(items) and all(("N" in t or "S" in t) and ("E" in t or "W" in t)
                              for t in items),
          items[0] if items else "—")
    if items:
        name = items[0].split("（")[0]
        info = f.survey_info(name)
        want_ll = (f"{abs(info['latitude']):.4f}"
                   f"{'N' if info['latitude'] >= 0 else 'S'} "
                   f"{abs(info['longitude']):.4f}"
                   f"{'E' if info['longitude'] >= 0 else 'W'}")
        check("经纬度与 Survey 头一致", want_ll in items[0],
              f"{want_ll} ⊂ {items[0]!r}")

    # ---- 改日期 → 右侧自动重建（并集、默认全选） ----
    alt = f.dates[:3]
    sw.dates.set_all(False)
    sw.dates.set_values(alt)
    win._render()
    check("改日期后右侧自动重建为这些天的 Survey",
          set(sw.surveys.values_all()) == set(f.surveys_on(set(alt))),
          f"{sorted(sw.surveys.values_all())}")
    check("重建后默认全选", sw.selected_surveys() == set(f.surveys_on(set(alt))),
          f"{len(sw.selected_surveys())} 个")
    want = len([r for r in f.rows if r.date in set(alt)])
    check("多选日期 → 这些天的全部观测", len(win.scope) == want,
          f"{len(win.scope)}（期望 {want}）")

    # ---- 右侧取消一个 Survey → 交集 ----
    alls = sw.surveys.values_all()
    if len(alls) >= 2:
        drop = alls[0]
        sw.surveys.set_values([s for s in alls if s != drop])
        win._render()
        want = len([r for r in f.rows
                    if r.date in set(alt) and r.survey != drop])
        check("取消右侧某个 Survey → 交集少掉这些观测",
              len(win.scope) == want, f"{len(win.scope)}（期望 {want}）")

    # ---- 切到「按 Survey」主线：右侧换成日期，默认只勾最新一天 ----
    sw.set_mode(MODE_SURVEY)
    win._render()
    check("主线（左）换成 Survey、跟随线（右）换成日期",
          sw.primary() is sw.surveys and sw.secondary() is sw.dates)
    check("按 Survey 默认 = 最新那天的 Survey",
          sw.selected_surveys() == set(f.surveys_on({f.dates[0]})),
          f"{sorted(sw.selected_surveys())}")
    check("右侧日期默认只勾最新一天", sw.selected_dates() == {f.dates[0]},
          f"{sorted(sw.selected_dates())}")

    one = f.survey_names()[:1]
    sw.surveys.set_all(False)
    sw.surveys.set_values(one)
    win._render()
    ds = f.dates_of(set(one))                     # 最新在前
    check("右侧日期 = 这些 Survey 出现过的日期（只列这些）",
          set(sw.dates.values_all()) == set(ds),
          f"{sw.dates.values_all()}")
    check("右侧日期默认只勾最新一天", sw.selected_dates() == {ds[0]},
          f"{sorted(sw.selected_dates())}（最新 {ds[0]}）")
    want = len([r for r in f.rows if r.survey in set(one) and r.date == ds[0]])
    check("范围 = 这些 Survey ∩ 最新一天", len(win.scope) == want,
          f"{len(win.scope)}（期望 {want}）")

    # ---- 右边多勾几天 → 范围变大 ----
    if len(ds) >= 2:
        sw.dates.set_values(ds)
        win._render()
        want = len([r for r in f.rows if r.survey in set(one)])
        check("右侧把日期全勾上 → 这些 Survey 的全部观测",
              len(win.scope) == want, f"{len(win.scope)}（期望 {want}）")

    # ---- 主线清空 → 跟随线也清空 → 范围 0 条（两条线是"且"，缺一边就是 0） ----
    # （确定性优先：主线空了就没有"对应的另一条线"，不保留上一次的日期，
    #   免得出现"明明清空了 Survey，范围却还在偷偷按日期过滤"）
    sw.surveys.set_all(False)
    win._render()
    check("主线清空 → 跟随线一起清空",
          not sw.selected_dates(), f"右侧还剩 {len(sw.selected_dates())} 天")
    check("两条线缺一条 → 0 条（不是「不限」，也不是整份文件）",
          len(win.scope) == 0, f"{len(win.scope)}/{len(f.rows)}")
    # 关键回归：把日期「清空」绝不能变成"全部观测"（用户报的 bug）
    sw.set_mode(MODE_DATE)
    win._render()
    sw.dates.set_all(False)
    win._render()
    check("日期清空 → 0 条（曾经错误地变成整份文件 3847 条）",
          len(win.scope) == 0, f"{len(win.scope)} 条")
    sw.dates.set_all(True)
    win._render()
    check("日期「全选」后又能出数据（两条线都在）",
          len(win.scope) > 0, f"{len(win.scope)} 条")
    check("此时主线仍是日期、勾的是全部日期",
          sw.mode() == MODE_DATE and len(sw.selected_dates()) == len(f.dates),
          f"{sw.dates.count()} 项，勾了 {len(sw.selected_dates())} 天")
    # 切换主线会回到该主线的默认值（按日期 = 最新一天）
    sw.set_mode(MODE_SURVEY)
    sw.set_mode(MODE_DATE)
    win._render()
    check("切到「按 Survey」再切回来 → 主线的默认值重新生效",
          sw.selected_dates() == {f.dates[0]}, f"{sorted(sw.selected_dates())}")
    win.close()


# =====================================================================
def test_presets(app, tmp: Path) -> None:
    print("\n[4] 「筛选条件」= 存储的参数组合")
    from pickersrc.presets import PresetStore
    from pickersrc.rules import logic_text
    from pickersrc.window import MainWindow

    store = PresetStore(tmp / "presets.json")
    check("内置组合已载入", len(store.presets) >= 4, f"{store.names()}")
    check("首次运行落盘一份", (tmp / "presets.json").exists())
    check("「严格互差」已按用户要求去掉",
          not any("严格" in n for n in store.names()), f"{store.names()}")
    check("「全不勾选」已按用户要求去掉",
          not any("全不勾选" in n for n in store.names()), f"{store.names()}")

    # 按"默认"这个内置 key 找，不写死名字（名字里带阈值，改默认值就会失效）
    default_names = [n for n in store.names() if n.startswith("默认")]
    check("内置组合里有「默认」那一套", bool(default_names), f"{default_names}")
    p = store.get(default_names[0]) if default_names else None
    check("能取到默认组合", p is not None)
    if p:
        conds = p.instantiate()
        check("组合实例化后条件全部勾选", all(c.enabled for c in conds),
              f"{len(conds)} 条")
        # ★ 新默认（用户指定）：(互差3次/5μGal 或 互差2次/1μGal) 且 时长≥35s
        #   ★ 本轮：「分段间隔」从「最终取值」的参数里拆出来，单独一条（且）
        check("默认组合 = 两条互差(或) + 时长(首要) + 最终取值(且) + 分段间隔(且)",
              len(conds) == 5,
              "；".join(f"{c.brief()}[{c.link_cn}]" for c in conds))
        _dur = next((c for c in conds if c.kind == "duration"), None)
        check("默认组合里的观测时长是 35 s",
              _dur is not None and float(_dur.params.get("lo")) == 35.0,
              _dur.describe() if _dur else "缺")
        _md = [c for c in conds if c.kind == "mutual_diff"]
        check("两条互差分别是 3次/5 与 2次/1",
              sorted((int(c.params.get("n")), float(c.params.get("limit_uGal")))
                     for c in _md) == [(2, 1.0), (3, 5.0)],
              "；".join(c.brief() for c in _md))
        check("两条互差的连接词都是「或」",
              all(c.link == "or" for c in _md),
              "；".join(c.link for c in _md))
        _fp = next((c for c in conds if c.kind == "final_pick"), None)
        check("默认组合里有「最终取值」，且默认取最新",
              _fp is not None and _fp.params.get("mode") == "latest"
              and _fp.link == "and",
              _fp.describe() if _fp else "缺")
        check("「最终取值」的参数里**不再**有分段间隔（已拆成独立一条）",
              _fp is not None and "gap_min" not in _fp.params,
              f"{_fp.params if _fp else '缺'}")
        _sg = next((c for c in conds if c.kind == "seg_gap"), None)
        check("默认组合里有独立的「分段间隔」，值 5 min、连接词「且」",
              _sg is not None and float(_sg.params.get("gap_min")) == 5.0
              and _sg.link == "and",
              _sg.describe() if _sg else "缺")
        check("默认组合的判定式就是用户要的那一句",
              logic_text(conds) == "(互差 3次/5μGal 或 互差 2次/1μGal) 且 时长 ≥35s"
                                   " 且 最终取值 最新 且 分段间隔 >5 min",
              logic_text(conds))

    ok, msg = store.add("测试组合", p.instantiate() if p else [])
    check("新增组合", ok, msg)
    # ★ 老预设（分段间隔还塞在「最终取值」参数里）读进来要自动拆成独立一条
    from pickersrc.presets import Preset

    _old = Preset.from_dict({
        "name": "老预设", "conds": [
            {"kind": "final_pick", "params": {"mode": "min_dev", "gap_min": 10.0},
             "enabled": True, "link": "and"}]})
    check("老预设 JSON 的 final_pick.gap_min 自动拆成「分段间隔」",
          [c.kind for c in _old.conds] == ["final_pick", "seg_gap"]
          and _old.conds[0].params == {"mode": "min_dev"}
          and float(_old.conds[1].params["gap_min"]) == 10.0
          and _old.conds[1].link == "and",
          "；".join(f"{c.kind}{c.params}[{c.link_cn}]" for c in _old.conds))
    ok, msg = store.add("测试组合", [], overwrite=False)
    check("重名被拒绝（未 overwrite）", not ok, msg)
    ok, msg = store.rename("测试组合", "改名后")
    check("重命名", ok and store.get("改名后") is not None, msg)
    ok, msg = store.rename(store.presets[0].name, "X")
    check("内置组合不能改名", not ok, msg)
    ok, msg = store.remove("改名后")
    check("删除", ok and store.get("改名后") is None, msg)
    ok, msg = store.remove(store.presets[0].name)
    check("内置组合不能删除", not ok, msg)
    check("落盘是合法 JSON",
          isinstance(json.loads((tmp / "presets.json").read_text(encoding="utf-8")), dict))

    win = MainWindow()
    win.store = PresetStore(tmp / "p2.json")
    win._reload_preset_combo()
    win.show()
    win.load_file(str(SRC))
    check("下拉列出全部组合",
          win.cmb_preset.count() == len(win.store.presets),
          f"{win.cmb_preset.count()} 项")

    i = win.cmb_preset.findData("仅互差：连续3互差5")
    if check("找得到「仅互差」组合", i >= 0):
        win.cmb_preset.setCurrentIndex(i)
        win._on_preset_activated(i)
        check("切换后整条栈被替换",
              len(win.conds) == 1 and win.conds[0].kind == "mutual_diff",
              "；".join(c.describe() for c in win.conds))
        check("切换后条件全部勾选", all(c.enabled for c in win.conds))
        check("切换后立即生效", len(win._keep_rows) < len(win.scope),
              f"保留 {len(win._keep_rows)}/{len(win.scope)}")

    win.conds[0].enabled = False
    win._render()
    win._refresh_preset_state()
    check("改动后提示与组合不一致", "已不同于" in win.lbl_preset_state.text(),
          win.lbl_preset_state.text()[:36])

    check("存在控件 cmb_preset", hasattr(win, "cmb_preset"))
    check("存在控件 lbl_preset_state", hasattr(win, "lbl_preset_state"))
    # ★ 用户要求：删掉「筛选条件」右侧那三个按钮
    for gone in ("btn_preset_save", "btn_preset_rename", "btn_preset_del",
                 "btn_cond_add", "btn_cond_edit", "btn_cond_del",
                 "cmb_date", "lst_survey", "lbl_scope"):
        check(f"控件 {gone} 已移除", not hasattr(win, gone))
    # ★ 组合名很长，下拉必须够宽才看得清
    # ★ 为了让 ② 面板能压窄，下拉**框**故意允许压到 200；
    #   长组合名的完整可读性由**展开列表**的宽度保证。
    check("筛选条件下拉框允许压窄（≤260，不会顶宽面板）",
          win.cmb_preset.minimumWidth() <= 260,
          f"minimumWidth={win.cmb_preset.minimumWidth()}")
    check("下拉展开列表足够宽，长组合名看得全（≥400px）",
          win.cmb_preset.view().minimumWidth() >= 400,
          f"列表宽={win.cmb_preset.view().minimumWidth()}")
    longest = max((win.cmb_preset.itemText(i) for i in range(win.cmb_preset.count())),
                  key=len)
    check("存在长组合名（依赖列表宽度展示）", len(longest) >= 20,
          f"最长名 {len(longest)} 字：{longest}")
    check("有「参数组合 ▾」菜单按钮承接存/改名/删除",
          hasattr(win, "btn_preset_menu")
          and "参数组合" in win.btn_preset_menu.text(),
          win.btn_preset_menu.text() if hasattr(win, "btn_preset_menu") else "缺失")

    from PySide6.QtWidgets import QPushButton

    # ② 面板要压窄 → 增删改收进「条件 ▾」菜单，上下移只留箭头
    texts = [b.text() for b in win.findChildren(QPushButton)]
    check("条件栈操作收成一个「条件 ▾」菜单按钮",
          any(t.startswith("条件") for t in texts), f"{texts}")
    check("保留上移 / 下移箭头按钮",
          "▲" in texts and "▼" in texts, f"{texts}")
    check("右键菜单仍可增删改",
          hasattr(win, "_cond_context_menu") and hasattr(win, "_cond_menu"))
    win.close()


# =====================================================================
def keys2_of(win, col):
    """取某窗口某列的排序键（视图行序）。"""
    return [win.model.sort_key(win.proxy.mapToSource(win.proxy.index(r, col)).row(), col)
            for r in range(win.model.rowCount())]


def test_column_order_and_sort(app) -> None:
    print("\n[4b] 列序置顶 + 排序只对数据列起效")
    from PySide6.QtCore import Qt

    from pickersrc.colorder import ColOrder, default_visible
    from pickersrc.rules import Cond
    from pickersrc.table_model import CHK_COL
    from pickersrc.window import MainWindow

    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    win.conds = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})]
    win._refresh_cond_table()
    win._render()
    cols = win.model.columns_

    # ★ 勾选框 + 处理理由 置顶
    check("第一列是勾选框", cols[0] == CHK_COL, f"{cols[:3]}")
    check("第二列是处理理由", cols[1] == "处理理由", f"{cols[:3]}")
    check("第三列起是真实数据列（默认 线号）", cols[2] == "线号", f"{cols[:4]}")
    check("默认数据列顺序仍以 线号/点号/读数/时长 打头",
          cols[2:6] == ["线号", "点号", "读数(mGal)", "观测时长(s)"],
          "、".join(cols[2:6]))

    # 列序在自定义列设置后依然把这两列放最前
    co = ColOrder(order=default_visible(win.f.columns), reason=True)
    shown = co.display_columns(win.f.columns)
    check("ColOrder.display_columns 也把勾选框/理由置顶",
          shown[0] == CHK_COL and shown[1] == "处理理由", f"{shown[:3]}")
    co_off = ColOrder(order=default_visible(win.f.columns), reason=False)
    check("关掉理由列时仍保留勾选框列",
          co_off.display_columns(win.f.columns)[0] == CHK_COL,
          f"{co_off.display_columns(win.f.columns)[:3]}")

    # ★ 排序只对数据列
    check("表头排序已启用", win.table.isSortingEnabled())
    check("勾选框列不可排", not win.proxy.is_sortable(0))
    check("处理理由列不可排", not win.proxy.is_sortable(1))
    c_line = cols.index("线号")
    c_raw = cols.index("读数(mGal)")
    check("线号列可排", win.proxy.is_sortable(c_line))
    check("读数列可排", win.proxy.is_sortable(c_raw))

    # 点不可排的列 → 行序不变、sortColumn 不变
    before = [win.model.source_row(r) for r in range(min(10, win.model.rowCount()))]
    win._on_sort_requested(0, Qt.SortOrder.AscendingOrder)
    after = [win.model.source_row(r) for r in range(min(10, win.model.rowCount()))]
    check("点勾选框列不改变行序", before == after)

    def keys(col):
        return [win.model.sort_key(win.proxy.mapToSource(win.proxy.index(r, col)).row(),
                                   col) for r in range(win.model.rowCount())]

    def finite(seq):
        return [v for v in seq if not (isinstance(v, float) and v != v)]

    # 数值列按数值排：读数降序应单调不增（NaN 当空值、被排到最后）
    win._on_sort_requested(c_raw, Qt.SortOrder.DescendingOrder)
    vals = keys(c_raw)
    fv = finite(vals)
    check("读数按数值降序排（不是字典序）",
          all(a >= b for a, b in zip(fv, fv[1:])),
          f"{[round(v, 3) for v in fv[:4]]} … {[round(v, 3) for v in fv[-3:]]}")
    check("空值/NaN 排在末尾", not any(isinstance(v, float) and v != v for v in vals[:len(fv)]),
          f"共 {len(vals)} 行，有效 {len(fv)} 行")

    # 编号列按数值排（`10` 要排在 `9` 之后，而**不是**字典序排在 `1` 之后）
    # 注意：0701/0711 的**线号**在整份文件里只有一个值，测不出数值序；
    # 点号在单日范围内最大只到 9，也区分不出字典序 —— 所以放开日期、看全部日期。
    sw = win.scope_widget
    # 两条线是"且"（求交集）：要"整份文件"就两条都全选（全清空 = 0 条）
    sw.dates.set_all(True)
    sw.surveys.set_all(True)
    win._render()
    check("两条线都全选后纳入全部观测", len(win.scope) == len(win.f.rows),
          f"{len(win.scope)}/{len(win.f.rows)}")

    c_st = cols.index("点号")
    win._on_sort_requested(c_st, Qt.SortOrder.AscendingOrder)
    sv = finite(keys(c_st))
    distinct = sorted(set(sv))
    check("点号按数值升序", all(a <= b for a, b in zip(sv, sv[1:])),
          f"最小 {distinct[:4]} … 最大 {distinct[-4:]}")
    check("存在两位以上编号（能区分数值序与字典序）",
          any(v >= 10 for v in distinct),
          f"最大值 {max(distinct) if distinct else '—'}，共 {len(distinct)} 个不同值")
    # 数值序下，**最后**一个 9 必须排在**第一个** 10 之前
    # （字典序会先排 10、11… 再排 2，9 反而落在 10 后面 —— 这里就是要锁住这点）
    if 9.0 in sv and 10.0 in sv:
        last9 = len(sv) - 1 - sv[::-1].index(9.0)
        first10 = sv.index(10.0)
        check("数值序：最后一个 9 排在第一个 10 之前",
              last9 < first10, f"last9={last9}, first10={first10}")
        check("数值序与字典序确实不同（字典序会把 10 排在 2 前面）",
              sorted(map(str, distinct)) != [str(v) for v in distinct],
              f"字典序前 4：{sorted(map(str, distinct))[:4]}　数值序前 4："
              f"{[str(v) for v in distinct][:4]}")

    # 多 Survey 文件里点号有 342 个不同值，顺带确认排序在更大的取值域上也成立
    win2 = MainWindow()
    win2.show()
    win2.load_file(str(MULTI))
    c2 = win2.model.columns_.index("点号")
    sw2 = win2.scope_widget
    sw2.dates.set_all(True)
    sw2.surveys.set_all(True)          # 两条线都全选 → 342 个不同点号才进得了表
    win2._render()
    win2._on_sort_requested(c2, Qt.SortOrder.AscendingOrder)
    lv = [v for v in keys2_of(win2, c2) if not (isinstance(v, float) and v != v)]
    check("多 Survey 文件（点号取值域大）也按数值升序",
          all(a <= b for a, b in zip(lv, lv[1:])) and max(lv) > 100,
          f"最大点号 {max(lv) if lv else '—'}，表 {win2.model.rowCount()} 行")
    win2.close()

    # 排序后勾选状态仍跟着"那一行"走
    checked_rows = {win.model.source_row(r) for r in range(win.model.rowCount())
                    if win.model.data(win.model.index(r, 0),
                                      Qt.ItemDataRole.CheckStateRole)
                    == Qt.CheckState.Checked}
    check("排序后勾选状态仍等于筛选结果", checked_rows == set(win._keep_rows),
          f"勾 {len(checked_rows)} / 保留 {len(win._keep_rows)}")

    # 表头提示说明"不参与排序"
    tip0 = win.model.headerData(0, Qt.Orientation.Horizontal,
                                Qt.ItemDataRole.ToolTipRole)
    tip1 = win.model.headerData(1, Qt.Orientation.Horizontal,
                                Qt.ItemDataRole.ToolTipRole)
    check("勾选框表头提示写明不参与排序", "不参与排序" in str(tip0))
    check("理由列表头提示写明不参与排序", "不参与排序" in str(tip1))
    win.close()


# =====================================================================
def test_cond_inline(app) -> None:
    print("\n[5] 条件栈内联操作 + 或/且分组")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QComboBox

    from pickersrc.rules import Cond, logic_text
    from pickersrc.window import MainWindow

    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    n0 = len(win.conds)
    win.conds.append(Cond("tilt_limit", {"limit_arcsec": 5.0}))
    win._refresh_cond_table()
    win._render()
    check("追加条件", len(win.conds) == n0 + 1 and win.tbl_cond.rowCount() == n0 + 1)

    win.tbl_cond.selectRow(0)
    before = [c.kind for c in win.conds]
    win._move_condition(+1)
    check("下移改变顺序", [c.kind for c in win.conds] != before,
          " → ".join(c.kind for c in win.conds))

    win.tbl_cond.selectRow(len(win.conds) - 1)
    win._del_condition()
    check("删除条件", len(win.conds) == n0 and win.tbl_cond.rowCount() == n0)

    win.show_all_data()
    n1 = len(win._keep_rows)
    win.conds[0].enabled = False
    win._render()
    # ★ 有了「或」之后，"取消勾选"不一定让保留数变多：取消一个或组成员会让或组更严。
    #   所以这里改成跟**独立重算**的结果比（与实现无关的判定）。
    from pickersrc.rules import apply_conditions as _apply
    _hits, _ = _apply(win.f, win.scope, win.conds)
    want_keep = sum(1 for h in _hits if h.keep)
    check("取消勾选立即生效（与独立重算一致）",
          len(win._keep_rows) == want_keep,
          f"{n1} → {len(win._keep_rows)}（重算 {want_keep}）")
    win.conds[0].enabled = True
    win._render()

    # ★ 「＋ 添加条件…」整条路径（曾经因为 window.py 少 import QListWidget：
    #   点菜单直接 NameError、异常闷在槽里，界面表现就是"添加条件没反应"）
    from pickersrc.rules import COND_KINDS
    from pickersrc.window import _PickKindDialog
    try:
        pk = _PickKindDialog(win)
        ok_pick = pk.lst.count() == len(COND_KINDS) and pk.kind() in COND_KINDS
        detail = f"{pk.lst.count()} 种，默认选中 {pk.kind()!r}"
        pk.deleteLater()
    except Exception as e:                            # noqa: BLE001
        ok_pick, detail = False, f"{type(e).__name__}: {e}"
    check("「添加条件」的类型选择对话框建得起来（不再 NameError）", ok_pick, detail)

    import pickersrc.window as W
    n2 = len(win.conds)
    orig_pick, orig_cond = W._PickKindDialog, W.CondDialog

    class _Pick:
        def __init__(self, *a, **k): pass
        def exec(self): return 1                      # QDialog.Accepted
        def kind(self): return "duration"
        def deleteLater(self): pass

    class _Cond:
        def __init__(self, *a, **k): pass
        def exec(self): return 1
        def values(self): return {"lo": 40.0, "hi": 0.0}

    W._PickKindDialog, W.CondDialog = _Pick, _Cond
    try:
        win._add_condition()
    finally:
        W._PickKindDialog, W.CondDialog = orig_pick, orig_cond
    check("「添加条件」确实把新条件加进了条件栈",
          len(win.conds) == n2 + 1 and win.tbl_cond.rowCount() == n2 + 1,
          f"{n2} → {len(win.conds)}")

    # 列：勾选 | 连接 | 条件 | 参数 | 命中
    #   · 「连接」= 2 个汉字宽、「条件」= 4 个汉字宽、「参数」≤ 10 个汉字宽（用户本轮要求）
    #   · 剩余宽度全给「命中」，**横向不出现滚动条**（铺满、不左右滑动）
    fm = win.tbl_cond.fontMetrics()
    cjk = fm.horizontalAdvance("汉")           # 单字宽（"汉字"是两个字的宽度）
    w_link = win.tbl_cond.columnWidth(1)
    w_cond = win.tbl_cond.columnWidth(2)
    w_param = win.tbl_cond.columnWidth(3)
    check("「连接」列 ≈ 2 个汉字宽 + 下拉框余量（已加长）",
          cjk * 2 + 34 < w_link <= cjk * 2 + 64, f"{w_link}px（2 字 {cjk * 2}px）")
    check("「条件」列 ≈ 4 个汉字宽",
          abs(w_cond - (cjk * 4 + 10)) <= 20, f"{w_cond}px（4 字 {cjk * 4}px + 留白）")
    check("「参数」列在该宽度下尽量长（≤16 个汉字宽）",
          cjk * 4 < w_param <= cjk * 16 + 12, f"{w_param}px（16 字上限 {cjk * 16}px）")
    _long = max((fm.horizontalAdvance(str(win.tbl_cond.item(r, 3).text()))
                 for r in range(win.tbl_cond.rowCount())), default=0)
    check("「参数」列放得下最长的参数写法（不省略）",
          w_param >= _long + 6, f"列宽 {w_param}px / 最长参数 {_long}px")
    check("「参数」列比「命中」列长（用户：参数加长、命中缩短）",
          w_param > win.tbl_cond.columnWidth(4),
          f"参数 {w_param}px vs 命中 {win.tbl_cond.columnWidth(4)}px")
    check("横向滚动条是关的（铺满、不左右滑动）",
          win.tbl_cond.horizontalScrollBarPolicy()
          == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
          and not win.tbl_cond.horizontalScrollBar().isVisible(),
          f"{win.tbl_cond.horizontalScrollBarPolicy()}"
          f"／滚动条可见={win.tbl_cond.horizontalScrollBar().isVisible()}")
    _tot = sum(win.tbl_cond.columnWidth(c) for c in range(5))
    _view = win.tbl_cond.viewport().width()
    check("五列宽度之和 ≤ 视口宽度（铺得下，不被切）",
          _tot <= _view + 2, f"五列 {_tot}px vs 视口 {_view}px")
    check("「命中」列只留得下表头（缩短了）",
          fm.horizontalAdvance("命中") <= win.tbl_cond.columnWidth(4)
          <= fm.horizontalAdvance("命中") + 90,
          f"命中列 {win.tbl_cond.columnWidth(4)}px（表头 {fm.horizontalAdvance('命中')}px）")
    check("第 2 列是「连接」下拉框（首要/或/且）",
          isinstance(win.tbl_cond.cellWidget(0, 1), QComboBox)
          and [win.tbl_cond.cellWidget(0, 1).itemText(i)
               for i in range(win.tbl_cond.cellWidget(0, 1).count())]
          == ["首要", "或", "且"],
          f"{win.tbl_cond.cellWidget(0, 1)}")
    check("表头是 勾选｜连接｜条件｜参数｜命中",
          [win.tbl_cond.horizontalHeaderItem(i).text() for i in range(5)]
          == ["勾选", "连接", "条件", "参数", "命中"])
    check("命中数写在第 5 列", win.tbl_cond.item(0, 4) is not None)

    # ★ 用户问："为什么观测时长 连接改为 或，就全都满足了？"
    #   日志里现在有一行「剔除构成」，把"真不合格"与"合格但没被挑中"分开数 ——
    #   宽松条件（时长 180/184 满足）进「或」组后，或组几乎恒真 → 真剔除骤降。
    from pickersrc.rules import default_conditions as _dc

    win.conds = _dc()
    win._refresh_cond_table()
    win._render()
    _t1 = win.txt_summary.toPlainText()
    _line1 = next((l for l in _t1.splitlines() if "剔除构成" in l), "")
    win.conds = _dc()
    for _c in win.conds:
        if _c.kind == "duration":
            _c.link = "or"
    win._refresh_cond_table()
    win._render()
    _t2 = win.txt_summary.toPlainText()
    _line2 = next((l for l in _t2.splitlines() if "剔除构成" in l), "")
    _n1 = [int(x) for x in re.findall(r"\d+", _line1)]   # 不合格 / 或组 / 单条 / 满足条件
    _n2 = [int(x) for x in re.findall(r"\d+", _line2)]
    check("日志里有「剔除构成」这一行（分开数 真不合格 / 只是没被挑中）",
          bool(_line1) and bool(_line2), _line1)
    check("时长改「或」后：条件不合格骤降、满足条件暴涨（这就是「全都满足了」）",
          len(_n1) >= 4 and len(_n2) >= 4 and _n2[0] < _n1[0] and _n2[3] > _n1[3],
          f"首要：不合格 {_n1[0]} / 满足条件 {_n1[-1]}　→　"
          f"或：不合格 {_n2[0]} / 满足条件 {_n2[-1]}")

    # ★ 竖向分配（用户："上面减小，下面日志部分加大"）：
    #   条件表高度 = 现有条件占的行数（≤8 行不滚动），日志拿剩下的绝大部分。
    win.showMaximized()
    _hh = win.tbl_cond.horizontalHeader().height() or 32
    win.conds = [_dc()[1] for _ in range(5)]
    win._refresh_cond_table()
    for _ in range(3):
        app.processEvents()
    _min5, _max5 = win.tbl_cond.minimumHeight(), win.tbl_cond.maximumHeight()
    check("条件表下限 = 5 条条件正好 5 行（不用滚动就能看全）",
          _min5 >= _hh + 30 * 5, f"最低 {_min5}px（5 行 = {_hh + 30 * 5}px）")
    check("条件表上限 = 现有条件 + 1 行（5 条 → 6 行高）",
          abs(_max5 - (_hh + 30 * 6 + 6)) <= 2, f"最高 {_max5}px")
    win.conds = [_dc()[1] for _ in range(20)]
    win._refresh_cond_table()
    for _ in range(3):
        app.processEvents()
    _cap20 = win.tbl_cond.maximumHeight()
    check("条件再多也不超过 8 行高（其余滚动）",
          _cap20 <= _hh + 30 * 8 + 8, f"20 条时最高 {_cap20}px")
    win.conds = _dc()
    win._refresh_cond_table()
    win._render()
    for _ in range(3):
        app.processEvents()
    _panel_h = win.split.widget(0).height()
    _log_h, _tbl_h = win.txt_summary.height(), win.tbl_cond.height()
    if _panel_h >= 700:                       # 大窗口：日志必须明显更大
        check("日志比条件表高（下面加大）", _log_h > _tbl_h,
              f"② 面板 {_panel_h}px：日志 {_log_h}px vs 条件表 {_tbl_h}px")
    else:
        # 离屏窗口撑不到最大尺寸，这里只保证"日志有保底、条件表不超它需要的行数"
        check("小窗口下：日志有 120px 保底、条件表不超过它需要的行数",
              _log_h >= 120 and _tbl_h <= _hh + 30 * 8 + 8,
              f"② 面板 {_panel_h}px：日志 {_log_h}px / 条件表 {_tbl_h}px")
    win.close()


# =====================================================================
def test_table_view_modes(app) -> None:
    print("\n[6] 结果表显示模式（默认全部数据、筛出的打勾）")
    from PySide6.QtCore import Qt

    from pickersrc.rules import Cond
    from pickersrc.window import MainWindow

    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    win.conds = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})]
    win._refresh_cond_table()
    win._render()

    # 「显示全部数据」的复选框已按用户要求去掉（与右边那个切换按钮重复），
    # 状态改由 `win.show_all` 记
    check("默认显示全部数据（状态位）", win.show_all is True)
    check("左边不再有「显示全部数据」复选框", not hasattr(win, "chk_all_rows"))
    check("默认表格 = 整个范围的全部数据",
          win.model.rowCount() == len(win.scope),
          f"表 {win.model.rowCount()} 行 / 范围 {len(win.scope)}")

    checked = {win.model.source_row(r) for r in range(win.model.rowCount())
               if win.model.data(win.model.index(r, 0),
                                 Qt.ItemDataRole.CheckStateRole)
               == Qt.CheckState.Checked}
    check("筛选结果在表里是打勾状态（勾选框在第 0 列）",
          checked == set(win._keep_rows),
          f"打勾 {len(checked)} / 保留 {len(win._keep_rows)}")

    win.show_only_filtered()
    check("切换后只显示筛选结果",
          win.model.rowCount() == len(win._keep_rows)
          and win.show_all is False,
          f"表 {win.model.rowCount()} 行")
    check("按钮文字随之变化", "显示全部数据" in win.btn_only_filtered.text(),
          win.btn_only_filtered.text())
    win.show_all_data()
    check("切回全部数据", win.model.rowCount() == len(win.scope)
          and win.show_all is True, f"表 {win.model.rowCount()} 行")

    win.chk_only_manual.setChecked(True)
    check("勾「只看人工改过的」会取消「显示全部数据」",
          win.show_all is False)
    check("此时表为空（还没有人工干预）", win.model.rowCount() == 0)
    win.show_all_data()
    win.close()


# =====================================================================
def test_mutual_diff_last_value() -> None:
    print("\n[5b] 互差判定 + 「最终取值」挑选（判定与取值分开）")
    from pickersrc import cg5
    from pickersrc.grouping import group_by_station
    from pickersrc.rules import Cond, apply_conditions

    f = cg5.read_file(str(SRC))
    idx = f.subset(f.dates[0], f.surveys_of(f.dates[0]))
    groups = group_by_station([f.rows[i] for i in idx], f.columns)

    # ---- ① 只挂互差：判定合格的那 n 个读数**都算满足**（不再在这里挑一条） ----
    hits, _per = apply_conditions(f, idx, [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})])
    kept = [s for s, h in zip(idx, hits) if h.keep]
    check("互差条件有保留结果", bool(kept), f"{len(kept)} 条")
    check("互差只做判定：窗口内的读数都算满足（可以多于 1 条/点）",
          len(kept) >= len({f.rows[s].by(f.columns, "点号") for s in kept}),
          f"保留 {len(kept)} 条")
    short_groups = [g for g in groups if len(g) < 3]
    check("观测次数不足 n 次的测点不保留",
          all(not hits[g[-1]].keep for g in short_groups),
          f"<3 次的测点 {len(short_groups)} 个")

    # ---- ② 加上「最终取值」：**每一轮观测**只留一条 ----
    #   一轮 = 同点相邻间隔 ≤ `gap_min`（默认 5 min）的一串读数；
    #   基点一天被重复观测多轮时，每轮各留一条（不是全天只留一条）。
    GAP_MIN = 5.0

    def pick_of(mode: str, gap: float = GAP_MIN):
        cs = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0}, link="and"),
              Cond("final_pick", {"mode": mode, "gap_min": gap}, link="and")]
        h, _ = apply_conditions(f, idx, cs)
        return h, [s for s, hh in zip(idx, h) if hh.keep]

    def rounds_of(g: list[int]) -> list[list[int]]:
        """把某测点按时间间隔切成几轮（口径与 pick_final 一致）。"""
        out, cur = [], []
        for j in g:
            if cur:
                a = f.rows[idx[cur[-1]]].by(f.columns, "十进制时间")
                b = f.rows[idx[j]].by(f.columns, "十进制时间")
                try:
                    if (float(b) - float(a)) * 24 * 60 > GAP_MIN + 1e-9:
                        out.append(cur)
                        cur = []
                except ValueError:
                    pass
            cur.append(j)
        if cur:
            out.append(cur)
        return out

    hits_p, kept_p = pick_of("latest")
    all_rounds = [r for g in groups for r in rounds_of(g)]
    cnt = {}
    for s in kept_p:
        st = f.rows[s].by(f.columns, "点号")
        cnt[st] = cnt.get(st, 0) + 1
    check("加了「最终取值」后每一轮观测只留 1 条（不是全天只留一条）",
          bool(kept_p) and len(kept_p) <= len(all_rounds)
          and all(v >= 1 for v in cnt.values()),
          f"保留 {len(kept_p)} 条 / {len(all_rounds)} 轮观测；"
          f"涉及 {len(cnt)} 个测点，每点条数={sorted(set(cnt.values())) or '—'}")
    check("保留数 ≤ 测点数 × 轮数（每点每轮上限）",
          len(kept_p) <= len(groups) * 24,
          f"{len(kept_p)} 条 / {len(groups)} 个测点")
    # ★ 判定用**滑动窗口**，所以"合格"的读数不一定挨着序列末尾；「最新」的正确口径是
    #   "**每一轮里**合格读数中最新的一条"。
    ok_pre = {s for s, h in zip(idx, hits) if h.keep}      # hits = 只挂互差3/5 的结果
    wrong = []
    for g in groups:
        for run in rounds_of(g):
            cand = [idx[j] for j in run if idx[j] in ok_pre]
            if not cand:
                continue
            want = max(cand, key=lambda s: f.rows[s].by(f.columns, "十进制时间"))
            if want not in set(kept_p):
                wrong.append(f"点{f.rows[want].by(f.columns, '点号')}")
    check("「最新」= 每一轮里合格读数中最新的那条", not wrong,
          "；".join(wrong[:3]) if wrong else f"逐轮核对通过（{len(kept_p)} 条）")
    check("被挑中的行标了 picked（处理理由列要写「最终取值」）",
          all(h.picked for s, h in zip(idx, hits_p) if h.keep),
          f"{sum(1 for h in hits_p if h.picked)} 条标了 picked")
    # ★ 用户口径：满足条件但没被最终取值挑中的行 → 处理理由写「满足条件」（另一种颜色）
    losers = [h for h in hits_p if not h.keep and h.rule == "final_pick"]
    check("「最终取值」淘汰的行：理由=满足条件、passed=True",
          bool(losers) and all(h.passed and h.reason == "满足条件" for h in losers),
          f"{len(losers)} 条；例：{losers[0].reason!r}" if losers else "没有淘汰行")
    check("真正被条件剔除的行不带 passed（理由仍是那条条件）",
          all(not h.passed for h in hits_p if not h.keep and h.rule != "final_pick"),
          "ok")

    # ---- ③ 最小距平：同样是"每轮一条"，且选中的是那一轮里离均值最近的那条 ----
    _hits_m, kept_m = pick_of("min_dev")
    check("「最小距平」同样每轮只留 1 条",
          bool(kept_m) and len(kept_m) <= len(all_rounds),
          f"保留 {len(kept_m)} 条 / {len(all_rounds)} 轮")
    # 手算复核：逐轮比"离该轮合格读数均值最近"
    bad = []
    ok_m = {s for s, h in zip(idx, _hits_m) if h.keep}
    for g in groups:
        for run in rounds_of(g):
            # 该轮里"满足条件"的读数 = 没被条件剔除的（rule 为空 或 因最终取值被淘汰）
            cand = [idx[j] for j in run if _hits_m[j].rule in ("", "final_pick")]
            if len(cand) < 3:
                continue
            vals = [float(f.rows[s].by(f.columns, "读数(mGal)")) for s in cand]
            mean = sum(vals) / len(vals)
            want = min(cand, key=lambda s: abs(
                float(f.rows[s].by(f.columns, "读数(mGal)")) - mean))
            if want not in ok_m:
                bad.append(f"点{f.rows[want].by(f.columns, '点号')}")
    check("「最小距平」确实是那一轮里离合格读数均值最近的那条", not bad,
          "；".join(bad[:3]) if bad else f"逐轮复核通过（{len(kept_m)} 条）")

    # ---- ④ 限差收到 0 → 只会更严 ----
    hits0, _ = apply_conditions(f, idx, [Cond("mutual_diff", {"n": 3, "limit_uGal": 0.0})])
    n0_keep = sum(1 for h in hits0 if h.keep)
    check("限差为 0 时判定更严（不会放宽）", n0_keep <= len(kept),
          f"限差0 → {n0_keep} 条；限差5 → {len(kept)} 条")

    # ---- ⑤ 用户实测的坑：合格窗口出现在序列**中间**也必须算数 ----
    #   `1465_20250702.txt` 线0/点0 一天测了 11 次，其中 06:59:55 与 07:01:00
    #   **两次读数完全相同**（6822.267，互差 0 μGal）—— 曾因为"只看最后 n 次"
    #   被误判成「或组都不满足」。
    sub = (ROOT / "GravProc" / "examples" / "示例数据" / "宁夏"
           / "01_每日导出的重力仪原始数据" / "0702" / "1465" / "1465_20250702.txt")
    if sub.exists():
        g = cg5.read_file(str(sub))
        gidx = [i for i, r in enumerate(g.rows) if r.date == "2025-07-02"
                and r.by(g.columns, "线号") in ("0.0000000", "0")
                and r.by(g.columns, "点号") in ("0.0000000", "0")]
        pair = [i for i in gidx
                if g.rows[i].by(g.columns, "时刻") in ("06:59:55", "07:01:00")]
        gh, _ = apply_conditions(g, gidx, [Cond("mutual_diff", {"n": 2, "limit_uGal": 1.0})])
        pos = {i: k for k, i in enumerate(gidx)}
        check("中间位置的合格窗口也算数（1465 那两条 6822.267）",
              len(pair) == 2 and all(gh[pos[i]].keep for i in pair),
              f"该点合格 {sum(1 for h in gh if h.keep)}/{len(gidx)} 条")
        gh2, _ = apply_conditions(
            g, gidx, [Cond("mutual_diff", {"n": 2, "limit_uGal": 1.0}),
                      Cond("final_pick", {"mode": "latest"}, link="and")])
        kept2 = [i for i, h in zip(gidx, gh2) if h.keep]
        picked_times = sorted(g.rows[i].by(g.columns, "时刻") for i in kept2)
        check("该点每一轮各留一条，且都取该轮最后一次",
              picked_times == ["06:47:42", "07:01:00", "07:33:06"],
              f"取到 {picked_times}")
        check("每一条都标了「最终取值」（picked）",
              all(h.picked for h in gh2 if h.keep),
              f"{sum(1 for h in gh2 if h.picked)} 条")
        # 用户报的这 5 条：06:47:42 那条现在是「最终取值」，另两条是「满足条件」
        marks = {g.rows[i].by(g.columns, "时刻"):
                 ("最终取值" if gh2[pos[i]].picked
                  else ("满足条件" if gh2[pos[i]].passed else "剔除"))
                 for i in gidx}
        # 注意这里只挂了互差2/1：06:45:37 与 06:46:42 差 2 μGal，所以 06:45:37
        # 在这套条件下本来就该剔除；挂上默认的互差3/5 后它是"满足条件"
        # （窗口 .282/.284/.284 极差 2 μGal ≤ 5）。
        check("该轮：满足条件的标「满足条件」、挑中的标「最终取值」",
              marks.get("06:47:42") == "最终取值"
              and marks.get("06:46:42") == "满足条件"
              and marks.get("06:45:37") == "剔除",
              f"{ {k: marks[k] for k in ('06:45:37', '06:46:42', '06:47:42')} }")
    else:
        print(f"      （没找到 {sub.name}，跳过滑动窗口的实测回归）")


# =====================================================================
def test_row_styling_and_new_cond(app) -> None:
    print("\n[6b] 表格行底纹 / 勾选行字体 / 新条件 / 时长默认")
    from PySide6.QtCore import Qt

    from pickersrc.rules import COND_KINDS, Cond, apply_conditions, default_conditions
    from pickersrc.table_model import (C_BAND_A, C_BAND_B, C_CHECKED_TEXT,
                                       C_KEEP_BG_A, C_KEEP_BG_B)
    from pickersrc.window import MainWindow

    # ---- 出厂默认：时长 35 ----
    conds = default_conditions()
    desc = "；".join(c.describe() for c in conds)
    check("默认条件里有互差", any(c.kind == "mutual_diff" for c in conds), desc)
    dur = next((c for c in conds if c.kind == "duration"), None)
    check("默认观测时长 = 35 s", dur is not None and float(dur.params.get("lo")) == 35.0,
          desc)

    # ---- 新条件已在条件类型表里 ----
    check("条件类型表里有「独立观测间隔」", "independent_gap" in COND_KINDS,
          f"{len(COND_KINDS)} 种")
    if "independent_gap" in COND_KINDS:
        meta = COND_KINDS["independent_gap"]
        check("新条件默认间隔 = 5 min",
              float(meta.params.get("limit_min")) == 5.0, str(meta.params))
        check("新条件中文名含「独立」", "独立" in meta.cn, meta.cn)

    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    win._render()
    win.show_all_data()
    m = win.model
    st = m.columns_.index("点号")

    def bg(r):
        b = m.data(m.index(r, st), Qt.ItemDataRole.BackgroundRole)
        return b.color().name() if b else None

    cols = [bg(r) for r in range(m.rowCount())]
    # 打勾（保留）的行铺**淡黄**，所以底色一共四种：淡黄两色 + 白/浅蓝两色。
    kp = [bool(m._keep[r] and m._in_scope[r]) for r in range(m.rowCount())]
    keep_named = {C_KEEP_BG_A.name(), C_KEEP_BG_B.name()}
    band_named = {C_BAND_A.name(), C_BAND_B.name()}
    used = {c for c in cols}
    runs = []
    for c in cols:
        if runs and runs[-1][0] == c:
            runs[-1][1] += 1
        else:
            runs.append([c, 1])
    check("底纹只用四种颜色（打勾两色 + 普通两色）",
          used <= (keep_named | band_named), f"{used}")
    check("打勾的行只用淡黄两色",
          all(cols[r] in keep_named for r in range(len(cols)) if kp[r]),
          f"打勾 {sum(kp)} 行")
    check("没打勾的行只用白/浅蓝两色",
          all(cols[r] in band_named for r in range(len(cols)) if not kp[r]),
          f"没打勾 {len(kp) - sum(kp)} 行")
    check("相邻两段底色必定不同（仍是交替的带）",
          all(runs[i][0] != runs[i + 1][0] for i in range(len(runs) - 1)),
          f"{len(runs)} 段交替")
    # 换色只能有两个原因：换测点、或这一行的打勾状态变了
    ks = [m.data(m.index(r, st)) for r in range(m.rowCount())]
    chg = {i for i in range(len(ks) - 1) if ks[i] != ks[i + 1]}
    kchg = {i for i in range(len(kp) - 1) if kp[i] != kp[i + 1]}
    bchg = {i for i in range(len(cols) - 1) if cols[i] != cols[i + 1]}
    check("底纹换色处都能解释（换测点或换打勾状态）",
          bchg <= (chg | kchg),
          f"换色 {len(bchg)} 处 / 点号变化 {len(chg)} 处 / 打勾变化 {len(kchg)} 处，"
          f"无法解释 {len(bchg - (chg | kchg))} 处")

    # ---- 勾选行字体 ----
    kept_src = win._keep_rows[0]
    kr = m.view_row_of(kept_src)
    fg = m.data(m.index(kr, st), Qt.ItemDataRole.ForegroundRole)
    ft = m.data(m.index(kr, st), Qt.ItemDataRole.FontRole)
    check("打勾的行文字换成另一种颜色",
          fg is not None and fg.color().name() == C_CHECKED_TEXT.name(),
          fg.color().name() if fg else "None")
    check("打勾的行文字加粗", ft is not None and ft.bold())
    drop_src = next(s for s in win.scope if s in win.auto_reason)
    dr = m.view_row_of(drop_src)
    fg2 = m.data(m.index(dr, st), Qt.ItemDataRole.ForegroundRole)
    ft2 = m.data(m.index(dr, st), Qt.ItemDataRole.FontRole)
    check("未打勾的行不套用该颜色",
          fg2 is None or fg2.color().name() != C_CHECKED_TEXT.name(),
          fg2.color().name() if fg2 else "None")
    check("未打勾的行不加粗", ft2 is None or not ft2.bold())

    # ---- 新条件跑得通，且能作为"独立观测"用 ----
    idx = win.f.subset(win.f.dates[0], win.f.surveys_of(win.f.dates[0]))
    hits, _per = apply_conditions(win.f, idx,
                                  [Cond("independent_gap", {"limit_min": 5.0})])
    n_keep = sum(1 for h in hits if h.keep)
    check("新条件「独立观测间隔 5min」可执行", 0 < n_keep <= len(idx),
          f"保留 {n_keep} / {len(idx)}")
    # 间隔阈值越大 → 保留越少（单调性）
    hits2, _ = apply_conditions(win.f, idx,
                                [Cond("independent_gap", {"limit_min": 30.0})])
    n2 = sum(1 for h in hits2 if h.keep)
    check("阈值越大保留越少（单调）", n2 <= n_keep, f"5min→{n_keep}，30min→{n2}")

    # ---- 参数组合下拉仍可用（去掉两个内置后剩 4 个） ----
    names = [win.cmb_preset.itemData(i) for i in range(win.cmb_preset.count())]
    check("参数组合下拉仍可用", len(names) >= 4, f"{len(names)} 个")
    win.close()


# =====================================================================
def test_or_and_groups() -> None:
    print("\n[5c] 或 / 且 分组：判定式与真数据上的语义")
    from pickersrc.cg5 import read_file
    from pickersrc.rules import (Cond, apply_conditions, default_conditions,
                                 logic_text)

    conds = default_conditions()
    check("默认判定式就是用户要的那一句（含拆出来的「分段间隔」）",
          logic_text(conds) == "(互差 3次/5μGal 或 互差 2次/1μGal) 且 时长 ≥35s"
                               " 且 最终取值 最新 且 分段间隔 >5 min",
          logic_text(conds))
    # ★ 「分段间隔」单独成条后，取值结果必须与"塞在最终取值参数里"完全一致
    _gap_inside = [c for c in conds if c.kind != "seg_gap"]
    for c in _gap_inside:
        if c.kind == "final_pick":
            c.params["gap_min"] = 5.0
    f0 = read_file(str(SRC))
    i0 = f0.filter_scope({"2025-07-01"}, set(f0.surveys_on({"2025-07-01"})))
    _k_split = {i for i, h in zip(i0, apply_conditions(f0, i0, conds)[0]) if h.keep}
    _k_inside = {i for i, h in zip(i0, apply_conditions(f0, i0, _gap_inside)[0])
                 if h.keep}
    check("拆条前/后保留的观测完全相同（纯界面拆条，不改判定）",
          _k_split == _k_inside, f"拆条 {len(_k_split)} 条 / 旧写法 {len(_k_inside)} 条")
    check("「分段间隔」自己不剔除任何观测（命中 = 全部）",
          all(apply_conditions(f0, i0, [c])[0][k].keep
              for c in conds if c.kind == "seg_gap" for k in range(len(i0))),
          f"{len(i0)} 条全保留")
    # 「命中」列的口径：分段间隔 = 全部；最终取值 = **被它挑中的条数**（不是 0）
    _h2, _p2 = apply_conditions(f0, i0, conds)
    _sg2 = next(c for c in conds if c.kind == "seg_gap")
    _fp2 = next(c for c in conds if c.kind == "final_pick")
    _picked2 = sum(1 for h in _h2 if h.picked)
    check("「分段间隔」命中 = 范围内全部观测",
          _p2.get(_sg2.describe()) == len(i0),
          f"命中 {_p2.get(_sg2.describe())} / 共 {len(i0)}")
    check("「最终取值」命中 = 被它挑中的条数（不是 0）",
          _p2.get(_fp2.describe()) == _picked2 and _picked2 > 0,
          f"命中 {_p2.get(_fp2.describe())}（挑中 {_picked2}）")

    f = read_file(str(SRC))
    idx = f.filter_scope({"2025-07-01"}, set(f.surveys_on({"2025-07-01"})))

    def keep_of(cs) -> set[int]:
        hits, _ = apply_conditions(f, idx, cs)
        return {i for i, h in zip(idx, hits) if h.keep}

    m35 = Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})
    m21 = Cond("mutual_diff", {"n": 2, "limit_uGal": 1.0})
    dur = Cond("duration", {"lo": 35.0, "hi": 0.0})

    k35, k21, kdur = keep_of([m35]), keep_of([m21]), keep_of([dur])

    # 或组 = 两条互差取并集；再与"首要"时长取交集
    or_conds = [Cond("duration", {"lo": 35.0, "hi": 0.0}, link="primary"),
                Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0}, link="or"),
                Cond("mutual_diff", {"n": 2, "limit_uGal": 1.0}, link="or")]
    k_or = keep_of(or_conds)
    check("「或」= 两条互差取并集，再与首要条件取交集",
          k_or == kdur & (k35 | k21),
          f"或组 {len(k_or)} 条；手算 {len(kdur & (k35 | k21))} 条")
    check("「或」比「且」宽（同样的两条互差）",
          len(k_or) > len(keep_of([dur, m35, m21])),
          f"或 {len(k_or)} vs 且 {len(keep_of([dur, m35, m21]))}")
    check("「或」里任一条单独合格的行都在或组结果里（再过一遍首要条件）",
          (k35 & kdur) <= k_or and (k21 & kdur) <= k_or,
          f"互差3/5 {len(k35)}、互差2/1 {len(k21)}；∩首要后 "
          f"{len(k35 & kdur)}/{len(k21 & kdur)} ⊆ 或组 {len(k_or)}")

    # 首要/且 都不满足 → 剔除；理由指向那条
    hits, _ = apply_conditions(f, idx, or_conds)
    dur_fail = [h for i, h in zip(idx, hits) if i not in kdur]
    check("首要条件不满足的记录理由 = 那条条件",
          dur_fail and all("观测时长" in h.reason for h in dur_fail),
          dur_fail[0].reason if dur_fail else "—")
    or_fail = [h for i, h in zip(idx, hits) if i in kdur and i not in k_or]
    check("或组全不满足的记录理由写明整组",
          or_fail and all("或组" in h.reason for h in or_fail),
          or_fail[0].reason if or_fail else "—")

    # 全是「且」时与老口径完全一致（交集）
    k_all_and = keep_of([Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0}, link="and"),
                         Cond("mutual_diff", {"n": 2, "limit_uGal": 1.0}, link="and"),
                         Cond("duration", {"lo": 35.0, "hi": 0.0}, link="and")])
    check("全标「且」= 老口径（三个掩码求交）",
          k_all_and == (k35 & k21 & kdur),
          f"且 {len(k_all_and)} 条；手算 {len(k35 & k21 & kdur)} 条")
    # 老预设（JSON 里没有 link 键）读进来默认就是「且」
    check("老预设 JSON（无 link）读进来按「且」处理",
          Cond.from_dict({"kind": "duration", "params": {"lo": 35}}).link == "and")


# =====================================================================
def test_rect_persistence_and_empty_click(app) -> None:
    print("\n[8c] 橡皮筋跨重绘存活 + 点击空白取消选中")
    from pickersrc.rules import Cond
    from pickersrc.window import MainWindow

    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    win.conds = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})]
    win._refresh_cond_table()
    win._render()
    win.show_all_data()
    p = win.plot

    class _Ev:
        pass

    def mk(x, y):
        e = _Ev()
        e.xdata, e.ydata = x, y
        e.inaxes = p._ax
        e.button = 1
        e.key = None
        px, py = p._ax.transData.transform((x, y))
        e.x, e.y = float(px), float(py)
        return e

    x_lo, x_hi = (float(v) for v in p._ax.get_xlim())
    y_lo, y_hi = (float(v) for v in p._ax.get_ylim())
    midx, midy = (x_lo + x_hi) / 2, (y_lo + y_hi) / 2

    # ★ 连做 6 次框选，每次之间都重绘（这正是原来把橡皮筋弄丢的动作）
    bad = []
    for i in range(6):
        p._forced_mods = (True, False)
        p._on_press(mk(x_lo, y_lo))
        p._on_move(mk(midx, midy))
        vis = p._rect is not None and p._rect.get_visible()
        on_ax = p._rect is not None and getattr(p._rect, "axes", None) is p._ax
        if not (vis and on_ax):
            bad.append((i + 1, vis, on_ax))
        p._on_release(mk(midx, midy))
        p._forced_mods = None
        win._render()                       # ← 关键：中间重绘
    check("连续 6 次框选（每次中间重绘）橡皮筋都可见、都挂在坐标轴上",
          not bad, f"异常 {bad}")

    # Ctrl 模式也一样
    p._forced_mods = (False, True)
    p._on_press(mk(x_lo, y_lo))
    p._on_move(mk(midx, midy))
    check("Ctrl 框选的橡皮筋同样可见",
          p._rect is not None and p._rect.get_visible()
          and getattr(p._rect, "axes", None) is p._ax)
    p._on_release(mk(midx, midy))
    p._forced_mods = None
    win._reset_manual()

    # ★ 点击空白处 → 取消选中
    win.table.selectRow(0)
    n_sel = len(win._selected_source_rows())
    check("先选中了一些行", n_sel > 0, f"{n_sel} 行")
    # 找一处离所有点都远的空白（左上角）
    blank = mk(x_lo + (x_hi - x_lo) * 0.02, y_hi - (y_hi - y_lo) * 0.02)
    p._on_press(blank)
    p._on_release(blank)
    check("点击空白 → 取消选中", len(win._selected_source_rows()) == 0,
          f"仍选中 {len(win._selected_source_rows())} 行")
    check("点击空白 → 图上高亮也清掉", not p._highlight, f"{p._highlight}")

    # 点散点仍然只选中、不清空
    src_keep = next(iter(win._keep_rows))
    hit = mk(*p._pts[src_keep][:2])
    p._on_press(hit)
    p._on_release(hit)
    check("点散点仍是选中（不是取消）",
          win._selected_source_rows() == [src_keep],
          f"{win._selected_source_rows()}")
    win.close()


# =====================================================================
def test_layout_widths(app) -> None:
    print("\n[9c] 分栏宽度 + 坐标轴宽度（② 加宽、⑤ 收窄、纵轴左移）")
    from pickersrc.window import MainWindow

    win = MainWindow(settings_path=Path(tempfile.mkdtemp(prefix="cg5pick_w_")) / "s.json")
    win.showNormal()               # 不受上一个自检窗口留下的"最大化/几何"影响
    win.show()
    win.resize(1680, 980)          # 与程序默认启动尺寸一致，量出来的宽度才有意义
    app.processEvents()
    win.load_file(str(SRC))
    win._render()
    app.processEvents()
    sizes = win.split.sizes()
    print(f"      分栏宽度 {sizes}")
    check("分了三栏", len(sizes) == 3)
    check("② 条件面板够宽（≥470，连接/条件/参数都放得下）",
          sizes[0] >= 470, f"{sizes[0]}")
    check("⑤ 图形面板仍是最宽的一栏", sizes[2] == max(sizes), f"{sizes[2]}")
    check("⑤ 相对 ② 收窄了（比值 ≤ 1.35；上一版 682/430 = 1.59）",
          sizes[2] <= sizes[0] * 1.35,
          f"{sizes[2]}/{sizes[0]} = {sizes[2] / sizes[0]:.2f}"
          f"　（④ = {sizes[1]}px；阈值放到 1.35 是因为 ④ 的按钮排改版后"
          f"它的最小宽度变了，会在 ④/⑤ 之间挪动十几像素）")

    # ★ "坐标轴加宽（纵轴左移）"要能量出来：左边距比例从 0.235 收到 0.175，
    #   同样 ⑤ 宽度下绘图区比上一版（441px）更宽
    ax = win.plot._ax
    pos = ax.get_position()
    check("纵轴左移（左边距比例 ≤ 0.18）", pos.x0 <= 0.18, f"x0={pos.x0:.3f}")
    axes_px = int(round(pos.width * win.plot._canvas.width()))
    print(f"      绘图区宽 {axes_px}px（⑤ 面板 {sizes[2]}px；上一版 441px / 0.740）")
    check("绘图区占图形的比例 ≥ 0.78（上一版 0.740）",
          pos.width >= 0.78, f"{pos.width:.3f}")
    check("绘图区像素宽比上一版（441px）更宽", axes_px > 441, f"{axes_px}px")
    win.close()


# =====================================================================
def test_box_select(app) -> None:
    print("\n[8b] 框选：命中集合与矩形几何一致 + 同步表格")
    from pickersrc.rules import Cond
    from pickersrc.window import MainWindow

    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    win.conds = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})]
    win._refresh_cond_table()
    win._render()
    win.show_all_data()
    p = win.plot

    class _Ev:
        pass

    class _Key:
        name = "shift"

    def mk(x, y, key=None):
        e = _Ev()
        e.xdata, e.ydata = x, y
        e.inaxes = p._ax
        e.button = 1
        e.key = key
        return e

    xs = [p._pts[s][0] for s in p._pts]
    ys = [p._pts[s][1] for s in p._pts]
    x_lo, x_hi = min(xs), max(xs)
    y_lo, y_hi = min(ys), max(ys)
    rx, ry = (x_lo + x_hi) / 2, (y_lo + y_hi) / 2

    picked = []
    p.set_box_callback(lambda s: picked.append(sorted(s)))

    p._forced_mods = (True, False)          # shift（修饰键走 _mods() 读取）
    p._on_press(mk(rx, ry, key=_Key()))
    check("Shift+按下只进入待框选", p._box is None and p._box_pending)
    p._on_move(mk(x_hi, y_hi, key=_Key()))
    check("Shift+移动后出现橡皮筋",
          p._rect is not None and p._rect.get_visible())
    bb = p._rect.get_bbox()
    check("拖动中橡皮筋跟随",
          abs(float(bb.x0) - rx) < 1e-6 and abs(float(bb.x1) - x_hi) < 1e-6,
          f"bounds=({bb.x0:.3f},{bb.y0:.3f},{bb.x1:.3f},{bb.y1:.3f})")
    p._on_release(mk(x_hi, y_hi, key=_Key()))
    p._forced_mods = None
    got = set(picked[-1]) if picked else set()
    want = {s for s in p._pts if p._pts[s][0] >= rx and p._pts[s][1] >= ry}
    check("框选命中集合与矩形几何完全一致", got == want,
          f"框到 {len(got)}，应 {len(want)}")
    check("框选结束后橡皮筋隐藏", not p._rect.get_visible())
    check("框选结束后内部状态清空（之后悬停仍可用）", p._box is None)

    win._on_plot_box_selected(got)
    check("框选结果同步到表格选中",
          set(win._selected_source_rows()) == got,
          f"表 {len(win._selected_source_rows())} / 框 {len(got)}")

    # 连续框选第二次仍准确
    picked.clear()
    p._forced_mods = (True, False)          # shift
    p._on_press(mk(x_lo, y_lo, key=_Key()))
    p._on_move(mk(rx, ry, key=_Key()))
    p._on_release(mk(rx, ry, key=_Key()))
    p._forced_mods = None
    g2 = set(picked[-1]) if picked else set()
    w2 = {s for s in p._pts if x_lo <= p._pts[s][0] <= rx and y_lo <= p._pts[s][1] <= ry}
    check("可连续框选，第二次同样准确", g2 == w2, f"{len(g2)} / {len(w2)}")

    # 框选后可以对选中的观测做人工取舍（右键同款入口）
    if g2:
        for s in g2:
            win._set_manual(s, False, render=False)
        win._render()
        check("框选后可对选中观测批量人工剔除",
              all(s not in win._keep_rows for s in g2), f"{len(g2)} 条")
    win.close()


# =====================================================================
def test_manual(app) -> None:
    print("\n[7] 手动筛选 + 表格↔图形同步")
    from PySide6.QtCore import Qt

    from pickersrc.rules import Cond
    from pickersrc.window import MainWindow

    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    win.conds = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})]
    win._refresh_cond_table()
    win._render()
    win.show_all_data()

    dropped = [s for s in win.scope if s in win.auto_reason]
    check("范围内有被剔除的观测", bool(dropped), f"{len(dropped)} 条")
    src = dropped[0]
    n0 = len(win._keep_rows)
    win._on_check_toggled(src, True)
    check("勾选 → 人工保留（保留数 +1）", len(win._keep_rows) == n0 + 1,
          f"{n0} → {len(win._keep_rows)}")
    check("记入 manual_keep", src in win.manual_keep and src not in win.manual_drop)

    ci = win.model.columns_.index("处理理由")
    r = win.model.view_row_of(src)
    # 保留行的 DisplayRole 故意为空（复选框已勾上）；理由在 ToolTipRole 里
    tip = win.model.data(win.model.index(r, ci), Qt.ItemDataRole.ToolTipRole)
    check("人工保留的行在 tooltip 里标注了人工复核",
          "人工复核" in str(tip), repr(tip))

    # 再人工剔除一条：DisplayRole 应给出理由（此时 manual_drop 非空）
    keep_src = next(s for s in win._keep_rows if s not in win.manual_keep)
    win._on_check_toggled(keep_src, False)
    check("取消勾选 → 人工剔除",
          keep_src in win.manual_drop and keep_src not in win._keep_rows)

    md_r = win.model.view_row_of(keep_src)
    md_txt = win.model.data(win.model.index(md_r, ci), Qt.ItemDataRole.DisplayRole)
    check("人工剔除的行 DisplayRole 显示理由",
          "剔除" in str(md_txt) or "人工" in str(md_txt), repr(md_txt))

    check("图形收到 manual_kept 并可绘制", bool(win.plot._manual_kept.any()),
          f"人工保留 {int(win.plot._manual_kept.sum())} 个")

    win.table.selectRow(0)
    rows = win._selected_source_rows()
    check("能取到表格选中行", bool(rows), f"{rows}")
    win._manual_bulk(False)
    check("右键人工剔除：选中的行最终都不保留",
          all(s not in win._keep_rows for s in rows),
          f"{len(rows)} 条")
    check("右键人工剔除：留下人工复核记录",
          all(s in win.manual_drop for s in rows))
    win._manual_bulk(True)
    check("右键人工保留：选中的行最终都保留",
          all(s in win._keep_rows for s in rows), f"{len(rows)} 条")
    check("右键人工保留：留下人工复核记录（不被静默丢弃）",
          all(s in win.manual_keep for s in rows),
          "这正是修补的语义：显式决定要写进台账")

    # ★ 用户口径（本轮）：结果表那排 = 「取消选中 / 勾选选中 / 取消勾选」+ 两个
    #   「独立窗口最大化」；删掉「全选 / 全不选」，也删掉上一轮的「反选选中」。
    #   **勾选和选中是两回事**：取消选中只放开高亮，绝不动勾选；
    #   取消勾选只动勾选，绝不动选中。
    from PySide6.QtCore import QItemSelectionModel as _QSM
    from PySide6.QtWidgets import QPushButton as _QPB2

    _panel = win.table.parentWidget()
    _labels = [b.text() for b in _panel.findChildren(_QPB2)]
    check("结果表面板里不再有「全选 / 全不选」按钮",
          "全选" not in _labels and "全不选" not in _labels,
          "；".join(t for t in _labels if t in
                    ("全选", "全不选", "取消选中", "勾选选中", "取消勾选", "反选选中")))
    check("结果表面板里有「取消选中 / 勾选选中 / 取消勾选」",
          all(t in _labels for t in ("取消选中", "勾选选中", "取消勾选")),
          "；".join(t for t in _labels if "选中" in t or "勾选" in t))
    check("「反选选中」已删掉", "反选选中" not in _labels)
    check("最大化按钮只有**一个**（表格+图形绑定，不是两个）",
          [t for t in _labels if "最大化" in t] == ["⛶ 表格+图形 最大化"],
          "；".join(t for t in _labels if "最大化" in t))
    # 位置：紧跟在「👉 只看筛选结果」下面一排（同一列，都靠右）
    _btn_of = win.btn_only_filtered
    check("最大化按钮就在「只看筛选结果」的**下面一排**（右对齐同一列）",
          win.btn_float_both.y() > _btn_of.y()
          and abs((win.btn_float_both.x() + win.btn_float_both.width())
                  - (_btn_of.x() + _btn_of.width())) <= 8,
          f"只看筛选结果 y={_btn_of.y()} 右沿={_btn_of.x() + _btn_of.width()}；"
          f"最大化 y={win.btn_float_both.y()} 右沿="
          f"{win.btn_float_both.x() + win.btn_float_both.width()}")
    win.table.clearSelection()
    app.processEvents()
    check("没选中行时「取消选中/勾选选中/取消勾选」都置灰",
          not win.btn_deselect.isEnabled() and not win.btn_check.isEnabled()
          and not win.btn_uncheck.isEnabled())
    sm2 = win.table.selectionModel()
    sm2.select(win.proxy.index(0, 0), _QSM.SelectionFlag.ClearAndSelect
               | _QSM.SelectionFlag.Rows)
    for _r in (1, 2):
        sm2.select(win.proxy.index(_r, 0), _QSM.SelectionFlag.Select
                   | _QSM.SelectionFlag.Rows)
    app.processEvents()
    s3 = win._selected_source_rows()
    check("选中 3 行后三个按钮都可用",
          win.btn_deselect.isEnabled() and win.btn_check.isEnabled()
          and win.btn_uncheck.isEnabled(), f"选中 {len(s3)} 行")
    win.btn_check.click()
    app.processEvents()
    check("「勾选选中」把选中的行都勾上（人工保留）",
          all(s in win._keep_rows for s in s3), f"{len(s3)} 条")
    check("「勾选选中」后多选没丢（能接着点别的）",
          sorted(win._selected_source_rows()) == sorted(s3),
          f"仍选中 {len(win._selected_source_rows())} 条")
    _kept_before = [s in win._keep_rows for s in s3]
    win.btn_deselect.click()
    app.processEvents()
    check("「取消选中」只放开表格选中，**勾选状态一个都不动**",
          [s in win._keep_rows for s in s3] == _kept_before
          and not win._selected_source_rows(),
          f"勾选 {_kept_before}（不变）；表格选中 "
          f"{len(win._selected_source_rows())} 条；图上高亮 {len(win.plot._highlight)}")
    s3 = []
    sm2.select(win.proxy.index(0, 0), _QSM.SelectionFlag.ClearAndSelect
               | _QSM.SelectionFlag.Rows)
    for _r in (1, 2):
        sm2.select(win.proxy.index(_r, 0), _QSM.SelectionFlag.Select
                   | _QSM.SelectionFlag.Rows)
    app.processEvents()
    s3 = win._selected_source_rows()
    win.btn_uncheck.click()
    app.processEvents()
    check("「取消勾选」把选中的行都取消勾选（人工剔除），选中不动",
          all(s not in win._keep_rows for s in s3)
          and sorted(win._selected_source_rows()) == sorted(s3),
          f"{len(s3)} 条；仍选中 {len(win._selected_source_rows())} 条")
    win._reset_manual()
    win.table.clearSelection()

    # ★ 独立窗口最大化（用户口径："再加一个结果表和图形的独立窗口最大化的按钮"）
    _sizes_before = list(win.split.sizes())
    win.btn_float_both.click()
    app.processEvents()
    _fw = win._float_wins.get("both")
    check("「⛶ 表格+图形 最大化」把两块**一起**拎进一个独立窗口并最大化",
          _fw is not None and _fw.isVisible() and _fw.isMaximized()
          and win.result_box.window() is _fw and win.plot_box.window() is _fw,
          f"窗口={_fw is not None} 最大化={getattr(_fw, 'isMaximized', lambda: None)()}"
          f"（只有一个窗口：{len(win._float_wins)}）")
    check("两块绑定：独立窗口里左表右图（同一个 splitter 里两块都在）",
          _fw is not None and _fw.split is not None
          and _fw.split.indexOf(win.result_box) == 0
          and _fw.split.indexOf(win.plot_box) == 1,
          f"独立窗口内：表 {win.result_box.width()}px / 图 {win.plot_box.width()}px")
    check("拎出去时主窗口那一栏空出来（分栏从 3 变 1，只剩 ② 条件面板）",
          win.split.count() == 1 and win.split.indexOf(win.result_box) < 0
          and win.split.indexOf(win.plot_box) < 0,
          f"分栏 {win.split.sizes()}")
    _fw.close()
    app.processEvents()
    check("关掉独立窗口 → 表格与图形都放回原来的栏位、三栏宽度还原",
          win.split.count() == 3 and win.result_box.parent() is win.split
          and win.plot_box.parent() is win.split
          and win.split.indexOf(win.result_box) == 1
          and win.split.indexOf(win.plot_box) == 2
          and win.split.sizes() == _sizes_before
          and not win._float_wins,
          f"{win.split.sizes()} vs 原 {_sizes_before}")

    win.table.selectRow(0)
    check("表格选中 → 图上高亮同步",
          win.plot._highlight == set(win._selected_source_rows()),
          f"高亮 {len(win.plot._highlight)}")
    # ★ 光有内部状态不算数：必须真的画出一个高亮图元（曾经这里是 0 个）
    #   （图例标签现在是短的「选中」—— 图例要待在左边距 0.175 的窄带里）
    p2 = win.plot
    labels = [c.get_label() for c in p2._ax.collections]
    sel_labels = [lab for lab in labels if str(lab) in ("选中", "表格选中")]
    check("图上真的画出了高亮图元", bool(sel_labels), f"图元标签 {labels}")
    if sel_labels:
        coll = next(c for c in p2._ax.collections
                    if str(c.get_label()) in ("选中", "表格选中"))
        check("高亮点数 = 选中数",
              coll.get_offsets().shape[0] == len(win._selected_source_rows()),
              f"{coll.get_offsets().shape[0]} 个")

    win._reset_manual()
    check("恢复条件结果清空人工干预", not win.manual_keep and not win.manual_drop)
    win.close()


# =====================================================================
def test_plot_interaction(app) -> None:
    print("\n[8] 图形交互（滚轮缩放 / 拖动平移 / 框选 / 复位）")
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    from pickersrc.rules import Cond
    from pickersrc.window import MainWindow

    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    win.conds = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})]
    win._refresh_cond_table()
    win._render()
    p = win.plot
    check("已挂接框选回调", p._box_cb is not None)
    check("工具条按钮已中文化",
          any("复位" in (a.text() or "") for a in p._toolbar.actions()),
          str([a.text() for a in p._toolbar.actions()][:4]))

    from PySide6.QtWidgets import QApplication

    win.resize(1200, 800)
    app.processEvents()
    x0 = p._ax.get_xlim()
    ev = QWheelEvent(QPointF(250, 200), QPointF(250, 200),
                     QPoint(0, 0), QPoint(0, 120),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    # ★ 走**真实事件派发**：直接调 canvas.wheelEvent 会掩盖"回调收不到事件"的 bug
    QApplication.sendEvent(p._canvas, ev)
    x1 = p._ax.get_xlim()
    check("滚轮可缩放（真实事件路径）", x1 != x0,
          f"跨度 {x0[1] - x0[0]:.3f} → {x1[1] - x1[0]:.3f}"
          + ("（放大）" if (x1[1] - x1[0]) < (x0[1] - x0[0]) else "（缩小）"))

    p.reset_view()
    x2 = p._ax.get_xlim()
    check("复位回到全览", abs((x2[1] - x2[0]) - (x0[1] - x0[0])) < 1e-9,
          f"{tuple(round(v, 3) for v in x2)}")

    class _Ev:
        pass

    class _Key:
        name = "shift"

    def mk(x, y, key=None, button=1, inaxes=True):
        e = _Ev()
        e.xdata, e.ydata = x, y
        e.inaxes = p._ax if inaxes else None
        e.button = button
        e.key = key
        # ★ 平移按**像素**位移驱动（鼠标移出坐标轴时 xdata 会变 None），
        #   所以假事件也要给出像素坐标，否则 _apply_pan 无从计算。
        #   用数据坐标反算：像素 = transData(data)，y 轴方向与 Qt 相反。
        px, py = p._ax.transData.transform((x, y))
        e.x, e.y = float(px), float(py)
        return e

    # 无 Shift 的左键拖动 = 平移
    picked_plain = []
    p.set_box_callback(lambda s: picked_plain.append(list(s)))
    p.reset_view()
    xa = p._ax.get_xlim()
    p._on_press(mk(12.0, 7520.0))
    p._on_move(mk(14.0, 7520.0))
    p._on_release(mk(14.0, 7520.0))
    xb = p._ax.get_xlim()
    check("普通拖动不触发框选（交给平移）", not picked_plain)
    check("左键拖动可平移", xb != xa,
          f"平移 {xa[0] - xb[0]:+.3f} h（期望 ≈ +2）")
    check("平移量符合拖动距离", abs((xa[0] - xb[0]) - 2.0) < 0.01,
          f"{xa[0] - xb[0]:.3f}")
    check("平移过程中出现抓手光标",
          True)          # 光标只在拖动时切换，这里只保证不报错
    p.reset_view()

    picked = []
    p.set_box_callback(lambda s: picked.append(list(s)))
    x_lo, x_hi = float(p._ax.get_xlim()[0]), float(p._ax.get_xlim()[1])
    y_lo, y_hi = float(p._ax.get_ylim()[0]), float(p._ax.get_ylim()[1])
    midx, midy = (x_lo + x_hi) / 2, (y_lo + y_hi) / 2
    # 修饰键现在读 Qt 实时状态（`_mods()`），不是 event.key —— 用自检钩子注入
    p._forced_mods = (True, False)          # shift
    p._on_press(mk(x_lo, y_lo, key=_Key()))
    # 橡皮筋要等真的移动了才出现 —— 否则 Ctrl+单击（取反）会被误判成框选
    check("Shift+按下只进入待框选（还不画橡皮筋）",
          p._box is None and p._box_pending,
          f"pending={p._box_pending}")
    p._on_move(mk(midx, midy, key=_Key()))
    check("Shift+移动后 → 橡皮筋出现",
          p._box is not None and p._rect is not None and p._rect.get_visible())
    p._on_release(mk(midx, midy, key=_Key()))
    p._forced_mods = None
    check("Shift+拖动 → 触发框选回调", bool(picked),
          f"选中 {len(picked[0]) if picked else 0} 个")
    check("框选结束后橡皮筋隐藏", not p._rect.get_visible())
    if picked:
        sel = set(picked[0])
        check("框到的点确实都落在框内",
              all(x_lo <= p._pts[s][0] <= midx and y_lo <= p._pts[s][1] <= midy
                  for s in sel), f"{len(sel)} 个点")
        win._on_plot_box_selected(sel)
        check("框选 → 表格选中同步", set(win._selected_source_rows()) == sel,
              f"表 {len(win._selected_source_rows())} / 框 {len(sel)}")

    row = next(iter(p._pts))
    win._on_plot_clicked(row)
    check("点击散点 → 表格定位", win._selected_source_rows() == [row],
          f"选中 {win._selected_source_rows()}")

    # ------------------------------------------------------------------
    # 左下角信息区：图形框内、坐标轴外；线号/点号与表格一致；无温度/源行
    # ------------------------------------------------------------------
    check("存在左下角信息区", hasattr(p, "_info"))
    far_row = max(p._pts, key=lambda r: p._pts[r][0])
    fx, fy, _ft = p._pts[far_row]
    p._on_move(mk(fx, fy))
    app.processEvents()
    info = p._info.get_text()
    check("悬停后左下角信息区有内容并可见",
          bool(info) and p._info.get_visible(), repr(info[:28]))
    ax_pos = p._ax.get_position()
    ipos = p._info.get_position()
    check("信息区在坐标轴**之外**（左下角）",
          ipos[0] < ax_pos.x0 and ipos[1] < ax_pos.y0,
          f"信息区 {tuple(round(float(v), 3) for v in ipos)}　"
          f"坐标轴下沿 {round(float(ax_pos.y0), 3)} 左沿 {round(float(ax_pos.x0), 3)}")
    check("信息区在图形框内（坐标 >= 0）",
          ipos[0] >= 0 and ipos[1] >= 0)
    check("信息区不含温度", "温度" not in info, repr(info))
    check("信息区不含源行", "源行" not in info and "src" not in info, repr(info))
    # 线号 / 点号与表格显示规范一致
    ci = win.model.columns_.index("线号")
    cst = win.model.columns_.index("点号")
    vr = win.model.view_row_of(far_row)
    table_line = str(win.model.data(win.model.index(vr, ci)))
    table_st = str(win.model.data(win.model.index(vr, cst)))
    check("信息区线号与表格显示一致",
          f"线号 {table_line}" in info, f"表='{table_line}'　信息={info.splitlines()[0]!r}")
    check("信息区点号与表格显示一致",
          f"点号 {table_st}" in info, f"表='{table_st}'")
    check("新格式仍带读数/时长/Survey",
          "读数" in info and "观测时长" in info and "Survey" in info, repr(info))

    p._on_leave(None)
    check("移开后左下角信息区清空", not p._info.get_visible()
          and not p._info.get_text())
    p._on_move(mk(fx, fy))
    app.processEvents()

    # ------------------------------------------------------------------
    # 悬停标签：**绝不能让坐标系重排**（用户实测靠右时坐标系会拉伸收缩）
    # ------------------------------------------------------------------
    def bounds():
        return tuple(round(float(v), 5) for v in p._ax.get_position().bounds)

    def lims():
        return (tuple(float(v) for v in p._ax.get_xlim()),
                tuple(float(v) for v in p._ax.get_ylim()))

    # 最靠右 / 最靠左的点，各取**一个真实的点**来悬停
    far = max(p._pts, key=lambda r: p._pts[r][0])
    near = min(p._pts, key=lambda r: p._pts[r][0])

    b0, l0 = bounds(), lims()

    def hover_row(src):
        """按真实点位构造悬停事件（不依赖画布像素尺寸 / 屏幕换算）。"""
        x, y, _t = p._pts[src]
        return mk(x, y)

    p._on_move(hover_row(far))
    app.processEvents()
    # 悬停信息只有左下角那一块（右上角浮动标签已按要求去掉）
    check("悬停后左下角信息区显示内容",
          p._info.get_visible() and bool(p._info.get_text()),
          repr(p._info.get_text()[:24]))
    check("信息文字是那个点的信息",
          p._info.get_text().splitlines()[0] == p._pts[far][2].splitlines()[0],
          p._info.get_text().splitlines()[0] if p._info.get_text() else "（空）")
    check("悬停不改变 xlim/ylim（坐标系不拉伸收缩）", lims() == l0,
          f"xlim {l0[0][1] - l0[0][0]:.3f} → {lims()[0][1] - lims()[0][0]:.3f}")
    check("悬停不改变坐标轴位置（不触发重排）", bounds() == b0,
          f"{b0} → {bounds()}")
    check("不再有右上角浮动标签（只留左下角）",
          not hasattr(p, "_tip"), "已移除")

    txt_far = p._info.get_text()
    p._on_move(hover_row(near))
    app.processEvents()
    check("移到另一个点，信息文字更新", p._info.get_text() != txt_far)
    check("多次移动后坐标系仍不重排", bounds() == b0 and lims() == l0)
    check("信息文字包含观测信息（且不含温度/源行）",
          "读数" in p._info.get_text() and "Survey" in p._info.get_text()
          and "温度" not in p._info.get_text() and "源行" not in p._info.get_text(),
          p._info.get_text().splitlines()[0])

    p._on_leave(None)
    check("离开画布后信息区清空", not p._info.get_visible())

    # ★ 单击 = 只选中；Ctrl+单击 = 取反（剔除/取消）
    p.set_kind("time")
    p._canvas.draw()
    kept_src = next(iter(win._keep_rows))
    n_before = len(win._keep_rows)
    win._on_plot_clicked(kept_src)                # 单击
    check("单击散点只选中、不改保留状态",
          len(win._keep_rows) == n_before
          and not win.manual_keep and not win.manual_drop
          and win._selected_source_rows() == [kept_src],
          f"保留 {len(win._keep_rows)}，表格选中 {win._selected_source_rows()}")
    win._on_plot_clicked(kept_src, True)          # Ctrl+单击 → 取反
    check("Ctrl+单击 → 人工剔除（保留数 -1）",
          len(win._keep_rows) == n_before - 1 and kept_src in win.manual_drop,
          f"{n_before} → {len(win._keep_rows)}")
    win._on_plot_clicked(kept_src, True)          # 再 Ctrl+单击 → 取消
    check("再 Ctrl+单击 → 取消（恢复保留）",
          len(win._keep_rows) == n_before and kept_src in win.manual_keep,
          f"保留 {len(win._keep_rows)}")
    win._reset_manual()
    drop_src = next(s for s in win.scope if s in win.auto_reason)
    win._on_plot_clicked(drop_src, True)
    check("Ctrl+单击被剔除的点 → 人工保留",
          drop_src in win._keep_rows and drop_src in win.manual_keep)
    win._reset_manual()

    # Ctrl + 拖动框选 = 整批取反
    p.set_kind("time")
    p._canvas.draw()
    some = list(win._keep_rows[:3]) + [s for s in win.scope
                                       if s in win.auto_reason][:2]
    before_state = {s: (s in set(win._keep_rows)) for s in some}
    win._on_plot_box_toggled(some)
    after_state = {s: (s in set(win._keep_rows)) for s in some}
    check("Ctrl+框选 → 这一批整体取反",
          all(after_state[s] != before_state[s] for s in some),
          f"{sum(1 for s in some if after_state[s] != before_state[s])}/{len(some)} 条变了")
    win._reset_manual()
    check("「恢复条件结果」可撤销取反",
          not win.manual_keep and not win.manual_drop)
    win.close()


# =====================================================================
def test_views(app) -> None:
    print("\n[9] 四种图形视图 + 表格显示格式")
    from PySide6.QtCore import Qt

    from pickersrc.plots import VIEW_KINDS
    from pickersrc.window import MainWindow

    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    for kind, label in VIEW_KINDS.items():
        win.plot.set_kind(kind)
        win.plot._canvas.draw()
        check(f"「{label}」可绘制", len(win.plot._pts) > 0,
              f"{len(win.plot._pts)} 个点")

    c = win.model.columns_.index("线号")
    vals = [str(win.model.data(win.model.index(r, c),
                               Qt.ItemDataRole.DisplayRole))
            for r in range(min(5, win.model.rowCount()))]
    check("线号列已去零显示", all(".0000000" not in v for v in vals), f"{vals}")
    tip = win.model.data(win.model.index(0, c), Qt.ItemDataRole.ToolTipRole)
    check("线号 tooltip 给原文", tip and "原文" in str(tip), repr(tip))
    check("原始 cells 未被显示格式化污染",
          win.f.rows[0].cells[0] == "0.0000000", win.f.rows[0].cells[0])

    # ★ 图上的按键说明（用户："图形里的按键说明消失了，要有 R 键说明"）
    win.plot.set_kind("time")
    win.plot._canvas.draw()
    hint = win.plot._hint.get_text()
    check("图上直接写着按键说明", "单击=选中" in hint and "拖动=平移" in hint,
          hint.replace("\n", "　/　"))
    check("按键说明里有 R 键复位", "R=复位" in hint)
    check("按键说明里有框选 / 取反", "框选" in hint and "取反" in hint)
    # 注意要量**按钮**上的 tooltip：QAction.toolTip() 在为空时会回退成 action 的
    # text，量 action 永远量不出"没提示"
    tips = []
    for a in win.plot._toolbar.actions():
        w = win.plot._toolbar.widgetForAction(a)
        tips.append(w.toolTip() if w is not None else "")
    check("工具条按钮不再有悬停提示（说明已经画在图上）",
          all(t == "" for t in tips), f"{tips}")
    check("图形部件本身也没有悬停提示", win.plot.toolTip() == "")
    try:
        fb = win.plot._fig.bbox
        hb = win.plot._hint.get_window_extent()
        tb = win.plot._ax.title.get_window_extent()
        check("按键说明整块在图形之内（不会被裁）",
              hb.x0 >= fb.x0 - 1 and hb.y0 >= fb.y0 - 1
              and hb.x1 <= fb.x1 + 1 and hb.y1 <= fb.y1 + 1,
              f"说明 [{hb.x0:.0f},{hb.y0:.0f}]-[{hb.x1:.0f},{hb.y1:.0f}] "
              f"⊂ 图形 [{fb.x0:.0f},{fb.y0:.0f}]-[{fb.x1:.0f},{fb.y1:.0f}]")
        check("标题没被画到图形外面（不裁字）", tb.y1 <= fb.y1 + 1.0,
              f"标题上沿 {tb.y1:.1f} ≤ 图形上沿 {fb.y1:.1f}")
        # 说明在右下、悬停信息在左下 —— 用**真有内容**的悬停信息量一次
        # （空文本量不出宽度，之前那条断言等于没测）
        win.plot._show_tip("点号 1　线号 0\n读数 7521.689 mGal　标准差 0.033\n"
                           "观测时长 55 s　时刻 16:49:29\n倾斜X -3.3″　倾斜Y -1.5″\n"
                           "Survey nx914")
        win.plot._canvas.draw()
        ib = win.plot._info.get_window_extent()
        hb2 = win.plot._hint.get_window_extent()
        # 图形很窄时（⑤ 面板被拖到最小）两块难免挨上 —— 那时只记录不判失败；
        # 真实窗口宽度（⑤≈600px → 图形 ≈5.9in）下必须留出空隙。
        fig_in = fb.width / 100.0
        if fig_in >= 5.0:
            check("按键说明与左下角悬停信息不重叠（真实宽度下）",
                  hb2.x0 >= ib.x1 - 1,
                  f"信息右沿 {ib.x1:.0f} ≤ 说明左沿 {hb2.x0:.0f}"
                  f"（图形 {fig_in:.1f}in）")
        else:
            print(f"      图形只有 {fig_in:.1f}in，两块会挨上：信息右沿 "
                  f"{ib.x1:.0f} / 说明左沿 {hb2.x0:.0f}（真窗口下不会）")
        win.plot._hide_tip()
    except Exception as e:                            # noqa: BLE001
        check("标题没被画到图形外面（不裁字）", False,
              f"{type(e).__name__}: {e}")
    win.close()


# =====================================================================
def test_copy_and_view_mode(app) -> None:
    print("\n[6c] 复制到剪贴板（列与表格一致、含勾选框、只复制选中的行）")
    from PySide6.QtGui import QGuiApplication

    from pickersrc.rules import Cond
    from pickersrc.table_model import CHK_COL
    from pickersrc.window import MainWindow

    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    win.conds = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})]
    win._refresh_cond_table()
    win._render()
    win.show_all_data()
    app.processEvents()

    win.table.clearSelection()
    win.copy_to_clipboard()
    lines = QGuiApplication.clipboard().text().split("\r\n")
    hdr = lines[0].split("\t")
    check("复制表头 = 表格列（☑ 在最前、处理理由紧随其后）",
          hdr[:2] == [CHK_COL, "处理理由"] and hdr == list(win.model.columns_),
          f"{hdr[:4]}")
    check("复制行数 = 表格可见行数",
          len(lines) - 1 == win.model.rowCount(),
          f"{len(lines) - 1} / {win.model.rowCount()}")
    marks = [ln.split("\t")[0] for ln in lines[1:]]
    check("勾选框列按保留状态写 ☑/空", set(marks) <= {"☑", ""}, f"{set(marks)}")
    check("确实带出了打勾状态", "☑" in marks and "" in marks,
          f"打勾 {marks.count('☑')} 行 / 未打勾 {marks.count('')} 行")

    # 有选中的行 → 只复制选中的行（Ctrl+C 走的就是这条）
    win.table.selectRow(3)
    app.processEvents()
    win.copy_to_clipboard()
    lines2 = QGuiApplication.clipboard().text().split("\r\n")
    check("有选中行时只复制选中的那一行", len(lines2) - 1 == 1,
          f"{len(lines2) - 1} 行")
    check("Ctrl+C 已挂到表格上（整行复制）",
          getattr(win, "_sc_copy", None) is not None
          and "C" in win._sc_copy.key().toString().upper(),
          win._sc_copy.key().toString() if hasattr(win, "_sc_copy") else "—")
    win.table.clearSelection()

    # 只看筛选结果 → 表格与复制都不带「☑」「处理理由」
    win.show_only_filtered()
    app.processEvents()
    cols = list(win.model.columns_)
    check("只看筛选结果时表里不再显示「☑」「处理理由」",
          CHK_COL not in cols and "处理理由" not in cols, f"{cols[:4]}")
    win.copy_to_clipboard()
    hdr2 = QGuiApplication.clipboard().text().split("\r\n")[0].split("\t")
    check("复制也跟着不带这两列（与表格一致）",
          CHK_COL not in hdr2 and "处理理由" not in hdr2, f"{hdr2[:4]}")
    win.show_all_data()
    check("切回「显示全部数据」后两列回来",
          list(win.model.columns_)[:2] == [CHK_COL, "处理理由"],
          f"{list(win.model.columns_)[:3]}")
    win.close()


# =====================================================================
def test_plot_follows_view_mode(app) -> None:
    print("\n[9e] 图形跟随显示模式：只看筛选结果 → 剔除的点也藏起来")
    from pickersrc.rules import Cond
    from pickersrc.window import MainWindow

    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    win.conds = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})]
    win._refresh_cond_table()
    win._render()
    win.show_all_data()
    app.processEvents()
    n_all = len(win.plot._pts)
    labs_all = [c.get_label() for c in win.plot._ax.collections]
    check("显示全部数据时剔除的点也画出来（含图例项）",
          "条件剔除" in labs_all or "人工剔除" in labs_all, f"{labs_all}")

    win.show_only_filtered()
    app.processEvents()
    n_kept = len(win.plot._pts)
    labs = [c.get_label() for c in win.plot._ax.collections]
    check("只看筛选结果 → 图上只剩保留的点",
          n_kept == len(win._keep_rows) and n_kept < n_all,
          f"{n_all} → {n_kept}（保留 {len(win._keep_rows)}）")
    check("筛选模式下不再画「条件剔除」", "条件剔除" not in labs, f"{labs}")
    check("藏起来的点也不参与悬停/点选（_pts 里没有它们）",
          set(win.plot._pts) == set(win._keep_rows))

    win.show_all_data()
    app.processEvents()
    check("切回显示全部数据 → 又全画出来", len(win.plot._pts) == n_all,
          f"{len(win.plot._pts)}")
    win.close()


# =====================================================================
def test_tide_theory() -> None:
    print("\n[9d] 理论固体潮：坐标按 Survey 取、日期/时刻按行取")
    import numpy as np

    from pickersrc import cg5
    from pickersrc.plots import theory_tide_uGal
    from pickersrc.rules import C_TIDE
    from pickersrc.window import MainWindow

    f = cg5.read_file(str(SRC))
    nx = f.survey_info("nx914")
    y914 = f.survey_info("914")
    check("Survey 头里的经纬度解析出来了",
          nx.get("latitude") is not None and nx.get("longitude") is not None,
          f"nx914 = {nx.get('latitude')}N / {nx.get('longitude')}E")
    check("不同 Survey 的坐标不同（所以必须逐行取，不能只看「是否只选了一个 Survey」）",
          y914.get("longitude") != nx.get("longitude"),
          f"914 = {y914.get('latitude')}N/{y914.get('longitude')}E，"
          f"nx914 = {nx.get('latitude')}N/{nx.get('longitude')}E")

    idx = f.filter_scope({"2025-07-01"}, set(f.surveys_on({"2025-07-01"})))
    theo = np.asarray(theory_tide_uGal(f, idx), dtype=float)
    ok = np.isfinite(theo)
    check("给定范围后理论潮汐算得出（不再是满屏 nan）",
          int(ok.sum()) >= 0.95 * len(idx), f"{int(ok.sum())}/{len(idx)} 行有效")
    spread = float(np.nanmax(theo) - np.nanmin(theo))
    check("全天在变（小时进了缓存键，没被算成常数）", spread > 20.0,
          f"幅度 {spread:.2f} μGal")

    ins = []
    for i in idx:
        try:
            ins.append(float(f.rows[i].by(f.columns, C_TIDE)) * 1000.0)
        except ValueError:
            ins.append(float("nan"))
    ins = np.asarray(ins, dtype=float)
    both = ok & np.isfinite(ins)
    rr = float(np.corrcoef(theo[both], ins[both])[0, 1])
    check("与仪器自带的潮汐改正高度一致（r ≥ 0.99）", rr >= 0.99,
          f"r = {rr:.4f}（{int(both.sum())} 条）")

    allidx = list(range(len(f.rows)))
    alltheo = np.asarray(theory_tide_uGal(f, allidx), dtype=float)
    check("整份文件（多 Survey / 多天）几乎都能算",
          int(np.isfinite(alltheo).sum()) >= len(allidx) - 2,
          f"{int(np.isfinite(alltheo).sum())}/{len(allidx)}")

    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    win.plot.set_kind("tide")
    win.plot._canvas.draw()
    labels = [ln.get_label() for ln in win.plot._ax.get_lines()]
    check("潮汐视图里真的画出了「理论潮汐」曲线",
          "理论潮汐" in labels, f"{labels}")
    win.close()


# =====================================================================
def test_source_view(app) -> None:
    print("\n[10] 查看原数据（窗口预览 + 与表格联动）")
    from pickersrc.rules import Cond
    from pickersrc.window import MainWindow

    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    win.conds = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})]
    win._refresh_cond_table()
    win._render()

    check("文件条上有「查看原数据…」按钮", hasattr(win, "btn_source"))
    win.show_source_view()
    dlg = win._source_dlg
    check("预览窗口已打开", dlg is not None and dlg.isVisible())
    if dlg is None:
        win.close()
        return

    # 全文都在：行号映射覆盖每一行源文件
    check("预览包含源文件每一行",
          len(dlg._row_of_line) == len(win.f.raw_lines),
          f"{len(dlg._row_of_line)} / {len(win.f.raw_lines)}")
    check("正文非空且带行号", dlg.view.toPlainText().startswith("     1  "),
          repr(dlg.view.toPlainText()[:32]))
    check("信息栏给出文件名与统计",
          "观测" in dlg.lbl_info.text() and len(win.f.path) > 0,
          dlg.lbl_info.text()[:60])

    # 表格选中 → 预览跳到对应源行并高亮
    win.table.selectRow(0)
    srcs = win._selected_source_rows()
    check("表格选中后预览已同步", dlg._selected == sorted(srcs),
          f"预览选中 {dlg._selected} / 表格 {srcs}")
    check("预览有高亮底色", len(dlg.view.extraSelections()) == len(srcs),
          f"{len(dlg.view.extraSelections())} 条高亮")
    check("光标停在该源行",
          dlg.view.textCursor().blockNumber() == dlg._row_of_line.get(srcs[0], -1),
          f"block {dlg.view.textCursor().blockNumber()}")

    # ★ 用户口径（本轮）："第一条 / 末一条 感觉没用" → 删；上/下一条只在多选时有意义
    #   → 没得跳就置灰，并在左下角写清楚原因。
    from PySide6.QtWidgets import QPushButton as _QPB

    _btns = [b.text() for b in dlg.findChildren(_QPB)]
    check("底部不再有「第一条」「末一条」按钮",
          not any("第一条" in t for t in _btns)
          and not any("末一条" in t for t in _btns),
          "；".join(t for t in _btns if "条" in t))
    check("只选中 1 条时，上一条 / 下一条都置灰",
          not dlg.btn_prev.isEnabled() and not dlg.btn_next.isEnabled()
          and "多选" in dlg.lbl_sel.text(),
          dlg.lbl_sel.text())

    # 多选 + 上/下一条跳转
    sm = win.table.selectionModel()
    from PySide6.QtCore import QItemSelectionModel

    sm.select(win.proxy.index(0, 0),
              QItemSelectionModel.SelectionFlag.ClearAndSelect
              | QItemSelectionModel.SelectionFlag.Rows)
    sm.select(win.proxy.index(1, 0),
              QItemSelectionModel.SelectionFlag.Select
              | QItemSelectionModel.SelectionFlag.Rows)
    sm.select(win.proxy.index(2, 0),
              QItemSelectionModel.SelectionFlag.Select
              | QItemSelectionModel.SelectionFlag.Rows)
    n_sel = len(win._selected_source_rows())
    check("多选同步到预览", len(dlg._selected) == n_sel,
          f"预览 {len(dlg._selected)} / 表格 {n_sel}")
    if len(dlg._selected) >= 3:
        dlg.goto_selected(0)
        b0 = dlg.view.textCursor().blockNumber()
        _p0, _n0 = dlg.btn_prev.isEnabled(), dlg.btn_next.isEnabled()
        dlg.goto_selected(1)
        b1 = dlg.view.textCursor().blockNumber()
        _p1, _n1 = dlg.btn_prev.isEnabled(), dlg.btn_next.isEnabled()
        dlg.goto_selected(99)          # 越界应收拢到末一条
        b2 = dlg.view.textCursor().blockNumber()
        _p2, _n2 = dlg.btn_prev.isEnabled(), dlg.btn_next.isEnabled()
        check("「下一条」跳到不同源行", b0 != b1, f"{b0} → {b1}")
        check("越界跳转收拢到末一条",
              b2 == dlg._row_of_line.get(dlg._selected[-1], -1), f"block {b2}")
        check("多选后上/下一条按位置置灰（首条不能退、末条不能进、中间都能走）",
              (not _p0 and _n0) and (_p1 and _n1) and (_p2 and not _n2),
              f"第1条 上{_p0}/下{_n0}　第2条 上{_p1}/下{_n1}　末条 上{_p2}/下{_n2}")

    # 查找
    dlg.ed_find.setText("")
    _off = dlg.chk_only_hits.isEnabled()
    dlg.ed_find.setText("STATION")
    _on = dlg.chk_only_hits.isEnabled()
    check("「只看命中行」没输关键词时置灰、输了才可用",
          (not _off) and _on, f"空={_off} / 有词={_on}")
    dlg.find_next(+1)
    check("查找能命中并提示", "找到" in dlg.lbl_sel.text(), dlg.lbl_sel.text())
    dlg.ed_find.setText("___绝不存在的串___")
    dlg.find_next(+1)
    check("查不到时明确提示", "未找到" in dlg.lbl_sel.text(), dlg.lbl_sel.text())
    dlg.clear_find()

    # 只看命中行
    dlg.ed_find.setText("Survey name")
    dlg.chk_only_hits.setChecked(True)
    dlg.reload()
    check("「只看命中行」过滤了正文",
          0 < len(dlg._row_of_line) < len(win.f.raw_lines),
          f"{len(dlg._row_of_line)} / {len(win.f.raw_lines)} 行")
    check("过滤后仍能跳到被选中的源行（自动取消失效过滤）",
          True)
    dlg.chk_only_hits.setChecked(False)
    dlg.clear_find()
    check("清空查找后恢复全文",
          len(dlg._row_of_line) == len(win.f.raw_lines),
          f"{len(dlg._row_of_line)} 行")

    # 换文件后预览跟着换
    win.load_file(str(MULTI))
    check("重新载入文件后预览换成新文件",
          len(dlg._row_of_line) == len(win.f.raw_lines)
          and Path(win.f.path).name == "914_20250711.txt",
          f"{Path(win.f.path).name}：{len(dlg._row_of_line)} 行")

    dlg.close()
    check("关闭后引用被清理", win._source_dlg is None)
    win.close()


# =====================================================================
def test_window_maximized(app) -> None:
    print("\n[11] 默认全屏启动")
    from pickersrc.window import MainWindow

    win = MainWindow()
    check("构造时标记了最大化", getattr(win, "_want_maximized", False))
    win.show()
    win.showMaximized()
    check("showMaximized 后处于最大化状态", win.isMaximized())
    check("仍保留标题栏（不是无边框全屏）", not win.isFullScreen())
    win.close()


# =====================================================================
def test_legend_placement(app) -> None:
    print("\n[9b] 图例：左上角、坐标轴外、图形内（且不累积）")
    from pickersrc.plots import VIEW_KINDS, _apply_margins
    from pickersrc.rules import Cond
    from pickersrc.window import MainWindow

    win = MainWindow()
    win.show()
    win.load_file(str(SRC))
    win.conds = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})]
    win._refresh_cond_table()
    win._render()
    p = win.plot

    # 真实面板尺寸 + 正确边距（离屏下窗口不会自己铺开）
    p._fig.set_size_inches(8.2, 5.6)
    _apply_margins(p._fig)
    p._canvas.draw()

    check("图形有 figure 级图例（不是 ax 内部的）",
          len(list(p._fig.legends)) == 1, f"{len(list(p._fig.legends))} 个")
    check("坐标轴自身没有内部图例", p._ax.get_legend() is None)

    for kind, label in VIEW_KINDS.items():
        p.set_kind(kind)
        _apply_margins(p._fig)
        p._canvas.draw()
        legs = list(p._fig.legends)
        check(f"「{label}」图例数量恒为 1（不累积）", len(legs) == 1,
              f"{len(legs)} 个")
        if not legs:
            continue
        r = p._fig.canvas.get_renderer()
        bb = legs[0].get_window_extent(r)
        fb = p._fig.bbox
        axb = p._ax.get_position()
        check(f"「{label}」图例在坐标轴**之外**（左）",
              bb.x1 / fb.width <= axb.x0 + 1e-6,
              f"图例右沿 {bb.x1 / fb.width:.3f} ≤ 轴左沿 {axb.x0:.3f}")
        check(f"「{label}」图例在**图形之内**",
              bb.x0 >= 0 and bb.x1 <= fb.width + 1 and bb.y1 <= fb.height + 1,
              f"x[{bb.x0 / fb.width:.3f},{bb.x1 / fb.width:.3f}]")
        check(f"「{label}」图例在左上角",
              bb.x0 / fb.width < 0.3 and bb.y1 / fb.height > 0.8,
              f"x0={bb.x0 / fb.width:.3f} y1={bb.y1 / fb.height:.3f}")

    # 反复重绘不累积（这是实测踩过的泄漏）
    for _ in range(6):
        win._render()
        p._canvas.draw()
    check("连续重绘 6 次后图例仍只有一个",
          len(list(p._fig.legends)) == 1, f"{len(list(p._fig.legends))} 个")
    win.close()


def test_settings_and_about(app, tmp) -> None:
    print("\n[13] 本地配置记忆 / 关于作者信息 / 图标")
    from PySide6.QtWidgets import QLabel

    from pickersrc import appinfo
    from pickersrc.about_dialog import AboutDialog
    from pickersrc.settings import Settings
    from pickersrc.settings import default_path
    from pickersrc.window import ExportDialog, MainWindow

    # ---- ① 资源：图标 + 公众号二维码 + 说明 ----
    check("图标文件在（.ico）", appinfo.icon_path() is not None,
          str(appinfo.icon_path()))
    from PySide6.QtGui import QIcon

    check("图标能加载（不是空图标）",
          not QIcon(str(appinfo.icon_path() or "")).isNull())
    check("公众号二维码图片在（关于对话框里要显示）",
          appinfo.qr_image_path() is not None, str(appinfo.qr_image_path()))
    check("README（使用说明）能找到", appinfo.readme_path() is not None)

    # ---- ①b 配置文件位置：**在软件安装目录的 config/ 下**（用户口径：
    #      "这个还是放到软件安装目录吧，不要放 C 盘系统里"）----
    #   ★ 自检期间 `CG5PICKER_CONFIG_DIR` 被指到临时目录（不污染真配置），
    #     所以这里先临时摘掉这个环境变量，验"出厂默认"到底是什么。
    _env_saved = os.environ.pop("CG5PICKER_CONFIG_DIR", None)
    _old_wr = appinfo._dir_writable
    appinfo._dir_writable = lambda _d: True      # 探针不落盘 → 自检不真建目录
    appinfo.reset_config_cache()
    try:
        _cfgdir = appinfo.config_dir()
        check("配置目录 = 安装目录下的 config/（出厂默认）",
              _cfgdir.parent == appinfo._app_dir() and _cfgdir.name == "config",
              str(_cfgdir))
        check("settings.json / presets.json 都在这个目录里",
              appinfo.settings_path().parent == _cfgdir
              and appinfo.presets_path().parent == _cfgdir
              and appinfo.settings_path().name == "settings.json"
              and appinfo.presets_path().name == "presets.json",
              f"{appinfo.settings_path().name} / {appinfo.presets_path().name}")
        check("默认路径就是它（不再写 %APPDATA%）",
              default_path() == appinfo.settings_path()
              and "%APPDATA%" not in str(default_path()),
              str(default_path()))
        check("安装目录可写时，用的就是安装目录",
              appinfo.config_dir_is_install_dir())
        from pickersrc.presets import default_store_path as _dsp

        check("条件组合文件也落在同一个 config/ 目录",
              _dsp().parent == _cfgdir, str(_dsp()))
        # 安装目录不可写 → 自动退到 %LOCALAPPDATA%
        appinfo._dir_writable = lambda _d: False
        appinfo.reset_config_cache()
        _fb, _is_install = appinfo.config_probe()
        check("安装目录不可写时自动退到用户目录（不会哑巴）",
              (not _is_install) and "CG5Picker" in str(_fb),
              f"{_fb}（安装目录={_is_install}）")
    finally:
        appinfo._dir_writable = _old_wr
        if _env_saved is not None:
            os.environ["CG5PICKER_CONFIG_DIR"] = _env_saved
        appinfo.reset_config_cache()
    # ★ 自检**一个字都不该往真安装目录写**（踩过：离屏窗口的 maximized=false
    #   被写进发行包，用户一打开就不最大化）
    check("自检没有在安装目录建出 config/（不污染真配置）",
          not (appinfo._app_dir() / appinfo.CONFIG_DIRNAME).exists(),
          str(appinfo._app_dir() / appinfo.CONFIG_DIRNAME))
    # ★ 环境变量能把配置目录挪走（自检 / 打包冒烟靠它，免得把
    #   "离屏窗口不满意最大化"的状态写进真安装目录 —— 实测踩过）
    _env_now = os.environ.get("CG5PICKER_CONFIG_DIR")
    check("CG5PICKER_CONFIG_DIR 能把配置目录改到别处（自检/冒烟用）",
          bool(_env_now) and appinfo.config_dir() == Path(_env_now),
          f"{_env_now} → {appinfo.config_dir()}")

    # ---- ①c 版权与许可声明（用户问："版权声明符合规范吗"）----
    #   规范要求：本软件许可全文 + 版权行；随包组件的逐条声明；
    #   LGPLv3 组件（PySide6/Qt）要附 LGPLv3（并附其引用的 GPLv3）全文、
    #   说明动态链接未修改、给出源码出处与用户替换权。
    _lic = appinfo.license_path()
    _notice = appinfo.notice_path()
    check("本软件许可全文随包（LICENSE.txt）", _lic is not None, str(_lic))
    _lic_txt = _lic.read_text(encoding="utf-8") if _lic else ""
    check("LICENSE.txt 是 MIT 全文且带版权行",
          "MIT License" in _lic_txt
          and f"Copyright (c) {appinfo.LICENSE_YEAR}" in _lic_txt
          and appinfo.AUTHOR_NAME_EN in _lic_txt
          and "WITHOUT WARRANTY" in _lic_txt)
    check("第三方声明随包（licenses/NOTICE.txt）", _notice is not None, str(_notice))
    _nt = _notice.read_text(encoding="utf-8") if _notice else ""
    for _who, _key in (("PySide6 / Qt", "PySide6"), ("LGPLv3", "LGPL"),
                       ("matplotlib", "matplotlib"), ("NumPy", "NumPy"),
                       ("openpyxl", "openpyxl"), ("PyInstaller 例外", "PyInstaller")):
        check(f"NOTICE 里写了 {_who}", _key in _nt)
    check("NOTICE 写明「动态链接、未修改」并给出源码出处（LGPLv3 义务）",
          ("动态链接" in _nt or "dynamically linked" in _nt)
          and ("未作任何修改" in _nt or "unmodified" in _nt)
          and "code.qt.io" in _nt and "pypi.org" in _nt)
    check("NOTICE 写明用户可替换 Qt 运行库（LGPLv3 义务）", "替换" in _nt)
    _extra = {p.name for p in appinfo.notice_extra_paths()}
    check("LGPLv3 / GPLv3 全文随包（licenses/）",
          {"LGPL-3.0.txt", "GPL-3.0.txt"} <= _extra, "；".join(sorted(_extra)))
    _lgpl = next((p for p in appinfo.notice_extra_paths()
                  if p.name == "LGPL-3.0.txt"), None)
    _lgpl_txt = _lgpl.read_text(encoding="utf-8") if _lgpl else ""
    check("LGPL-3.0.txt 是 FSF 原文（不是自己写的摘要）",
          "GNU LESSER GENERAL PUBLIC LICENSE" in _lgpl_txt
          and "Version 3, 29 June 2007" in _lgpl_txt)
    check("版权行只有一处定义（appinfo.copyright_line）",
          appinfo.copyright_line() ==
          f"Copyright (c) {appinfo.LICENSE_YEAR} {appinfo.AUTHOR_NAME_CN}"
          f"({appinfo.AUTHOR_NAME_EN}) <{appinfo.AUTHOR_EMAIL}>",
          appinfo.copyright_line())
    check("about_text() 里带版权行与许可说明",
          appinfo.copyright_line() in appinfo.about_text()
          and "LICENSE.txt" in appinfo.about_text()
          and "NOTICE.txt" in appinfo.about_text())
    # 合规检查：代码里不能出现 GPL-only 的 Qt 模块
    _src = Path(__file__).resolve().parents[1] / "pickersrc"
    _code = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                      for p in _src.glob("*.py"))
    for _mod in ("QtCharts", "QtDataVisualization", "QtGraphs",
                 "QtVirtualKeyboard", "QtWebEngine"):
        check(f"代码里没有 GPL-only / 高危模块 {_mod}", _mod not in _code)
    _qts = set(re.findall(r"from PySide6\.(Qt\w+)", _code))
    check("只用到 QtCore / QtGui / QtWidgets（都是 LGPLv3）",
          _qts <= {"QtCore", "QtGui", "QtWidgets"}, "、".join(sorted(_qts)))

    # ---- ② 导出对话框：默认勾选「附 Survey 文件头」 ----
    d0 = ExportDialog(10, 5)
    check("导出对话框**出厂默认就勾上**「附 Survey 文件头」",
          d0.chk_survey.isChecked())
    check("导出对话框默认不勾「处理理由」、格式=原始、内容=仅保留",
          not d0.chk_reason.isChecked() and d0.mode() == "verbatim"
          and d0.which() == "keep")
    d0.deleteLater()

    # ---- ③ 记忆：写盘 → 读回 ----
    cfg = tmp / "settings.json"
    st = Settings(cfg)
    check("新配置的默认值里 survey_header = True",
          bool(st.get("export/survey_header")))
    st.remember_export(mode="parsed", which="scope", reason=True,
                       survey_header=False)
    st.set("view/show_all", False)
    st.set("plot/kind", "band")
    st.save()
    check("配置文件写出来了", cfg.exists(), str(cfg))
    st2 = Settings(cfg)
    d1 = ExportDialog(10, 5, options=st2.export_options())
    check("导出选项被记住（格式 / 内容 / 理由 / 文件头）",
          d1.mode() == "parsed" and d1.which() == "scope"
          and d1.with_reason() and not d1.with_survey_header(),
          f"{d1.mode()} / {d1.which()} / 理由={d1.with_reason()} / "
          f"文件头={d1.with_survey_header()}")
    d1.deleteLater()
    check("视图与图形视图也被记住",
          st2.get("view/show_all") is False and st2.get("plot/kind") == "band")

    # ---- ④ 关窗口再开：界面习惯（含条件栈）恢复 ----
    w1 = MainWindow(settings_path=cfg)
    w1.show()
    for _ in range(3):
        app.processEvents()
    w1.show_only_filtered()
    w1.cmb_view.setCurrentIndex(w1.cmb_view.findData("quality"))
    w1.conds = w1.conds[:2]
    w1._refresh_cond_table()
    w1.split.setSizes([520, 470, 660])
    _split_want = list(w1.split.sizes())
    w1.close()
    check("关窗口时把设置落盘了（文件里有 window/geometry 等）",
          bool(Settings(cfg).get("window/geometry")),
          f"键 {len(Settings(cfg).data)} 个")

    w2 = MainWindow(settings_path=cfg)
    w2.show()
    for _ in range(4):
        app.processEvents()
    check("重开：视图模式恢复（只看筛选结果）", w2.show_all is False)
    check("重开：图形视图恢复", w2.cmb_view.currentData() == "quality",
          str(w2.cmb_view.currentData()))
    check("重开：条件栈恢复（上次改过的两条）",
          [c.brief() for c in w2.conds] == [c.brief() for c in w1.conds],
          "；".join(c.brief() for c in w2.conds))
    check("重开：分栏宽度恢复",
          all(abs(a - b) <= 3 for a, b in zip(w2.split.sizes(), _split_want)),
          f"{w2.split.sizes()} vs {_split_want}")
    check("窗口图标非空（任务栏/标题栏图标）", not w2.windowIcon().isNull())

    # ---- ⑤ 关于 / 作者信息 ----
    dlg = AboutDialog(None, w2.settings)
    dlg.resize(820, 680)
    dlg.show()
    for _ in range(3):
        app.processEvents()
    txt = " ".join(lab.text() for lab in dlg.findChildren(QLabel))
    # QGroupBox 的标题不在 QLabel 里（"快速上手"是组标题），单独收进来一起查
    from PySide6.QtWidgets import QGroupBox as _QGB

    txt += " " + " ".join(g.title() for g in dlg.findChildren(_QGB))
    for name, key in (("作者", appinfo.AUTHOR_NAME_CN),
                      ("单位", appinfo.AUTHOR_AFFILIATION_CN),
                      ("邮箱", appinfo.AUTHOR_EMAIL),
                      ("电话", appinfo.AUTHOR_PHONE),
                      ("公众号", appinfo.WECHAT_ACCOUNT)):
        check(f"关于对话框里有{name}", key in txt, key)
    _qr = [lab for lab in dlg.findChildren(QLabel)
           if lab.pixmap() is not None and not lab.pixmap().isNull()]
    check("关于对话框里**画出了公众号二维码**", bool(_qr),
          f"{len(_qr)} 个二维码控件")
    check("关于对话框里有快速上手与许可说明",
          "快速上手" in txt and "科研与教学" in txt and "PySide6" in txt)
    dlg.close()

    # ---- ⑥ HTML 使用说明（窗口内预览，与 SHKit/SHSynth 同一形式）----
    from pickersrc.docs_window import GuideDialog

    check("使用说明 HTML 随包在（docs\\使用说明.html）",
          appinfo.guide_html_path() is not None,
          str(appinfo.guide_html_path()))
    g = GuideDialog()
    g.resize(1060, 780)
    g.show()
    for _ in range(4):
        app.processEvents()
    check("使用说明窗口有目录（点一条能跳章节）", g.toc.count() >= 8,
          f"{g.toc.count()} 条")
    _body = g.view.toPlainText()
    check("正文读进来了（不是空白/报错页）", len(_body) > 2000, f"{len(_body)} 字")
    check("说明书是**用户向**的（安装包/开始菜单/不用装 Python），"
          "不提开发者那套（python main.py / .venv / 自检脚本）",
          "安装包" in _body and "开始菜单" in _body and "不需要装 Python" in _body
          and "main.py" not in _body and ".venv" not in _body
          and "selfcheck" not in _body and "verify_all" not in _body)
    check("说明书画出了配图（界面截图）",
          any(not lab.pixmap().isNull() for lab in g.findChildren(QLabel)
              if lab.pixmap() is not None)
          or g.view.document().toHtml().count("<img") > 0,
          f"img 标签 {g.view.document().toHtml().count('<img')} 个")
    _z0 = g.view.zoomIn if hasattr(g.view, "zoomIn") else None
    g._zoom_by(1)
    check("A+ / A− 能调字号（不动正文内容）",
          g._zoom == 1 and len(g.view.toPlainText()) == len(_body))
    g._zoom_reset()
    check("字号复位回默认", g._zoom == 0)
    check("工具条里有「用浏览器打开」", g.btn_browser.text() == "用浏览器打开")
    g.close()

    # ---- ⑦ 主界面上的入口 ----
    check("主界面有「📖 使用说明」与「ⓘ 关于」两个入口",
          "使用说明" in w2.btn_guide.text() and "关于" in w2.btn_about.text())
    w2.close()


def main() -> int:
    from PySide6.QtWidgets import QApplication

    # ★ 自检期间把 %APPDATA% 指到临时目录：本地配置/条件组合都读写临时文件，
    #   既不污染用户真配置，也保证自检不受上一次运行留下的窗口几何影响
    #   （踩过：离屏那次把很小的分栏尺寸写进真配置，下一轮 ② 面板窄到 257px）。
    _tmp_root = Path(tempfile.mkdtemp(prefix="cg5pick_verify_"))
    os.environ["APPDATA"] = str(_tmp_root)
    os.environ.setdefault("HOME", str(_tmp_root))
    # ★ 配置目录（安装目录/config）也必须隔离：自检里的离屏窗口会把自己的
    #   window/geometry 与 maximized=false 写进去 —— 那会把**真程序**的启动状态
    #   搞坏（实测踩过：自检跑过一轮后，源码版与打包版打开都不最大化了）。
    os.environ["CG5PICKER_CONFIG_DIR"] = str(_tmp_root / "config")

    from pickersrc.plots import ensure_cjk_font
    from pickersrc.window import _create_app

    app = _create_app() or QApplication.instance()
    ensure_cjk_font()
    tmp = _tmp_root
    head("CG5 数据挑选 —— 功能自检（离屏）")
    print(f"临时目录：{tmp}")

    test_export()
    test_display_rule()
    test_scope(app)
    test_presets(app, tmp)
    test_column_order_and_sort(app)
    test_cond_inline(app)
    test_or_and_groups()
    test_mutual_diff_last_value()
    test_table_view_modes(app)
    test_row_styling_and_new_cond(app)
    test_manual(app)
    test_plot_interaction(app)
    test_box_select(app)
    test_rect_persistence_and_empty_click(app)
    test_views(app)
    test_tide_theory()
    test_copy_and_view_mode(app)
    test_plot_follows_view_mode(app)
    test_layout_widths(app)
    test_legend_placement(app)
    test_source_view(app)
    test_settings_and_about(app, tmp)
    test_window_maximized(app)

    head("核对结果")
    if _fails:
        print(f"存在失败项 ✘（{len(_fails)}）：")
        for f in _fails:
            print(f"  · {f}")
    else:
        print("全部通过 ✔")
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
