// SPDX-License-Identifier: MIT
// abi3 builds (Python 3.12+) compile under Py_LIMITED_API, which lacks CPython's
// unchecked access macros. There they become the limited API's functions, with
// the same reference semantics; PyTuple_SetItem additionally needs the tuple to
// be unshared, which holds for the fresh tuples the bindings fill.
#pragma once
#include <nanobind/nanobind.h>

#ifdef Py_LIMITED_API
#define PyTuple_GET_ITEM PyTuple_GetItem
#define PyTuple_SET_ITEM PyTuple_SetItem
#define PyTuple_GET_SIZE PyTuple_Size
#define PyList_GET_ITEM PyList_GetItem
#define PyList_SET_ITEM PyList_SetItem
#define PyList_GET_SIZE PyList_Size
#define PyFloat_AS_DOUBLE PyFloat_AsDouble
#define PyDict_GET_SIZE PyDict_Size
#define PyBytes_GET_SIZE PyBytes_Size
#define PyBytes_AS_STRING PyBytes_AsString
#endif
