// SPDX-License-Identifier: MIT
#include "msf/common.hpp"
#include <algorithm>
#include <cmath>
#include <limits>

namespace msf {
namespace {
template<class T> bool all_finite(const T& x) {
  return std::all_of(x.begin(), x.end(), [](double v){return std::isfinite(v);});
}
template<class T> Result<T> error(const char* code, const char* message) {
  Result<T> r; r.errors.push_back({code, message}); return r;
}
}
bool finite(const Mat4& m) { return all_finite(m); }
Mat4 identity() { return {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1}; }
Mat4 multiply(const Mat4& a, const Mat4& b) {
  Mat4 c{};
  for (int i=0;i<4;++i) for (int j=0;j<4;++j)
    for (int k=0;k<4;++k) c[i*4+j]+=a[i*4+k]*b[k*4+j];
  return c;
}
Result<Mat4> inverse(const Mat4& a) {
  if (!finite(a)) return error<Mat4>("nonfinite", "Matrix must be finite");
  double aug[4][8]{};
  for (int i=0;i<4;++i) for (int j=0;j<4;++j) {
    aug[i][j]=a[i*4+j]; aug[i][j+4]=(i==j);
  }
  for (int col=0;col<4;++col) {
    int pivot=col;
    for (int row=col+1;row<4;++row)
      if (std::abs(aug[row][col])>std::abs(aug[pivot][col])) pivot=row;
    if (aug[pivot][col]==0) return error<Mat4>("singular", "Matrix has no inverse");
    if (pivot!=col) for (int j=0;j<8;++j) std::swap(aug[pivot][j],aug[col][j]);
    const double divisor=aug[col][col];
    for (int j=0;j<8;++j) aug[col][j]/=divisor;
    for (int row=0;row<4;++row) if (row!=col) {
      const double factor=aug[row][col];
      for (int j=0;j<8;++j) aug[row][j]-=factor*aug[col][j];
    }
  }
  Result<Mat4> result;
  for (int i=0;i<4;++i) for (int j=0;j<4;++j) result.value[i*4+j]=aug[i][j+4];
  if (!finite(result.value)) return error<Mat4>("nonfinite", "Inverse overflowed");
  return result;
}
Result<Vec3> transform_point(const Mat4& m, const Vec3& p) {
  if (!finite(m)||!all_finite(p)) return error<Vec3>("nonfinite", "Point and matrix must be finite");
  double out[4]{};
  for (int i=0;i<4;++i) out[i]=m[i*4]*p[0]+m[i*4+1]*p[1]+m[i*4+2]*p[2]+m[i*4+3];
  if (!std::isfinite(out[3])||std::abs(out[3]-1)>1e-10)
    return error<Vec3>("nonaffine", "Position transform requires affine matrix");
  Result<Vec3> result; result.value={out[0],out[1],out[2]};
  if (!all_finite(result.value)) return error<Vec3>("nonfinite", "Transform overflowed");
  return result;
}
Result<Quat> normalize(const Quat& q) {
  if (!all_finite(q)) return error<Quat>("nonfinite", "Quaternion must be finite");
  const double norm=std::hypot(std::hypot(q[0],q[1]),std::hypot(q[2],q[3]));
  if (norm==0||!std::isfinite(norm)) return error<Quat>("quaternion", "Quaternion norm must be nonzero and finite");
  Result<Quat> result; for (int i=0;i<4;++i) result.value[i]=q[i]/norm; return result;
}
Result<Mat4> compose_trs(const Vec3& t, const Quat& q, const Vec3& s) {
  if (!all_finite(t)||!all_finite(s)) return error<Mat4>("nonfinite", "TRS must be finite");
  auto n=normalize(q); if (!n) return {{},n.errors};
  const auto [x,y,z,w]=n.value;
  Result<Mat4> r; r.value={
    (1-2*(y*y+z*z))*s[0], 2*(x*y-z*w)*s[1], 2*(x*z+y*w)*s[2], t[0],
    2*(x*y+z*w)*s[0], (1-2*(x*x+z*z))*s[1], 2*(y*z-x*w)*s[2], t[1],
    2*(x*z-y*w)*s[0], 2*(y*z+x*w)*s[1], (1-2*(x*x+y*y))*s[2], t[2],
    0,0,0,1};
  if (!finite(r.value)) return error<Mat4>("nonfinite", "TRS overflowed");
  return r;
}
Result<bool> validate_trs(const Mat4& m, double tolerance) {
  if (!finite(m)||!std::isfinite(tolerance)||tolerance<=0)
    return error<bool>("nonfinite", "Invalid matrix/tolerance");
  if (std::abs(m[12])>tolerance||std::abs(m[13])>tolerance||std::abs(m[14])>tolerance||std::abs(m[15]-1)>tolerance)
    return error<bool>("nonaffine", "Matrix must be affine");
  double lengths[3]{};
  for (int j=0;j<3;++j) {
    lengths[j]=std::hypot(std::hypot(m[j],m[4+j]),m[8+j]);
    if (lengths[j]==0) return error<bool>("singular", "TRS has zero scale");
  }
  for (int i=0;i<3;++i) for (int j=i+1;j<3;++j) {
    double dot=0;
    for (int k=0;k<3;++k) dot+=(m[k*4+i]/lengths[i])*(m[k*4+j]/lengths[j]);
    if (std::abs(dot)>tolerance) return error<bool>("shear", "Matrix cannot be represented by TRS without shear");
  }
  return {true,{}};
}
Result<Mat4> reparent_local(const Mat4& p, const Mat4& c) {
  if (!finite(c)) return error<Mat4>("nonfinite", "Child matrix must be finite");
  auto inv=inverse(p); if (!inv) return {{},inv.errors};
  auto result=multiply(inv.value,c); auto valid=validate_trs(result);
  if (!valid) return {{},valid.errors};
  return {result,{}};
}
Result<Quat> slerp(const Quat& a, const Quat& b, double t) {
  if (!std::isfinite(t)||t<0||t>1) return error<Quat>("fraction", "Interpolation fraction outside [0,1]");
  auto qa=normalize(a),qb=normalize(b);
  if (!qa) return qa; if (!qb) return qb;
  double dot=0; for (int i=0;i<4;++i) dot+=qa.value[i]*qb.value[i];
  if (dot<0) {dot=-dot;for (auto& x:qb.value)x=-x;}
  dot=std::clamp(dot,-1.0,1.0); Quat result{};
  if (dot>0.9995) for(int i=0;i<4;++i)result[i]=qa.value[i]+t*(qb.value[i]-qa.value[i]);
  else {
    const double theta=std::acos(dot),sin_theta=std::sin(theta);
    for(int i=0;i<4;++i) result[i]=(std::sin((1-t)*theta)*qa.value[i]+std::sin(t*theta)*qb.value[i])/sin_theta;
  }
  return normalize(result);
}
Result<std::vector<double>> hermite(const std::vector<double>& p0,
 const std::vector<double>& out0,const std::vector<double>& p1,
 const std::vector<double>& in1,double t,double dt,bool quaternion) {
  if(p0.empty()||p0.size()!=out0.size()||p0.size()!=p1.size()||p0.size()!=in1.size()||(quaternion&&p0.size()!=4))
    return error<std::vector<double>>("shape", "Curve shape mismatch");
  if(!all_finite(p0)||!all_finite(out0)||!all_finite(p1)||!all_finite(in1)||!std::isfinite(t)||t<0||t>1||!std::isfinite(dt)||dt<=0)
    return error<std::vector<double>>("curve", "Curve values, duration and fraction must be valid");
  const double h00=2*t*t*t-3*t*t+1,h10=t*t*t-2*t*t+t,h01=-2*t*t*t+3*t*t,h11=t*t*t-t*t;
  Result<std::vector<double>> r; r.value.resize(p0.size());
  for (std::size_t i=0;i<p0.size();++i) r.value[i]=h00*p0[i]+h10*dt*out0[i]+h01*p1[i]+h11*dt*in1[i];
  if (!all_finite(r.value)) return error<std::vector<double>>("nonfinite", "Curve overflowed");
  if(quaternion) {
    auto q=normalize({r.value[0],r.value[1],r.value[2],r.value[3]}); if(!q)return {{},q.errors};
    r.value.assign(q.value.begin(),q.value.end());
  }
  return r;
}
} // namespace msf
