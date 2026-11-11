"""Execute the real bounded decoder and capability policy using synthetic blocks, no Metal or game files."""
import ctypes
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]


class BCDecode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name)
        cc = os.environ.get('CC', 'cc')
        if not shutil.which(cc):
            raise unittest.SkipTest('C compiler required')
        lib = root / ('bc.dll' if os.name == 'nt' else 'bc.so')
        policy = root / 'policy.c'
        policy.write_text('#include "gpu_compat.h"\nint policy(int bc,int astc,int a7,int on,int force) { '
                          'return dm_gpu_compat_path((dm_gpu_caps){bc,astc,a7},on,force); }\n')
        sources = [str(REPO / 'dm/gfx/tex/bc_fallback.c'), str(policy)]
        if Path(cc).stem.lower() == 'cl':
            cmd = [cc, '/nologo', '/LD', '/std:c11', '/O2', f'/I{REPO / "dm/gfx/tex"}', *sources,
                   '/link', f'/OUT:{lib}', '/EXPORT:dm_bc_decode', '/EXPORT:dm_bc_pixel_bytes', '/EXPORT:dm_bc_upload_layout', '/EXPORT:policy']
        else:
            cmd = [cc, '-shared', '-fPIC', '-O2', '-std=c11', f'-I{REPO / "dm/gfx/tex"}', *sources, '-o', str(lib)]
        subprocess.run(cmd, cwd=root, check=True, capture_output=True)
        cls.lib = ctypes.CDLL(str(lib))
        if os.name == 'nt':
            import _ctypes
            cls.addClassCleanup(_ctypes.FreeLibrary, cls.lib._handle)
        cls.lib.dm_bc_decode.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t,
                                         ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t]
        cls.lib.dm_bc_decode.restype = ctypes.c_int
        cls.lib.dm_bc_upload_layout.argtypes = [ctypes.c_uint] * 6 + [ctypes.POINTER(ctypes.c_size_t)] * 3

    def decode(self, fmt, block, w=4, h=4):
        pb = self.lib.dm_bc_pixel_bytes(fmt)
        out = ctypes.create_string_buffer(w * h * pb)
        self.assertEqual(self.lib.dm_bc_decode(fmt, w, h, block, len(block), len(block), out, len(out), w * pb), 1)
        return out.raw

    def test_bc1_punchthrough_and_rgb_opaque(self):
        block = bytes(4) + b'\xff' * 4
        self.assertEqual(self.decode(133, block), bytes(64))
        self.assertEqual(self.decode(134, block), bytes(64))  # sRGB does not touch alpha
        self.assertEqual(self.decode(131, block), bytes([0, 0, 0, 255]) * 16)

    def test_bc2_bc3_alpha_and_srgb(self):
        color = b'\xff\xff\x00\x00' + bytes(4)
        for f in (135, 136, 137, 138):
            alpha = b'\xff' * 8 if f <= 136 else b'\xff\x00' + bytes(6)
            self.assertEqual(self.decode(f, alpha + color), b'\xff' * 64)

    def test_bc4_bc5_signed_channels(self):
        self.assertEqual(self.decode(139, b'\xff\x00' + bytes(6)), b'\xff' * 16)
        self.assertEqual(self.decode(140, b'\x81\x7f' + bytes(6)), b'\x81' * 16)
        self.assertEqual(self.decode(141, b'\xff\x00' + bytes(6) + b'\x80\x00' + bytes(6)), b'\xff\x80' * 16)
        self.assertEqual(self.decode(142, b'\x81\x7f' + bytes(6) + b'\x7f\x81' + bytes(6)), b'\x81\x7f' * 16)

    def test_bc6_half_and_bc7(self):
        for f in (143, 144):
            self.assertEqual(self.decode(f, bytes(16)), (bytes(6) + b'\x00\x3c') * 16)
        # BC7 mode 6: two identical endpoints, p-bits 1; indices all zero.
        fields = [(64, 7), (127, 7), (127, 7), (0, 7), (0, 7), (0, 7), (0, 7), (127, 7), (127, 7), (1, 1), (1, 1)]
        value = shift = 0
        for v, bits in fields:
            value |= v << shift
            shift += bits
        for f in (145, 146):
            self.assertEqual(self.decode(f, value.to_bytes(16, 'little')), b'\xff\x01\x01\xff' * 16)

    def test_partial_blocks_padding_and_invalid_bounds(self):
        rng = random.Random(0xA15)
        for f in range(131, 147):
            pb = self.lib.dm_bc_pixel_bytes(f)
            for w, h in ((1, 1), (3, 7), (9, 5), (4, 4)):
                bb = 8 if f <= 134 or f in (139, 140) else 16
                sp = ((w + 3) // 4) * bb + 16
                source = rng.randbytes(sp * ((h + 3) // 4))
                dp = w * pb + 13
                out = ctypes.create_string_buffer(b'\xcd' * (dp * h + 32), dp * h + 32)
                self.assertEqual(self.lib.dm_bc_decode(f, w, h, source, len(source), sp, out, dp * h, dp), 1)
                for y in range(h):
                    self.assertEqual(out.raw[y * dp + w * pb:(y + 1) * dp], b'\xcd' * 13)
                self.assertEqual(out.raw[dp * h:], b'\xcd' * 32)
                before = out.raw
                self.assertEqual(self.lib.dm_bc_decode(f, w, h, source, 0, sp, out, dp * h, dp), 0)
                self.assertEqual(out.raw, before)
        self.assertEqual(self.lib.dm_bc_decode(130, 4, 4, b'0' * 16, 16, 16, out, 64, 16), 0)

    def test_gpu_capability_matrix(self):
        policy = self.lib.policy
        for bc in (0, 1):
            for astc in (0, 1):
                for a7 in (0, 1):
                    for on in (0, 1):
                        for force in (0, 1):
                            self.assertEqual(policy(bc, astc, a7, on, force), bool(on and astc and a7 and (not bc or force)))

    def test_upload_stride_arithmetic(self):
        sp, ip, span = ctypes.c_size_t(), ctypes.c_size_t(), ctypes.c_size_t()
        layout = self.lib.dm_bc_upload_layout
        self.assertEqual(layout(133, 5, 7, 12, 12, 2, ctypes.byref(sp), ctypes.byref(ip), ctypes.byref(span)), 1)
        self.assertEqual((sp.value, ip.value, span.value), (24, 72, 112))
        for args in ((137, 4, 4, 0xffffffff, 0xffffffff, 2), (133, 4, 4, 0xffffffff, 0xffffffff, 0xffffffff),
                     (133, 4, 4, 3, 4, 1), (133, 4, 4, 4, 4, 0)):
            self.assertEqual(layout(*args, ctypes.byref(sp), ctypes.byref(ip), ctypes.byref(span)), 0)


if __name__ == '__main__':
    unittest.main()
