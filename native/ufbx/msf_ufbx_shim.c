/* SPDX-License-Identifier: MIT */
#include "msf_ufbx_shim.h"
#include "ufbx.h"
#include <stdlib.h>
#include <string.h>

struct msf_fbx {
    ufbx_scene *scene;
    msf_fbx_limits limits;
    uint32_t *shim_of_element; /* element_id -> shim node index, UINT32_MAX for the root and non-nodes */
};

static int32_t shim_index(const msf_fbx *h, const ufbx_node *node) {
    if (!node || node->is_root) return -1;
    return (int32_t)h->shim_of_element[node->element_id];
}

static void matrix16(const ufbx_matrix *m, double *out) {
    for (int c = 0; c < 4; c++) {
        out[4 * c + 0] = m->cols[c].x;
        out[4 * c + 1] = m->cols[c].y;
        out[4 * c + 2] = m->cols[c].z;
        out[4 * c + 3] = c == 3 ? 1.0 : 0.0;
    }
}

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
    /* Node paths grow with depth, so very deep hierarchies would make path handling quadratic. */
    opts.node_depth_limit = 1024;
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
    if (limits) h->limits = *limits;
    h->shim_of_element = (uint32_t *)malloc(sizeof(uint32_t) * (scene->elements.count + 1));
    if (!h->shim_of_element) {
        msf_fbx_close(h);
        set_error(err, n, "msf_fbx_open: out of memory");
        return 0;
    }
    for (size_t i = 0; i < scene->elements.count; i++) h->shim_of_element[i] = UINT32_MAX;
    uint32_t next = 0;
    for (size_t i = 0; i < scene->nodes.count; i++) {
        const ufbx_node *node = scene->nodes.data[i];
        if (!node->is_root) h->shim_of_element[node->element_id] = next++;
    }
    *out = h;
    return 1;
}

static const ufbx_node *node_at(const msf_fbx *h, uint32_t i) {
    uint32_t seen = 0;
    for (size_t k = 0; k < h->scene->nodes.count; k++) {
        const ufbx_node *node = h->scene->nodes.data[k];
        if (node->is_root) continue;
        if (seen++ == i) return node;
    }
    return NULL;
}

int msf_fbx_node_get(const msf_fbx *h, uint32_t i, msf_fbx_node *out) {
    if (!h || !out) return 0;
    const ufbx_node *node = node_at(h, i);
    if (!node) return 0;
    memset(out, 0, sizeof(*out));
    out->parent = shim_index(h, node->parent);
    out->name = node->name.data;
    out->name_len = node->name.length;
    out->mesh = node->mesh ? (int32_t)node->mesh->typed_id : -1;
    out->is_bone = node->bone != NULL || node->attrib_type == UFBX_ELEMENT_BONE;
    out->helper = node->is_geometry_transform_helper ? 1 : node->is_scale_helper ? 2 : 0;
    out->inherit_mode = (int)node->inherit_mode;
    out->original_inherit_mode = (int)node->original_inherit_mode;
    switch (node->attrib_type) {
    case UFBX_ELEMENT_LIGHT: out->skipped = "light"; break;
    case UFBX_ELEMENT_CAMERA: out->skipped = "camera"; break;
    case UFBX_ELEMENT_STEREO_CAMERA: out->skipped = "stereo camera"; break;
    case UFBX_ELEMENT_CAMERA_SWITCHER: out->skipped = "camera switcher"; break;
    case UFBX_ELEMENT_LINE_CURVE: out->skipped = "line curve"; break;
    case UFBX_ELEMENT_NURBS_CURVE: out->skipped = "NURBS curve"; break;
    case UFBX_ELEMENT_NURBS_SURFACE: out->skipped = "NURBS surface"; break;
    case UFBX_ELEMENT_NURBS_TRIM_SURFACE: out->skipped = "NURBS trim surface"; break;
    case UFBX_ELEMENT_PROCEDURAL_GEOMETRY: out->skipped = "procedural geometry"; break;
    case UFBX_ELEMENT_MARKER: out->skipped = "marker"; break;
    case UFBX_ELEMENT_LOD_GROUP: out->skipped = "LOD group"; break;
    default: out->skipped = NULL; break;
    }
    static const char *const pivot_props[] = {"RotationPivot", "ScalingPivot", "RotationOffset", "ScalingOffset",
                                              "PreRotation", "PostRotation"};
    ufbx_vec3 zero = {0.0, 0.0, 0.0};
    for (size_t k = 0; k < sizeof(pivot_props) / sizeof(pivot_props[0]); k++) {
        ufbx_vec3 v = ufbx_find_vec3(&node->props, pivot_props[k], zero);
        if (v.x != 0.0 || v.y != 0.0 || v.z != 0.0) out->pivots = 1;
    }
    matrix16(&node->node_to_parent, out->to_parent);
    matrix16(&node->node_to_world, out->to_world);
    return 1;
}

static const ufbx_mesh *mesh_at(const msf_fbx *h, uint32_t m) {
    if (!h || m >= h->scene->meshes.count) return NULL;
    return h->scene->meshes.data[m];
}

static int usable_face(const ufbx_mesh *mesh, size_t f) {
    int hole = mesh->face_hole.count > f && mesh->face_hole.data[f];
    return !hole && mesh->faces.data[f].num_indices >= 3;
}

int msf_fbx_mesh_sizes(const msf_fbx *h, uint32_t m, uint32_t sizes[6]) {
    const ufbx_mesh *mesh = mesh_at(h, m);
    if (!mesh || !sizes) return 0;
    uint32_t triangles = 0, holes = 0, small = 0;
    for (size_t f = 0; f < mesh->faces.count; f++) {
        if (mesh->face_hole.count > f && mesh->face_hole.data[f]) holes++;
        else if (mesh->faces.data[f].num_indices < 3) small++;
        if (usable_face(mesh, f)) triangles += mesh->faces.data[f].num_indices - 2;
    }
    uint32_t channels = 0;
    for (size_t d = 0; d < mesh->blend_deformers.count; d++) channels += (uint32_t)mesh->blend_deformers.data[d]->channels.count;
    sizes[0] = (uint32_t)mesh->vertices.count;
    sizes[1] = triangles;
    sizes[2] = holes;
    sizes[3] = small;
    sizes[4] = (uint32_t)mesh->skin_deformers.count;
    sizes[5] = channels;
    return 1;
}

int msf_fbx_mesh_fill(const msf_fbx *h, uint32_t m, double *positions, uint32_t points, uint32_t *tri_points, uint32_t triangles) {
    const ufbx_mesh *mesh = mesh_at(h, m);
    uint32_t sizes[6];
    if (!mesh || !positions || !tri_points || !msf_fbx_mesh_sizes(h, m, sizes)) return 0;
    if (points != sizes[0] || triangles != sizes[1]) return 0;
    for (size_t v = 0; v < mesh->vertices.count; v++) {
        positions[3 * v + 0] = mesh->vertices.data[v].x;
        positions[3 * v + 1] = mesh->vertices.data[v].y;
        positions[3 * v + 2] = mesh->vertices.data[v].z;
    }
    size_t scratch_count = mesh->max_face_triangles * 3;
    uint32_t *scratch = (uint32_t *)malloc(sizeof(uint32_t) * (scratch_count ? scratch_count : 1));
    if (!scratch) return 0;
    uint32_t written = 0;
    for (size_t f = 0; f < mesh->faces.count; f++) {
        if (!usable_face(mesh, f)) continue;
        uint32_t made = ufbx_triangulate_face(scratch, scratch_count, mesh, mesh->faces.data[f]);
        uint32_t expected = mesh->faces.data[f].num_indices - 2;
        for (uint32_t t = 0; t < expected; t++) {
            for (int k = 0; k < 3; k++) {
                /* A degenerate face may give fewer triangles; repeat its first corner so counts stay fixed. */
                uint32_t index = t < made ? scratch[3 * t + k] : mesh->faces.data[f].index_begin;
                tri_points[3 * written + k] = mesh->vertex_indices.data[index];
            }
            written++;
        }
    }
    free(scratch);
    return written == triangles;
}

void msf_fbx_close(msf_fbx *h) {
    if (!h) return;
    ufbx_free_scene(h->scene);
    free(h->shim_of_element);
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
    out->blend_channels = (uint32_t)s->blend_channels.count;
    out->materials = (uint32_t)s->materials.count;
    out->textures = (uint32_t)s->textures.count;
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

static const ufbx_skin_deformer *skin_at(const msf_fbx *h, uint32_t m, uint32_t d) {
    const ufbx_mesh *mesh = mesh_at(h, m);
    if (!mesh || d >= mesh->skin_deformers.count) return NULL;
    return mesh->skin_deformers.data[d];
}

int msf_fbx_skin_sizes(const msf_fbx *h, uint32_t m, uint32_t d, uint32_t sizes[2]) {
    const ufbx_skin_deformer *skin = skin_at(h, m, d);
    if (!skin || !sizes) return 0;
    sizes[0] = (uint32_t)skin->clusters.count;
    sizes[1] = (uint32_t)skin->weights.count;
    return 1;
}

int msf_fbx_skin_fill(const msf_fbx *h, uint32_t m, uint32_t d, uint32_t *vertex_offsets, uint32_t points,
                      uint32_t *cluster_of_entry, double *weights, uint32_t entries,
                      int32_t *cluster_node, double *geometry_to_bone, uint32_t clusters, int *skinning_method) {
    const ufbx_skin_deformer *skin = skin_at(h, m, d);
    const ufbx_mesh *mesh = mesh_at(h, m);
    if (!skin || !vertex_offsets || !cluster_of_entry || !weights || !cluster_node || !geometry_to_bone || !skinning_method) return 0;
    if (points != mesh->vertices.count || entries != skin->weights.count || clusters != skin->clusters.count) return 0;
    uint32_t written = 0;
    for (uint32_t v = 0; v < points; v++) {
        vertex_offsets[v] = written;
        if (v >= skin->vertices.count) continue;
        const ufbx_skin_vertex sv = skin->vertices.data[v];
        for (uint32_t k = 0; k < sv.num_weights; k++) {
            uint32_t at = sv.weight_begin + k;
            if (at >= skin->weights.count || written >= entries) return 0;
            cluster_of_entry[written] = skin->weights.data[at].cluster_index;
            weights[written] = skin->weights.data[at].weight;
            written++;
        }
    }
    vertex_offsets[points] = written;
    for (uint32_t c = 0; c < clusters; c++) {
        const ufbx_skin_cluster *cluster = skin->clusters.data[c];
        cluster_node[c] = shim_index(h, cluster->bone_node);
        matrix16(&cluster->geometry_to_bone, geometry_to_bone + 16 * c);
    }
    *skinning_method = (int)skin->skinning_method;
    return written == entries;
}

static const ufbx_blend_channel *channel_at(const msf_fbx *h, uint32_t m, uint32_t c, uint32_t *deformer_index,
                                            const ufbx_blend_deformer **deformer) {
    const ufbx_mesh *mesh = mesh_at(h, m);
    if (!mesh) return NULL;
    uint32_t seen = 0;
    for (size_t d = 0; d < mesh->blend_deformers.count; d++) {
        const ufbx_blend_deformer *blend = mesh->blend_deformers.data[d];
        if (c < seen + blend->channels.count) {
            if (deformer_index) *deformer_index = (uint32_t)d;
            if (deformer) *deformer = blend;
            return blend->channels.data[c - seen];
        }
        seen += (uint32_t)blend->channels.count;
    }
    return NULL;
}

int msf_fbx_blend_sizes(const msf_fbx *h, uint32_t m, uint32_t c, uint32_t sizes[2]) {
    const ufbx_blend_channel *channel = channel_at(h, m, c, NULL, NULL);
    if (!channel || !sizes) return 0;
    uint32_t total = 0;
    for (size_t k = 0; k < channel->keyframes.count; k++) {
        const ufbx_blend_shape *shape = channel->keyframes.data[k].shape;
        total += shape ? (uint32_t)shape->num_offsets : 0;
    }
    sizes[0] = (uint32_t)channel->keyframes.count;
    sizes[1] = total;
    return 1;
}

int msf_fbx_blend_fill(const msf_fbx *h, uint32_t m, uint32_t c, uint32_t *deformer, uint32_t *key_counts,
                       uint32_t *indices, double *offsets, double *target_weights, uint32_t keyframes, uint32_t total,
                       double *weight, const char **names, size_t *name_lengths) {
    const ufbx_blend_deformer *blend = NULL;
    const ufbx_blend_channel *channel = channel_at(h, m, c, deformer, &blend);
    uint32_t sizes[2];
    if (!channel || !key_counts || !indices || !offsets || !target_weights || !weight || !names || !name_lengths) return 0;
    if (!msf_fbx_blend_sizes(h, m, c, sizes) || sizes[0] != keyframes || sizes[1] != total) return 0;
    uint32_t written = 0;
    for (uint32_t k = 0; k < keyframes; k++) {
        const ufbx_blend_keyframe key = channel->keyframes.data[k];
        uint32_t count = key.shape ? (uint32_t)key.shape->num_offsets : 0;
        key_counts[k] = count;
        target_weights[k] = key.target_weight;
        for (uint32_t i = 0; i < count; i++) {
            indices[written] = key.shape->offset_vertices.data[i];
            offsets[3 * written + 0] = key.shape->position_offsets.data[i].x;
            offsets[3 * written + 1] = key.shape->position_offsets.data[i].y;
            offsets[3 * written + 2] = key.shape->position_offsets.data[i].z;
            written++;
        }
    }
    *weight = channel->weight;
    names[0] = blend->name.data;
    name_lengths[0] = blend->name.length;
    names[1] = channel->name.data;
    name_lengths[1] = channel->name.length;
    return written == total;
}

int msf_fbx_stack_get(const msf_fbx *h, uint32_t s, msf_fbx_stack *out) {
    if (!h || !out || s >= h->scene->anim_stacks.count) return 0;
    const ufbx_anim_stack *stack = h->scene->anim_stacks.data[s];
    out->name = stack->name.data;
    out->name_len = stack->name.length;
    out->time_begin = stack->time_begin;
    out->time_end = stack->time_end;
    return 1;
}

int msf_fbx_blend_channel_id(const msf_fbx *h, uint32_t m, uint32_t c, uint32_t *id) {
    const ufbx_blend_channel *channel = channel_at(h, m, c, NULL, NULL);
    if (!channel || !id) return 0;
    *id = channel->typed_id;
    return 1;
}

int msf_fbx_evaluate(const msf_fbx *h, uint32_t s, double time, double *to_parent, double *to_world, uint32_t nodes,
                     double *channel_weights, uint32_t channels, char *err, size_t n) {
    if (!h || !to_parent || (channels && !channel_weights) || s >= h->scene->anim_stacks.count) {
        set_error(err, n, "msf_fbx_evaluate: bad argument");
        return 0;
    }
    if (nodes != h->scene->nodes.count - 1 || channels != h->scene->blend_channels.count) {
        set_error(err, n, "msf_fbx_evaluate: counts do not match the scene");
        return 0;
    }
    ufbx_evaluate_opts opts;
    memset(&opts, 0, sizeof(opts));
    opts.temp_allocator.memory_limit = h->limits.memory_limit;
    opts.temp_allocator.allocation_limit = h->limits.allocation_limit;
    opts.result_allocator.memory_limit = h->limits.memory_limit;
    opts.result_allocator.allocation_limit = h->limits.allocation_limit;
    ufbx_error error;
    ufbx_scene *state = ufbx_evaluate_scene(h->scene, h->scene->anim_stacks.data[s]->anim, time, &opts, &error);
    if (!state) {
        char text[1024];
        ufbx_format_error(text, sizeof(text), &error);
        set_error(err, n, text);
        return 0;
    }
    uint32_t written = 0;
    for (size_t k = 0; k < state->nodes.count; k++) {
        const ufbx_node *node = state->nodes.data[k];
        if (node->is_root) continue;
        matrix16(&node->node_to_parent, to_parent + 16 * written);
        if (to_world) matrix16(&node->node_to_world, to_world + 16 * written);
        written++;
    }
    for (uint32_t c = 0; c < channels; c++) channel_weights[c] = state->blend_channels.data[c]->weight;
    ufbx_free_scene(state);
    return written == nodes;
}

int msf_fbx_skinned_points(const msf_fbx *h, int32_t s, double time, uint32_t m, double *world, uint32_t points,
                           char *err, size_t n) {
    if (!h || !world || m >= h->scene->meshes.count || (s >= 0 && (size_t)s >= h->scene->anim_stacks.count)) {
        set_error(err, n, "msf_fbx_skinned_points: bad argument");
        return 0;
    }
    ufbx_evaluate_opts opts;
    memset(&opts, 0, sizeof(opts));
    opts.evaluate_skinning = true;
    ufbx_error error;
    const ufbx_anim *anim = s >= 0 ? h->scene->anim_stacks.data[s]->anim : h->scene->anim;
    ufbx_scene *state = ufbx_evaluate_scene(h->scene, anim, time, &opts, &error);
    if (!state) {
        char text[1024];
        ufbx_format_error(text, sizeof(text), &error);
        set_error(err, n, text);
        return 0;
    }
    const ufbx_mesh *mesh = state->meshes.data[m];
    int ok = points == mesh->num_vertices && mesh->skinned_position.values.count >= points && mesh->instances.count > 0;
    if (ok) {
        const ufbx_node *node = mesh->instances.data[0];
        for (uint32_t v = 0; v < points; v++) {
            ufbx_vec3 p = mesh->skinned_position.values.data[v];
            if (mesh->skinned_is_local) p = ufbx_transform_position(&node->geometry_to_world, p);
            world[3 * v + 0] = p.x;
            world[3 * v + 1] = p.y;
            world[3 * v + 2] = p.z;
        }
    } else {
        set_error(err, n, "msf_fbx_skinned_points: mesh has no skinned positions for every point");
    }
    ufbx_free_scene(state);
    return ok;
}
