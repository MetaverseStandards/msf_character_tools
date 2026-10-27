/* SPDX-License-Identifier: MIT */
#include "msf_ufbx_shim.h"
#include "ufbx.h"
#include <stdlib.h>
#include <string.h>

struct msf_fbx {
    ufbx_scene *scene;
};

static void set_error(char *err, size_t n, const char *message) {
    if (err && n) {
        strncpy(err, message, n - 1);
        err[n - 1] = '\0';
    }
}

int msf_fbx_open(const uint8_t *data, size_t len, const msf_fbx_limits *limits, msf_fbx **out, char *err, size_t n) {
    if (!data || !out) {
        set_error(err, n, "msf_fbx_open: null argument");
        return 0;
    }
    *out = NULL;
    ufbx_load_opts opts;
    memset(&opts, 0, sizeof(opts));
    opts.target_axes = ufbx_axes_right_handed_y_up;
    opts.target_unit_meters = 1.0;
    opts.space_conversion = UFBX_SPACE_CONVERSION_MODIFY_GEOMETRY;
    opts.geometry_transform_handling = UFBX_GEOMETRY_TRANSFORM_HANDLING_MODIFY_GEOMETRY;
    opts.inherit_mode_handling = UFBX_INHERIT_MODE_HANDLING_COMPENSATE;
    opts.pivot_handling = UFBX_PIVOT_HANDLING_ADJUST_TO_PIVOT;
    opts.load_external_files = false;
    opts.ignore_embedded = true;
    if (limits) {
        opts.temp_allocator.memory_limit = limits->memory_limit;
        opts.temp_allocator.allocation_limit = limits->allocation_limit;
        opts.result_allocator.memory_limit = limits->memory_limit;
        opts.result_allocator.allocation_limit = limits->allocation_limit;
    }
    ufbx_error error;
    ufbx_scene *scene = ufbx_load_memory(data, len, &opts, &error);
    if (!scene) {
        char text[1024];
        ufbx_format_error(text, sizeof(text), &error);
        set_error(err, n, text);
        return 0;
    }
    msf_fbx *h = (msf_fbx *)calloc(1, sizeof(msf_fbx));
    if (!h) {
        ufbx_free_scene(scene);
        set_error(err, n, "msf_fbx_open: out of memory");
        return 0;
    }
    h->scene = scene;
    *out = h;
    return 1;
}

void msf_fbx_close(msf_fbx *h) {
    if (!h) return;
    ufbx_free_scene(h->scene);
    free(h);
}

int msf_fbx_info_get(const msf_fbx *h, msf_fbx_info *out) {
    if (!h || !out) return 0;
    const ufbx_scene *s = h->scene;
    memset(out, 0, sizeof(*out));
    uint32_t helpers = 0;
    for (size_t i = 0; i < s->nodes.count; i++) {
        const ufbx_node *node = s->nodes.data[i];
        if (node->is_geometry_transform_helper || node->is_scale_helper) helpers++;
    }
    out->nodes = (uint32_t)(s->nodes.count - 1); /* without the ufbx root */
    out->meshes = (uint32_t)s->meshes.count;
    out->anim_stacks = (uint32_t)s->anim_stacks.count;
    out->helper_nodes = helpers;
    out->unit_meters = s->settings.original_unit_meters;
    out->fps = s->settings.frames_per_second;
    out->ascii = s->metadata.ascii ? 1 : 0;
    out->version = s->metadata.version;
    /* settings.axes keeps the file's own axes even when the load converts them. */
    out->axes_converted = !(s->settings.axes.right == UFBX_COORDINATE_AXIS_POSITIVE_X
                            && s->settings.axes.up == UFBX_COORDINATE_AXIS_POSITIVE_Y
                            && s->settings.axes.front == UFBX_COORDINATE_AXIS_POSITIVE_Z);
    return 1;
}
