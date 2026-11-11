#!/usr/bin/env python3
"""Offline BC2/3/7 -> ASTC 4x4 for explicit, little-endian KTX1 2D assets.

Writes a new container with ASTC format metadata; never remaps every texture of
a BC format, modifies the source, or guesses offsets inside unknown archives.
Galaxy's runtime-generated Wii textures must use the Vulkan runtime fallback.
Requires a C compiler and Arm's astcenc command-line encoder (e.g. brew install astcenc).
"""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

MAGIC = b'\xabKTX 11\xbb\r\n\x1a\n'
# GL internal format -> (Vulkan format, sRGB). BC4/5 need channel semantics; BC6H needs HDR. Do not silently quantize those to LDR.
FORMATS = {0x83F2: (135, False), 0x83F3: (137, False), 0x8E8C: (145, False),
           0x8C4E: (136, True), 0x8C4F: (138, True), 0x8E8D: (146, True)}
REPO = Path(__file__).resolve().parents[1]


def levels(data):
    if len(data) < 64 or data[:12] != MAGIC:
        raise ValueError('expected a KTX1 container')
    header = list(struct.unpack_from('<13I', data, 12))
    endian, typ, ts, fmt, internal, base, w, h, depth, arrays, faces, mips, kv = header
    if endian != 0x04030201 or typ or ts != 1 or fmt or base != 0x1908 or internal not in FORMATS:
        raise ValueError('only little-endian compressed RGBA BC2/3/7 KTX1 is supported')
    if not w or not h or w > 16384 or h > 16384 or depth or arrays or faces != 1 or not 1 <= mips <= max(w, h).bit_length() or kv % 4:
        raise ValueError('only bounded, non-array 2D KTX1 mip chains are supported')
    pos = 64 + kv
    result = []
    for m in range(mips):
        mw, mh = max(1, w >> m), max(1, h >> m)
        need = ((mw + 3) // 4) * ((mh + 3) // 4) * 16
        if pos + 4 > len(data) or struct.unpack_from('<I', data, pos)[0] != need or pos + 4 + need > len(data):
            raise ValueError(f'truncated or inconsistent mip {m}')
        result.append((pos + 4, need, mw, mh))
        pos += 4 + need
    if pos != len(data):
        raise ValueError('unexpected trailing bytes; refusing an ambiguous container')
    return header, result


def astc_payload(data, w, h):
    if len(data) < 16 or data[:7] != b'\x13\xab\xa1\x5c\x04\x04\x01':
        raise ValueError('encoder did not produce ASTC 4x4 2D')
    dims = tuple(int.from_bytes(data[p:p + 3], 'little') for p in (7, 10, 13))
    if dims != (w, h, 1) or len(data) != 16 + ((w + 3) // 4) * ((h + 3) // 4) * 16:
        raise ValueError('wrong ASTC dimensions or payload length')
    return data[16:]


def transcode(data, encode):
    header, images = levels(data)
    vk, srgb = FORMATS[header[4]]
    out = bytearray(data)
    for pos, size, w, h in images:
        payload = encode(bytes(data[pos:pos + size]), vk, srgb, w, h)
        if len(payload) != size:
            raise ValueError('ASTC conversion changed the block footprint')
        out[pos:pos + size] = payload
    header[4] = 0x93D0 if srgb else 0x93B0  # ASTC 4x4 sRGB / LDR, explicitly declared
    struct.pack_into('<13I', out, 12, *header)
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source', type=Path)
    ap.add_argument('output', type=Path, help='new .ktx file; source must remain available for native-BC builds')
    ap.add_argument('--encoder', default='astcenc', help='Arm astcenc executable')
    ap.add_argument('--cache', type=Path, required=True, help='private build cache outside the repository')
    ap.add_argument('--cc', default=os.environ.get('CC', 'cc'))
    args = ap.parse_args()
    data = args.source.read_bytes()
    levels(data)  # validate before invoking tools or creating output
    if args.output.resolve().is_relative_to(REPO) or args.cache.resolve().is_relative_to(REPO):
        ap.error('game-derived output and cache must stay outside the repository')
    if args.output.exists() or args.output.resolve() == args.source.resolve():
        ap.error('output must be a new file')
    encoder = shutil.which(args.encoder)
    if not encoder:
        ap.error('astcenc not found: install Arm astcenc or pass --encoder')
    encoder_hash = hashlib.sha256(Path(encoder).read_bytes()).digest()
    decoder_hash = hashlib.sha256(b''.join((REPO / p).read_bytes() for p in
        ('dm/gfx/tools/bc_to_tga.c', 'dm/gfx/tex/bc_fallback.c', 'dm/third_party/bcdec/bcdec.h'))).digest()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent, prefix='bc-astc-') as tmp:
        work = Path(tmp)
        decoder = work / ('bc_to_tga.exe' if os.name == 'nt' else 'bc_to_tga')
        sources = [str(REPO / 'dm/gfx/tools/bc_to_tga.c'), str(REPO / 'dm/gfx/tex/bc_fallback.c')]
        cmd = [args.cc, '/nologo', '/O2', '/std:c11', *sources, f'/Fe:{decoder}'] if Path(args.cc).stem.lower() == 'cl' else \
              [args.cc, '-O2', '-std=c11', *sources, '-o', str(decoder)]
        subprocess.run(cmd, cwd=work, check=True)

        def encode(blocks, vk, srgb, w, h):
            key = hashlib.sha256(b'nxnative-astc-v1-medium-rgba\0' + encoder_hash + decoder_hash +
                                 struct.pack('<III', vk, w, h) + blocks).hexdigest()
            cached = args.cache / f'{key}.astc'
            if cached.exists():
                return astc_payload(cached.read_bytes(), w, h)
            raw, tga, astc = work / 'input.bc', work / 'input.tga', work / 'output.astc'
            raw.write_bytes(blocks)
            subprocess.run([str(decoder), str(vk), str(w), str(h), str(raw), str(tga)], check=True)
            subprocess.run([encoder, '-cs' if srgb else '-cl', str(tga), str(astc), '4x4', '-medium'], check=True)
            result = astc.read_bytes()
            payload = astc_payload(result, w, h)
            # Publish only complete entries, including when independent builds share this cache.
            with tempfile.NamedTemporaryFile(dir=args.cache, prefix=f'.{key}.', delete=False) as staged:
                staged.write(result)
                staged_path = Path(staged.name)
            try:
                os.replace(staged_path, cached)
            finally:
                staged_path.unlink(missing_ok=True)
            return payload

        result = transcode(data, encode)
        with args.output.open('xb') as stream:
            stream.write(result)
    print(f'Converted {args.source.name}: {len(result)} bytes, ASTC 4x4; original retained. Device validation pending.')


if __name__ == '__main__':
    main()
