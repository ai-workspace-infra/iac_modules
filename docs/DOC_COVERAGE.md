# Documentation Coverage Matrix

This matrix tracks the bilingual canonical documentation set for `iac_modules` and maps it back to the current codebase and older docs.

该矩阵用于跟踪 `iac_modules` 的双语规范文档，并将其与当前代码状态和历史文档对应起来。

| Category | EN | ZH | Current status | Existing references | Next check |
| --- | --- | --- | --- | --- | --- |
| Architecture | Yes | Yes | Seeded from current codebase and existing docs. | `CloudNeutral-Architecture-Blueprint-2025.md` | Keep diagrams and ownership notes synchronized with actual directories, services, and integration dependencies. |
| Design | Yes | Yes | Seeded from current codebase and existing docs. | `Multi-Cloud-Landing-Zone-Planning.md` | Promote one-off implementation notes into reusable design records when behavior, APIs, or deployment contracts change. |
| Deployment | Yes | Yes | Seeded from current codebase; deeper legacy consolidation is still needed. | None yet; use the new canonical page as the starting point. | Verify deployment steps against current scripts, manifests, CI/CD flow, and environment contracts before each release. |
| User Guide | Yes | Yes | Seeded from current codebase; deeper legacy consolidation is still needed. | None yet; use the new canonical page as the starting point. | Prefer workflow-oriented examples and keep screenshots or terminal snippets aligned with the latest UI or CLI behavior. |
| Developer Guide | Yes | Yes | Seeded from current codebase; deeper legacy consolidation is still needed. | None yet; use the new canonical page as the starting point. | Keep setup and test commands tied to actual package scripts, Make targets, or language toolchains in this repository. |
| Vibe Coding Reference | Yes | Yes | Seeded from current codebase; deeper legacy consolidation is still needed. | None yet; use the new canonical page as the starting point. | Review prompt templates and repo rules whenever the project adds new subsystems, protected areas, or mandatory verification steps. |
