/* 知日 Service Worker — 离线可用 + 网络优先更新策略 */
const CACHE = 'zhiri-v4';
const PRECACHE = ['./', './index.html', './manifest.json', './icon-192.png', './icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE)
      .then(c => c.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  const isPage = url.pathname.endsWith('/') || url.pathname.endsWith('.html');
  const isData = url.pathname.endsWith('news.json') || url.pathname.endsWith('study.json');

  if (isPage || isData) {
    // 网络优先：拿到新内容就更新缓存；断网时回退缓存（页面兜底 index.html）
    e.respondWith(
      fetch(req)
        .then(res => {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(req, copy));
          return res;
        })
        .catch(() =>
          caches.match(req).then(m => m || caches.match('./index.html'))
        )
    );
    return;
  }

  // 静态资源：缓存优先，未命中再取网络并缓存
  e.respondWith(
    caches.match(req).then(m =>
      m || fetch(req).then(res => {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(req, copy));
        return res;
      })
    )
  );
});
