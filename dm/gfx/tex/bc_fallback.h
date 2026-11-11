// Checked, allocation-free BC image decoding. Format IDs deliberately match Vulkan's BC range (131..146).
#ifndef DM_BC_FALLBACK_H
#define DM_BC_FALLBACK_H
#include <stddef.h>
#include <stdint.h>
int dm_bc_format(unsigned format); // 1..7, 6 = BC6H; zero for other formats
unsigned dm_bc_block_bytes(unsigned format);
unsigned dm_bc_pixel_bytes(unsigned format); // BC4 R8, BC5 RG8, BC6H RGBA16F, others RGBA8
int dm_bc_upload_layout(unsigned format, unsigned w, unsigned h, unsigned row_length, unsigned image_height, unsigned layers,
                        size_t *row_pitch, size_t *image_pitch, size_t *span);
// Decode a tightly bounded rectangle, respecting padded source and destination row pitches. No write on bad sizes.
int dm_bc_decode(unsigned format, unsigned w, unsigned h, const void *src, size_t src_size, size_t src_pitch,
                 void *dst, size_t dst_size, size_t dst_pitch);
#endif
