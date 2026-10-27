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
} msf_fbx_info;

typedef struct {
    int32_t parent;          /* shim node index, or -1 at the top level */
    const char *name;
    size_t name_len;
    int32_t mesh;            /* mesh index, or -1 */
    int is_bone;
    int helper;              /* 0 none, 1 geometry-transform helper, 2 scale helper */
    int inherit_mode;        /* ufbx_inherit_mode after compensation */
    int original_inherit_mode;
    double to_parent[16];    /* column-major 4x4 */
    double to_world[16];
} msf_fbx_node;

int msf_fbx_open(const uint8_t *data, size_t len, const msf_fbx_limits *limits, msf_fbx **out, char *err, size_t n);
void msf_fbx_close(msf_fbx *h);
int msf_fbx_info_get(const msf_fbx *h, msf_fbx_info *out);
int msf_fbx_node_get(const msf_fbx *h, uint32_t i, msf_fbx_node *out);
/* sizes: points, triangles, hole faces, faces with fewer than 3 corners, skin deformers, blend channels */
int msf_fbx_mesh_sizes(const msf_fbx *h, uint32_t m, uint32_t sizes[6]);
/* Points as x,y,z; triangles ear-clipped by ufbx, as point indices. The counts must equal msf_fbx_mesh_sizes. */
int msf_fbx_mesh_fill(const msf_fbx *h, uint32_t m, double *positions, uint32_t points, uint32_t *tri_points, uint32_t triangles);
#endif
