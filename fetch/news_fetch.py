#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
news_fetch.py — 知日新闻抓取（GitHub Actions 每日 08:00 调用，输出仓库根 news.json）
数据源（权威媒体，直连解析）：
  国内：央视新闻 www.cctv.com 首页 / 新华网 www.news.cn 首页
  国际：人民网国际 world.people.com.cn
规则：
  - 只保留 当天 发布的文章（URL 含当天日期）；当天不足 3 条时补充昨天
  - 每条含标题/来源/时间/摘要/原文链接/主题分类
  - 不复制全文，仅保存标题+摘要+链接
"""
import html as html_mod
import json, os, re, sys, urllib.request
from datetime import datetime, date

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'news.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}

THEME_KW = [
    ('民生', re.compile(r'医保|养老|社保|补贴|菜价|消费品|生活|供水|供电|出行|民生')),
    ('政策', re.compile(r'政策|文件|发布|印发|规定|措施|条例|部署|意见')),
    ('财经', re.compile(r'经济|金融|央行|利率|财政|市场|物价|就业|外贸|增长|关税')),
    ('科技', re.compile(r'科技|AI|人工智能|航天|芯片|机器人|卫星|量子|算力|模型')),
    ('医疗', re.compile(r'医疗|医保|医院|药品|健康|疾病|疫苗|门诊|卫生')),
    ('社会', re.compile(r'社会|社区|改造|救援|通报|服务|保障|志愿者')),
    ('环境', re.compile(r'环境|生态|气候|天气|高温|能源|台风|洪水|污染|排放')),
    ('教育', re.compile(r'教育|学校|学生|高考|教师|教材|课程|大学')),
    ('文化', re.compile(r'文化|电影|作家|艺术|音乐|出版')),
    ('体育', re.compile(r'体育|奥运|足球|比赛|联赛')),
]

def get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        ctype = r.headers.get('Content-Type', '') or ''
    enc = 'utf-8'
    m = re.search(r'charset=([\w-]+)', ctype, re.I)
    if m:
        enc = m.group(1)
    else:
        head = raw[:2048].decode('ascii', 'ignore')
        m = re.search(r'charset=["\']?([\w-]+)', head, re.I)
        if m:
            enc = m.group(1)
    if enc.lower() in ('gb2312', 'gbk'):
        enc = 'gb18030'
    try:
        return raw.decode(enc, 'ignore')
    except LookupError:
        return raw.decode('utf-8', 'ignore')

def zh_translate(text, limit=160):
    """英文标题/摘要 → 中文（Google 免费接口，失败回退原文）"""
    if not text:
        return ''
    ascii_ratio = sum(1 for c in text if ord(c) < 128) / max(1, len(text))
    if ascii_ratio < 0.5:
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
    return text

def bbc_world_group(today):
    """BBC World（国外权威官方源，RSS 当天 + 自动译中）"""
    import xml.etree.ElementTree as ET
    import time as _t
    txt = get('https://feeds.bbci.co.uk/news/world/rss.xml', timeout=20)
    root = ET.fromstring(txt)
    out = []
    for it in root.findall('.//item'):
        pub = it.findtext('pubDate') or ''
        try:
            d = datetime.strptime(pub[:16], '%a, %d %b %Y')   # "Wed, 05 Aug 2026" 16字符
            d = d.date()
        except Exception:
            continue
        if d != today:
            continue
        title = re.sub(r'\s+', ' ', it.findtext('title') or '').strip()
        if len(title) < 8:
            continue
        desc = re.sub(r'<[^>]+>', '', it.findtext('description') or '')
        desc = re.sub(r'\s+', ' ', desc).strip()
        out.append({'title': title, 'url': it.findtext('link') or '', 'desc': desc, 'pub': d})
        if len(out) >= 8:
            break
    result = []
    for i, it in enumerate(out[:8]):
        result.append({
            'group': 'gj', 'theme': '国际', 'title': zh_translate(it['title']),
            'source': 'BBC', 'time': '今天', 'url': it['url'],
            'summary': zh_translate(it['desc'][:140]) or '（点击查看原文）', 'day': 0,
        })
        _t.sleep(0.6)  # 错峰，避免翻译限流
    return result

def chinanews_gj_group(today):
    """中新网国际（国内权威，URL 当天过滤）"""
    h = get('https://www.chinanews.com.cn/gj/', timeout=15)
    items = parse_links(h, [
        (r'<a[^>]*href="(https?://www\.chinanews\.com\.cn/gj/\d{4}/\d{2}-\d{2}/[^"]+)"[^>]*>([^<]{8,60})</a>', 10),
    ], limit=20)
    return collect(today, 'gj', '中新网', 'https://www.chinanews.com.cn', items)

def xinhua_world_group(today):
    """新华网国际频道（URL 当天过滤）"""
    h = get('https://www.news.cn/world/', timeout=15)
    items = parse_links(h, [
        (r'<a[^>]*href="(/(?:world/)?\d{6,8}/[^"]+\.html)"[^>]*>([^<]{10,60})</a>', 12),
    ], limit=20)
    return collect(today, 'gj', '新华网', 'https://www.news.cn', items)

def url_date(url):
    """从文章 URL 提取日期：返回 (date) 或 None"""
    m = re.search(r'/(20\d{2})/(\d{2})-(\d{2})/', url)       # 中新网 /2026/08-03/
    if m:
        try: return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError: return None
    m = re.search(r'/(20\d{2})/(\d{2})/(\d{2})/', url)       # 央视 /2026/08/03/
    if m:
        try: return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError: return None
    m = re.search(r'/(20\d{2})(\d{2})(\d{2})/', url)          # 新华 /20260803/
    if m:
        try: return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError: return None
    m = re.search(r'/n1/(20\d{2})/(\d{2})(\d{2})/', url)      # 人民网 /n1/2026/0803/
    if m:
        try: return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError: return None
    return None

def guess_theme(title):
    for name, re_ in THEME_KW:
        if re_.search(title):
            return name
    return '要闻'

def day_label(day):
    if day <= 0: return '今天'
    if day == 1: return '昨天'
    return '%d天前' % day

def parse_links(html, patterns, limit=20):
    items = []
    seen = set()
    for href_pat, min_len in patterns:
        for m in re.finditer(href_pat, html):
            url, title = m.group(1), m.group(2).strip()
            title = re.sub(r'\s+', ' ', title)
            if len(title) < min_len or title in seen:
                continue
            seen.add(title)
            items.append((title, url))
            if len(items) >= limit:
                return items
    return items
def article_desc(url):
    """抓文章页，取 meta description 或正文首段作为简要内容"""
    try:
        h = get(url, timeout=8)
        h = re.sub(r'<!--.*?-->', '', h, flags=re.S)  # 去掉 HTML 注释（央视视频站有 [!--begin:htmlVideoCode--] 残留）
        h = re.sub(r'\[!--.*?--\][a-zA-Z0-9]{4,20}', '', h)
        h = re.sub(r'\[!--.*?--\]', '', h)
        m = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{20,200})', h)
        if not m:
            m = re.search(r'<meta[^>]+content=["\']([^"\']{20,200})["\'][^>]+name=["\']description["\']', h)
        if m:
            d = html_mod.unescape(re.sub(r'\s+', ' ', m.group(1))).strip()
            if len(d) >= 20:
                return d[:150] + ('…' if len(d) > 150 else '')
        ps = re.findall(r'<p[^>]*>([^<]{30,200})</p>', h)
        for p in ps:
            d = html_mod.unescape(re.sub(r'\s+', ' ', p)).strip()
            if len(d) >= 30 and d != '':
                return d[:150] + ('…' if len(d) > 150 else '')
    except Exception:
        pass
    return ''

def collect(today, group, source, base, items, with_summary=6):
    """items: [(title, url)] -> 严格只保留当天发布的文章（宁缺毋滥，不补昨天）"""
    out = []
    for title, url in items:
        if not url.startswith('http'):
            url = base + url if url.startswith('/') else base + '/' + url
        d = url_date(url)
        if d is None:
            continue
        day = (today - d).days
        if day < 0:
            day = 0
        if day > 0:
            continue  # 只要当天发布的新闻
        out.append({'title': title, 'url': url, 'day': day})
    result = []
    for i, it in enumerate(out[:8]):
        summary = article_desc(it['url']) if i < with_summary else ''
        result.append({
            'group': group, 'theme': guess_theme(it['title']),
            'title': it['title'], 'source': source,
            'time': '今天', 'url': it['url'],
            'summary': summary or '（点击查看原文）', 'day': 0,
        })
    return result

def main():
    today = date.today()
    groups = []
    errors = []

    # 1) 央视（国内）
    try:
        h = get('https://www.cctv.com/')
        items = parse_links(h, [
            (r'<a[^>]*href="(https://(?:news|tv)\.cctv\.com/\d{4}/\d{2}/\d{2}/[^"]+)"[^>]*>([^<]{8,80})</a>', 10),
        ], limit=30)
        g = collect(today, 'gn', '央视新闻', 'https://www.cctv.com', items)
        if g: groups.append(g)
    except Exception as e:
        errors.append('央视: %s' % e)

    # 2) 新华（国内）
    try:
        h = get('https://www.news.cn/')
        items = parse_links(h, [
            (r'<a[^>]*href="(/(?:[a-z]+/)?\d{6,8}/[^"]+\.html)"[^>]*>([^<]{10,60})</a>', 12),
        ], limit=30)
        g = collect(today, 'gn', '新华网', 'https://www.news.cn', items)
        if g: groups.append(g)
    except Exception as e:
        errors.append('新华: %s' % e)

    # 3) 国际新闻（BBC 国外权威 + 人民网国际/中新网国际/新华国际）
    try:
        g = bbc_world_group(today)
        if g: groups.append(g)
    except Exception as e:
        errors.append('BBC: %s' % e)
    try:
        h = get('https://world.people.com.cn/')
        items = parse_links(h, [
            (r'<a[^>]*href="(https?://world\.people\.com\.cn/n1/\d{4}/[^"]+)"[^>]*>([^<]{8,60})</a>', 10),
        ], limit=30)
        g = collect(today, 'gj', '人民网', 'https://world.people.com.cn', items)
        if g: groups.append(g)
    except Exception as e:
        errors.append('人民网国际: %s' % e)
    try:
        g = chinanews_gj_group(today)
        if g: groups.append(g)
    except Exception as e:
        errors.append('中新网国际: %s' % e)
    try:
        g = xinhua_world_group(today)
        if g: groups.append(g)
    except Exception as e:
        errors.append('新华国际: %s' % e)

    # 合并、排序（今天在前）
    all_items = [it for g in groups for it in g]
    all_items.sort(key=lambda x: x['day'])
    now = datetime.utcnow() + timedelta(hours=8)  # 北京时间（Actions 服务器为 UTC）
    payload = {
        'fetchedAt': now.strftime('%H:%M'),
        'fetchedDate': now.strftime('%Y-%m-%d'),
        'source': 'zhiri-server',
        'items': all_items[:30],
    }
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    if not all_items:
        print('NEWS_FETCH_FAIL: %s' % '; '.join(errors))
        sys.exit(1)
    if errors:
        print('NEWS_FETCH_PARTIAL: %s' % '; '.join(errors))
    print('NEWS_OK: %d 条（今天 %d）' % (len(all_items), sum(1 for x in all_items if x['day'] == 0)))

if __name__ == '__main__':
    main()
