// SPDX-License-Identifier: MIT
#include "msf/common.hpp"
#include "msf/expression.hpp"
#include "msf/skeletal.hpp"
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>
namespace py=pybind11;
template<class T>T checked(msf::Result<T> r) {
  if(!r)throw py::value_error(r.errors[0].code+": "+r.errors[0].message);
  return std::move(r.value);
}
PYBIND11_MODULE(_msf_native,m) {
  m.doc()="Value-owned numerical pilot; asset APIs and evidence compilation remain in Python.";
  m.def("identity",&msf::identity);
  m.def("multiply",&msf::multiply);
  m.def("inverse",[](const msf::Mat4& a){return checked(msf::inverse(a));});
  m.def("transform_point",[](const msf::Mat4& a,const msf::Vec3& p){return checked(msf::transform_point(a,p));});
  m.def("compose_trs",[](const msf::Vec3& t,const msf::Quat& r,const msf::Vec3& s){return checked(msf::compose_trs(t,r,s));});
  m.def("reparent_local",[](const msf::Mat4& p,const msf::Mat4& c){return checked(msf::reparent_local(p,c));});
  m.def("slerp",[](const msf::Quat& a,const msf::Quat& b,double t){return checked(msf::slerp(a,b,t));});
  m.def("hermite",[](const std::vector<double>& p0,const std::vector<double>& o0,const std::vector<double>& p1,const std::vector<double>& i1,double t,double dt,bool q){return checked(msf::hermite(p0,o0,p1,i1,t,dt,q));},py::arg("p0"),py::arg("out0"),py::arg("p1"),py::arg("in1"),py::arg("fraction"),py::arg("duration"),py::arg("quaternion")=false);
  m.def("morph_positions",[](const std::vector<msf::Vec3>& b,const std::vector<std::vector<msf::Vec3>>& d,const std::vector<double>& w){return checked(msf::morph_positions(b,d,w));});
  m.def("skin_positions",[](const std::vector<msf::Vec3>& positions,const std::vector<std::array<std::size_t,4>>& joints,const std::vector<std::array<double,4>>& weights,const msf::Mat4& world,const std::vector<msf::Mat4>& jw,const std::vector<msf::Mat4>& ibm){
    if(positions.size()!=joints.size()||positions.size()!=weights.size())throw py::value_error("shape: Vertex arrays must match");
    std::vector<msf::SkinVertex> vertices;
    for(std::size_t i=0;i<positions.size();++i)vertices.push_back({positions[i],joints[i],weights[i]});
    return checked(msf::skin_positions(vertices,world,jw,ibm));
  });
  py::class_<msf::Domain>(m,"Domain").def(py::init<>()).def_readwrite("minimum",&msf::Domain::minimum).def_readwrite("maximum",&msf::Domain::maximum);
  py::enum_<msf::Operator>(m,"Operator").value("identity",msf::Operator::identity).value("affine",msf::Operator::affine).value("weighted_sum",msf::Operator::weighted_sum);
  py::class_<msf::Instruction>(m,"Instruction").def(py::init<>()).def_readwrite("inputs",&msf::Instruction::inputs).def_readwrite("output",&msf::Instruction::output).def_readwrite("operation",&msf::Instruction::operation).def_readwrite("scale",&msf::Instruction::scale).def_readwrite("offset",&msf::Instruction::offset).def_readwrite("weights",&msf::Instruction::weights);
  py::class_<msf::ScalarProgram>(m,"ScalarProgram").def(py::init<>()).def_readwrite("domains",&msf::ScalarProgram::domains).def_readwrite("instructions",&msf::ScalarProgram::instructions);
  m.def("evaluate_scalars",[](const msf::ScalarProgram& p,const std::vector<double>& v,const std::vector<bool>& valid){return checked(msf::evaluate_scalars(p,v,valid));});
}
