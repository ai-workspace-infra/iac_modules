# 托管角色接口：离线计划与fixture执行

Owner: supabase-cloud内独立接口；不是selfhost Playbooks，不通过Terraform local-exec或null_resource执行。Spec/SecretRef输入、闭合计划及脱敏Receipt见../contracts/database-provision-v1。plan_roles.py从stdin输出review计划；RoleExecutor只接受fixture env和注入fixture Driver/Resolver。没有production connector、真实Vault transport或可用动态lease服务，不能标ready。

已用临时backend=false、空HOME/无凭据环境安装并核验supabase/supabase 1.11.0 schema：资源只有apikey/branch/edge_function/edge_function_secrets/project/settings/third_party_auth；没有库内角色资源。supabase_project.database_password sensitive=true、write_only=false，不能保证秘密不入state。证据见contracts/database-provision-v1/VALIDATION.json。新contract_templates固定1.11.0；旧root provider约束保留，不迁移其state。

新角色接口不触发provider资源/引擎管理，operation=roles要求显式adopt_existing既有目标；create_new引擎创建后须另行验证目标归属，不能拿create_new计划隐式接管已有实例。权限、源只读、RLS/PUBLIC/函数有效权限及migratectl需独立生产验收。短期OIDC/现有KVv2/CAS接口只mock，真实秘密访问/写入/轮换暂停。
