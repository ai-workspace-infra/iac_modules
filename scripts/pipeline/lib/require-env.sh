#!/usr/bin/env bash
# 共享的必需环境变量守卫。
#
# 用法:
#   . "$(dirname "${BASH_SOURCE[0]}")/lib/require-env.sh"
#   require_env MATRIX_HOST POSTGRES_ROOT_PASSWORD
#
# 为什么需要这个: 这些变量绝大多数用于「选择部署目标」或「提供凭据」。
# 空值不会让下游命令失败, 而是让它作用到错误的目标, 或者带着空凭据继续跑:
#
#   * ansible 的空 host pattern / 空 --limit 会匹配零台主机, 而 ad-hoc 与
#     `ansible-playbook --limit` 在零主机命中时都返回 exit 0 —— 部署什么都没做,
#     流水线却是绿的。
#   * vault-action 开着 ignoreNotFound, 键名写错只会得到空字符串, 于是
#     `docker login` 用空密码、terraform backend 拿到 region="" 才在很后面炸掉。
#
# 也就是说: 这些变量的失败模式是「静默走错」, 不是「报错停下」。所以必须在
# 脚本入口显式断言, 而不能指望下游命令自己报错。
require_env() {
  local missing=() v
  for v in "$@"; do
    if [ -z "${!v:-}" ]; then
      missing+=("${v}")
    fi
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    echo "::error::${BASH_SOURCE[1]##*/}: missing or empty required environment variable(s): ${missing[*]}" >&2
    echo "  这些变量由调用它的 workflow step 的 env: 块提供; 空值会让本步骤静默作用到错误目标。" >&2
    exit 1
  fi
}
