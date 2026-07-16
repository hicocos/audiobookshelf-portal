#!/usr/bin/env python3
import struct, json
from pathlib import Path

OUT = Path('/root/audiobookshelf-portal/web/public/anime/generated')
items = []
for p in sorted(OUT.glob('*.png')):
    if p.name == 'test-single.png':
        continue
    b = p.read_bytes()[:24]
    w = h = None
    if b.startswith(b'\x89PNG'):
        w, h = struct.unpack('>II', b[16:24])
    items.append({
        'file': '/anime/generated/' + p.name,
        'name': p.stem,
        'width': w,
        'height': h,
        'bytes': p.stat().st_size,
    })

manifest = {
    'count': len(items),
    'image_base_url': 'https://img.xmu.la/v1',
    'model': 'gpt-image-2',
    'sizes': sorted({(x['width'], x['height']) for x in items}),
    'items': items,
}
(OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
print('count=', manifest['count'])
print('sizes=', manifest['sizes'])
print('total_bytes=', sum(x['bytes'] for x in items))

html = '''<!doctype html><meta charset="utf-8"><title>MoYin generated assets</title>
<style>
body{margin:0;background:#081827;color:#e7f6fd;font-family:system-ui,-apple-system,"PingFang SC",sans-serif}
.h{padding:24px 24px 0}
.h h1{margin:0;font-size:24px}
.h p{color:#a6bfca;margin:6px 0 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:18px;padding:24px}
.card{background:linear-gradient(145deg,#10243a,#0d1f33);border:1px solid #2d5470;border-radius:16px;padding:10px}
img{width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:12px;display:block;background:#000}
.name{margin-top:10px;font-size:12px;line-height:1.4;word-break:break-all}
.dim{color:#a6bfca;font-size:11px}
</style>
<div class="h"><h1>MoYin.CC 二次元音频门户素材</h1><p>''' + str(manifest['count']) + ' 张 · ' + str(manifest['sizes'][0][0]) + '×' + str(manifest['sizes'][0][1]) + ' · 来自 xmula gpt-image-2</p></div>
<div class="grid">'''
for x in items:
    html += f'<div class="card"><img src="{x["file"]}"><div class="name"><b>{x["name"]}</b><div class="dim">{x["width"]}x{x["height"]} · {x["bytes"]/1024:.0f} KB</div></div></div>'
html += '</div>'
(OUT / 'gallery.html').write_text(html)
print('wrote', OUT / 'manifest.json')
print('wrote', OUT / 'gallery.html')
