#!/usr/bin/env python3
from pathlib import Path
import os
import shutil
import sys

SRC = Path('/www/pt')
DST = Path('/www/wwwroot/books')

if not SRC.exists() or not DST.exists():
    raise SystemExit('source or destination missing')

checked = 0
converted = 0
skipped = 0
for sdir in sorted(p for p in SRC.iterdir() if p.is_dir()):
    ddir = DST / sdir.name
    if not ddir.exists():
        continue
    print(f'folder={sdir.name}', flush=True)
    for sf in sdir.rglob('*'):
        if not sf.is_file():
            continue
        tf = ddir / sf.relative_to(sdir)
        if not tf.exists() or not tf.is_file():
            continue
        checked += 1
        ss = sf.stat()
        ts = tf.stat()
        if not (ss.st_dev == ts.st_dev and ss.st_ino == ts.st_ino):
            skipped += 1
            continue
        tmp = tf.with_name(tf.name + '.unlink-copy-tmp')
        try:
            if tmp.exists():
                tmp.unlink()
            shutil.copy2(tf, tmp, follow_symlinks=True)
            os.replace(tmp, tf)
            converted += 1
            if converted % 100 == 0:
                print(f'converted={converted} checked={checked} skipped={skipped} current={tf}', flush=True)
        except Exception as exc:
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass
            print(f'ERROR at {tf}: {exc}', file=sys.stderr, flush=True)
            raise
print(f'done checked={checked} converted={converted} skipped={skipped}', flush=True)
