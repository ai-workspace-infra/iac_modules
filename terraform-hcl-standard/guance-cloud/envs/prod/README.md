# Guance PROD workdir（未授权）

**不得在此执行 `render`/`apply`。** PROD 需要独立 workspace、凭据、state、评审与明确授权，门槛见
[../../docs/prod-promotion-gate.md](../../docs/prod-promotion-gate.md)，由 `scripts/prod_gate.py` 校验。
目前 `generate.py` 拒绝 `environment: prod`。
