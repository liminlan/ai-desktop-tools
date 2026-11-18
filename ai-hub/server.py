# -*- coding: utf-8 -*-
"""
AI 聚合助手 · 本地服务
- 打开 index.html 单页应用
- /proxy 转发请求到各家大模型接口（绕开浏览器跨域限制）
只用 Python 标准库，无需 pip 安装任何依赖。
"""
import io as _io
import json
import os
import re
import socket
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
START_PORT = 8760
MAX_PORT = 8799

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.htm': 'text/html; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.webp': 'image/webp',
    '.txt': 'text/plain; charset=utf-8',
    '.md': 'text/plain; charset=utf-8',
}




# ======================================================================
#  工具能力：联网搜索 / 抓网页 / 计算 / 本地文件区
# ======================================================================
import ast as _ast
import base64 as _b64
import html as _html
import math as _math
import time as _time
import ssl as _ssl
import uuid as _uuid

WORK_DIR = os.path.join(ROOT, '文件区')
_UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}
_CTX = _ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = _ssl.CERT_NONE


def _get(url, timeout=15, headers=None):
    req = urllib.request.Request(url, headers=headers or _UA)
    return urllib.request.urlopen(req, timeout=timeout, context=_CTX)


def _strip_tags(html_text):
    t = re.sub(r'<script[^>]*>.*?</script>', ' ', html_text or '', flags=re.S | re.I)
    t = re.sub(r'<style[^>]*>.*?</style>', ' ', t, flags=re.S | re.I)
    t = re.sub(r'<!--.*?-->', ' ', t, flags=re.S)
    t = re.sub(r'<br\s*/?>', '\n', t, flags=re.I)
    t = re.sub(r'</(p|div|li|h\d|tr)>', '\n', t, flags=re.I)
    t = re.sub(r'<[^>]+>', ' ', t)
    t = _html.unescape(t)
    t = re.sub(r'[ \t\u00a0]+', ' ', t)
    t = re.sub(r'\n\s*\n+', '\n\n', t)
    return t.strip()


def _bing_search(query, limit=8):
    """抓 cn.bing.com 的结果页。不依赖任何 Key。"""
    out = []
    url = 'https://cn.bing.com/search?q=' + urllib.parse.quote(query) + '&setlang=zh-CN&mkt=zh-CN'
    html_text = _get(url, timeout=15).read().decode('utf-8', 'ignore')
    for block in re.findall(r'<li class="b_algo".*?</li>', html_text, re.S):
        m = re.search(r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        link = _html.unescape(m.group(1))
        title = _strip_tags(m.group(2))
        snip = ''
        for pat in (r'<p[^>]*>(.*?)</p>', r'<div class="b_caption"[^>]*>(.*?)</div>', r'<div class="b_snippet"[^>]*>(.*?)</div>'):
            mm = re.search(pat, block, re.S)
            if mm:
                raw = _strip_tags(mm.group(1))
                if len(raw) > 20:
                    snip = raw
                    break
        if title and link.startswith('http'):
            out.append({'title': title[:120], 'url': link[:400], 'snippet': snip[:400]})
        if len(out) >= limit:
            break
    return out


def _so360_search(query, limit=8):
    out = []
    url = 'https://www.so.com/s?q=' + urllib.parse.quote(query)
    html_text = _get(url, timeout=15).read().decode('utf-8', 'ignore')
    for m in re.finditer(r'<h3[^>]*>(.*?)</h3>(.*?)(?=<h3|<ul class="pagination|</body>)', html_text, re.S):
        title = _strip_tags(m.group(1))
        if not title or len(title) < 4:
            continue
        body = _strip_tags(m.group(2))[:300]
        out.append({'title': title[:120], 'url': 'https://www.so.com/s?q=' + urllib.parse.quote(title[:40]),
                    'snippet': body})
        if len(out) >= limit:
            break
    return out


def _bocha_search(query, key, limit=8):
    body = json.dumps({'query': query, 'count': limit, 'summary': True}, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request('https://api.bochaai.com/v1/web-search', data=body,
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Bearer ' + key}, method='POST')
    data = json.loads(urllib.request.urlopen(req, timeout=20, context=_CTX).read().decode('utf-8', 'ignore'))
    pages = (((data.get('data') or {}).get('webPages') or {}).get('value') or [])
    out = []
    for p in pages[:limit]:
        out.append({'title': (p.get('name') or '')[:120],
                    'url': (p.get('url') or '')[:400],
                    'snippet': _strip_tags(p.get('snippet') or p.get('summary') or '')[:400]})
    return out


def tool_search(query, engine='auto', key=''):
    query = (query or '').strip()
    if not query:
        return {'error': '搜索词不能为空'}
    errors = []
    if key and engine in ('bocha', 'auto'):
        try:
            r = _bocha_search(query, key)
            if r:
                return {'engine': 'bocha', 'results': r}
        except Exception as e:
            errors.append('bocha: %s' % e)
    if engine in ('bing', 'auto'):
        try:
            r = _bing_search(query)
            if r:
                return {'engine': 'bing', 'results': r}
            errors.append('bing: 没有解析到结果')
        except Exception as e:
            errors.append('bing: %s' % e)
    try:
        r = _so360_search(query)
        if r:
            return {'engine': '360', 'results': r}
    except Exception as e:
        errors.append('360: %s' % e)
    return {'error': '搜索失败（' + '；'.join(errors) + '）',
            'hint': '可能是网络受限。可在设置里填博查（bocha）搜索 Key 走 API。'}


def tool_fetch(url, limit=8000):
    url = (url or '').strip()
    if not url.startswith(('http://', 'https://')):
        return {'error': '地址必须以 http(s) 开头'}
    try:
        resp = _get(url, timeout=20, headers=dict(_UA, Accept='text/html,application/xhtml+xml,*/*'))
        raw = resp.read()
        ctype = (resp.headers.get('Content-Type') or '').lower()
        if 'application/pdf' in ctype or url.lower().endswith('.pdf'):
            return {'error': '这是 PDF，请把 PDF 直接当附件上传，工具里读不了'}
        try:
            text = raw.decode('utf-8')
        except Exception:
            text = raw.decode('gbk', 'ignore')
        title = ''
        m = re.search(r'<title[^>]*>(.*?)</title>', text, re.S | re.I)
        if m:
            title = _strip_tags(m.group(1))
        body = _strip_tags(text)
        return {'url': url, 'title': title, 'text': body[:limit], 'truncated': len(body) > limit}
    except Exception as e:
        return {'error': '抓取失败：%s' % e}


_ALLOWED_MATH = {
    'abs': abs, 'round': round, 'min': min, 'max': max, 'sum': sum, 'len': len,
    'sqrt': _math.sqrt, 'pow': pow, 'log': _math.log, 'log10': _math.log10,
    'sin': _math.sin, 'cos': _math.cos, 'tan': _math.tan, 'pi': _math.pi, 'e': _math.e,
    'floor': _math.floor, 'ceil': _math.ceil,
}
_ALLOWED_NODES = (_ast.Expression, _ast.BinOp, _ast.UnaryOp, _ast.Constant, _ast.Call,
                  _ast.Name, _ast.Load, _ast.Add, _ast.Sub, _ast.Mult, _ast.Div,
                  _ast.FloorDiv, _ast.Mod, _ast.Pow, _ast.USub, _ast.UAdd,
                  _ast.Tuple, _ast.List, _ast.Compare, _ast.Lt, _ast.LtE,
                  _ast.Gt, _ast.GtE, _ast.Eq, _ast.NotEq, _ast.IfExp, _ast.And, _ast.Or)


def tool_calc(expr):
    expr = (expr or '').strip()
    if not expr:
        return {'error': '算式为空'}
    try:
        tree = _ast.parse(expr, mode='eval')
        for node in _ast.walk(tree):
            if not isinstance(node, _ALLOWED_NODES):
                return {'error': '不支持这种写法：%s' % type(node).__name__}
            if isinstance(node, _ast.Name) and node.id not in _ALLOWED_MATH:
                return {'error': '不认识的名称：%s' % node.id}
        val = eval(compile(tree, '<calc>', 'eval'), {'__builtins__': {}}, _ALLOWED_MATH)  # noqa: S307
        if isinstance(val, float):
            val = round(val, 10)
        return {'expr': expr, 'value': val}
    except Exception as e:
        return {'error': '算不出来：%s' % e}


def _safe_path(rel):
    os.makedirs(WORK_DIR, exist_ok=True)
    rel = (rel or '').replace('\\', '/').strip().lstrip('/')
    if rel.startswith('../') or '/../' in rel or rel == '..':
        raise ValueError('不允许跳出文件区')
    full = os.path.normpath(os.path.join(WORK_DIR, rel))
    if not full.startswith(WORK_DIR):
        raise ValueError('不允许跳出文件区')
    return full


def tool_fs(action, path='', content='', append=False):
    try:
        if action == 'list':
            os.makedirs(WORK_DIR, exist_ok=True)
            items = []
            for name in sorted(os.listdir(WORK_DIR)):
                full = os.path.join(WORK_DIR, name)
                items.append({'name': name, 'dir': os.path.isdir(full),
                              'size': (0 if os.path.isdir(full) else os.path.getsize(full))})
            return {'dir': '文件区', 'items': items}
        if action == 'read':
            full = _safe_path(path)
            if not os.path.isfile(full):
                return {'error': '没有这个文件：%s' % path}
            if os.path.getsize(full) > 400000:
                return {'error': '文件太大（>400KB），先分段读'}
            with open(full, 'r', encoding='utf-8', errors='ignore') as f:
                return {'path': path, 'content': f.read()[:20000]}
        if action == 'write':
            full = _safe_path(path)
            os.makedirs(os.path.dirname(full) or WORK_DIR, exist_ok=True)
            mode = 'a' if append else 'w'
            with open(full, mode, encoding='utf-8') as f:
                f.write(content or '')
            return {'ok': True, 'path': path, 'bytes': len(content or '')}
        return {'error': '不认识的动作：%s' % action}
    except Exception as e:
        return {'error': str(e)}


# ======================================================================
#  语音：识别（第三方 ASR 转发）+ 合成（edge-tts）
# ======================================================================
def _multipart(fields, files):
    boundary = '----AIHub' + _uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                      % (boundary, k, v)).encode('utf-8'))
    for k, (fname, mime, data) in files.items():
        parts.append(('--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"\r\n'
                      'Content-Type: %s\r\n\r\n' % (boundary, k, fname, mime)).encode('utf-8'))
        parts.append(data)
        parts.append(b'\r\n')
    parts.append(('--%s--\r\n' % boundary).encode('utf-8'))
    return boundary, b''.join(parts)


def asr_transcribe(base, key, model, lang, audio_b64, mime='audio/webm'):
    if not audio_b64:
        return {'error': '没有音频数据'}
    base = (base or '').strip().rstrip('/')
    if not base.startswith(('http://', 'https://')):
        return {'error': '识别接口地址必须以 http(s) 开头'}
    url = base if base.endswith('/audio/transcriptions') else base + '/audio/transcriptions'
    try:
        raw = _b64.b64decode(audio_b64.split(',')[-1])
    except Exception:
        return {'error': '音频解码失败'}
    ext = 'webm' if 'webm' in mime else ('wav' if 'wav' in mime else ('mp4' if 'mp4' in mime else 'ogg'))
    fields = {'model': model or 'whisper-1', 'response_format': 'json'}
    if lang:
        fields['language'] = lang
    boundary, body = _multipart(fields, {'file': ('audio.' + ext, mime, raw)})
    req = urllib.request.Request(url, data=body, method='POST', headers={
        'Content-Type': 'multipart/form-data; boundary=' + boundary,
        'Authorization': 'Bearer ' + key,
    })
    try:
        resp = urllib.request.urlopen(req, timeout=120, context=_CTX)
        data = resp.read()
    except urllib.error.HTTPError as e:
        try:
            msg = e.read().decode('utf-8', 'ignore')[:300]
        except Exception:
            msg = ''
        return {'error': '识别服务返回 %s：%s' % (e.code, msg)}
    except Exception as e:
        return {'error': '连不上识别服务：%s' % e}
    try:
        j = json.loads(data.decode('utf-8', 'ignore'))
        text = j.get('text') or (j.get('result') or [{}])[0].get('text') if isinstance(j, dict) else ''
        if not text and isinstance(j, dict):
            text = j.get('transcription') or ''
        return {'text': (text or '').strip()}
    except Exception:
        return {'text': data.decode('utf-8', 'ignore')[:2000]}


_TTS_OK = None


def _ensure_tts():
    global _TTS_OK
    if _TTS_OK is not None:
        return _TTS_OK
    try:
        import edge_tts  # noqa: F401
        _TTS_OK = True
    except ImportError:
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            subprocess.run([sys.executable, '-m', 'pip', 'install', '--quiet',
                            '--disable-pip-version-check', 'edge-tts'],
                           timeout=240, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=flags if os.name == 'nt' else 0)
        except Exception:
            pass
        try:
            import edge_tts  # noqa: F401
            _TTS_OK = True
        except ImportError:
            _TTS_OK = False
    return _TTS_OK


def tts_speak(text, voice='zh-CN-XiaoxiaoNeural', rate='+0%'):
    if not _ensure_tts():
        return None, {'error': '语音合成需要 edge-tts 库，自动安装失败。可手动执行 pip install edge-tts'}
    text = (text or '').strip()
    if not text:
        return None, {'error': '没有要朗读的文字'}
    try:
        import asyncio
        import edge_tts

        async def run():
            comm = edge_tts.Communicate(text[:4000], voice or 'zh-CN-XiaoxiaoNeural', rate=rate or '+0%')
            buf = _io.BytesIO()
            async for chunk in comm.stream():
                if chunk.get('type') == 'audio':
                    buf.write(chunk['data'])
            return buf.getvalue()

        audio = asyncio.new_event_loop().run_until_complete(run())
        if not audio:
            return None, {'error': '合成没有返回音频'}
        return audio, None
    except Exception as e:
        return None, {'error': '语音合成失败：%s' % e}


# ======================================================================
#  导出：Markdown → Word / PPT / Excel（真实 Office 文件）
# ======================================================================
_LIBS_OK = None


def _ensure_libs():
    """首次导出时按需安装 python-docx / python-pptx / openpyxl。"""
    global _LIBS_OK
    if _LIBS_OK is not None:
        return _LIBS_OK
    try:
        import docx  # noqa: F401
        import pptx  # noqa: F401
        import openpyxl  # noqa: F401
        _LIBS_OK = True
        return True
    except ImportError:
        pass
    try:
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '--quiet', '--disable-pip-version-check',
             'python-docx', 'python-pptx', 'openpyxl'],
            timeout=240, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags if os.name == 'nt' else 0,
        )
    except Exception:
        pass
    try:
        import docx  # noqa: F401
        import pptx  # noqa: F401
        import openpyxl  # noqa: F401
        _LIBS_OK = True
    except ImportError:
        _LIBS_OK = False
    return _LIBS_OK


def _plain(text):
    """去掉 markdown 行内标记，用于 PPT / 表格单元格。"""
    t = re.sub(r'`([^`]*)`', r'\1', text or '')
    t = re.sub(r'\*\*(.*?)\*\*', r'\1', t)
    t = re.sub(r'\*(.*?)\*', r'\1', t)
    t = re.sub(r'\[(.*?)\]\((.*?)\)', r'\1', t)
    t = re.sub(r'^>\s*', '', t)
    return t.strip()


def parse_md(md):
    """把 Markdown 拆成块：('h', level, text) / ('p', text) / ('bullet', text)
       ('num', text) / ('code', text) / ('table', rows)"""
    blocks = []
    lines = (md or '').replace('\r', '').split('\n')
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue
        # 代码块
        if line.startswith('```'):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].strip().startswith('```'):
                buf.append(lines[i])
                i += 1
            i += 1
            blocks.append(('code', '\n'.join(buf)))
            continue
        # 表格
        if line.startswith('|') and i + 1 < len(lines) and re.match(r'\|?\s*:?-{2,}', lines[i + 1].strip()):
            rows = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not re.match(r'^:?-{2,}', cells[0] if cells else ''):
                    rows.append([_plain(c) for c in cells])
                i += 1
            if rows:
                blocks.append(('table', rows))
            continue
        # 标题
        m = re.match(r'^(#{1,4})\s+(.*)$', line)
        if m:
            blocks.append(('h', len(m.group(1)), _plain(m.group(2))))
            i += 1
            continue
        # 列表
        if re.match(r'^[-*+]\s+', line):
            blocks.append(('bullet', _plain(re.sub(r'^[-*+]\s+', '', line))))
            i += 1
            continue
        if re.match(r'^\d+[.)]\s+', line):
            blocks.append(('num', _plain(re.sub(r'^\d+[.)]\s+', '', line))))
            i += 1
            continue
        # 段落（合并连续行）
        buf = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
                r'^(#{1,4}\s|[-*+]\s|\d+[.)]\s|\||```)', lines[i].strip()):
            buf.append(lines[i].strip())
            i += 1
        blocks.append(('p', _plain(' '.join(buf))))
    return blocks


PPT_THEMES = {
    'deep': {'bg': '0F1218', 'fg': 'FFFFFF', 'body': 'D8DEEB', 'accent': '4D6BFE',
             'sub': '8A94A8', 'panel': '171C26', 'line': '2B3242'},
    'light': {'bg': 'FFFFFF', 'fg': '12161F', 'body': '333A48', 'accent': '2F4BDB',
              'sub': '6B7280', 'panel': 'F4F6FB', 'line': 'DDE2EC'},
}


def _docx_shade(cell, color):
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), color)
    tcPr.append(shd)


def _docx_page_footer(section, title):
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run((title or '') + '    ')
    run.font.size = Pt(9)
    run.font.color.rgb = __import__('docx').shared.RGBColor(0x88, 0x8F, 0x9C)

    r = p.add_run()
    fld = OxmlElement('w:fldSimple')
    fld.set(qn('w:instr'), 'PAGE')
    r._r.addnext(fld)
    tail = p.add_run(' 页')
    tail.font.size = Pt(9)


def build_docx(title, md, theme='auto'):
    from docx import Document
    from docx.shared import Pt, RGBColor, Cm
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT

    doc = Document()
    title = (title or '未命名文档').strip()

    # 版心与默认字体
    sec = doc.sections[0]
    sec.left_margin = Cm(2.6)
    sec.right_margin = Cm(2.6)
    sec.top_margin = Cm(2.4)
    sec.bottom_margin = Cm(2.2)

    normal = doc.styles['Normal']
    normal.font.name = '微软雅黑'
    normal.font.size = Pt(10.5)
    try:
        normal.element.rPr.rFonts.set(
            __import__('docx').oxml.ns.qn('w:eastAsia'), '微软雅黑')
    except Exception:
        pass
    normal.paragraph_format.line_spacing = 1.45
    normal.paragraph_format.space_after = Pt(6)

    # 主标题
    hp = doc.add_paragraph()
    hp.paragraph_format.space_before = Pt(10)
    hp.paragraph_format.space_after = Pt(16)
    hr = hp.add_run(title)
    hr.bold = True
    hr.font.size = Pt(22)
    hr.font.name = '微软雅黑'
    hr.font.color.rgb = RGBColor(0x1B, 0x2B, 0x5C)

    _docx_page_footer(sec, title)

    for blk in parse_md(md):
        kind = blk[0]
        if kind == 'h':
            level, text = blk[1], blk[2]
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(14 if level <= 2 else 10)
            p.paragraph_format.space_after = Pt(6)
            r = p.add_run(text)
            r.bold = True
            r.font.size = Pt(16 if level <= 2 else 13)
            r.font.name = '微软雅黑'
            r.font.color.rgb = RGBColor(0x24, 0x3A, 0x7A) if level <= 2 else RGBColor(0x33, 0x3D, 0x52)
        elif kind == 'bullet':
            p = doc.add_paragraph(blk[1], style='List Bullet')
            p.paragraph_format.space_after = Pt(3)
        elif kind == 'num':
            p = doc.add_paragraph(blk[1], style='List Number')
            p.paragraph_format.space_after = Pt(3)
        elif kind == 'code':
            for line in blk[1].split('\n'):
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(0)
                p.paragraph_format.left_indent = Cm(0.6)
                r = p.add_run(line or ' ')
                r.font.name = 'Consolas'
                r.font.size = Pt(9)
                r.font.color.rgb = RGBColor(0x2E, 0x3A, 0x4E)
        elif kind == 'table':
            rows = blk[1]
            cols = max(len(r) for r in rows)
            table = doc.add_table(rows=len(rows), cols=cols)
            table.style = 'Table Grid'
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            for ri, row in enumerate(rows):
                for ci in range(cols):
                    cell = table.cell(ri, ci)
                    cell.text = _plain(row[ci]) if ci < len(row) else ''
                    for para in cell.paragraphs:
                        para.paragraph_format.space_after = Pt(0)
                        for run in para.runs:
                            run.font.size = Pt(9.5)
                            if ri == 0:
                                run.bold = True
                                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    if ri == 0:
                        _docx_shade(cell, '4D6BFE')
                    elif ri % 2 == 0:
                        _docx_shade(cell, 'F2F5FF')
        else:
            p = doc.add_paragraph(blk[1])
            p.paragraph_format.first_line_indent = Cm(0)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY

    buf = _io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _pptx_set_bg(slide, color):
    from pptx.dml.color import RGBColor
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = RGBColor.from_string(color)


def _pptx_box(slide, x, y, w, h, color, line_color=None):
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = RGBColor.from_string(color)
    if line_color:
        shp.line.color.rgb = RGBColor.from_string(line_color)
        shp.line.width = Pt(0.75)
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def _pptx_text(slide, x, y, w, h, text, size, color, bold=False, align=None, spacing=6):
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    lines = text if isinstance(text, list) else [text]
    first = True
    for ln in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.text = ln
        p.font.size = Pt(size)
        p.font.bold = bold
        p.font.color.rgb = RGBColor.from_string(color)
        p.space_after = Pt(spacing)
        if align is not None:
            p.alignment = align
    return box


def build_pptx(title, md, theme='deep'):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.enum.shapes import MSO_SHAPE

    th = PPT_THEMES.get(theme if theme in PPT_THEMES else 'deep', PPT_THEMES['deep'])
    title = (title or '演示文稿').strip()

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    # ---------- 切分页面内容 ----------
    sections = []
    cur = {'title': None, 'items': []}
    for blk in parse_md(md):
        if blk[0] == 'h' and blk[1] <= 2:
            if cur['title'] or cur['items']:
                sections.append(cur)
            cur = {'title': blk[2], 'items': []}
        elif blk[0] == 'table':
            cur['items'].append(('table', blk[1]))
        elif blk[0] == 'code':
            cur['items'].append(('code', blk[1]))
        elif blk[0] == 'h':
            cur['items'].append(('sub', blk[2]))
        elif blk[0] in ('bullet', 'num'):
            cur['items'].append(('bullet', _plain(blk[1])))
        else:
            cur['items'].append(('p', _plain(blk[1])))
    if cur['title'] or cur['items']:
        sections.append(cur)
    if not sections:
        sections = [{'title': title, 'items': [('p', '（内容为空）')]}]

    # ---------- 封面 ----------
    s0 = prs.slides.add_slide(prs.slide_layouts[6])
    _pptx_set_bg(s0, th['bg'])
    _pptx_box(s0, 0, 0, 0.42, 7.5, th['accent'])
    _pptx_box(s0, 9.9, 0.7, 2.4, 2.4, th['accent'])
    _pptx_box(s0, 10.3, 1.1, 1.6, 1.6, th['bg'])
    _pptx_text(s0, 1.1, 2.35, 8.4, 1.9, title, 40, th['fg'], bold=True)
    _pptx_text(s0, 1.15, 4.05, 8.4, 0.5, '由 AI 聚合助手整理生成', 14, th['sub'])
    _pptx_box(s0, 1.15, 4.62, 1.5, 0.06, th['accent'])
    import datetime
    _pptx_text(s0, 1.15, 4.95, 6.0, 0.4, datetime.date.today().strftime('%Y 年 %m 月 %d 日'), 12, th['sub'])

    # ---------- 目录 ----------
    if len(sections) >= 3:
        st = prs.slides.add_slide(prs.slide_layouts[6])
        _pptx_set_bg(st, th['bg'])
        _pptx_box(st, 0, 0, 13.333, 0.14, th['accent'])
        _pptx_text(st, 0.9, 0.62, 6, 0.7, '目 录', 26, th['fg'], bold=True)
        _pptx_box(st, 0.95, 1.35, 0.9, 0.05, th['accent'])
        col_w = 5.6
        per_col = (len(sections) + 1) // 2
        for i, sec in enumerate(sections):
            cx = 0.95 if i < per_col else 0.95 + col_w
            cy = 1.75 + (i % per_col) * 0.62
            _pptx_text(st, cx, cy, 0.5, 0.4, '%02d' % (i + 1), 12, th['accent'], bold=True)
            _pptx_text(st, cx + 0.55, cy - 0.03, col_w - 0.7, 0.45,
                       (sec['title'] or '第 %d 节' % (i + 1))[:34], 14, th['body'])

    # ---------- 内容页 ----------
    body_slides = []
    for si, sec in enumerate(sections):
        items = sec['items']
        # 只有标题没有正文 → 章节过渡页
        if not items:
            sd = prs.slides.add_slide(prs.slide_layouts[6])
            _pptx_set_bg(sd, th['bg'])
            _pptx_box(sd, 0, 0, 0.42, 7.5, th['accent'])
            _pptx_text(sd, 1.1, 2.45, 2.2, 1.0, '%02d' % (si + 1), 44, th['accent'], bold=True)
            _pptx_text(sd, 1.12, 3.45, 10.4, 1.0, (sec['title'] or title)[:40], 30, th['fg'], bold=True)
            _pptx_box(sd, 1.15, 4.45, 1.2, 0.05, th['accent'])
            body_slides.append(sd)
            continue

        # 按“行单位”分页：bullet/p=1，code=2，table=3
        PER = 8
        chunks, buf, used = [], [], 0
        for it in items:
            w = 3 if it[0] == 'table' else (2 if it[0] == 'code' else 1)
            if buf and used + w > PER:
                chunks.append(buf)
                buf, used = [], 0
            buf.append(it)
            used += w
        if buf:
            chunks.append(buf)

        for ci, chunk in enumerate(chunks):
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            _pptx_set_bg(slide, th['bg'])
            _pptx_box(slide, 0, 0, 13.333, 0.12, th['accent'])
            t = sec['title'] or title
            if len(chunks) > 1:
                t = '%s（%d/%d）' % (t, ci + 1, len(chunks))
            _pptx_text(slide, 0.85, 0.52, 11.6, 0.75, t, 24, th['fg'], bold=True)
            _pptx_box(slide, 0.9, 1.34, 0.75, 0.045, th['accent'])

            y = 1.62
            for kind, val in chunk:
                if kind == 'table':
                    rows = val[:9]
                    cols = max(len(r) for r in rows) if rows else 1
                    cols = min(cols, 7)
                    h = 0.42 * len(rows) + 0.1
                    shape = slide.shapes.add_table(len(rows), cols, Inches(0.9), Inches(y),
                                                   Inches(11.4), Inches(h))
                    tbl = shape.table
                    for ri, row in enumerate(rows):
                        for cj in range(cols):
                            cell = tbl.cell(ri, cj)
                            cell.text = _plain(row[cj]) if cj < len(row) else ''
                            for p in cell.text_frame.paragraphs:
                                p.font.size = Pt(11)
                                p.font.bold = (ri == 0)
                                p.font.color.rgb = RGBColor.from_string(th['fg'] if ri == 0 else th['body'])
                                for run in p.runs:
                                    run.font.size = Pt(11)
                            cell.fill.solid()
                            cell.fill.fore_color.rgb = RGBColor.from_string(
                                th['accent'] if ri == 0 else (th['panel'] if ri % 2 else th['bg']))
                            cell.margin_left = Inches(0.08)
                    y += h + 0.18
                elif kind == 'code':
                    n = min(len(val.split('\n')), 9)
                    _pptx_box(slide, 0.9, y, 11.4, 0.3 * n + 0.24, th['panel'], th['line'])
                    _pptx_text(slide, 1.05, y + 0.12, 11.1, 0.3 * n,
                               val.split('\n')[:9], 10.5, th['body'], spacing=2)
                    y += 0.3 * n + 0.4
                else:
                    size = 18 if kind == 'sub' else 15
                    color = th['accent'] if kind == 'sub' else th['body']
                    _pptx_text(slide, 1.05 if kind == 'bullet' else 0.9, y, 11.2, 0.42,
                               ('· ' if kind == 'bullet' else '') + val, size, color,
                               bold=(kind == 'sub'), spacing=4)
                    y += 0.44 if kind == 'sub' else 0.4
            body_slides.append(slide)

    # 页码 + 页脚
    for idx, slide in enumerate(body_slides, start=2):
        _pptx_text(slide, 12.1, 6.92, 0.9, 0.3, '%02d' % idx, 10, th['sub'], align=PP_ALIGN.RIGHT)
        _pptx_text(slide, 0.9, 6.92, 6.0, 0.3, 'AI 聚合助手', 9.5, th['sub'])

    # ---------- 结束页 ----------
    se = prs.slides.add_slide(prs.slide_layouts[6])
    _pptx_set_bg(se, th['bg'])
    _pptx_box(se, 0, 0, 13.333, 0.12, th['accent'])
    _pptx_text(se, 0.9, 2.9, 11.5, 1.0, '谢 谢', 34, th['fg'], bold=True)
    _pptx_text(se, 0.95, 3.95, 10, 0.5, '以上内容由 AI 聚合助手根据对话生成', 13, th['sub'])

    buf = _io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def build_xlsx(title, md, theme='auto'):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    blocks = parse_md(md)
    tables = []
    last_head = None
    for blk in blocks:
        if blk[0] == 'h':
            last_head = blk[2]
        elif blk[0] == 'table':
            tables.append((last_head, blk[1]))

    head_fill = PatternFill('solid', fgColor='4D6BFE')
    zebra_fill = PatternFill('solid', fgColor='F1F4FF')
    thin = Side(style='thin', color='D6DCEB')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    if not tables:
        ws = wb.active
        ws.title = '内容'
        ws['A1'] = title or '内容'
        ws['A1'].font = Font(bold=True, size=15, color='243A7A')
        r = 3
        for blk in blocks:
            if blk[0] == 'h':
                c = ws.cell(row=r, column=1, value=_plain(blk[2]))
                c.font = Font(bold=True, size=12, color='333D52')
                r += 1
            elif blk[0] == 'table':
                continue
            else:
                c = ws.cell(row=r, column=1, value=_plain(blk[1] if blk[0] != 'code' else blk[1]))
                c.alignment = Alignment(wrap_text=True, vertical='top')
                r += 1
        ws.column_dimensions['A'].width = 92
        ws.sheet_properties.tabColor = '4D6BFE'
    else:
        wb.remove(wb.active)
        used = set()
        for idx, (head, rows) in enumerate(tables, 1):
            name = (re.sub(r'[\\/*?:\[\]]', '', _plain(head or '')) or ('Sheet%d' % idx))[:28]
            if name in used:
                name = name[:26] + str(idx)
            used.add(name)
            ws = wb.create_sheet(name)
            ws.sheet_properties.tabColor = '4D6BFE'
            ws.append([_plain(c) for c in rows[0]])
            for cell in ws[1]:
                cell.font = Font(bold=True, color='FFFFFF', size=11)
                cell.fill = head_fill
                cell.alignment = Alignment(vertical='center', horizontal='center', wrap_text=True)
                cell.border = border
            ws.row_dimensions[1].height = 26

            numeric_cols = set()
            for ri, row in enumerate(rows[1:], start=2):
                for ci, val in enumerate(row, start=1):
                    text = _plain(val)
                    num = None
                    probe = text.replace(',', '').replace('¥', '').replace('￥', '').strip()
                    if re.fullmatch(r'-?\d+(\.\d+)?', probe):
                        try:
                            num = float(probe) if '.' in probe else int(probe)
                            numeric_cols.add(ci)
                        except ValueError:
                            num = None
                    cell = ws.cell(row=ri, column=ci, value=num if num is not None else text)
                    cell.font = Font(size=10.5)
                    cell.border = border
                    cell.alignment = Alignment(vertical='center',
                                               horizontal='right' if num is not None else 'left',
                                               wrap_text=(num is None))
                    if ri % 2 == 0:
                        cell.fill = zebra_fill

            for col in ws.columns:
                letter = get_column_letter(col[0].column)
                width = max((len(str(c.value or '')) for c in col), default=8)
                ws.column_dimensions[letter].width = min(max(width + 3, 10), 56)
            for ci in numeric_cols:
                for c in ws[get_column_letter(ci)]:
                    if isinstance(c.value, float):
                        c.number_format = '#,##0.00'

            ws.freeze_panes = 'A2'
            if ws.max_row > 2:
                ws.auto_filter.ref = 'A1:%s%d' % (get_column_letter(ws.max_column), ws.max_row)

    buf = _io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


EXPORT_TYPES = {
    'docx': ('application/vnd.openxmlformats-officedocument.wordprocessingml.document', build_docx, '.docx'),
    'pptx': ('application/vnd.openxmlformats-officedocument.presentationml.presentation', build_pptx, '.pptx'),
    'xlsx': ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', build_xlsx, '.xlsx'),
}

class Handler(BaseHTTPRequestHandler):
    server_version = 'AIHub/1.0'
    protocol_version = 'HTTP/1.1'

    # ---------- 日志：只保留错误，避免刷屏 ----------
    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------- OPTIONS ----------
    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header('Content-Length', '0')
        self.end_headers()

    # ---------- 静态文件 ----------
    def do_GET(self):
        path = self.path.split('?')[0].split('#')[0]
        if path in ('/', '/index.html'):
            path = '/index.html'
        if path == '/health':
            self._json(200, {'ok': True})
            return

        fs_path = os.path.normpath(os.path.join(ROOT, path.lstrip('/')))
        if not fs_path.startswith(ROOT):
            self._json(403, {'error': 'forbidden'})
            return
        if not os.path.isfile(fs_path):
            self._json(404, {'error': 'not found'})
            return

        ext = os.path.splitext(fs_path)[1].lower()
        ctype = MIME.get(ext, 'application/octet-stream')
        try:
            with open(fs_path, 'rb') as f:
                data = f.read()
        except OSError as e:
            self._json(500, {'error': str(e)})
            return

        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


    def _do_export(self):
        try:
            raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
            req = json.loads(raw.decode('utf-8'))
        except Exception as e:
            self._json(400, {'error': '请求体解析失败: %s' % e})
            return

        kind = (req.get('kind') or 'docx').lower()
        if kind not in EXPORT_TYPES:
            self._json(400, {'error': '不支持的文件类型：%s' % kind})
            return

        if not _ensure_libs():
            self._json(500, {'error': '生成 Office 文件需要三个 Python 库，自动安装失败。请在程序目录执行：\n'
                                     'pip install python-docx python-pptx openpyxl\n装完重新双击启动.bat 即可。'})
            return

        mime, builder, ext = EXPORT_TYPES[kind]
        title = (req.get('title') or 'AI 导出').strip()[:80]
        md = req.get('markdown') or ''
        try:
            theme = (req.get('theme') or 'auto').strip()
            try:
                data = builder(title, md, theme) if kind != 'docx' else builder(title, md)
            except TypeError:
                data = builder(title, md)
        except Exception as e:
            self._json(500, {'error': '生成文件失败：%s' % e})
            return

        safe = re.sub(r'[\\/:*?"<>|]', '_', title) or 'export'
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Content-Disposition',
                         "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (
                             'export' + ext, urllib.parse.quote(safe + ext)))
        self.send_header('Cache-Control', 'no-store')
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    # ---------- 代理 ----------

    def _body_json(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        return json.loads(raw.decode('utf-8') or '{}')

    def _do_tool(self, path):
        try:
            req = self._body_json()
        except Exception as e:
            self._json(400, {'error': '请求体解析失败: %s' % e})
            return
        name = path.split('/')[-1]
        if name == 'search':
            out = tool_search(req.get('query'), req.get('engine') or 'auto', req.get('key') or '')
        elif name == 'fetch':
            out = tool_fetch(req.get('url'))
        elif name == 'calc':
            out = tool_calc(req.get('expr'))
        elif name == 'fs':
            out = tool_fs(req.get('action') or 'list', req.get('path') or '', req.get('content') or '',
                          bool(req.get('append')))
        else:
            out = {'error': '没有这个工具'}
        self._json(200, out)

    def _do_asr(self):
        try:
            req = self._body_json()
        except Exception as e:
            self._json(400, {'error': '请求体解析失败: %s' % e})
            return
        out = asr_transcribe(req.get('base'), req.get('apiKey'), req.get('model'),
                             req.get('lang'), req.get('audio'), req.get('mime') or 'audio/webm')
        self._json(200, out)

    def _do_tts(self):
        try:
            req = self._body_json()
        except Exception as e:
            self._json(400, {'error': '请求体解析失败: %s' % e})
            return
        audio, err = tts_speak(req.get('text'), req.get('voice'), req.get('rate'))
        if err:
            self._json(200, err)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'audio/mpeg')
        self.send_header('Content-Length', str(len(audio)))
        self.send_header('Cache-Control', 'no-store')
        self._cors()
        self.end_headers()
        try:
            self.wfile.write(audio)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _do_imgedit(self):
        try:
            req = self._body_json()
        except Exception as e:
            self._json(400, {'error': '请求体解析失败: %s' % e})
            return
        url = (req.get('url') or '').strip()
        if not url.startswith(('http://', 'https://')):
            self._json(400, {'error': '接口地址不合法'})
            return
        try:
            src = req.get('image') or ''
            if not src and req.get('imageUrl'):
                # 前端给的是网址：本地下载后再上传，避免浏览器跨域
                dl = _get(req['imageUrl'], timeout=60).read()
                src = 'data:image/png;base64,' + _b64.b64encode(dl).decode()
            raw = _b64.b64decode(src.split(',')[-1])
            mime = req.get('mime') or 'image/png'
            if 'jpeg' in src[:40] or 'jpg' in src[:40]:
                mime = 'image/jpeg'
            ext = 'png' if 'png' in mime else 'jpg'
            boundary, body = _multipart(
                {'model': req.get('model') or 'gpt-image-1',
                 'prompt': req.get('prompt') or '',
                 'n': '1',
                 'size': req.get('size') or '1024x1024'},
                {'image': ('image.' + ext, mime, raw)})
            up = urllib.request.Request(url, data=body, method='POST', headers={
                'Content-Type': 'multipart/form-data; boundary=' + boundary,
                'Authorization': 'Bearer ' + (req.get('apiKey') or ''),
            })
            resp = urllib.request.urlopen(up, timeout=300, context=_CTX)
            data = resp.read()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self._cors()
            self.end_headers()
            self.wfile.write(data)
        except urllib.error.HTTPError as e:
            try:
                msg = e.read().decode('utf-8', 'ignore')[:400]
            except Exception:
                msg = ''
            self._json(200, {'error': '改图接口返回 %s：%s' % (e.code, msg)})
        except Exception as e:
            self._json(200, {'error': '改图失败：%s' % e})

    def do_POST(self):
        path = self.path.split('?')[0]
        if path == '/export':
            self._do_export()
            return
        if path.startswith('/tool/'):
            self._do_tool(path)
            return
        if path == '/asr':
            self._do_asr()
            return
        if path == '/tts':
            self._do_tts()
            return
        if path == '/imgedit':
            self._do_imgedit()
            return
        if path != '/proxy':
            self._json(404, {'error': 'not found'})
            return

        try:
            raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
            req = json.loads(raw.decode('utf-8'))
            url = (req.get('url') or '').strip()
            api_key = (req.get('apiKey') or '').strip()
            payload = req.get('payload') or {}
        except Exception as e:
            self._json(400, {'error': '请求体解析失败: %s' % e})
            return

        if not url.startswith(('http://', 'https://')):
            self._json(400, {'error': '接口地址不合法，必须以 http:// 或 https:// 开头'})
            return

        headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream'}
        if api_key:
            headers['Authorization'] = 'Bearer ' + api_key

        try:
            upstream = urllib.request.Request(
                url,
                data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                headers=headers,
                method='POST',
            )
            resp = urllib.request.urlopen(upstream, timeout=300)
        except urllib.error.HTTPError as e:
            body = b''
            try:
                body = e.read()
            except Exception:
                pass
            try:
                parsed = json.loads(body.decode('utf-8', 'ignore'))
                msg = parsed.get('error') if isinstance(parsed, dict) else None
                if isinstance(msg, dict):
                    msg = msg.get('message') or json.dumps(msg, ensure_ascii=False)
                if not msg:
                    msg = json.dumps(parsed, ensure_ascii=False)
            except Exception:
                msg = body.decode('utf-8', 'ignore')[:500]
            hint = ''
            if e.code == 401:
                hint = '（Key 无效或未开通权限，去控制台核对一下）'
            elif e.code == 404:
                hint = '（接口地址或模型名可能不对）'
            elif e.code == 402:
                hint = '（账户余额不足）'
            elif e.code == 429:
                hint = '（触发限流，稍后再试）'
            self._json(200 if False else e.code, {'error': '%s%s' % (msg, hint)})
            return
        except Exception as e:
            self._json(502, {'error': '请求上游失败：%s' % e})
            return

        ctype = resp.headers.get('Content-Type', 'application/json')
        try:
            if 'text/event-stream' in ctype:
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'close')
                self._cors()
                self.end_headers()
                while True:
                    chunk = resp.read(2048)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                try:
                    self.wfile.write(b'\n\n')
                    self.wfile.flush()
                except Exception:
                    pass
            else:
                data = resp.read()
                self.send_response(200)
                self.send_header('Content-Type', ctype)
                self.send_header('Content-Length', str(len(data)))
                self._cors()
                self.end_headers()
                self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            try:
                self._json(502, {'error': '转发中断：%s' % e})
            except Exception:
                pass


def pick_port():
    for port in range(START_PORT, MAX_PORT + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    return 0


def main():
    port = pick_port()
    if not port:
        print('找不到可用端口，请关闭占用 8760-8799 的程序后重试。')
        input('按回车退出…')
        return

    httpd = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    url = 'http://127.0.0.1:%d/' % port

    print('=' * 52)
    print('  AI 聚合助手 已启动')
    print('  地址：%s' % url)
    print('  关闭这个窗口即可退出（也可以按 Ctrl+C）')
    print('=' * 52)

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n已退出。')
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()
