// SPDX-License-Identifier: MIT
#include "msf/common.hpp"
#include "numeric.hpp"
#include <algorithm>
#include <cmath>

namespace msf {
using namespace detail;
bool finite(const Mat4& m) {
  return std::all_of(m.begin(), m.end(), [](double value) { return std::isfinite(value); });
}
Mat4 identity() { return {1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1}; }
Result<Mat4> multiply(const Mat4& a, const Mat4& b) {
  return compute<Mat4>([&] {
    numbers(a); numbers(b);
    Mat4 result{};
    for (int i = 0; i < 4; ++i) for (int j = 0; j < 4; ++j)
      for (int k = 0; k < 4; ++k)
        result[i*4+j] = add(result[i*4+j], product(a[i*4+k], b[k*4+j]));
    return result;
  });
}
Result<Mat4> inverse(const Mat4& a) {
  return compute<Mat4>([&] {
    numbers(a);
    double aug[4][8]{};
    for (int i = 0; i < 4; ++i) for (int j = 0; j < 4; ++j) {
      aug[i][j] = a[i*4+j]; aug[i][j+4] = (i == j);
    }
    for (int col = 0; col < 4; ++col) {
      int pivot = col;
      for (int row = col+1; row < 4; ++row)
        if (std::abs(aug[row][col]) > std::abs(aug[pivot][col])) pivot = row;
      if (aug[pivot][col] == 0) refuse("singular", "Matrix has no inverse");
      if (pivot != col) for (int j = 0; j < 8; ++j) std::swap(aug[pivot][j], aug[col][j]);
      const double divisor = aug[col][col];
      for (double& value : aug[col]) value = divide(value, divisor);
      for (int row = 0; row < 4; ++row) if (row != col) {
        const double factor = aug[row][col];
        for (int j = 0; j < 8; ++j) aug[row][j] = sub(aug[row][j], product(factor, aug[col][j]));
      }
    }
    Mat4 result{};
    for (int i = 0; i < 4; ++i) for (int j = 0; j < 4; ++j) result[i*4+j] = aug[i][j+4];
    return result;
  });
}
Result<Vec3> transform_point(const Mat4& m, const Vec3& p) {
  return compute<Vec3>([&] {
    affine(m); numbers(p);
    Vec3 result{};
    for (int i = 0; i < 3; ++i) {
      for (int j = 0; j < 3; ++j) result[i] = add(result[i], product(m[i*4+j], p[j]));
      result[i] = add(result[i], m[i*4+3]);
    }
    return result;
  });
}
Result<Quat> normalize(const Quat& q) {
  return compute<Quat>([&] {
    numbers(q);
    const double norm = number(std::hypot(std::hypot(q[0], q[1]), std::hypot(q[2], q[3])));
    if (norm == 0) refuse("quaternion", "Quaternion norm must be nonzero");
    Quat result{};
    for (int i = 0; i < 4; ++i) result[i] = divide(q[i], norm);
    return result;
  });
}
Result<Mat4> compose_trs(const Vec3& t, const Quat& q, const Vec3& s) {
  return compute<Mat4>([&] {
    numbers(t); numbers(s);
    const auto [x,y,z,w] = take(normalize(q));
    const double xx=product(x,x), yy=product(y,y), zz=product(z,z);
    const double xy=product(x,y), xz=product(x,z), yz=product(y,z);
    const double xw=product(x,w), yw=product(y,w), zw=product(z,w);
    const auto diagonal = [](double a, double b) { return sub(1, product(2, add(a,b))); };
    const auto twice = [](double value) { return product(2, value); };
    const double rot[3][3] = {
      {diagonal(yy,zz), twice(sub(xy,zw)), twice(add(xz,yw))},
      {twice(add(xy,zw)), diagonal(xx,zz), twice(sub(yz,xw))},
      {twice(sub(xz,yw)), twice(add(yz,xw)), diagonal(xx,yy)}};
    Mat4 result=identity();
    for (int i = 0; i < 3; ++i) {
      for (int j = 0; j < 3; ++j) result[i*4+j] = product(rot[i][j], s[j]);
      result[i*4+3] = t[i];
    }
    return result;
  });
}
Result<bool> validate_trs(const Mat4& m, double tolerance) {
  return compute<bool>([&] {
    numbers(m); number(tolerance);
    if (tolerance <= 0) refuse("nonfinite", "TRS tolerance must be positive");
    affine(m, tolerance);
    std::array<Vec3,3> unit{};
    for (int j = 0; j < 3; ++j) {
      const double length = number(std::hypot(std::hypot(m[j],m[4+j]),m[8+j]));
      if (length == 0) refuse("singular", "TRS has zero scale");
      for (int i = 0; i < 3; ++i) unit[j][i] = divide(m[i*4+j], length);
    }
    for (int i = 0; i < 3; ++i) for (int j = 0; j < i; ++j)
      if (std::abs(dot(unit[i],unit[j])) > tolerance)
        refuse("shear", "Matrix cannot be represented by TRS without shear");
    const auto& a=unit[0]; const auto& b=unit[1]; const auto& c=unit[2];
    const Vec3 cross={sub(product(b[1],c[2]),product(b[2],c[1])),
                      sub(product(b[2],c[0]),product(b[0],c[2])),
                      sub(product(b[0],c[1]),product(b[1],c[0]))};
    const double determinant=dot(a,cross);
    if (determinant == 0) refuse("singular", "Normalized determinant is zero");
    if (std::abs(sub(std::abs(determinant),1)) > tolerance)
      refuse("shear", "Normalized determinant must have magnitude near one");
    return true;
  });
}
Result<Mat4> reparent_local(const Mat4& p, const Mat4& c) {
  return compute<Mat4>([&] {
    affine(p); affine(c);
    const auto result=take(multiply(take(inverse(p)),c));
    take(validate_trs(result));
    return result;
  });
}
Result<Quat> slerp(const Quat& a, const Quat& b, double t) {
  return compute<Quat>([&] {
    auto qa=take(normalize(a)); auto qb=take(normalize(b));
    number(t);
    if (t < 0 || t > 1) refuse("fraction", "Interpolation fraction outside [0,1]");
    if (t == 0) return qa;
    double cosine=0;
    if (t == 1) {
      // Endpoints need only the ordered rounded dot's hemisphere sign.
      for (int i = 0; i < 4; ++i) {
        int a_exp=0, b_exp=0;
        std::frexp(qa[i], &a_exp); std::frexp(qb[i], &b_exp);
        const double term=(qa[i] == 0 || qb[i] == 0 || a_exp+b_exp <= -1075) ? 0 : qa[i]*qb[i];
        cosine=add(cosine,term);
      }
      if (cosine < 0) for (double& value : qb) value=-value;
      return qb;
    }
    cosine=dot(qa,qb);
    if (cosine < 0) { cosine=-cosine; for (double& value : qb) value=-value; }
    cosine=std::min(1.0,cosine);
    Quat result{};
    if (cosine > .9995) {
      for (int i = 0; i < 4; ++i) result[i]=add(qa[i],product(t,sub(qb[i],qa[i])));
    } else {
      const double angle=number(std::acos(cosine)), divisor=number(std::sin(angle));
      const double aw=divide(number(std::sin(product(sub(1,t),angle))),divisor);
      const double bw=divide(number(std::sin(product(t,angle))),divisor);
      for (int i = 0; i < 4; ++i) result[i]=add(product(aw,qa[i]),product(bw,qb[i]));
    }
    return take(normalize(result));
  });
}
Result<std::vector<double>> hermite(const std::vector<double>& p0,
 const std::vector<double>& out0, const std::vector<double>& p1,
 const std::vector<double>& in1, double t, double dt, bool quaternion) {
  return compute<std::vector<double>>([&] {
    if (p0.empty() || p0.size()!=out0.size() || p0.size()!=p1.size() ||
        p0.size()!=in1.size() || (quaternion && p0.size()!=4))
      refuse("shape", "Curve shape mismatch");
    numbers(p0); numbers(out0); numbers(p1); numbers(in1); number(t); number(dt);
    if (t < 0 || t > 1) refuse("fraction", "Interpolation fraction outside [0,1]");
    if (dt <= 0) refuse("curve", "Hermite duration must be positive");
    const double t2=product(t,t), t3=product(t2,t);
    const double twice_t2=product(2,t2), thrice_t2=product(3,t2), twice_t3=product(2,t3);
    const double h00=add(sub(twice_t3,thrice_t2),1), h10=add(sub(t3,twice_t2),t);
    const double h01=add(-twice_t3,thrice_t2), h11=sub(t3,t2);
    std::vector<double> result(p0.size());
    for (std::size_t i = 0; i < p0.size(); ++i) {
      double value=add(0,product(h00,p0[i]));
      value=add(value,out0[i] == 0 ? 0 : product(product(h10,dt),out0[i]));
      value=add(value,product(h01,p1[i]));
      result[i]=add(value,in1[i] == 0 ? 0 : product(product(h11,dt),in1[i]));
    }
    if (quaternion) {
      const auto q=take(normalize({result[0],result[1],result[2],result[3]}));
      result.assign(q.begin(),q.end());
    }
    return result;
  });
}
} // namespace msf
