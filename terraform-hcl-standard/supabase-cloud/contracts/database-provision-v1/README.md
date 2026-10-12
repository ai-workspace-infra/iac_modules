# DatabaseProvisionSpec/v1 与离线接口（准备阶段）

边界：Playbooks自建PostgreSQL；supabase-cloud托管Supabase，用户明确要求托管库内角色接口留模块内，不交给自建Playbooks。共享Python契约是版本同步副本；不是跨仓执行依赖。生产访问均关闭，动态credentials只有Protocol。

Spec闭合结构与placeholder见example.json：identity/env/instance/database，backend，create_new|adopt_existing|existing_external，显式operation/operation_id，每仓40位SHA，SecretRef(kind/mount/path/field/expected_version)，TLS verify-full+CA引用，安全开关。未知字段拒绝，JSON不含密码DSN。LOGIN用途分dba/runtime/ddl_migrator/readonly_export/readonly_audit/monitor；owner NOLOGIN无DSN。普通操作拒绝轮换、重建、删库、切主，403/超时不当不存在，已有角色缺凭据停止。

Receipt只含版本/identity/backend/mode/operation/id/仓SHA/status/枚举checks，不输出秘密/provider错误。offline_pass不是ready；真实日志/CMDB消费者未迁移。例子SHA为最初观察基线，不代表后续未提交工作树已固定。

|卡|owner|输入→输出|验证|
|---|---|---|---|
|1|playbooks|非秘密Spec→validator/Receipt|contract拒绝fixtures|
|2|iac_modules|producer字节→consumer副本|契约字节比对|
|3|playbooks|Spec+显式schema+角色快照→SQL计划/fixture事务接口|单元/一次性PG计划语义；生产Driver未实现|
|4|iac_modules|mode+state策略→opt-in renderer/templates|temporary workdir fixtures；external validate|
|5|playbooks|OIDC ref/KVv2/CAS→注入mock adapter|403/超时/失败恢复|
|6|iac_modules|同Vault接口+旧ref→metadata fixture兼容|不取旧值，不创建mount/policy/token|
|7|playbooks|只读源/固定迁移构件→独立权限验收清单|生产与migratectl未运行|

roles_adapter产生可review不含密码的SQL计划，严格引用标识符；snapshot查询参数单独传入Driver。新增登录密码由resolver仅在fixture执行内取得，计划不包含值；已有角色只验证、不ALTER密码。全事务、计划漂移检查、advisory锁、权限验证、失败回滚，异常使用固定码。执行要求env=fixture和fixture_only注入Driver/Resolver；没有production connector。Driver日志与utility PASSWORD literal安全是实现义务，mock成功不能证明实际输密安全；Python字符串不能保证清零。计划不创建引擎/schema/business表，不复制Accounts52+Billing1 DDL/seed；只处理显式schema授权，migratectl需明确SET ROLE NOLOGIN owner。pg_monitor显式INHERIT TRUE/SET FALSE；DBA与migrator成员INHERIT FALSE/SET TRUE。

VaultAdapter仅fixture transport，auth_ref只引用短期OIDC；当前existing mount=kv。新logical path=<env>/databases/<instance>/<db>/<purpose>，KVv2 CAS expected_version必传，staging/operation_id→验证→active，超时unknown且通过同id读取确认，不盲目重复写。失败保留staging，不自动覆盖并发active；每purpose发布，不假装多key原子。Vault加密持久staging不同于runner临时明文。真实创建/写入/轮换及OIDC/IAM改造暂停。

旧kv/prod/databases和kv/prod/database-upgrade的PROD_SUPABASE_READONLY_DSN只提供allowlist metadata接口；不读secret值，field_presence=not_checked_metadata_only，不自动迁移/覆盖/删secret。

权限验收须单独覆盖SUPERUSER/BYPASSRLS/递归成员/SET ROLE、PUBLIC DB/schema/table/sequence/default ACL、函数EXECUTE/security definer/search_path、RLS enable/force/policy/owner绕过。default_transaction_read_only不能替代权限。一次性fixture只证明其具体负向权限场景，不证明源或生产安全。源迁移只读、audit/export/monitor和业务migratectl分别验收。

兼容路由和保留的旧风险见COMPATIBILITY.md；本PR不切caller，不删除旧executor，不部署。优先临时身份/动态凭据、内存/stdin/受控tmpfs；Mac普通/tmp不是tmpfs。目标减少凭据落盘，不宣称绝对无落盘。

测试：PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s contracts/database-provision-v1 -v（Supabase模块下对应路径）。fixture-only组件不用于生产验收。
