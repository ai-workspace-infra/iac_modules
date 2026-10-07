# 兼容清单与切换边界

本PR是additive准备，不切换现有caller。第一批草稿默认inspect/删DSN outputs会破坏caller，已从本PR撤回；现有main entry、输密行为、Supabase outputs与init.sh保持原样，不能声称已安全达标。

|Caller|旧路由与剩余风险|显式新接口/迁移|
|---|---|---|
|deploy_postgre_vhosts.yml:149,162|postgres main部署，仍有密码缓存/ALTER|未来caller指定tasks_from=contract+operation；先验证受控engine，不直接替换main|
|setup-postgres-standalone.yaml:10；deploy_iam_domain.yml:6|standalone/IAM引擎及compose env依赖|仍使用旧入口；strict contract拒绝legacy engine，engine迁移后再切caller|
|deploy_postgresql_svc_plus.yml:25|旧service有docker rm/force-recreate|旧入口未改变；contract入口明确停止engine，普通roles不触及容器|
|deploy_observability_agent.yml:118|exporter affinity/事实初始化、旧monitor密码维护|旧入口保留；未来分离affinity/安装与已验证monitor凭据复用，不隐式改密码|
|write_passwords_to_vault.yml:19|旧defaults读取、自动创建mount、无CAS写入|不接新接口；迁移需已存在mount/短期OIDC/CAS，真实执行暂停|
|platform-ops-toolkit/scripts/serverless_uat/init_supabase_account_db.sh:237|无参数调用旧init.sh|旧init.sh保持可调用；新init_contract.sh必须RESOURCES/WORKDIR且只render，不隐式init|
|GitOps resources/svc.plus/dev/supabase/supabase.yaml及并行副本|旧声明含环境模板引用|未读值/未改文件；显式mode和安全标志由该owner未来迁移|
|Toolkit部署/billing及数据库快照reader|旧Vault DSN键和PROD_SUPABASE_READONLY_DSN读者|旧输出/secret不删、不迁移、不双写；仅新增mock metadata reader|

新Playbooks入口通过include_role tasks_from: contract启用；未指定operation明确失败，inspect仅验证输入、不探测真实实例。roles仍明确停止，直到生产安全Driver/Resolver就绪。strict默认true；关闭strict不会调用旧engine，因为没有安全engine adapter。现有caller无需兼容开关，不会因本PR改变行为。

新Supabase入口是render_contract.py/init_contract.sh，模板位于contract_templates；legacy render.py/init.sh/root HCL和DSN outputs保留。新入口external无resource/import，adopt显式，create独立，strict阻止managedstate密码。非strict+ack_sensitive_state仅风险选项，不代表允许部署。旧state/outputs仍可能包含秘密，本任务不读取或清理。

Toolkit/GitOps调用者未修改；这是兼容准备而非切换完成。实际生产改造按owner→固定SHA caller→非变更演练/环境验收→删除旧路由；不把离线通过当生产验收。
