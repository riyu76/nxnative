// Experimental Vulkan BC fallback policy. Pure C so capability decisions can be tested without Metal.
#ifndef DM_GPU_COMPAT_H
#define DM_GPU_COMPAT_H
#include <stdlib.h>
#include <string.h>
typedef struct { int bc, astc, apple7; } dm_gpu_caps;
static inline int dm_gpu_compat_enabled(void) {
    const char *e = getenv("DM_GPU_COMPAT"); return e && !strcmp(e, "1");
}
static inline int dm_gpu_compat_path(dm_gpu_caps c, int enabled, int force) {
    return enabled && c.astc && c.apple7 && (!c.bc || force);
}
#ifdef __OBJC__
#import <Metal/Metal.h>
#include <TargetConditionals.h>
static inline dm_gpu_caps dm_gpu_capabilities(id<MTLDevice> d) {
    return (dm_gpu_caps){d.supportsBCTextureCompression, [d supportsFamily:MTLGPUFamilyApple2], [d supportsFamily:MTLGPUFamilyApple7]};
}
static inline int dm_gpu_use_fallback(id<MTLDevice> d) {
    int force = 0;
#if TARGET_OS_OSX
    const char *f = getenv("DM_GPU_COMPAT_FORCE"); force = f && !strcmp(f, "1");
#endif
    return dm_gpu_compat_path(dm_gpu_capabilities(d), dm_gpu_compat_enabled(), force);
}
#endif
#endif
