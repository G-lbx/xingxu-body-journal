"""Offline body-scale report extraction using native OCR and spatial labels.

Values always come from recognized text. Missing/ambiguous labels stay empty;
the parser never infers metrics from a template position or another metric.
"""
from __future__ import annotations

import functools
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unicodedata

FIELD_LABELS = {
    'weight': ('Current weight', '当前体重', '体重'),
    'bmi': ('BMI', '体质指数', '身体质量指数'),
    'standard_weight': ('Standard weight', '标准体重'),
    'body_fat': ('Bfp', 'Body fat percentage', 'Body fat rate', '体脂率', '脂肪率'),
    'fat_mass': ('Fat weight', 'Fat mass', '脂肪量', '脂肪重量'),
    'water_pct': ('WaterRate', 'Water rate', '水分率', '身体水分率', '水分百分比'),
    'water_mass': ('Water', '水分量', '水分重量'),
    'muscle_pct': ('MuscleRate', 'Muscle rate', '肌肉率'),
    'muscle_mass': ('Muscle', 'Muscle mass', '肌肉量', '肌肉重量'),
    'protein_pct': ('ProteinRate', 'Protein rate', '蛋白质率', '蛋白率'),
    'protein_mass': ('Protein', 'Protein mass', '蛋白质量', '蛋白质重量'),
    'skeletal_pct': ('SmuscleRate', 'Skeletal muscle rate', '骨骼肌率'),
    'skeletal_mass': ('Smuscle', 'Skeletal muscle', '骨骼肌量', '骨骼肌重量'),
    'bmr': ('Bmr', 'Basal metabolic rate', '基础代谢', '基础代谢率'),
    'visceral_fat': ('Vf', 'Visceral fat', '内脏脂肪', '内脏脂肪等级', '内脏脂肪指数'),
    'bone_mass': ('Bone', 'Bone mass', '骨量', '骨重量'),
    'fat_free_mass': ('Fat free weight', 'Fat free mass', '去脂体重', '去脂重量'),
    'score': ('Score', '身体得分', '身体评分', '得分', '评分'),
    'body_age': ('Physical age', 'Body age', '身体年龄', '体年龄'),
    'obesity_pct': ('Obesity', '肥胖度', '肥胖率'),
    'weight_control': ('Weight control', '体重控制'),
    'muscle_control': ('Muscle control', '肌肉控制'),
    'fat_control': ('Fat control', '脂肪控制'),
}
DISPLAY = {key: labels[-1] for key, labels in FIELD_LABELS.items()}
DISPLAY.update(weight='体重', bmi='BMI', body_fat='体脂率', bmr='基础代谢', body_age='身体年龄')
_FIELDS = ('measured_at', *FIELD_LABELS)
_SCRIPT = Path(__file__).resolve().parent / 'scripts' / 'windows_ocr.ps1'
_MAC_HELPER = Path(__file__).resolve().parent / 'scripts' / 'macos_ocr'


def engine_name() -> str:
    return 'Apple Vision' if sys.platform == 'darwin' else 'Windows OCR' if sys.platform == 'win32' else '本机 OCR'


def _powershell() -> str | None:
    if os.name != 'nt':
        return None
    native = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe'
    return str(native) if native.is_file() else shutil.which('powershell.exe')


def _run(args: list[str], timeout: int = 35) -> dict:
    if sys.platform == 'darwin':
        if not _MAC_HELPER.is_file():
            raise RuntimeError('缺少 Mac OCR 组件，请重新下载完整程序包；源码运行请先执行 scripts/build_macos_ocr.sh。')
        command = [str(_MAC_HELPER), '--check'] if args == ['-Check'] else [str(_MAC_HELPER), '--image', args[1]]
    else:
        exe = _powershell()
        if not exe:
            raise RuntimeError('当前系统未提供可用的本机 OCR。')
        command = [exe, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(_SCRIPT), *args]
    proc = subprocess.run(
        command,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
    )
    output = proc.stdout.decode('utf-8-sig', errors='replace').strip()
    try:
        data = json.loads(output)
    except (ValueError, TypeError) as exc:
        raise RuntimeError('本机 OCR 未返回可读取的结果，请手动填写。') from exc
    if proc.returncode or data.get('error'):
        raise RuntimeError('本机 OCR 暂不可用或图片无法解码，请手动填写。')
    return data


@functools.lru_cache(maxsize=1)
def available() -> bool:
    """Check the local OCR language engine without loading an image."""
    if sys.platform == 'darwin' and not _MAC_HELPER.is_file():
        return False
    if sys.platform != 'darwin' and (not _SCRIPT.is_file() or not _powershell()):
        return False
    try:
        return bool(_run(['-Check'], timeout=12).get('available'))
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        return False


def _normalize(text: str) -> str:
    text = unicodedata.normalize('NFKC', str(text))
    return text.replace('·', '.').replace('•', '.').replace('。', '.').replace('−', '-').replace('—', '-').replace('一', '-')


def _compact(text: str) -> str:
    return re.sub(r'\s+', '', _normalize(text)).lower()


_ALIASES = sorted(
    ((_compact(alias), key) for key, aliases in FIELD_LABELS.items() for alias in aliases),
    key=lambda item: -len(item[0]),
)


def _number(text: str) -> tuple[float, bool] | None:
    clean = _compact(text).strip(':：=()[]')
    # OCR often renders the zero in +0.6 as O. Only correct numeric decimal
    # contexts, and report the correction for the user's review.
    corrected = bool(re.search(r'(?<![a-z])o(?=\.\d)', clean))
    if corrected:
        clean = re.sub(r'(?<![a-z])o(?=\.\d)', '0', clean)
    match = re.fullmatch(r'([+-]?(?:\d+(?:\.\d+)?|\.\d+))(?:kg|kcal(?:/日|/d)?|%|岁|公斤|千克|千卡(?:/天)?|级)?', clean)
    if not match:
        return None
    number = float(match[1])
    return (number, corrected) if math.isfinite(number) else None


def _label(text: str) -> tuple[str, tuple[float, bool] | None] | None:
    compact = _compact(text)
    for alias, key in _ALIASES:
        for prefix in ('', '0', 'o', '6'):
            target = prefix + alias
            if compact == target or compact == target + '(kg)' or compact == target + '(%)':
                return key, None
            if compact.startswith(target):
                rest = compact[len(target):].lstrip(':=')
                numeric = _number(rest)
                if numeric is not None:
                    return key, numeric
    return None


def _box(words: list[dict], text: str | None = None) -> dict | None:
    try:
        x = min(float(w['x']) for w in words)
        y = min(float(w['y']) for w in words)
        right = max(float(w['x']) + float(w['width']) for w in words)
        bottom = max(float(w['y']) + float(w['height']) for w in words)
    except (ValueError, KeyError, TypeError):
        return None
    if not all(math.isfinite(v) for v in (x, y, right, bottom)):
        return None
    return {'text': text if text is not None else ' '.join(str(w.get('text', '')) for w in words),
            'x': x, 'y': y, 'right': right, 'bottom': bottom, 'height': bottom-y}


def _date(lines: list[dict]) -> str | None:
    from datetime import datetime
    dates = []
    for line in lines:
        text = _normalize(line.get('text', ''))
        if re.search(r'last|previous|上次|上一次|较前', text, re.I):
            continue
        match = re.search(r'(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?\s+(\d{1,2})\s*:\s*(\d{2})', text)
        if match:
            try:
                value = datetime(*map(int, match.groups())).strftime('%Y-%m-%dT%H:%M')
            except ValueError:
                continue
            box = _box(line.get('words', []))
            dates.append((box['y'] if box else len(dates), value))
    return min(dates)[1] if dates else None


def parse_ocr(payload: dict | str) -> dict:
    """Parse native OCR line/word geometry; strings support labelled lines only.

    Returns the same envelope as extract_image(). Coordinate-free text requires
    label and number on the same line; we never zip unrelated labels/values.
    """
    if isinstance(payload, str):
        payload = {'text': payload, 'lines': [{'text': s} for s in payload.splitlines()]}
    fields = {key: None for key in _FIELDS}
    warnings: list[str] = []
    raw_lines = payload.get('lines', [])
    raw_text = '\n'.join(str(line.get('text', '')) for line in raw_lines) or str(payload.get('text', ''))
    fields['measured_at'] = _date(raw_lines)
    width = float(payload.get('width') or 0)
    height = float(payload.get('height') or 0)
    boxes: list[dict] = []
    candidates: dict[str, list[tuple[float, bool]]] = {k: [] for k in FIELD_LABELS}
    for line in raw_lines:
        words = line.get('words', [])
        if not words:
            label = _label(line.get('text', ''))
            if label and label[1] is not None:
                candidates[label[0]].append(label[1])
            continue
        # Some recognizers combine the two columns into one line. Split on
        # the image midpoint before matching, retaining each word's geometry.
        groups = [words] if width <= 0 else [
            [w for w in words if float(w.get('x', 0)) < width/2],
            [w for w in words if float(w.get('x', 0)) >= width/2],
        ]
        for group in groups:
            box = _box(group) if group else None
            if box:
                box['column'] = int(width > 0 and box['x'] >= width/2)
                box['label'] = _label(box['text'])
                box['number'] = _number(box['text'])
                boxes.append(box)
    for label_box in boxes:
        label = label_box['label']
        if label is None:
            continue
        key, inline = label
        if inline is not None:
            candidates[key].append(inline)
            continue
        # Stop before the next label in this column, preventing a missing
        # value from borrowing a number from the following metric.
        next_y = min((b['y'] for b in boxes if b['label'] is not None and
                      b['column'] == label_box['column'] and b['y'] > label_box['bottom']), default=float('inf'))
        max_gap = max(2.5*label_box['height'], min(height*.05, 5.5*label_box['height']))
        options = []
        for value_box in boxes:
            if value_box['number'] is None or value_box['column'] != label_box['column']:
                continue
            dy = value_box['y'] - label_box['bottom']
            below = dy >= -0.15*label_box['height'] and dy <= max_gap
            alongside = abs(value_box['y']-label_box['y']) <= label_box['height']*.5 and value_box['x'] >= label_box['right']
            if not (below or alongside) or value_box['y'] >= next_y:
                continue
            # A value may sit a little left of its label (an icon occupies the
            # label's leading space), but cannot drift to the far status badge.
            if width and abs(value_box['x']-label_box['x']) > width*.22:
                continue
            options.append((max(0, dy) + abs(value_box['x']-label_box['x'])*.1, value_box['number']))
        if options:
            options.sort(key=lambda entry: entry[0])
            candidates[key].append(options[0][1])
    for key, values in candidates.items():
        if not values:
            continue
        unique = {round(value[0], 6) for value in values}
        if len(unique) != 1:
            warnings.append(f'{DISPLAY[key]}识别出多个不同数值，请对照原图填写。')
            continue
        fields[key] = values[0][0]
        if any(corrected for _, corrected in values):
            warnings.append(f'{DISPLAY[key]}中的字母 O 已按数字 0 处理，请核对该值。')
    missing = [DISPLAY[key] for key in FIELD_LABELS if fields[key] is None]
    if missing:
        warnings.append('未可靠识别：' + '、'.join(missing) + '。请对照原图补充，留空也可保存。')
    if not fields['measured_at']:
        warnings.append('未识别测量时间，请填写图片上的测量时间。')
    return {'fields': fields, 'raw_text': raw_text, 'warnings': warnings, 'engine': engine_name()}


def extract_image(path: str | Path) -> dict:
    """Read an image locally. All failures return an editable empty result."""
    try:
        resolved = Path(path).resolve(strict=True)
        if not resolved.is_file():
            raise ValueError('请选择有效的图片文件。')
        payload = _run(['-ImagePath', str(resolved)])
        return parse_ocr(payload)
    except subprocess.TimeoutExpired:
        reason = '本机 OCR 识别超时，请重试或手动填写。'
    except (OSError, ValueError, RuntimeError) as exc:
        reason = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else '无法读取图片，请重试或手动填写。'
    return {'fields': {key: None for key in _FIELDS}, 'raw_text': '', 'warnings': [reason], 'engine': engine_name()}


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps(extract_image(sys.argv[1]), ensure_ascii=False, indent=2))
