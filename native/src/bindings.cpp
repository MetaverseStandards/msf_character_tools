// SPDX-License-Identifier: MIT
#include "msf/common.hpp"
#include "msf/expression.hpp"
#include "msf/skeletal.hpp"
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
#include <cmath>

namespace py=pybind11;
namespace {
[[noreturn]] void refuse(const char* code, const char* message) {
  throw py::value_error(std::string(code)+": "+message);
}
template<class T> T checked(msf::Result<T> result) {
  if (!result) throw py::value_error(result.errors.front().code+": "+result.errors.front().message);
  return std::move(result.value);
}
double number(py::handle value) {
  if (!PyFloat_CheckExact(value.ptr()) && !PyLong_CheckExact(value.ptr()))
    refuse("type", "Expected an exact int or float; bool is not numeric");
  const double result=PyFloat_CheckExact(value.ptr()) ? PyFloat_AS_DOUBLE(value.ptr()) : PyLong_AsDouble(value.ptr());
  if (PyErr_Occurred()) { PyErr_Clear(); refuse("nonfinite", "Integer is not representable in binary64"); }
  if (!std::isfinite(result)) refuse("nonfinite", "Numeric input must be finite binary64");
  return result;
}
std::size_t read_index(py::handle value) {
  if (!PyLong_CheckExact(value.ptr())) refuse("binding", "Index must be an exact nonnegative int");
  const auto result=PyLong_AsSize_t(value.ptr());
  if (PyErr_Occurred()) { PyErr_Clear(); refuse("binding", "Index must be representable as size_t"); }
  return result;
}
bool boolean(py::handle value) {
  if (!PyBool_Check(value.ptr())) refuse("type", "Validity and quaternion mode require exact bool");
  return value.ptr()==Py_True;
}
py::sequence sequence(py::handle value) {
  if (!PyList_Check(value.ptr()) && !PyTuple_Check(value.ptr())) refuse("shape", "Expected a list or tuple");
  return py::reinterpret_borrow<py::sequence>(value);
}
template<class F> auto vector(py::handle value, F parse) {
  using T=decltype(parse(value));
  auto seq=sequence(value);
  std::vector<T> result; result.reserve(seq.size());
  for (auto item : seq) result.push_back(parse(item));
  return result;
}
template<std::size_t N, class F> auto array(py::handle value, F parse) {
  using T=decltype(parse(value));
  auto seq=sequence(value);
  if (seq.size()!=N) refuse("shape", "Incorrect component count");
  std::array<T,N> result{};
  for (std::size_t i=0; i<N; ++i) result[i]=parse(seq[i]);
  return result;
}
msf::Mat4 matrix(py::handle value) { return array<16>(value,number); }
msf::Vec3 point(py::handle value) { return array<3>(value,number); }
msf::Quat quaternion(py::handle value) { return array<4>(value,number); }
std::optional<double> bound(py::handle value) {
  return value.is_none() ? std::nullopt : std::optional<double>(number(value));
}
template<class T> T instance(py::handle value) {
  if (!py::isinstance<T>(value)) refuse("type", "Incorrect numerical program member type");
  return py::cast<T>(value);
}
msf::Mat4 transpose_storage(const msf::Mat4& values) {
  msf::Mat4 result{};
  for (int r=0; r<4; ++r) for (int c=0; c<4; ++c) result[r*4+c]=values[c*4+r];
  return result;
}
}
PYBIND11_MODULE(_msf_native,m) {
  m.doc()="Strict numerical pilot; asset APIs and evidence compilation remain in Python.";
  m.def("identity",&msf::identity);
  m.def("from_gltf_column_major",[](py::handle values) { return transpose_storage(matrix(values)); });
  m.def("to_gltf_column_major",[](py::handle values) { return transpose_storage(matrix(values)); });
  m.def("multiply",[](py::handle a,py::handle b) {
    const auto left=matrix(a); const auto right=matrix(b); return checked(msf::multiply(left,right));
  });
  m.def("inverse",[](py::handle a) { return checked(msf::inverse(matrix(a))); });
  m.def("transform_point",[](py::handle a,py::handle p) {
    const auto transform=matrix(a); const auto position=point(p); return checked(msf::transform_point(transform,position));
  });
  m.def("compose_trs",[](py::handle t,py::handle r,py::handle s) {
    const auto translation=point(t); const auto rotation=quaternion(r); const auto scale=point(s);
    return checked(msf::compose_trs(translation,rotation,scale));
  });
  m.def("reparent_local",[](py::handle p,py::handle c) {
    const auto parent=matrix(p); const auto child=matrix(c); return checked(msf::reparent_local(parent,child));
  });
  m.def("slerp",[](py::handle a,py::handle b,py::handle t) {
    const auto left=quaternion(a); const auto right=quaternion(b); const double fraction=number(t);
    return checked(msf::slerp(left,right,fraction));
  });
  m.def("hermite",[](py::handle p0,py::handle o0,py::handle p1,py::handle i1,py::handle t,py::handle dt,py::handle q) {
    const auto start=vector(p0,number); const auto out=vector(o0,number);
    const auto end=vector(p1,number); const auto in=vector(i1,number);
    const double fraction=number(t); const double duration=number(dt); const bool mode=boolean(q);
    return checked(msf::hermite(start,out,end,in,fraction,duration,mode));
  },py::arg("p0"),py::arg("out0"),py::arg("p1"),py::arg("in1"),py::arg("fraction"),py::arg("duration"),py::arg("quaternion")=false);
  m.def("morph_positions",[](py::handle b,py::handle d,py::handle w) {
    const auto basis=vector(b,point);
    const auto deltas=vector(d,[](py::handle target) { return vector(target,point); });
    const auto weights=vector(w,number); return checked(msf::morph_positions(basis,deltas,weights));
  });
  m.def("skin_positions",[](py::handle p,py::handle j,py::handle w,py::handle m,py::handle jw,py::handle ibm) {
    const auto positions=vector(p,point);
    const auto joints=vector(j,[](py::handle row) { return array<4>(row,read_index); });
    const auto weights=vector(w,[](py::handle row) { return array<4>(row,number); });
    const auto world=matrix(m); const auto worlds=vector(jw,matrix); const auto binds=vector(ibm,matrix);
    if (positions.size()!=joints.size() || positions.size()!=weights.size()) refuse("shape", "Vertex arrays must match");
    std::vector<msf::SkinVertex> vertices; vertices.reserve(positions.size());
    for (std::size_t i=0; i<positions.size(); ++i) vertices.push_back({positions[i],joints[i],weights[i]});
    return checked(msf::skin_positions(vertices,world,worlds,binds));
  });
  py::class_<msf::Domain>(m,"Domain").def(py::init<>())
    .def_property("minimum",[](const msf::Domain& d) { return d.minimum; },
      [](msf::Domain& d,py::handle v) { d.minimum=bound(v); })
    .def_property("maximum",[](const msf::Domain& d) { return d.maximum; },
      [](msf::Domain& d,py::handle v) { d.maximum=bound(v); });
  py::enum_<msf::Operator>(m,"Operator").value("identity",msf::Operator::identity)
    .value("affine",msf::Operator::affine).value("weighted_sum",msf::Operator::weighted_sum);
  py::class_<msf::Instruction>(m,"Instruction").def(py::init<>())
    .def_property("inputs",[](const msf::Instruction& i) { return i.inputs; },
      [](msf::Instruction& i,py::handle v) { i.inputs=vector(v,read_index); })
    .def_property("output",[](const msf::Instruction& i) { return i.output; },
      [](msf::Instruction& i,py::handle v) { i.output=read_index(v); })
    .def_property("operation",[](const msf::Instruction& i) { return i.operation; },
      [](msf::Instruction& i,py::handle v) {
        if (!py::isinstance<msf::Operator>(v)) refuse("operator", "Expected an Operator member");
        i.operation=py::cast<msf::Operator>(v);
      })
    .def_property("scale",[](const msf::Instruction& i) { return i.scale; },
      [](msf::Instruction& i,py::handle v) { i.scale=number(v); })
    .def_property("offset",[](const msf::Instruction& i) { return i.offset; },
      [](msf::Instruction& i,py::handle v) { i.offset=number(v); })
    .def_property("weights",[](const msf::Instruction& i) { return i.weights; },
      [](msf::Instruction& i,py::handle v) { i.weights=vector(v,number); });
  py::class_<msf::ScalarProgram>(m,"ScalarProgram").def(py::init<>())
    .def_property("domains",[](const msf::ScalarProgram& p) { return p.domains; },
      [](msf::ScalarProgram& p,py::handle v) { p.domains=vector(v,instance<msf::Domain>); },py::return_value_policy::copy)
    .def_property("instructions",[](const msf::ScalarProgram& p) { return p.instructions; },
      [](msf::ScalarProgram& p,py::handle v) { p.instructions=vector(v,instance<msf::Instruction>); },py::return_value_policy::copy);
  m.def("evaluate_scalars",[](py::handle p,py::handle v,py::handle valid) {
    const auto program=instance<msf::ScalarProgram>(p); const auto values=vector(v,number);
    const auto validity=vector(valid,boolean); return checked(msf::evaluate_scalars(program,values,validity));
  });
}
