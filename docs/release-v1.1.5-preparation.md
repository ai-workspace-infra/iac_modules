# Release v1.1.5 — 发布前准备记录

> 记录 2026-06-28 一轮 7 仓发布前准备：稳定性改进收口、发布分支/Tag 创建、两级分支保护、分支模型门禁、首个 hotfix PR 审核。
> 配套文档：分支模型策略见 [tldr-github-branch-model.md](tldr-github-branch-model.md)；稳定性根因与改进见 `xworkmate-app/docs/cases/06-gateway-turn-stability-and-robustness.md`。

---

## 0. TL;DR

- **稳定性改进全部落地**：T1–T13 + S0 + S5（四层 gateway turn 链路止血 + 持久 run 仓 + 可观测 + 插件稳定安装 + 提示精简），main 已合并并 live 验证通过。
- **7 仓建发布分支 + Tag**：`release/v1.1.5`（分支与 Tag 同名，推送用显式 refspec）。
- **两级分支保护**：`main` 轻保护（走 PR、禁 force-push）；`release/v*` 严保护（1 review + status checks + conversation + linear history + admin 不豁免）。
- **发布门禁**：`release/*` 仅接受 `hotfix/*` 或带 `cherry-pick`/`backport` 标签的 PR（workflow 待部署）。
- **首个 hotfix PR #16** 审核通过（PDF 成品排序），待合并。

---

## 1. 仓库清单与发布基线

| 仓库 | owner/repo | remote | `release/v1.1.5` 基线 commit |
|---|---|---|---|
| xworkmate-app | `ai-workspace-lab/xworkmate-app` | SSH | `b95be41` |
| xworkmate-bridge | `ai-workspace-lab/xworkmate-bridge` | SSH | `188ca4b` |
| xworkspace-console | `ai-workspace-lab/xworkspace-console` | SSH | `3ce3c6f` |
| openclaw-multi-session-plugins | `ai-workspace-lab/openclaw-multi-session-plugins` | SSH | `849972a` |
| playbooks | `ai-workspace-infra/playbooks` | SSH | `d806ba9` |
| iac_modules | `ai-workspace-infra/iac_modules` | SSH（**已从 Cloud-Neutral-Workshop 改正**）| `e489fa7` |
| xworkspace-core-skills | `ai-workspace-lab/xworkspace-core-skills` | SSH（**已从 https 改正**）| `c6b1a03` |

> 两处 remote 修正：`iac_modules` → `ai-workspace-infra`；`xworkspace-core-skills` → SSH（https + PAT 缺 `workflow` scope，无法写 `.github/workflows/`）。

---

## 2. 稳定性改进收口（进入 v1.1.5 的内容）

完整根因与设计见 cases/06。本轮确认 **已合并 main 且 live 验证**：

| 项 | 仓库 | 内容 |
|---|---|---|
| T1 | playbooks | Caddy `/acp*` 超时对齐 bridge 60min（30m→70m）|
| T2 | playbooks | 补齐非 `/acp` 路由流式配置（`flush_interval -1` + 长超时）|
| T3 | app | running 轮询加硬截止（DeadlineAt）|
| T4 | app | `停止` 本地权威化（清 pending）|
| T5 | app | 传输中断降级为「后台续跑·重连中」（有界续轮询，6 次耗尽落终态）|
| T6 | app | 失败路径与 pending 清理一致性 |
| T7/T8/T9 | bridge | 持久 per-session run 仓，脱离 WS 连接生命周期；DeadlineAt 兜底 interrupted |
| T10/T11/T12 | bridge | 错误语义（`retryable`/`poll`）+ runId 贯穿日志 + 三项指标经 `/api/ping` 暴露 |
| S0 | runtime | 插件稳定安装（真实目录 + `openclaw plugins install`），重启后 6 plugins 不丢 |
| S5 | app | gateway 提示工作区上下文精简，去除冲突的 App 本地路径 |

**live 健康（2026-06-27/28）**：bridge 运行 commit == main HEAD（无漂移）；`/api/ping.metrics` 三项均 0；网关稳定 6 plugins；四层 E2E 打通（summary.md 438B 落 task scope）。

### 已知 backlog（未进 v1.1.5，记录在案）
- **S1**：缺省 `expectedArtifactDirs` 兜底扫描 —— 已合并后回退（`0280893`→`81f65e3`），需解耦「扫描提示/阻塞导出」后重做。
- **T8b**：bridge run 仓跨进程重启持久化 —— 纯增量加固，~250–350 行评估在案，未做。

---

## 3. 发布分支与 Tag

每仓从 `main` 创建（分支与 Tag **同名** `release/v1.1.5`）：

```bash
git branch release/v1.1.5 main
git tag    release/v1.1.5 main
# 同名 → 显式 refspec 推送，避免歧义
git push origin refs/heads/release/v1.1.5:refs/heads/release/v1.1.5 \
                refs/tags/release/v1.1.5:refs/tags/release/v1.1.5
```

> 本地操作同名分支/Tag 用 `git checkout refs/heads/release/v1.1.5` 消歧义。

---

## 4. 两级分支保护（已应用）

### 4.1 `main`（轻保护，7 仓）
| 规则 | 值 |
|---|---|
| 要求 PR | ✅（`required_approving_review_count: 0`，可合自己的 PR）|
| 禁 force-push | ✅ `allow_force_pushes: false` |
| 禁删除 | ✅ `allow_deletions: false` |
| Admin 豁免 | ✅ 可绕过（`enforce_admins: false`）|
| Status checks / linear history | ❌ 不强制 |

### 4.2 `release/v1.1.5`（严保护，7 仓）
| 规则 | 值 |
|---|---|
| 禁直接 push | ✅（走 PR）|
| 禁 force-push / 禁删除 | ✅ / ✅ |
| Admin 不豁免 | ✅ `enforce_admins: true` |
| 强制 review | `required_approving_review_count: 1` + `dismiss_stale_reviews: true` |
| Status checks | `strict: true`（contexts 待来源校验 workflow 跑出后补）|
| Conversation 解决 | ✅ `required_conversation_resolution: true` |
| Linear history | ✅ `required_linear_history: true`（禁 merge commit）|

> API 注意：必传 `required_pull_request_reviews`/`required_status_checks`/`restrictions`（可为 `null`）否则 422；分支名 `/` 在 path 段需编码 `release%2Fv1.1.5`。
> 写 `.github/workflows/` 需 token 带 `workflow` scope 或改走 SSH git push（当前 token scopes：`repo, read:org, project, gist, admin:public_key`，**无 workflow**）。

---

## 5. 发布门禁 — PR 来源校验

`release/*` 仅接受 `hotfix/*` 或带 `cherry-pick`/`backport` 标签的 PR；禁止 main/develop/feature 直入。校验靠 `.github/workflows/validate-release-pr.yml`（详见 tldr-github-branch-model.md §4）。

- ⏳ **状态：待部署**。因 main 现已要求 PR，需为 7 仓各开 PR 合入 workflow；现有 `release/v1.1.5` 需 backport 该 workflow 才能对其 PR 实际生效（`pull_request_target` 用 base 分支的 workflow 版本）。

---

## 6. 首个 hotfix PR 审核

**[PR #16](https://github.com/ai-workspace-lab/xworkmate-app/pull/16)** — `fix(artifacts): prioritize PDF deliverables in sidebar`
- 路径：`hotfix/pdf-sync-anomaly-release` → `release/v1.1.5`（✅ 合规）
- 改动：2 文件 +67/-0；排序 comparator 加 PDF 优先 + 根目录优先
- 实证：`flutter test desktop_thread_artifact_service_test.dart` **4/4 通过**；`flutter analyze` 改动文件 **No issues**
- 结论：**通过，可合并**（单 commit，满足 linear history）
- nit（非阻塞）：PDF 深度 tie-break 的 `if(a==pdf)` 隐含 b 也是 pdf，可加注释

---

## 7. 剩余动作（发布前 checklist）

- [ ] 部署 `validate-release-pr.yml` 到 7 仓 main（走 PR）
- [ ] backport workflow 到 `release/v1.1.5`（hotfix PR），并把其 check 名加入 `required_status_checks.contexts`
- [ ] Approve + squash 合并 PR #16
- [ ] （可选）把现有 CI check（app: `build-and-release`/`pr-tests`/`release-e2e`）按需加入 release/v* required checks
- [ ] backlog 排期：S1 重做、T8b 跨重启持久化
