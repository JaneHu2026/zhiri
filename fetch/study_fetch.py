#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
study_fetch.py — 知日学习页抓取（GitHub Actions 每日 08:00 调用，输出仓库根 study.json）
数据源：
  1. YouTube AI 学习  — 7 个 AI 频道 RSS 直连（consent cookie），英文简介自动译中
  2. B站 AI 热点       — 热门榜 API（buvid cookie），AI/科技/学习关键词过滤，真实视频直链
  3. 抖音 AI 热点      — 抖音热榜 API（免登录），AI 关键词过滤，官方搜索链接
规则：只保存标题/作者/链接/热度，不下载视频；宁缺毋滥
"""
import json, os, re, sys, time, urllib.parse, urllib.request, http.cookiejar
import xml.etree.ElementTree as ET
from datetime import datetime

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'study.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
AI_TECH_KEYS = ['ai', '人工智能', '机器', '智能', '模型', 'gpt', '大模型', 'llm', '数字人', '芯片',
                'openai', '算法', '自动驾驶', '机器人', '算力', 'ai眼镜', 'agent', '智能体', '大语言模型', '深度学习']
AI_KEYS = AI_TECH_KEYS + ['学习', '教程', '教学', '课程', '干货', '编程', '代码', '开发', 'python']

def get(url, timeout=20, referer=None, extra=None):
    headers = dict(UA)
    if referer: headers['Referer'] = referer
    if extra: headers.update(extra)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'ignore')

def rel_pub(pub):
    try:
        t = datetime.fromisoformat(pub.replace('Z', '+00:00').replace(' ', 'T'))
        now = datetime.now(t.tzinfo) if t.tzinfo else datetime.now()
        diff = (now - t).total_seconds()
        if diff < 3600: return '%d分钟前' % max(1, int(diff / 60))
        if diff < 86400: return '%d小时前' % int(diff / 3600)
        if diff < 7 * 86400: return '%d天前' % int(diff / 86400)
        return t.strftime('%m月%d日')
    except Exception:
        return ''

def clean_desc(d, limit=180):
    d = re.sub(r'[…]{2,}\s*more\s*$', '', d.strip())
    d = re.sub(r'\s+', ' ', d).strip()
    return d[:limit] + ('…' if len(d) > limit else '')

def zh_translate(text, limit=120):
    if not text:
        return ''
    ascii_ratio = sum(1 for c in text if ord(c) < 128) / max(1, len(text))
    if ascii_ratio < 0.6:
        return text
    src = text[:limit]
    try:
        q = urllib.parse.quote(src)
        j = json.loads(get('https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q=' + q, timeout=10))
        parts = [seg[0] for seg in (j[0] or []) if seg and seg[0]]
        if parts:
            return ''.join(parts).strip()[:200]
    except Exception:
        pass
    try:
        q = urllib.parse.quote(src)
        j = json.loads(get('https://api.mymemory.translated.net/get?q=' + q + '&langpair=en|zh-CN', timeout=10))
        t = (j.get('responseData') or {}).get('translatedText') or ''
        if t:
            return t.strip()[:200]
    except Exception:
        pass
    return text

def fmt_dur(sec):
    try:
        m, s = divmod(int(sec), 60)
        return '%d:%02d' % (m, s)
    except Exception:
        return '—'

# ---------- YouTube（多频道最新 AI 视频 + 自动译中） ----------
YT_CHANNELS = [
    ('Andrej Karpathy', 'UCXUPKJO5MZQN11PqgIvyuvQ'),          # LLM 深度学习教学
    ('3Blue1Brown', 'UCYO_jab_esuFRV4b17AJtAw'),              # 深度学习可视化
    ('Two Minute Papers', 'UCbfYPyITQ-7l4upoX8nvctg'),        # AI 论文/新模型解读
    ('跟李沐学AI', 'UCDz_bzi6t_iY2GIJTHnxH6Q'),               # 中文 AI 深度学习教学
    ('AI Explained', 'UC_HhOkzorAO4_rRsTiiHZ_w'),             # 新模型/Agent 资讯解读
    ('1littlecoder', 'UCpV_X0VrL8-jg3t6wYGS-1g'),             # Agent/本地模型实战教程
    ('sentdex', 'UCfzlCWGWYyIQ0aLC5w48gBQ'),                  # Python AI 编程实战
    ('Wes Roth', 'UCjUv2vz7N2uX7q1mDgQ2k8g'),                 # AI 新模型/行业热点
    ('Matt Wolfe', 'UCWnP1qK4tR5R1UqA6MQsGgA'),               # AI 工具/资讯周报
    ('ColdFusion', 'UC4QZ_LzYJG9vi1MO0N5j3iw'),               # 科技趋势解读
    ('The AI Daily Brief', 'UCNzszBnbeeYzUZ6d0lM9G7w'),       # AI 每日简报
    ('Lex Clips', 'UCLPfNp95fG5aJSDnZfO4x8A'),                # AI 对谈精选
    ('DigitalEngineer', 'UC9Q6md8qY0rYhTVY5gGGOzA'),          # AI 前沿资讯
    ('Dave Ebbelaar', 'UC2hMWOaOlwr9vGmm4j8rfqA'),            # AI 实战教程
]
YT_NS = {'a': 'http://www.w3.org/2005/Atom', 'yt': 'http://www.youtube.com/xml/schemas/2015',
         'media': 'http://search.yahoo.com/mrss/'}

def yt_items():
    out = []
    for name, cid in YT_CHANNELS:
        try:
            url = 'https://www.youtube.com/feeds/videos.xml?channel_id=' + cid
            txt = get(url, timeout=15, extra={'Cookie': 'CONSENT=YES+cb.20210328-17-p0.en+FX+417'})
            root = ET.fromstring(txt)
            for e in root.findall('a:entry', YT_NS)[:2]:
                vid = (e.findtext('yt:videoId', default='', namespaces=YT_NS) or '').strip()
                if not vid:
                    continue
                pub = e.findtext('a:published', default='', namespaces=YT_NS) or ''
                desc = clean_desc(e.findtext('media:group/media:description', default='', namespaces=YT_NS) or '', 200)
                desc = re.sub(r'https?://\S+', '', desc)
                desc = re.sub(r'\s+', ' ', desc).strip(' -·–|')
                out.append({
                    'platform': 'youtube', 'author': name,
                    'title': e.findtext('a:title', default='', namespaces=YT_NS) or '',
                    'duration': '—',
                    'heat': 0,
                    'updated': pub,
                    'url': 'https://www.youtube.com/watch?v=' + vid,
                    'desc': zh_translate(desc),
                })
        except Exception:
            pass
        time.sleep(1)
    out.sort(key=lambda x: x['updated'], reverse=True)
    return out[:8]

# B站严格 AI 关键词（宁缺毋滥，避免"模型/教程"等宽词误匹配娱乐内容）
STRICT_AI_KEYS = ['人工智能', '大模型', '语言模型', '机器学习', '深度学习', '神经网络',
                  'gpt', 'llm', 'openai', 'chatgpt', 'sora', 'aigc', '智能体', 'agent',
                  '数字人', '自动驾驶', '机器人', '算力', 'ai', '芯片', 'ai眼镜',
                  'midjourney', 'stable diffusion', 'kimi', 'deepseek', 'claude', 'gemini',
                  '通义', '文心', '豆包', '元宝', '开源模型', '训练', '推理']

# ---------- B站 ----------
def bili_items():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = list(UA.items())
    try:
        op.open('https://www.bilibili.com/', timeout=15).read()
    except Exception:
        return []
    out = []
    seen = set()
    for rid in (0, 188):
        try:
            req = urllib.request.Request('https://api.bilibili.com/x/web-interface/ranking/v2?rid=%d&type=all' % rid, headers=UA)
            j = json.loads(op.open(req, timeout=15).read().decode('utf-8', 'ignore'))
            if j.get('code') != 0:
                continue
            for v in j['data']['list']:
                t = re.sub(r'<[^>]+>', '', v.get('title', '')).strip()
                bvid = v.get('bvid', '')
                if not t or not bvid or bvid in seen:
                    continue
                if not any(k in t.lower() for k in STRICT_AI_KEYS):
                    continue
                seen.add(bvid)
                out.append({
                    'platform': 'bilibili', 'author': (v.get('owner') or {}).get('name', ''),
                    'title': t, 'duration': fmt_dur(v.get('duration', 0)),
                    'heat': (v.get('stat') or {}).get('view', 0),
                    'updated': '',
                    'url': 'https://www.bilibili.com/video/' + bvid,
                    'desc': '',
                })
        except Exception:
            pass
        time.sleep(0.5)
    return out[:8]

# ---------- 抖音 ----------
def douyin_items():
    try:
        url = 'https://www.douyin.com/aweme/v1/web/hot/search/list/?detail_list=1'
        j = json.loads(get(url, referer='https://www.douyin.com/hot'))
        wl = (j.get('data') or {}).get('word_list') or []
    except Exception:
        return []
    out = []
    for w in wl:
        word = w.get('word') or ''
        if not word or not any(k in word.lower() for k in AI_TECH_KEYS):
            continue
        out.append({
            'platform': 'douyin', 'author': '抖音热榜',
            'title': word, 'duration': '—',
            'heat': w.get('hot_value') or 0,
            'updated': '',
            'url': 'https://www.douyin.com/search/' + urllib.parse.quote(word) + '?type=general',
            'desc': '热门话题「%s」：相关视频 %d 条' % (word, w.get('video_count') or 0),
        })
    return out[:6]

def main():
    groups = []
    errors = []
    for name, fn in [('YouTube', yt_items), ('B站', bili_items), ('抖音', douyin_items)]:
        try:
            items = fn()
            if items:
                groups.append(items)
            else:
                errors.append('%s: 无内容' % name)
        except Exception as e:
            errors.append('%s: %s' % (name, e))

    # 展平为知日格式
    all_items = []
    for g in groups:
        for it in g:
            all_items.append({
                'id': 'sv_ext',
                'platform': it['platform'], 'author': it['author'],
                'title': it['title'], 'duration': it['duration'],
                'heat': it['heat'],
                'updated': it['updated'] or datetime.now().isoformat(),
                'url': it['url'],
                'points': [it['desc']] if it.get('desc') else [],
                'flags': {'fav': False, 'watched': False, 'later': False},
            })

    now = datetime.now()
    payload = {
        'fetchedAt': now.strftime('%H:%M'),
        'fetchedDate': now.strftime('%Y-%m-%d'),
        'source': 'zhiri-server',
        'items': all_items[:30],
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    if not all_items:
        print('STUDY_FETCH_FAIL: %s' % '; '.join(errors))
        sys.exit(1)
    if errors:
        print('STUDY_FETCH_PARTIAL: %s' % '; '.join(errors))
    from collections import Counter
    print('STUDY_OK: %d 条 %s' % (len(all_items), dict(Counter(x['platform'] for x in all_items))))

if __name__ == '__main__':
    main()
