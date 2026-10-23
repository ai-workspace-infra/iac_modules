# Gateway single-A reconciliation contract (P2a)

`dns-reconcile.py plan|apply|restore` is an owner implementation for **UAT,
one DNS-only public IPv4 gateway A record with TTL 60**. It does not replace
`cloudflare-dns-record.py` (#388) cutover semantics. Toolkit renders a runtime
intent from GitOps declarations and current-run CMDB facts, selects and approves
the record, obtains the runtime token and orders enrollment after successful
provider/readback/resolver verification. The executor never reads Vault or SSHs.

The intent is a strict JSON object; unknown fields (including credential fields)
are refused. Example shape (IDs/addresses below are illustrative, not a target):

```json
{
  "version": 1,
  "environment": "uat",
  "run_id": "1234",
  "release_tag": "uat-daily-build-2026.10.05-r1",
  "account_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "zone_id": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "zone_name": "example.invalid",
  "owner_tag": "owner:gateway",
  "expected_record_id": null,
  "record": {
    "type": "A",
    "name": "gateway.example.invalid",
    "content": "8.8.4.4",
    "ttl": 60,
    "proxied": false
  }
}
```

`expected_record_id=null` means an explicitly expected absence. Updating an
existing record requires its exact 32-hex ID. The zone ID, name, active state and
account ID are read back before each operation. Any non-A record at the name,
duplicate A, incomplete/paginated result, unexpected ID or foreign `owner:` tag
fails before a write. Existing comment, tags and settings are preserved; this
batch does not adopt/yield canonical names or erase foreign ownership.

Place intent, plan, checkpoint and receipts in a fresh private runner directory
(0700, absolute physical path with no symlinks). Files are 0600. Pass
`CLOUDFLARE_DNS_API_TOKEN` at runtime; it is never an argument or JSON field.

```bash
python3 scripts/pipeline/dns-reconcile.py plan --intent "$RUN_DIR/intent.json" --output "$RUN_DIR/plan.json"
# Review/approve the exact captured prior state before apply.
python3 scripts/pipeline/dns-reconcile.py apply --plan "$RUN_DIR/plan.json" --checkpoint "$RUN_DIR/checkpoint.json" --receipt "$RUN_DIR/applied.json"
# Recovery is an explicit control-plane decision, not automatic broad deletion.
python3 scripts/pipeline/dns-reconcile.py restore --plan "$RUN_DIR/plan.json" --checkpoint "$RUN_DIR/checkpoint.json" --receipt "$RUN_DIR/restored.json"
```

`plan` only reads provider state. `apply` refuses drift since planning and saves
the original complete writable configuration before mutation. It verifies the
record ID and full configuration after writing, then requires exact single-A
answers from 1.1.1.1 and 8.8.8.8 within a bounded 120-second resolver wait and
reads the provider again. Errors remain errors; no success receipt is emitted.
Receipts bind environment/run/release/account/zone/name/record ID. A fresh
receipt path is required to prevent consuming a stale success after failure.

Retrying with the same checkpoint preserves the original recovery point. A
lost create response is intentionally not adopted: unknown record identity
requires operator inspection rather than creating again or deleting by name.
Provider API requests are not blindly retried. The same checkpoint uses a
nonblocking filesystem lock; caller workflows must also serialize the target
record. Cloudflare has no compare-and-swap transaction across read/write;
external writers can race the operation. Full readback detects drift, and
recovery refuses to overwrite that writer's changed state.

`restore` only changes a record whose exact ID and full configured state still
match this operation. An updated record recovers every saved writable field;
resolver recovery is verified for DNS-only original records. A newly created
record is deleted only by the ID returned to this operation and only when its
complete configured state matches. Deletion verifies provider absence; cached
resolver entries may outlive deletion, so its receipt explicitly sets
`resolver_verified=false`. No receipt asserts host/service acceptance.

API fields and pagination follow Cloudflare's official
[create-record](https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/create/)
and [list-records](https://developers.cloudflare.com/api/resources/dns/subresources/records/methods/list/)
contracts. Generated timestamps are not writable fields and are not restored.

## Evidence and next stages

Owner fake-provider/CLI tests exercise creation, update, no-op, full-state
recovery, lost responses, resolver failures, canonical conflicts, credentials,
target binding and concurrent changes. They perform no provider or host writes.
SIT/PROD, CNAME, canonical adopt/yield and multi-record reconcile remain separate
contracts. Legacy UAT/SIT implicit duplicate deletion is not implemented here.
Merge/review the owner and pin its full SHA before switching the gateway caller.
Caller contracts, explicit runtime UAT evidence and cleanup follow separately;
no Toolkit legacy executor is deleted by this owner PR.
