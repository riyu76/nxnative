#include "bc_fallback.h"
#include <string.h>
#define BCDEC_STATIC
#define BCDEC_BC4BC5_PRECISE
#define BCDEC_IMPLEMENTATION
#include "../../third_party/bcdec/bcdec.h"
int dm_bc_format(unsigned f) {
    if (f < 131 || f > 146) return 0;
    if (f <= 134) return 1;
    return (int)((f - 135) / 2 + 2);
}
unsigned dm_bc_block_bytes(unsigned f) { int b = dm_bc_format(f); return !b ? 0 : b == 1 || b == 4 ? 8 : 16; }
unsigned dm_bc_pixel_bytes(unsigned f) { int b = dm_bc_format(f); return !b ? 0 : b == 4 ? 1 : b == 5 ? 2 : b == 6 ? 8 : 4; }
int dm_bc_upload_layout(unsigned f, unsigned w, unsigned h, unsigned rl, unsigned ih, unsigned layers, size_t *sp, size_t *ip, size_t *span) {
    size_t bb = dm_bc_block_bytes(f), rows = ((size_t)h + 3) / 4;
    if (!bb || !w || !h || !layers || rl < w || ih < h || !sp || !ip || !span) return 0;
    size_t blocks = ((size_t)rl + 3) / 4, images = ((size_t)ih + 3) / 4, last = ((size_t)w + 3) / 4;
    if (blocks > SIZE_MAX / bb) return 0;
    size_t pitch = blocks * bb;
    if (images > SIZE_MAX / pitch) return 0;
    size_t image = pitch * images;
    if ((size_t)layers - 1 > SIZE_MAX / image) return 0;
    size_t prefix = ((size_t)layers - 1) * image;
    if (rows - 1 > (SIZE_MAX - prefix) / pitch) return 0;
    prefix += (rows - 1) * pitch;
    if (last > (SIZE_MAX - prefix) / bb) return 0;
    *sp = pitch; *ip = image; *span = prefix + last * bb; return 1;
}
static int fits(size_t rows, size_t pitch, size_t last, size_t size) {
    return rows && last <= pitch && last <= size && rows - 1 <= (size - last) / pitch;
}
int dm_bc_decode(unsigned f, unsigned w, unsigned h, const void *src, size_t sn, size_t sp, void *dst, size_t dn, size_t dp) {
    int bc = dm_bc_format(f); unsigned pb = dm_bc_pixel_bytes(f), bb = dm_bc_block_bytes(f);
    size_t nx = ((size_t)w + 3) / 4, ny = ((size_t)h + 3) / 4;
    if (!bc || !w || !h || !src || !dst || !sp || !dp || nx > SIZE_MAX / bb || (size_t)w > SIZE_MAX / pb ||
        !fits(ny, sp, nx * bb, sn) || !fits(h, dp, (size_t)w * pb, dn)) return 0;
    for (size_t y = 0; y < ny; y++) for (size_t x = 0; x < nx; x++) {
        uint64_t block[2] = {0}; uint16_t pixels[64] = {0}, rgb[48];
        memcpy(block, (const uint8_t *)src + y * sp + x * bb, bb); // decoder always gets aligned blocks
        switch (bc) {
            case 1: bcdec_bc1(block, pixels, 16); break;
            case 2: bcdec_bc2(block, pixels, 16); break;
            case 3: bcdec_bc3(block, pixels, 16); break;
            case 4: bcdec_bc4(block, pixels, 4, f == 140); break;
            case 5: bcdec_bc5(block, pixels, 8, f == 142); break;
            case 6:
                bcdec_bc6h_half(block, rgb, 12, f == 144);
                for (int p = 0; p < 16; p++) { memcpy(pixels + p * 4, rgb + p * 3, 6); pixels[p * 4 + 3] = 0x3c00; }
                break;
            case 7: bcdec_bc7(block, pixels, 16); break;
        }
        // Vulkan's BC1 RGB variant is opaque, even for the three-colour block mode.
        if (f == 131 || f == 132) for (int p = 0; p < 16; p++) ((uint8_t *)pixels)[4 * p + 3] = 255;
        unsigned cw = w - (unsigned)x * 4; if (cw > 4) cw = 4;
        for (unsigned r = 0; r < 4 && y * 4 + r < h; r++)
            memcpy((uint8_t *)dst + (y * 4 + r) * dp + x * 4 * pb, (uint8_t *)pixels + r * 4 * pb, cw * pb);
    }
    return 1;
}
