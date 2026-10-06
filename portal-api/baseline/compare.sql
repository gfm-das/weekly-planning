-- Lists everything that makes up the database schema, one line each, sorted: run it on two databases and compare the
-- answers (portal-api/baseline/check-baseline.ps1 does). Schemas public, dashboards and portal.
SELECT 'column ' || c.table_schema || '.' || c.table_name || '.' || c.column_name || ' ' || c.data_type || ' null=' || c.is_nullable
       || ' default=' || coalesce(regexp_replace(c.column_default, 'nextval\(.*\)', 'nextval'), '') || ' identity=' || coalesce(c.identity_generation, '')
FROM information_schema.columns c WHERE c.table_schema IN ('public', 'dashboards', 'portal')
UNION ALL SELECT 'constraint ' || conrelid::regclass || ' ' || conname || ' ' || pg_get_constraintdef(oid)
FROM pg_constraint WHERE connamespace IN (SELECT oid FROM pg_namespace WHERE nspname IN ('public', 'dashboards', 'portal'))
UNION ALL SELECT 'index ' || schemaname || '.' || indexname || ' ' || regexp_replace(indexdef, '\s+', ' ', 'g')
FROM pg_indexes WHERE schemaname IN ('public', 'dashboards', 'portal')
UNION ALL SELECT 'function ' || p.oid::regprocedure || ' owner=' || pg_get_userbyid(p.proowner) || ' md5=' || md5(pg_get_functiondef(p.oid))
FROM pg_proc p WHERE p.pronamespace IN (SELECT oid FROM pg_namespace WHERE nspname IN ('public', 'dashboards', 'portal')) AND p.prokind IN ('f', 'p')
UNION ALL SELECT 'view ' || schemaname || '.' || viewname || ' owner=' || viewowner || ' md5=' || md5(definition)
FROM pg_views WHERE schemaname IN ('public', 'dashboards', 'portal')
UNION ALL SELECT 'policy ' || schemaname || '.' || tablename || ' ' || policyname || ' ' || cmd || ' ' || roles::text || ' ' || coalesce(qual, '') || ' / ' || coalesce(with_check, '')
FROM pg_policies WHERE schemaname IN ('public', 'dashboards', 'portal')
UNION ALL SELECT 'trigger ' || tgrelid::regclass || ' ' || tgname || ' ' || md5(pg_get_triggerdef(oid))
FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN (SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname IN ('public', 'dashboards', 'portal'))
UNION ALL SELECT 'rls ' || n.nspname || '.' || c.relname || ' enabled=' || c.relrowsecurity::text || ' forced=' || c.relforcerowsecurity::text || ' options=' || coalesce(c.reloptions::text, '')
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname IN ('public', 'dashboards', 'portal') AND c.relkind IN ('r', 'v', 'm')
UNION ALL SELECT 'acl ' || n.nspname || '.' || c.relname || ' ' || c.relkind::text || ' owner=' || pg_get_userbyid(c.relowner) || ' ' || coalesce(c.relacl, acldefault((CASE c.relkind WHEN 'S' THEN 's' ELSE 'r' END)::"char", c.relowner))::text
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname IN ('public', 'dashboards', 'portal') AND c.relkind IN ('r', 'v', 'm', 'S')
UNION ALL SELECT 'acl function ' || p.oid::regprocedure || ' ' || coalesce(p.proacl, acldefault('f'::"char", p.proowner))::text
FROM pg_proc p WHERE p.pronamespace IN (SELECT oid FROM pg_namespace WHERE nspname IN ('public', 'dashboards', 'portal'))
UNION ALL SELECT 'acl schema ' || nspname || ' ' || coalesce(nspacl::text, 'default') FROM pg_namespace WHERE nspname IN ('public', 'dashboards', 'portal')
UNION ALL SELECT 'default-privileges ' || pg_get_userbyid(d.defaclrole) || ' ' || coalesce(n.nspname, '') || ' ' || d.defaclobjtype::text || ' ' || d.defaclacl::text
FROM pg_default_acl d LEFT JOIN pg_namespace n ON n.oid = d.defaclnamespace WHERE n.nspname IN ('public', 'dashboards', 'portal')
UNION ALL SELECT 'sequence ' || sequencename || ' ' || data_type::text FROM pg_sequences WHERE schemaname IN ('public', 'dashboards', 'portal')
ORDER BY 1;
