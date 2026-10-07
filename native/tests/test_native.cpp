// SPDX-License-Identifier: MIT
#include "msf/common.hpp"
#include "msf/expression.hpp"
#include "msf/skeletal.hpp"
#include <cmath>
#include <iostream>
#include <limits>
#include <stdexcept>
using namespace msf;
void require(bool b,const char* msg){if(!b)throw std::runtime_error(msg);}
void near(double a,double b){require(std::abs(a-b)<1e-9,"Numerical mismatch");}
int main(){try {
  auto parent=compose_trs({10,0,0},{0,0,0,1},{1,1,1}).value;
  auto child=compose_trs({15,0,0},{0,0,0,1},{1,1,1}).value;
  auto local=reparent_local(parent,child);require(bool(local),"Reparent failed");near(local.value[3],5);
  near(multiply(parent,local.value)[3],15);
  auto scale=compose_trs({0,0,0},{0,0,0,1},{2,1,1}).value;
  auto rotate=compose_trs({0,0,0},{0,0,std::sqrt(.5),std::sqrt(.5)},{1,1,1}).value;
  auto p=transform_point(multiply(rotate,scale),{1,0,0});require(bool(p),"Point failed");near(p.value[0],0);near(p.value[1],2);
  auto shear=identity();shear[1]=.25;require(!validate_trs(shear),"Shear accepted");
  auto zero=identity();zero[0]=0;require(!inverse(zero),"Singular accepted");
  auto q=slerp({0,0,0,1},{0,0,0,-1},.5);require(bool(q),"Antipodal slerp failed");near(q.value[3],1);
  auto curve=hermite({0},{2},{0},{0},.5,2);require(bool(curve),"Curve failed");near(curve.value[0],.5);
  auto morph=morph_positions({{1,0,0}},{{{0,1,0}}},{2});require(bool(morph),"Morph failed");near(morph.value[0][1],2);
  auto signed_morph=morph_positions({{1,0,0}},{{{0,1,0}}},{-.5});near(signed_morph.value[0][1],-.5);
  auto mesh=compose_trs({1,0,0},{0,0,0,1},{1,1,1}).value;
  SkinVertex v{morph.value[0],{0,0,0,0},{1,0,0,0}};
  auto skinned=skin_positions({v},mesh,{rotate},{identity()});require(bool(skinned),"Skin failed");near(skinned.value[0][0],-3);near(skinned.value[0][1],1);
  ScalarProgram program;program.domains={{{0},{1}},{{0},{1}},{{0},{1}}};
  program.instructions={{{0,1},2,Operator::weighted_sum,1,0,{.5,.5}}};
  auto eval=evaluate_scalars(program,{1,0,0},{true,true,false});require(bool(eval),"Scalar failed");near(eval.value[2],.5);
  require(!evaluate_scalars(program,{1,0,0},{false,true,false}),"Invalid tracking accepted");
  program.instructions[0].weights={2,2};require(!evaluate_scalars(program,{1,0,0},{true,true,false}),"Domain loss accepted");
  program.instructions[0].operation=static_cast<Operator>(99);require(!evaluate_scalars(program,{1,0,0},{true,true,false}),"Unknown operator accepted");
  program.instructions={{{1},0,Operator::identity,1,0,{}},{{0},1,Operator::identity,1,0,{}}};
  require(!evaluate_scalars(program,{1,0,0},{true,true,true}),"Cyclic instructions accepted");
  require(!morph_positions({{1,0,0}},{{{0,1,0}}},{std::numeric_limits<double>::infinity()}),"Nonfinite accepted");
  std::cout<<"native analytical tests passed\n";return 0;
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
