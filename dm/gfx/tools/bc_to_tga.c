// Private build-time decoder for transcode_bc_astc.py. No game-specific layout guesses.
#include "../tex/bc_fallback.h"
#include <stdio.h>
#include <stdlib.h>
int main(int argc, char **argv) {
    if (argc != 6) return 2;
    unsigned f = (unsigned)strtoul(argv[1], NULL, 10), w = (unsigned)strtoul(argv[2], NULL, 10), h = (unsigned)strtoul(argv[3], NULL, 10);
    if (!w || !h || w > 16384 || h > 16384 || (dm_bc_format(f) != 2 && dm_bc_format(f) != 3 && dm_bc_format(f) != 7)) return 2;
    size_t pitch = ((size_t)w + 3) / 4 * 16, sn = pitch * (((size_t)h + 3) / 4), dn = (size_t)w * h * 4;
    unsigned char *src = malloc(sn), *dst = malloc(dn); FILE *in = fopen(argv[4], "rb");
    if (!src || !dst || !in) return 1;
    int ok = fread(src, 1, sn, in) == sn && fgetc(in) == EOF; fclose(in);
    if (!ok || !dm_bc_decode(f, w, h, src, sn, pitch, dst, dn, (size_t)w * 4)) return 1;
    unsigned char hdr[18] = {0}; hdr[2] = 2; hdr[12] = w & 255; hdr[13] = w >> 8; hdr[14] = h & 255; hdr[15] = h >> 8; hdr[16] = 32; hdr[17] = 0x28;
    for (size_t p = 0; p < dn; p += 4) { unsigned char t = dst[p]; dst[p] = dst[p + 2]; dst[p + 2] = t; }
    FILE *out = fopen(argv[5], "wb"); if (!out) return 1;
    ok = fwrite(hdr, 1, 18, out) == 18 && fwrite(dst, 1, dn, out) == dn;
    if (fclose(out)) ok = 0;
    free(src); free(dst); return ok ? 0 : 1;
}
