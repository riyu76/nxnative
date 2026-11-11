// Real Metal upload/readback on the forced experimental Vulkan path. No copyrighted inputs.
#include "../vk/hle_vk.m"
int dm_guest_as_contains(uintptr_t address) { (void)address; return 0; }
void *front_metal_layer(void) { return NULL; }
module_t *module_of(const void *p) { (void)p; return NULL; }
module_t *g_mod; int g_nmod;
void svc_thread_dump(void) {}
uint64_t now_ns(void) { return clock_gettime_nsec_np(CLOCK_UPTIME_RAW); }
void dm_vi_layer_crop(int c[4]) { memset(c, 0, 4 * sizeof *c); }
int dm_opmode(void) { return 0; }
static int checks, fails;
#define CHECK(c, msg) do { checks++; if (!(c)) { fails++; fprintf(stderr, "FAIL: %s\n", msg); } } while (0)
static void check_pixels(VkImage im, unsigned mip, unsigned layer, unsigned w, unsigned h, int green) {
    id<MTLBuffer> out = [g_dev newBufferWithLength:256 * h options:MTLResourceStorageModeShared];
    id<MTLCommandBuffer> cb = [g_q commandBuffer]; id<MTLBlitCommandEncoder> be = [cb blitCommandEncoder];
    [be copyFromTexture:im->tex sourceSlice:layer sourceLevel:mip sourceOrigin:MTLOriginMake(0, 0, 0) sourceSize:MTLSizeMake(w, h, 1)
              toBuffer:out destinationOffset:0 destinationBytesPerRow:256 destinationBytesPerImage:0];
    [be endEncoding]; [cb commit]; [cb waitUntilCompleted]; CHECK(!cb.error, "decoded readback completes");
    for (unsigned y = 0; y < h; y++) for (unsigned x = 0; x < w; x++) {
        const uint8_t *p = (const uint8_t *)out.contents + y * 256 + x * 4;
        CHECK(p[0] == (green ? 0 : 255) && p[1] == (green ? 255 : 0) && p[2] == 0 && p[3] == 255, "all edge and layer pixels match");
    }
}
int main(void) {
    setenv("DM_GPU_COMPAT", "1", 1); setenv("DM_GPU_COMPAT_FORCE", "1", 1);
    @autoreleasepool {
        dev_init(); CHECK(g_bc_decode, "forced fallback on a BC-capable Mac");
        VkPhysicalDeviceFeatures features; pdev_feats(&features); CHECK(!features.textureCompressionBC, "partial fallback does not advertise the complete BC feature");
        VkImageCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D, .format = VK_FORMAT_BC1_RGBA_UNORM_BLOCK,
            .extent = {5, 7, 1}, .mipLevels = 2, .arrayLayers = 2, .samples = 1, .tiling = VK_IMAGE_TILING_OPTIMAL,
            .usage = VK_IMAGE_USAGE_SAMPLED_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT, .flags = VK_IMAGE_CREATE_MUTABLE_FORMAT_BIT};
        VkImage im; CHECK(h_vkCreateImage(&g_device, &ci, NULL, &im) == VK_SUCCESS, "fallback image created");
        CHECK(im->tex.pixelFormat == MTLPixelFormatRGBA8Unorm, "no unsupported BC Metal descriptor");
        VkImageSubresource sub = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT}; VkSubresourceLayout layout;
        h_vkGetImageSubresourceLayout(&g_device, im, &sub, &layout); CHECK(layout.rowPitch == 16, "guest memory layout remains BC");
        VkImageViewCreateInfo vi = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = im, .viewType = VK_IMAGE_VIEW_TYPE_2D_ARRAY,
            .format = VK_FORMAT_BC1_RGBA_SRGB_BLOCK, .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 2, 0, 2}};
        VkImageView view; CHECK(h_vkCreateImageView(&g_device, &vi, NULL, &view) == VK_SUCCESS && view->tex.pixelFormat == MTLPixelFormatRGBA8Unorm_sRGB, "sRGB view uses decoded storage");
        vi.format = VK_FORMAT_BC1_RGB_UNORM_BLOCK; VkImageView rejected_view;
        CHECK(h_vkCreateImageView(&g_device, &vi, NULL, &rejected_view) == VK_ERROR_FORMAT_NOT_SUPPORTED, "a different alpha interpretation is rejected");
        struct VkDeviceMemory_T memory = {.size = 256}; struct VkBuffer_T buffer = {.size = 256, .mem = &memory};
        id<MTLBuffer> input = mem_buf(&memory); uint8_t *p = input.contents;
        for (int i = 0; i < 32; i++) { memset(p + i * 8, 0, 8); p[i * 8 + 1] = 0xf8; }
        VkBufferImageCopy r = {.bufferRowLength = 8, .bufferImageHeight = 8, .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 2}, .imageExtent = {5, 7, 1}};
        subq_t sq = {0}; rs_t s = {.cb = [g_q commandBuffer], .sq = &sq};
        bc_upload(&s, &buffer, im, &r); end_blit(&s); [s.cb commit]; [s.cb waitUntilCompleted];
        CHECK(!s.cb.error, "padded, multilayer partial-edge upload completes");
        check_pixels(im, 0, 0, 5, 7, 0); check_pixels(im, 0, 1, 5, 7, 0);
        r.imageSubresource.mipLevel = 1; r.imageExtent = (VkExtent3D){2, 3, 1};
        s.cb = [g_q commandBuffer]; bc_upload(&s, &buffer, im, &r); end_blit(&s); [s.cb commit]; [s.cb waitUntilCompleted];
        check_pixels(im, 1, 1, 2, 3, 0);
        // Produce green BC blocks on the GPU before the upload. The decoder must see that write in this same submission.
        id<MTLBuffer> green = [g_dev newBufferWithLength:256 options:MTLResourceStorageModeShared];
        uint8_t *gp = green.contents; memset(gp, 0, 256); for (int i = 0; i < 32; i++) { gp[i * 8] = 0xe0; gp[i * 8 + 1] = 7; }
        s.cb = [g_q commandBuffer]; [blit(&s, C_COPYB) copyFromBuffer:green sourceOffset:0 toBuffer:input destinationOffset:0 size:256];
        r.imageSubresource.mipLevel = 0; r.imageExtent = (VkExtent3D){5, 7, 1};
        bc_upload(&s, &buffer, im, &r); end_blit(&s); [s.cb commit]; [s.cb waitUntilCompleted];
        check_pixels(im, 0, 0, 5, 7, 1);
        VkImage rejected; ci.usage |= VK_IMAGE_USAGE_STORAGE_BIT;
        CHECK(h_vkCreateImage(&g_device, &ci, NULL, &rejected) == VK_ERROR_FORMAT_NOT_SUPPORTED, "storage writes rejected before Metal");
        ci.usage &= ~VK_IMAGE_USAGE_STORAGE_BIT; ci.extent = (VkExtent3D){16384, 16384, 1};
        CHECK(h_vkCreateImage(&g_device, &ci, NULL, &rejected) == VK_ERROR_OUT_OF_DEVICE_MEMORY, "expanded storage budget enforced");
        h_vkDestroyImage(&g_device, im, NULL); CHECK(g_bc_live > 0, "view retains its storage charge after image destruction");
        h_vkDestroyImageView(&g_device, view, NULL);
        bc_memory_report();
    }
    CHECK(g_bc_live == 0, "destroying all views and completed command buffers releases the storage charge");
    printf("Vulkan BC fallback: %d checks, %d failures; synthetic Metal validation only, no A15 hardware validation\n", checks, fails);
    return fails != 0;
}
