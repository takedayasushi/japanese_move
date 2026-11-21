#!/usr/bin/env python3
"""
e-Stat 一次統計データ取得・JSON生成スクリプト（japanese_move 用）

対象年次: 2024年（住民基本台帳人口移動報告 年報の最新年次）
出典（すべて総務省統計局・e-Stat。ファイルダウンロード経由のため API キー不要）:
  表3-1  年齢（5歳階級）、男女別他都道府県からの転入者数        statInfId 000040243448
  表3-2  年齢（5歳階級）、男女別他都道府県への転出者数        statInfId 000040243449
  表3-3  年齢（5歳階級）、男女別転入超過数                    statInfId 000040243450
  表8-1  年齢（5歳階級）、男女、移動前の住所地別転入者数      statInfId 000040243456
  表8-2  年齢（5歳階級）、男女、移動後の住所地別転出者数      statInfId 000040243457
  表80   男女別国外からの転入者数、国外への転出者数及び職権消除等 statInfId 000040243483
  令和2年国勢調査 移動人口の男女・年齢等集計
         第6表 5年前の常住都道府県、年齢（5歳階級）、男女別人口 statInfId 000032169778

重要な注意:
- 数値はすべて実測値。補間・推計は一切しない。
- 85歳以上 = 85～89歳 + 90歳以上の合計。
- 海外との出入りは年齢別の公表がないため、全年代合計のみ（intl）。
- 国勢調査に「出生地別人口」の公表集計はないため、出生地構成の代わりに
  2020年国勢調査 第6表「5年前の常住地別人口（原数値）」を用いる（prevResidence）。
  2020年調査では移動状況「不詳」が多い（東京都で24.8%）ことに注意。
- 年齢階級別数値の合計（2,523,239人）は公表の総数（2,523,249人）と10人異なる
  （年齢階級表に含まれない10人分）。本JSONは年齢階級別の実測値を用いる。

使い方:
  python3 build_migration_data.py --year 2024 --out data/migration.json
  python3 build_migration_data.py --year 2024 --out data/migration.json --source-dir source
"""

import argparse
import datetime
import json
import re
import urllib.request
from pathlib import Path

AGE_GROUPS = [
    "0～4歳", "5～9歳", "10～14歳", "15～19歳", "20～24歳", "25～29歳",
    "30～34歳", "35～39歳", "40～44歳", "45～49歳", "50～54歳", "55～59歳",
    "60～64歳", "65～69歳", "70～74歳", "75～79歳", "80～84歳", "85歳以上",
]

PREFECTURES = [
    ("01", "北海道", "北海"), ("02", "青森県", "青森"), ("03", "岩手県", "岩手"),
    ("04", "宮城県", "宮城"), ("05", "秋田県", "秋田"), ("06", "山形県", "山形"),
    ("07", "福島県", "福島"), ("08", "茨城県", "茨城"), ("09", "栃木県", "栃木"),
    ("10", "群馬県", "群馬"), ("11", "埼玉県", "埼玉"), ("12", "千葉県", "千葉"),
    ("13", "東京都", "東京"), ("14", "神奈川県", "神奈川"), ("15", "新潟県", "新潟"),
    ("16", "富山県", "富山"), ("17", "石川県", "石川"), ("18", "福井県", "福井"),
    ("19", "山梨県", "山梨"), ("20", "長野県", "長野"), ("21", "岐阜県", "岐阜"),
    ("22", "静岡県", "静岡"), ("23", "愛知県", "愛知"), ("24", "三重県", "三重"),
    ("25", "滋賀県", "滋賀"), ("26", "京都府", "京都"), ("27", "大阪府", "大阪"),
    ("28", "兵庫県", "兵庫"), ("29", "奈良県", "奈良"), ("30", "和歌山県", "和歌山"),
    ("31", "鳥取県", "鳥取"), ("32", "島根県", "島根"), ("33", "岡山県", "岡山"),
    ("34", "広島県", "広島"), ("35", "山口県", "山口"), ("36", "徳島県", "徳島"),
    ("37", "香川県", "香川"), ("38", "愛媛県", "愛媛"), ("39", "高知県", "高知"),
    ("40", "福岡県", "福岡"), ("41", "佐賀県", "佐賀"), ("42", "長崎県", "長崎"),
    ("43", "熊本県", "熊本"), ("44", "大分県", "大分"), ("45", "宮崎県", "宮崎"),
    ("46", "鹿児島県", "鹿児島"), ("47", "沖縄県", "沖縄"),
]
PREF_CODES = [c for c, _, _ in PREFECTURES]
PREF_NAME = {c: n for c, n, _ in PREFECTURES}

ESTAT_DL = "https://www.e-stat.go.jp/stat-search/file-download?statInfId={id}&fileKind={kind}"

SOURCES = {
    "inflow_age":  ("000040243448", 0, "表3-1 年齢（5歳階級）、男女別他都道府県からの転入者数"),
    "outflow_age": ("000040243449", 0, "表3-2 年齢（5歳階級）、男女別他都道府県への転出者数"),
    "net_age":     ("000040243450", 0, "表3-3 年齢（5歳階級）、男女別転入超過数"),
    "inflow_od":   ("000040243456", 0, "表8-1 年齢（5歳階級）、男女、移動前の住所地別転入者数"),
    "outflow_od":  ("000040243457", 0, "表8-2 年齢（5歳階級）、男女、移動後の住所地別転出者数"),
    "intl":        ("000040243483", 0, "表80 男女別国外からの転入者数、国外への転出者数及び職権消除等"),
    "census6":     ("000032169778", 0, "令和2年国勢調査 第6表 5年前の常住都道府県、年齢（5歳階級）、男女別人口"),
}

UA = {"User-Agent": "Mozilla/5.0 (compatible; japanese_move data builder)"}


def download_sources(source_dir: Path) -> dict:
    source_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, (inf_id, kind, title) in SOURCES.items():
        dest = source_dir / f"{key}_{inf_id}.xlsx"
        if dest.exists() and dest.stat().st_size > 1000:
            print(f"  既存ファイルを利用: {dest.name}")
        else:
            url = ESTAT_DL.format(id=inf_id, kind=kind)
            print(f"  ダウンロード中: {title} ...")
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
                f.write(resp.read())
            print(f"    -> {dest.name} ({dest.stat().st_size:,} bytes)")
        paths[key] = dest
    return paths


def load_wb(path: Path):
    import openpyxl
    return openpyxl.load_workbook(path, data_only=True, read_only=True)


def find_header_row(ws, marker: str, max_scan: int = 12):
    for r in ws.iter_rows(min_row=1, max_row=max_scan, values_only=True):
        if r and r[0] == marker:
            return r
    raise ValueError(f"見出し行 '{marker}' が見つかりません")


def age_value_cols(ws):
    for r in ws.iter_rows(min_row=1, max_row=12, values_only=True):
        vals = [v for v in r if v is not None]
        if len(vals) >= 20 and vals[0] == "総数" and vals[1] == "0歳～4歳":
            return vals[:20]
    raise ValueError("年齢見出し行が見つかりません")


def parse_age_table_3x(path: Path):
    """表3-1/3-2/3-3 を読む。戻り値: {都道府県コード: [総数, 0-4, ..., 85-89, 90歳以上]（20値）}"""
    wb = load_wb(path)
    ws = wb[wb.sheetnames[0]]
    header = find_header_row(ws, "表章項目")
    val_start = next(i for i, v in enumerate(header) if v == "人")
    labels = age_value_cols(ws)
    assert labels[0] == "総数" and labels[1] == "0歳～4歳" and labels[-1] == "90歳以上", labels
    out = {}
    for r in ws.iter_rows(min_row=1, values_only=True):
        if not r or len(r) <= 6:
            continue
        if r[2] != "移動者":
            continue
        code_raw = str(r[5]).strip() if r[5] is not None else ""
        m = re.fullmatch(r"(\d{2})000", code_raw)
        if not m or m.group(1) not in PREF_CODES:
            continue
        vals = [int(v) if v is not None else 0 for v in r[val_start:val_start + 20]]
        out[m.group(1)] = vals
    assert len(out) == 47, f"都道府県が47件ありません: {len(out)}"
    return out


def collapse_85plus(vals20):
    """[総数, 0-4, ..., 85-89, 90歳以上] -> 18階級 [0-4, ..., 80-84, 85歳以上]"""
    ages = vals20[1:]
    assert len(ages) == 19
    return ages[:17] + [ages[17] + ages[18]]


def parse_od_table(path: Path, direction: str):
    """表8-1/8-2 を読む。戻り値: {(from, to): [18階級の人数]}"""
    wb = load_wb(path)
    ws = wb[wb.sheetnames[0]]
    header = find_header_row(ws, "表章項目")
    val_start = next(i for i, v in enumerate(header) if v == "人")
    labels = age_value_cols(ws)
    assert labels[0] == "総数" and labels[-1] == "90歳以上", labels
    out = {}
    for r in ws.iter_rows(min_row=1, values_only=True):
        if not r or len(r) <= 8:
            continue
        if r[4] != "移動者":
            continue
        if direction == "inflow":
            dest_raw, orig_raw = str(r[1]).strip(), str(r[7]).strip()
        else:
            orig_raw, dest_raw = str(r[1]).strip(), str(r[7]).strip()
        md = re.fullmatch(r"(\d{2})000", dest_raw)
        mo = re.fullmatch(r"(\d{2})000", orig_raw)
        if not md or not mo or md.group(1) not in PREF_CODES or mo.group(1) not in PREF_CODES:
            continue
        d, o = md.group(1), mo.group(1)
        if d == o:
            continue
        vals = [int(v) if v is not None else 0 for v in r[val_start:val_start + 20]]
        out[(o, d)] = collapse_85plus(vals)
    return out


def parse_intl(path: Path):
    """表80 を読む。戻り値: (in, out) 各 {都道府県コード: 人数}（全年代合計・移動者）"""
    wb = load_wb(path)
    ws = wb[wb.sheetnames[0]]
    inn, out = {}, {}
    for r in ws.iter_rows(min_row=1, values_only=True):
        if not r or len(r) < 10:
            continue
        if r[1] != "移動者":
            continue
        code_raw = str(r[4]).strip() if r[4] is not None else ""
        m = re.fullmatch(r"(\d{2})000", code_raw)
        if not m or m.group(1) not in PREF_CODES:
            continue
        inn[m.group(1)] = int(r[6])
        out[m.group(1)] = int(r[9])
    assert len(inn) == 47 and len(out) == 47
    return inn, out


def parse_census6(path: Path):
    """国勢調査 第6表を読む。戻り値: {現住地コード: [(code, label, count, pct), ...]（上位8件）}"""
    wb = load_wb(path)
    ws = wb[wb.sheetnames[0]]
    col_header = None
    for r in ws.iter_rows(min_row=1, max_row=12, values_only=True):
        if r and len(r) > 3 and r[3] == "00000_全国":
            col_header = r
            break
    assert col_header is not None
    col_of = {}
    for idx, v in enumerate(col_header):
        if isinstance(v, str) and re.fullmatch(r"(\d{2})000_.+", v) and v[:2] in PREF_CODES:
            col_of[v[:2]] = idx
    assert len(col_of) == 47, len(col_of)
    total = {}
    out = {}
    for r in ws.iter_rows(min_row=1, values_only=True):
        if not r or r[0] != "0_総数" or r[1] != "00_総数":
            continue
        row_label = str(r[2])
        if row_label == "00000_総数":
            total = {code: int(r[idx]) for code, idx in col_of.items()}
            continue
        if row_label.startswith("99997_"):
            code, label = "99", "国外"
        elif row_label.startswith("99998_"):
            code, label = "UNK1", "5年前の常住市区町村「不詳」"
        elif row_label.startswith("99999_"):
            code, label = "UNK2", "移動状況「不詳」"
        else:
            m = re.fullmatch(r"(\d{2})000_(.+)", row_label)
            if not m:
                continue
            code, label = m.group(1), m.group(2)
        for pref, idx in col_of.items():
            v = int(r[idx]) if r[idx] is not None else 0
            out.setdefault(pref, []).append((code, label, v))
    result = {}
    for pref, items in out.items():
        tot = total[pref]
        items.sort(key=lambda t: -t[2])
        result[pref] = [
            {"code": c, "label": lab, "count": v, "pct": round(v / tot * 100, 1) if tot else 0.0}
            for c, lab, v in items[:8]
        ]
        assert sum(v for _, _, v in items) == tot, f"{pref}: 内訳合計が総数と不一致"
    return result


def main():
    ap = argparse.ArgumentParser(description="Build migration.json from e-Stat files")
    ap.add_argument("--year", default="2024", help="対象年次 (例: 2024)")
    ap.add_argument("--out", default="data/migration.json", help="出力JSONパス")
    ap.add_argument("--source-dir", default="source", help="e-Stat Excel の保存先")
    ap.add_argument("--no-download", action="store_true", help="ダウンロードせず既存ファイルのみ使う")
    args = ap.parse_args()

    source_dir = Path(args.source_dir)
    if args.no_download:
        paths = {k: source_dir / f"{k}_{v[0]}.xlsx" for k, v in SOURCES.items()}
        missing = [str(p) for p in paths.values() if not p.exists()]
        if missing:
            raise SystemExit(f"不足ファイル: {missing}")
    else:
        paths = download_sources(source_dir)

    print("表3-1/3-2/3-3 を解析中...")
    inflow = parse_age_table_3x(paths["inflow_age"])
    outflow = parse_age_table_3x(paths["outflow_age"])
    netpub = parse_age_table_3x(paths["net_age"])
    print("表8-1/8-2 を解析中...")
    flows_in = parse_od_table(paths["inflow_od"], "inflow")
    flows_out = parse_od_table(paths["outflow_od"], "outflow")
    print("表80（海外）を解析中...")
    intl_in, intl_out = parse_intl(paths["intl"])
    print("国勢調査 第6表を解析中...")
    prev = parse_census6(paths["census6"])

    errors = []
    for code in PREF_CODES:
        ni = collapse_85plus(inflow[code])
        no = collapse_85plus(outflow[code])
        nn = collapse_85plus(netpub[code])
        for i in range(18):
            if ni[i] - no[i] != nn[i]:
                errors.append(f"転入超過不一致 {code} {AGE_GROUPS[i]}: {ni[i]}-{no[i]}={ni[i]-no[i]} vs 公表 {nn[i]}")
    for i in range(18):
        s = sum(collapse_85plus(netpub[c])[i] for c in PREF_CODES)
        if s != 0:
            errors.append(f"転入超過の全国合計が0でない {AGE_GROUPS[i]}: {s}")
    for i in range(18):
        s_in = sum(v[i] for v in flows_in.values())
        s_out = sum(v[i] for v in flows_out.values())
        if s_in != s_out:
            errors.append(f"OD表の流入合計と流出合計が不一致 {AGE_GROUPS[i]}: {s_in} vs {s_out}")
    wb = load_wb(paths["inflow_age"])
    ws = wb[wb.sheetnames[0]]
    header = find_header_row(ws, "表章項目")
    val_start = next(i for i, v in enumerate(header) if v == "人")
    national = None
    for r in ws.iter_rows(min_row=1, values_only=True):
        if r and r[2] == "移動者" and str(r[5]).strip() == "00000":
            national = collapse_85plus([int(v) if v is not None else 0 for v in r[val_start:val_start + 20]])
            break
    for i in range(18):
        s = sum(v[i] for v in flows_in.values())
        if s != national[i]:
            errors.append(f"OD合計と表3-1全国が不一致 {AGE_GROUPS[i]}: OD合計 {s} vs 全国 {national[i]}")
    mismatch = 0
    for k, v in flows_in.items():
        if flows_out.get(k) != v:
            mismatch += 1
    if mismatch:
        errors.append(f"表8-1/8-2 の不一致フロー: {mismatch}件")
    if set(flows_in) != set(flows_out):
        errors.append("表8-1/8-2 のフロー集合が異なる")

    print("検算: 転入超過の照合 47都道府県×18階級、OD合計、8-1/8-2照合を実施")
    if errors:
        print("【検算エラー】")
        for e in errors[:20]:
            print("  -", e)
        raise SystemExit(f"検算で {len(errors)} 件の不一致がありました")
    print("検算: 全項目一致")

    by_age = {}
    for i, age in enumerate(AGE_GROUPS):
        net = {code: collapse_85plus(netpub[code])[i] for code in PREF_CODES}
        flows = [
            {"from": o, "to": d, "count": v[i]}
            for (o, d), v in sorted(flows_in.items())
            if v[i] > 0
        ]
        by_age[age] = {"net": net, "flows": flows}

    data = {
        "meta": {
            "title": "日本人の県外移動アニメーション",
            "source": "総務省統計局『住民基本台帳人口移動報告』年報（2024年）および『国勢調査』（2020年）",
            "targetYear": args.year,
            "tables": {k: {"title": v[2], "statInfId": v[0]} for k, v in SOURCES.items()},
            "notes": [
                "数値はすべて実測値で、補間・推計はしていない。",
                "85歳以上は「85～89歳」と「90歳以上」の合計。",
                "転入超過数は都道府県間の移動のみ。海外との出入りは年齢別の公表がないため、全年代合計を別に表示している。",
                "国勢調査に「出生地別人口」の公表集計はないため、居住者の出身構成は2020年国勢調査 第6表「5年前の常住地別人口（原数値）」で代用している。2020年調査では移動状況「不詳」が多い（東京都で24.8%）。",
                "年齢階級別数値の合計（2,523,239人）は公表の総数（2,523,249人）と10人異なる（年齢階級表に含まれない10人分）。",
            ],
            "generatedAt": datetime.date.today().isoformat(),
        },
        "ageGroups": AGE_GROUPS,
        "prefectures": [
            {"code": c, "name": n, "short": s} for c, n, s in PREFECTURES
        ] + [{"code": "99", "name": "海外", "short": "海外"}],
        "byAge": by_age,
        "intl": {
            "in": intl_in,
            "out": intl_out,
            "totalIn": sum(intl_in.values()),
            "totalOut": sum(intl_out.values()),
            "note": "国外からの転入者数・国外への転出者数（2024年・全年代合計・移動者）。年齢別の公表はない。",
        },
        "prevResidence": prev,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"出力完了: {out_path} ({out_path.stat().st_size:,} bytes)")
    print(f"  年次: {args.year} / 年齢階級: {len(AGE_GROUPS)} / フロー総数(18階級): "
          f"{sum(len(by_age[a]['flows']) for a in AGE_GROUPS):,}")
    print(f"  都道府県間移動者数（2024年・全年代）: {sum(national):,}人")
    print(f"  国外からの転入: {sum(intl_in.values()):,}人 / 国外への転出: {sum(intl_out.values()):,}人")


if __name__ == "__main__":
    main()
