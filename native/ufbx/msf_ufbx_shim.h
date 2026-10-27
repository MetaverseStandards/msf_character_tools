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

int msf_fbx_open(const uint8_t *data, size_t len, const msf_fbx_limits *limits, msf_fbx **out, char *err, size_t n);
void msf_fbx_close(msf_fbx *h);
int msf_fbx_info_get(const msf_fbx *h, msf_fbx_info *out);
#endif
