/* SPDX-License-Identifier: MIT */
/* Flat-array access to a ufbx scene for msf-tools. Every function checks its
   indices and returns 0 with an error string instead of aborting. Pointers it
   hands out stay valid until msf_fbx_close. */
#ifndef MSF_UFBX_SHIM_H
#define MSF_UFBX_SHIM_H
#include <stddef.h>
#include <stdint.h>

typedef struct msf_fbx msf_fbx;
typedef struct { size_t memory_limit, allocation_limit; } msf_fbx_limits;
typedef struct {
    uint32_t nodes, meshes, anim_stacks, helper_nodes;
    double unit_meters, fps;
    int ascii;
    uint32_t version;
    int axes_converted;
    uint32_t blend_channels; /* in the whole scene; see msf_fbx_blend_channel_id */
    uint32_t materials, textures;
} msf_fbx_info;

typedef struct {
    const char *name;
    size_t name_len;
    double time_begin, time_end; /* seconds */
} msf_fbx_stack;

typedef struct {
    int32_t parent;          /* shim node index, or -1 at the top level */
    const char *name;
    size_t name_len;
    int32_t mesh;            /* mesh index, or -1 */
    int is_bone;
    int helper;              /* 0 none, 1 geometry-transform helper, 2 scale helper */
    int inherit_mode;        /* ufbx_inherit_mode after compensation */
    int original_inherit_mode;
    int pivots;              /* nonzero when any pivot, offset or pre/post rotation is authored */
    const char *skipped;     /* name of an attribute msf does not convert (camera, light, curve, ...), or NULL */
    double to_parent[16];    /* column-major 4x4 */
    double to_world[16];
} msf_fbx_node;

/* Bumped whenever a declaration or struct below changes; msf_tools refuses a shim with another value. */
#define MSF_FBX_SHIM_ABI 2
int msf_fbx_shim_abi(void);
/* The compiled ufbx's ufbx_source_version: major * 1000000 + minor * 1000 + patch. */
uint32_t msf_fbx_ufbx_version(void);
int msf_fbx_open(const uint8_t *data, size_t len, const msf_fbx_limits *limits, msf_fbx **out, char *err, size_t n);
void msf_fbx_close(msf_fbx *h);
int msf_fbx_info_get(const msf_fbx *h, msf_fbx_info *out);
int msf_fbx_node_get(const msf_fbx *h, uint32_t i, msf_fbx_node *out);
/* sizes: points, triangles, hole faces, faces with fewer than 3 corners, skin deformers, blend channels,
   vertex cache deformers (their cache files are never read) */
int msf_fbx_mesh_sizes(const msf_fbx *h, uint32_t m, uint32_t sizes[7]);
/* Points as x,y,z; triangles ear-clipped by ufbx, as point indices. The counts must equal msf_fbx_mesh_sizes. */
int msf_fbx_mesh_fill(const msf_fbx *h, uint32_t m, double *positions, uint32_t points, uint32_t *tri_points, uint32_t triangles);
/* Skin deformer d of mesh m. sizes: clusters, weight entries. */
int msf_fbx_skin_sizes(const msf_fbx *h, uint32_t m, uint32_t d, uint32_t sizes[2]);
/* Weights of point v are entries vertex_offsets[v] .. vertex_offsets[v + 1] - 1, each naming a cluster.
   cluster_node is the shim node index of each cluster's bone (-1 if it has none); geometry_to_bone holds a
   column-major 4x4 per cluster; skinning_method is the ufbx_skinning_method. */
int msf_fbx_skin_fill(const msf_fbx *h, uint32_t m, uint32_t d, uint32_t *vertex_offsets, uint32_t points,
                      uint32_t *cluster_of_entry, double *weights, uint32_t entries,
                      int32_t *cluster_node, double *geometry_to_bone, uint32_t clusters, int *skinning_method);
/* Blend channel c of mesh m, counting channels across the mesh's blend deformers in order.
   sizes: keyframes, offsets summed over keyframes. */
int msf_fbx_blend_sizes(const msf_fbx *h, uint32_t m, uint32_t c, uint32_t sizes[2]);
/* Keyframe k has key_counts[k] (point index, x/y/z offset) entries, in keyframe order, and a target weight
   (1.0 is the full shape). weight is the channel's static weight (DeformPercent / 100). names[0] and names[1]
   are the deformer and channel names, with lengths in name_lengths. */
int msf_fbx_blend_fill(const msf_fbx *h, uint32_t m, uint32_t c, uint32_t *deformer, uint32_t *key_counts,
                       uint32_t *indices, double *offsets, double *target_weights, uint32_t keyframes, uint32_t total,
                       double *weight, const char **names, size_t *name_lengths);
int msf_fbx_stack_get(const msf_fbx *h, uint32_t s, msf_fbx_stack *out);
/* Scene-wide index of blend channel c of mesh m, used to read msf_fbx_evaluate's channel weights. */
int msf_fbx_blend_channel_id(const msf_fbx *h, uint32_t m, uint32_t c, uint32_t *id);
/* Evaluate animation stack s at `time` seconds. Writes every node's node-to-parent matrix (and node-to-world when
   to_world is not NULL), 16 doubles each in node order, and every blend channel's weight. */
int msf_fbx_evaluate(const msf_fbx *h, uint32_t s, double time, double *to_parent, double *to_world, uint32_t nodes,
                     double *channel_weights, uint32_t channels, char *err, size_t n);
/* For tests: ufbx's own skinned positions of mesh m in world space, evaluated with stack s at `time` seconds
   (s < 0 uses the scene's default animation). */
int msf_fbx_skinned_points(const msf_fbx *h, int32_t s, double time, uint32_t m, double *world, uint32_t points,
                           char *err, size_t n);
#endif
