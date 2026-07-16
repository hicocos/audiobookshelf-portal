#!/usr/bin/env python3
import base64, json, os, re, sys, time, urllib.request, urllib.error
from pathlib import Path

ROOT = Path('/root/audiobookshelf-portal')
OUT = ROOT / 'web/public/anime/generated'
OUT.mkdir(parents=True, exist_ok=True)
ENV = Path('/root/.hermes/.env')
VAR = 'XMULA_IMAGE_API_KEY'
BASE = 'https://img.xmu.la/v1'
MODEL = 'gpt-image-2'

def load_key():
    for line in ENV.read_text(errors='ignore').splitlines():
        if line.startswith(VAR + '='):
            return line.split('=', 1)[1].strip()
    raise RuntimeError(f'missing {VAR}')

STYLE = (
    'High quality refined anime illustration asset for a dark navy/cyan audio portal website, '
    'beautiful Japanese anime style, polished game UI mascot art, glossy cyber audio aesthetic, '
    'cyan teal glow, violet and gold accents, clean silhouette, premium web decoration, '
    'no text, no letters, no logo, no watermark, no UI words, safe for website ornament, '
    'centered subject, isolated composition, transparent-feeling or simple dark gradient background.'
)

PROMPTS = [
    ('mascot_headphones_girl', 'cheerful anime girl mascot with long cyan pink twin tails, oversized headphones, holding a glowing audiobook crystal, full body dynamic pose'),
    ('mascot_reading_float', 'cute anime girl floating while reading a glowing audio book, sound wave ribbons around her, elegant and calm'),
    ('headphone_cat_spirit', 'small cyber cat spirit wearing headphones, sitting on a glowing audio wave orb, adorable website mascot'),
    ('audio_book_crystal', 'open fantasy audiobook crystal with pages turning into cyan sound waves and tiny stars'),
    ('neon_headphones_icon', 'large premium futuristic headphones with cyan glow, small music particles, decorative icon object'),
    ('floating_cassette_charm', 'retro cassette tape charm redesigned as futuristic anime cyber audio object, teal lights, cute rounded shape'),
    ('library_orb', 'magical digital library orb filled with tiny books and waveform rings, anime tech fantasy style'),
    ('soundwave_wing', 'pair of translucent angel wings made from cyan soundwaves and sparkles, elegant decorative asset'),
    ('chibi_admin_robot', 'small chibi robot librarian with headset, holding a key card and audio book, friendly'),
    ('renewal_ticket_magic', 'glowing renewal ticket card with sparkles, abstract no text, cyan gold magical tech aesthetic'),
    ('mobile_client_phone', 'futuristic smartphone with anime audio client interface represented only by abstract wave shapes, no readable text'),
    ('desktop_client_monitor', 'futuristic desktop monitor showing abstract audio wave dashboard, no readable text, cyan glow'),
    ('progress_ring_gem', 'glowing circular progress ring gem with audio waveform inside, premium cyber ornament'),
    ('shield_audio_access', 'cute magical shield with headphones emblem shape but no letters, access protection ornament'),
    ('star_microchip', 'anime holographic star microchip with cyan core and gold circuitry, polished decorative object'),
    ('floating_music_island', 'tiny floating island with headphones, books, and cyan waterfall of audio waves, dreamy anime background object'),
    ('chibi_sleepy_listener', 'chibi anime listener curled up with headphones and blanket, cozy night listening mood'),
    ('wave_dragon', 'small friendly dragon made of sound waves, cyan translucent body, fantasy anime style'),
    ('audio_compass', 'glowing compass for audio journey, cyan violet, stars and waveform needle, no text'),
    ('keycard_access', 'futuristic access keycard with abstract waveform pattern, no text or numbers, cyan gold glow'),
    ('book_stack_glow', 'stack of audiobooks with floating earbuds and wave particles, anime polished asset'),
    ('notification_bell_magic', 'cute notification bell made of glass and cyan light, sparkles, no symbols or text'),
    ('cloud_audio_server', 'soft cloud server island with glowing audio wave streams, anime cyber fantasy'),
    ('footer_mascot_chibi', 'tiny chibi anime girl mascot sitting on a sound wave, waving, headphones, suitable for footer decoration'),
]

NEG = 'Avoid text, letters, numbers, logos, watermark, realistic photo, horror, clutter, low quality, blurry, extra fingers, distorted face.'

def slug(s):
    return re.sub(r'[^a-z0-9_-]+', '-', s.lower()).strip('-')

def call_api(key, prompt, attempt=1):
    payload = json.dumps({
        'model': MODEL,
        'prompt': prompt,
        'size': '1024x1024',
        'n': 1,
    }).encode()
    req = urllib.request.Request(BASE.rstrip('/') + '/images/generations', data=payload, headers={
        'Authorization': 'Bearer ' + key,
        'Content-Type': 'application/json',
        'User-Agent': 'MoyinAssetGenerator/1.0',
    })
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))

def save_image(item, data):
    first = (data.get('data') or [{}])[0]
    name = slug(item)
    out = OUT / f'{name}.png'
    if first.get('b64_json'):
        raw = base64.b64decode(first['b64_json'])
        out.write_bytes(raw)
    elif first.get('url'):
        raw = urllib.request.urlopen(first['url'], timeout=120).read()
        out.write_bytes(raw)
    else:
        raise RuntimeError('no image data')
    return out, first

def main():
    key = load_key()
    manifest = []
    existing = {p.stem for p in OUT.glob('*.png')}
    for idx, (name, desc) in enumerate(PROMPTS, 1):
        if slug(name) in existing:
            print(f'[{idx:02d}/{len(PROMPTS)}] skip existing {name}', flush=True)
            continue
        prompt = f'{STYLE}\nSubject: {desc}.\nNegative: {NEG}'
        print(f'[{idx:02d}/{len(PROMPTS)}] generating {name}', flush=True)
        last_err = None
        for attempt in range(1, 4):
            try:
                data = call_api(key, prompt, attempt)
                out, first = save_image(name, data)
                manifest.append({
                    'name': name,
                    'file': '/anime/generated/' + out.name,
                    'prompt': desc,
                    'revised_prompt': first.get('revised_prompt', ''),
                    'source_url': first.get('url', ''),
                    'bytes': out.stat().st_size,
                })
                print(f'  saved {out.name} {out.stat().st_size} bytes', flush=True)
                break
            except Exception as e:
                last_err = e
                print(f'  attempt {attempt} failed: {type(e).__name__}: {str(e)[:240]}', flush=True)
                time.sleep(4 * attempt)
        else:
            print(f'FAILED {name}: {last_err}', flush=True)
        time.sleep(1.5)
    # merge manifest with existing files
    old_manifest_path = OUT / 'manifest.json'
    old = []
    if old_manifest_path.exists():
        try:
            old = json.loads(old_manifest_path.read_text())
        except Exception:
            old = []
    by_file = {x.get('file'): x for x in old if x.get('file')}
    for x in manifest:
        by_file[x['file']] = x
    # ensure every png is represented
    for p in sorted(OUT.glob('*.png')):
        f = '/anime/generated/' + p.name
        by_file.setdefault(f, {'name': p.stem, 'file': f, 'prompt': '', 'bytes': p.stat().st_size})
    final = list(by_file.values())
    old_manifest_path.write_text(json.dumps(final, ensure_ascii=False, indent=2))
    md = OUT / 'README.md'
    md.write_text('# MoYin.CC generated anime assets\n\n' + '\n'.join(f'- `{x["file"]}` — {x.get("name","")}' for x in final) + '\n')
    print(f'DONE assets={len(list(OUT.glob("*.png")))} manifest={old_manifest_path}', flush=True)

if __name__ == '__main__':
    main()
