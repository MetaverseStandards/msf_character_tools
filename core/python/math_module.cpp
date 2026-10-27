// SPDX-License-Identifier: MIT
// msf_tools.math3d's functions over Python values: the readers below check
// inputs exactly as the 0.3.0 module did (_number, _vector, _matrix), in its
// order, before the C++ maths runs.
#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

#include <string>
#include <vector>

#include "msf/diagnostics.hpp"
#include "msf/math3d.hpp"

namespace nb = nanobind;
namespace m3 = msf::math3d;
using msf::Code;

namespace {

double read_number(PyObject* value, const std::string& ref) {
    double result;
    if (PyFloat_CheckExact(value)) {
        result = PyFloat_AS_DOUBLE(value);
    } else if (PyLong_CheckExact(value)) {
        result = PyLong_AsDouble(value);
        if (result == -1.0 && PyErr_Occurred()) {
            PyErr_Clear();
            msf::fail(Code::E_NONFINITE, ref, "Value is not representable in binary64.");
        }
    } else {
        msf::fail(Code::E_TYPE, ref, "Expected an integer or float; booleans are not numeric.");
    }
    return m3::finite(result, ref);
}

bool is_sequence(PyObject* o) { return PyList_Check(o) || PyTuple_Check(o); }

Py_ssize_t length(PyObject* o) {
    Py_ssize_t n = PyObject_Length(o);
    if (n < 0) throw nb::python_error();
    return n;
}

// Every item, as iteration yields them (a subclass may override either).
std::vector<nb::object> items(PyObject* o) {
    std::vector<nb::object> out;
    nb::object it = nb::steal(PyObject_GetIter(o));
    if (!it.is_valid()) throw nb::python_error();
    while (PyObject* item = PyIter_Next(it.ptr())) out.push_back(nb::steal(item));
    if (PyErr_Occurred()) throw nb::python_error();
    return out;
}

m3::Vec read_vector(PyObject* values, Py_ssize_t count, const std::string& ref) {
    if (!is_sequence(values) || length(values) != count)
        msf::fail(Code::E_SHAPE, ref, "Expected exactly " + std::to_string(count) + " numeric components.");
    m3::Vec out;
    for (const nb::object& x : items(values)) out.push_back(read_number(x.ptr(), ref));
    return out;
}

m3::Mat read_matrix(PyObject* rows, const std::string& ref) {
    if (!is_sequence(rows) || length(rows) != 4) msf::fail(Code::E_SHAPE, ref, "Expected four matrix rows.");
    std::vector<m3::Vec> read;
    for (const nb::object& row : items(rows)) read.push_back(read_vector(row.ptr(), 4, ref));
    if (read.size() != 4) msf::fail(Code::E_SHAPE, ref, "Expected four matrix rows.");
    m3::Mat m{};
    for (int r = 0; r < 4; ++r)
        for (int c = 0; c < 4; ++c) m[r][c] = read[r][c];
    return m;
}

// Python's float arithmetic operands, for the scalar helpers.
double operand(nb::handle value) {
    double result = PyFloat_AsDouble(value.ptr());
    if (result == -1.0 && PyErr_Occurred()) throw nb::python_error();
    return result;
}

nb::tuple tuple_of(const double* values, std::size_t n) {
    nb::object out = nb::steal(PyTuple_New(static_cast<Py_ssize_t>(n)));
    for (std::size_t i = 0; i < n; ++i) PyTuple_SET_ITEM(out.ptr(), static_cast<Py_ssize_t>(i), PyFloat_FromDouble(values[i]));
    return nb::borrow<nb::tuple>(out);
}

nb::tuple tuple_of(const m3::Vec& v) { return tuple_of(v.data(), v.size()); }

nb::tuple tuple_of(const m3::Mat& m) {
    return nb::make_tuple(tuple_of(m[0].data(), 4), tuple_of(m[1].data(), 4), tuple_of(m[2].data(), 4), tuple_of(m[3].data(), 4));
}

m3::Mat affine(nb::handle m, nb::handle tolerance, const std::string& ref) {
    m3::Mat matrix = read_matrix(m.ptr(), ref);
    double tol = read_number(tolerance.ptr(), ref);
    m3::check_affine(matrix, tol, ref);
    return matrix;
}

m3::Vec normalize(nb::handle q) { return m3::normalize(read_vector(q.ptr(), 4, "/rotation")); }

double fraction(nb::handle value) { return m3::fraction(read_number(value.ptr(), "/animations")); }

}  // namespace

void bind_math3d(nb::module_& m) {
    m.attr("IDENTITY") = tuple_of(m3::kIdentity);
    m.attr("UNIT_QUATERNION_TOLERANCE") = m3::kUnitQuaternionTolerance;
    m.def("_number", [](nb::handle value, const std::string& ref) { return read_number(value.ptr(), ref); });
    m.def("_finite", [](double value, const std::string& ref) { return m3::finite(value, ref); });
    m.def("_vector", [](nb::handle values, Py_ssize_t count, const std::string& ref) {
        return tuple_of(read_vector(values.ptr(), count, ref));
    });
    m.def("_matrix", [](nb::handle rows, const std::string& ref) { return tuple_of(read_matrix(rows.ptr(), ref)); },
          nb::arg("rows").none(), nb::arg("ref") = "/transforms");
    m.def("_add", [](nb::handle a, nb::handle b, const std::string& ref) { return m3::add(operand(a), operand(b), ref); });
    m.def("_sub", [](nb::handle a, nb::handle b, const std::string& ref) { return m3::sub(operand(a), operand(b), ref); });
    m.def("_product", [](nb::handle a, nb::handle b, const std::string& ref) { return m3::product(operand(a), operand(b), ref); });
    m.def("_divide", [](nb::handle a, nb::handle b, const std::string& ref) { return m3::divide(operand(a), operand(b), ref); });
    // Takes any iterable, generators included: each item is added as it is
    // produced, so a refusal inside the generator comes first, as in Python.
    m.def("_sum", [](nb::handle values, const std::string& ref) {
        double result = 0.0;
        nb::object it = nb::steal(PyObject_GetIter(values.ptr()));
        if (!it.is_valid()) throw nb::python_error();
        while (PyObject* item = PyIter_Next(it.ptr())) {
            nb::object owned = nb::steal(item);
            result = m3::add(result, operand(owned), ref);
        }
        if (PyErr_Occurred()) throw nb::python_error();
        return result;
    });
    m.def("_fraction", &fraction, nb::arg("value").none());
    m.def("matrix", [](nb::handle values) {
        m3::Vec v = read_vector(values.ptr(), 16, "/transforms");
        m3::Mat out{};
        for (int r = 0; r < 4; ++r)
            for (int c = 0; c < 4; ++c) out[r][c] = v[static_cast<std::size_t>(c * 4 + r)];
        return tuple_of(out);
    }, nb::arg("values").none());
    m.def("column_major", [](nb::handle rows) {
        m3::Mat matrix = read_matrix(rows.ptr(), "/transforms");
        nb::list out;
        for (int c = 0; c < 4; ++c)
            for (int r = 0; r < 4; ++r) out.append(matrix[r][c]);
        return out;
    }, nb::arg("m").none());
    m.def("multiply", [](nb::handle a, nb::handle b) {
        m3::Mat ma = read_matrix(a.ptr(), "/transforms");
        m3::Mat mb = read_matrix(b.ptr(), "/transforms");
        return tuple_of(m3::multiply(ma, mb));
    }, nb::arg("a").none(), nb::arg("b").none());
    m.def("inverse", [](nb::handle rows) { return tuple_of(m3::inverse(read_matrix(rows.ptr(), "/transforms"))); },
          nb::arg("m").none());
    m.def("affine", [](nb::handle rows, nb::handle tolerance, const std::string& ref) {
        return tuple_of(affine(rows, tolerance, ref));
    }, nb::arg("m").none(), nb::arg("tolerance").none() = 1e-7, nb::arg("ref") = "/transforms");
    m.def("transform", [](nb::handle rows, nb::handle point) {
        m3::Mat matrix = affine(rows, nb::float_(1e-7), "/transforms");
        m3::Vec p = read_vector(point.ptr(), 3, "/transforms");
        auto out = m3::transform(matrix, p.data());
        return tuple_of(out.data(), 3);
    }, nb::arg("m").none(), nb::arg("p").none());
    m.def("normalize", [](nb::handle q) { return tuple_of(normalize(q)); }, nb::arg("q").none());
    m.def("authored_quaternion", [](nb::handle q, const std::string& ref) {
        m3::Vec v = read_vector(q.ptr(), 4, ref);
        m3::check_authored_quaternion(v, ref);
        return tuple_of(v);
    }, nb::arg("q").none(), nb::arg("ref") = "/rotation");
    m.def("validate_trs", [](nb::handle rows, nb::handle affine_tolerance, nb::handle tolerance, const std::string& ref) {
        m3::Mat matrix = affine(rows, affine_tolerance, ref);
        double tol = read_number(tolerance.ptr(), ref);
        m3::check_trs(matrix, tol, ref);
        return tuple_of(matrix);
    }, nb::arg("m").none(), nb::kw_only(), nb::arg("affine_tolerance").none() = 1e-9, nb::arg("tolerance").none() = 1e-9,
          nb::arg("ref") = "/transforms");
    m.def("trs", [](nb::handle t, nb::handle q, nb::handle s) {
        m3::Vec tv = read_vector(t.ptr(), 3, "/transforms");
        m3::Vec sv = read_vector(s.ptr(), 3, "/transforms");
        m3::Vec qv = read_vector(q.ptr(), 4, "/rotation");
        return tuple_of(m3::trs(tv, qv, sv));
    }, nb::arg("t").none() = nb::make_tuple(0, 0, 0), nb::arg("q").none() = nb::make_tuple(0, 0, 0, 1),
          nb::arg("s").none() = nb::make_tuple(1, 1, 1));
    m.def("linear", [](nb::handle a, nb::handle b, nb::handle t) {
        if (!is_sequence(a.ptr()) || length(a.ptr()) == 0) msf::fail(Code::E_SHAPE, "/animations", "Curve components must be nonempty.");
        Py_ssize_t n = length(a.ptr());
        m3::Vec va = read_vector(a.ptr(), n, "/animations");
        m3::Vec vb = read_vector(b.ptr(), n, "/animations");
        return tuple_of(m3::linear(va, vb, fraction(t)));
    }, nb::arg("a").none(), nb::arg("b").none(), nb::arg("fraction").none());
    m.def("slerp", [](nb::handle a, nb::handle b, nb::handle t) {
        m3::Vec na = normalize(a);
        m3::Vec nb_ = normalize(b);
        return tuple_of(m3::slerp(na, nb_, fraction(t)));
    }, nb::arg("a").none(), nb::arg("b").none(), nb::arg("t").none());
    m.def("hermite", [](nb::handle p0, nb::handle out0, nb::handle p1, nb::handle in1, nb::handle t, nb::handle duration,
                        nb::handle quaternion) {
        const std::string ref = "/animations";
        if (quaternion.ptr() != Py_True && quaternion.ptr() != Py_False) msf::fail(Code::E_TYPE, ref, "Quaternion mode must be an exact bool.");
        bool q = quaternion.ptr() == Py_True;
        if (!is_sequence(p0.ptr()) || length(p0.ptr()) == 0 || (q && length(p0.ptr()) != 4))
            msf::fail(Code::E_SHAPE, ref, "Curve needs nonempty matching components (four for quaternion).");
        Py_ssize_t n = length(p0.ptr());
        m3::Vec a = read_vector(p0.ptr(), n, ref), b = read_vector(out0.ptr(), n, ref);
        m3::Vec c = read_vector(p1.ptr(), n, ref), d = read_vector(in1.ptr(), n, ref);
        double ft = fraction(t);
        double dt = read_number(duration.ptr(), ref);
        return tuple_of(m3::hermite(a, b, c, d, ft, dt, q));
    }, nb::arg("p0").none(), nb::arg("out0").none(), nb::arg("p1").none(), nb::arg("in1").none(), nb::arg("fraction").none(),
          nb::arg("duration").none(), nb::arg("quaternion").none() = false);
    // Test hooks for the exact algorithms.
    m.def("_hypot", [](std::vector<double> values) { return m3::hypot(values.data(), values.size()); });
    m.def("_fsum", [](std::vector<double> values) -> nb::object {
        m3::FsumOutcome r = m3::fsum(values.data(), values.size());
        if (r.status == m3::FsumOutcome::Status::overflow) {
            PyErr_SetString(PyExc_OverflowError, "intermediate overflow in fsum");
            throw nb::python_error();
        }
        if (r.status == m3::FsumOutcome::Status::inf_minus_inf) throw nb::value_error("-inf + inf in fsum");
        return nb::float_(r.value);
    });
}
