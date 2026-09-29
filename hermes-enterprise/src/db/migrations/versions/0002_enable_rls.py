"""enable row level security policies across all tables and stored search function

Revision ID: 0002_enable_rls
Revises: 0001_initial_schema
Create Date: 2026-09-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0002_enable_rls'
down_revision: Union[str, None] = '0001_initial_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES_WITH_RLS = [
    "tenants", "users", "user_sessions", "invitations", "user_preferences",
    "conversations", "messages", "user_files", "memory_embeddings",
    "token_usage", "audit_logs", "tenant_gateway_configs",
    "user_gateway_bindings", "gateway_conversational_sessions"
]


def upgrade() -> None:
    # 1. Create helper functions
        op.execute("""
CREATE OR REPLACE FUNCTION current_app_tenant_id() RETURNS UUID AS $$
    BEGIN
        RETURN NULLIF(current_setting('app.current_tenant_id', true), '')::uuid;
    EXCEPTION WHEN OTHERS THEN
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql STABLE SECURITY DEFINER;
    """)
    op.execute("""
CREATE OR REPLACE FUNCTION current_app_user_id() RETURNS UUID AS $$
    BEGIN
        RETURN NULLIF(current_setting('app.current_user_id', true), '')::uuid;
    EXCEPTION WHEN OTHERS THEN
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql STABLE SECURITY DEFINER;
    """)
    op.execute("""
CREATE OR REPLACE FUNCTION is_app_admin() RETURNS BOOLEAN AS $$
    BEGIN
        RETURN COALESCE(current_setting('app.is_admin', true), 'false') = 'true';
    EXCEPTION WHEN OTHERS THEN
        RETURN FALSE;
    END;
    $$ LANGUAGE plpgsql STABLE SECURITY DEFINER;
    """)
    op.execute("""
CREATE OR REPLACE FUNCTION is_system_bypass() RETURNS BOOLEAN AS $$
    BEGIN
        RETURN COALESCE(current_setting('app.bypass_rls', true), 'off') = 'on';
    EXCEPTION WHEN OTHERS THEN
        RETURN FALSE;
    END;
    $$ LANGUAGE plpgsql STABLE SECURITY DEFINER;
    """)

    # 2. Stored Database Function: search_hybrid_memories (PROJECT.md line 111)
        op.execute("""
CREATE OR REPLACE FUNCTION search_hybrid_memories(
        p_tenant_id UUID,
        p_user_id UUID,
        p_query_text TEXT,
        p_query_embedding VECTOR(768),
        p_limit INT DEFAULT 10,
        p_rrf_k INT DEFAULT 60
    )
    RETURNS TABLE (
        memory_id UUID,
        content TEXT,
        metadata JSONB,
        scope VARCHAR(32),
        created_at TIMESTAMPTZ,
        rrf_score DOUBLE PRECISION
    )
    LANGUAGE plpgsql
    STABLE
    PARALLEL SAFE
    AS $$
    DECLARE
        v_has_text BOOLEAN := (p_query_text IS NOT NULL AND length(trim(p_query_text)) > 0);
        v_has_vec BOOLEAN := (p_query_embedding IS NOT NULL);
        v_tsquery TSQUERY;
        v_candidate_k INT := 50;
        v_w_vec DOUBLE PRECISION := 0.7;
        v_w_lex DOUBLE PRECISION := 0.3;
    BEGIN
        IF NOT v_has_text AND NOT v_has_vec THEN
            RETURN;
        END IF;

        IF v_has_text THEN
            v_tsquery := websearch_to_tsquery('english', p_query_text);
            IF v_tsquery = ''::tsquery THEN
                v_has_text := FALSE;
            END IF;
        END IF;

        RETURN QUERY
        WITH vector_search AS (
            SELECT 
                m.id,
                ROW_NUMBER() OVER (ORDER BY m.embedding <=> p_query_embedding) AS rank_vec
            FROM memory_embeddings m
            WHERE v_has_vec
              AND m.tenant_id = p_tenant_id
              AND (m.user_id = p_user_id OR m.scope = 'tenant')
            ORDER BY m.embedding <=> p_query_embedding
            LIMIT v_candidate_k
        ),
        lexical_search AS (
            SELECT 
                m.id,
                ROW_NUMBER() OVER (ORDER BY ts_rank_cd(m.tsv, v_tsquery, 32) DESC) AS rank_lex
            FROM memory_embeddings m
            WHERE v_has_text
              AND m.tenant_id = p_tenant_id
              AND (m.user_id = p_user_id OR m.scope = 'tenant')
              AND m.tsv @@ v_tsquery
            ORDER BY ts_rank_cd(m.tsv, v_tsquery, 32) DESC
            LIMIT v_candidate_k
        )
        SELECT 
            m.id AS memory_id,
            m.content,
            m.metadata,
            m.scope,
            m.created_at,
            (
                COALESCE(v_w_vec / (p_rrf_k + v.rank_vec), 0.0) +
                COALESCE(v_w_lex / (p_rrf_k + l.rank_lex), 0.0)
            )::DOUBLE PRECISION AS rrf_score
        FROM memory_embeddings m
        LEFT JOIN vector_search v ON m.id = v.id
        LEFT JOIN lexical_search l ON m.id = l.id
        WHERE v.id IS NOT NULL OR l.id IS NOT NULL
        ORDER BY rrf_score DESC
        LIMIT p_limit;
    END;
    $$;
    """)

    # 3. Enable and Force RLS on all tables
    for table in TABLES_WITH_RLS:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")

    # 4. Create Isolation Policies
    # Tenants
        op.execute("""
DROP POLICY IF EXISTS tenant_isolation_policy ON tenants;
    """)
    op.execute("""
CREATE POLICY tenant_isolation_policy ON tenants
        FOR ALL
        USING (is_system_bypass() OR id = current_app_tenant_id())
        WITH CHECK (is_system_bypass() OR id = current_app_tenant_id());
    """)

    # Users
        op.execute("""
DROP POLICY IF EXISTS users_isolation_policy ON users;
    """)
    op.execute("""
CREATE POLICY users_isolation_policy ON users
        FOR ALL
        USING (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND (id = current_app_user_id() OR is_app_admin())
            )
        )
        WITH CHECK (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND (id = current_app_user_id() OR is_app_admin())
            )
        );
    """)

    # User Sessions
        op.execute("""
DROP POLICY IF EXISTS user_sessions_isolation_policy ON user_sessions;
    """)
    op.execute("""
CREATE POLICY user_sessions_isolation_policy ON user_sessions
        FOR ALL
        USING (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND (user_id = current_app_user_id() OR is_app_admin())
            )
        )
        WITH CHECK (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND (user_id = current_app_user_id() OR is_app_admin())
            )
        );
    """)

    # Invitations
        op.execute("""
DROP POLICY IF EXISTS invitations_isolation_policy ON invitations;
    """)
    op.execute("""
CREATE POLICY invitations_isolation_policy ON invitations
        FOR ALL
        USING (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND is_app_admin()
            )
        )
        WITH CHECK (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND is_app_admin()
            )
        );
    """)

    # User Preferences
        op.execute("""
DROP POLICY IF EXISTS user_preferences_isolation_policy ON user_preferences;
    """)
    op.execute("""
CREATE POLICY user_preferences_isolation_policy ON user_preferences
        FOR ALL
        USING (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND user_id = current_app_user_id()
            )
        )
        WITH CHECK (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND user_id = current_app_user_id()
            )
        );
    """)

    # Conversations
        op.execute("""
DROP POLICY IF EXISTS conversations_isolation_policy ON conversations;
    """)
    op.execute("""
CREATE POLICY conversations_isolation_policy ON conversations
        FOR ALL
        USING (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND user_id = current_app_user_id()
            )
        )
        WITH CHECK (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND user_id = current_app_user_id()
            )
        );
    """)

    # Messages
        op.execute("""
DROP POLICY IF EXISTS messages_isolation_policy ON messages;
    """)
    op.execute("""
CREATE POLICY messages_isolation_policy ON messages
        FOR ALL
        USING (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND user_id = current_app_user_id()
            )
        )
        WITH CHECK (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND user_id = current_app_user_id()
            )
        );
    """)

    # User Files
        op.execute("""
DROP POLICY IF EXISTS user_files_isolation_policy ON user_files;
    """)
    op.execute("""
CREATE POLICY user_files_isolation_policy ON user_files
        FOR ALL
        USING (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND user_id = current_app_user_id()
            )
        )
        WITH CHECK (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND user_id = current_app_user_id()
            )
        );
    """)

    # Memory Embeddings
        op.execute("""
DROP POLICY IF EXISTS memory_embeddings_isolation_policy ON memory_embeddings;
    """)
    op.execute("""
CREATE POLICY memory_embeddings_isolation_policy ON memory_embeddings
        FOR ALL
        USING (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND (user_id = current_app_user_id() OR scope = 'tenant')
            )
        )
        WITH CHECK (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND (user_id = current_app_user_id() OR scope = 'tenant')
            )
        );
    """)

    # Token Usage
        op.execute("""
DROP POLICY IF EXISTS token_usage_isolation_policy ON token_usage;
    """)
    op.execute("""
CREATE POLICY token_usage_isolation_policy ON token_usage
        FOR ALL
        USING (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND (user_id = current_app_user_id() OR is_app_admin())
            )
        )
        WITH CHECK (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND (user_id = current_app_user_id() OR is_app_admin())
            )
        );
    """)

    # Audit Logs
        op.execute("""
DROP POLICY IF EXISTS audit_logs_select_policy ON audit_logs;
    """)
    op.execute("""
CREATE POLICY audit_logs_select_policy ON audit_logs
        FOR SELECT
        USING (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND is_app_admin()
            )
        );
    """)
    op.execute("""
DROP POLICY IF EXISTS audit_logs_insert_policy ON audit_logs;
    """)
    op.execute("""
CREATE POLICY audit_logs_insert_policy ON audit_logs
        FOR INSERT
        WITH CHECK (
            is_system_bypass()
            OR tenant_id = current_app_tenant_id()
        );
    """)

    # Tenant Gateway Configs
        op.execute("""
DROP POLICY IF EXISTS tenant_gateway_configs_isolation_policy ON tenant_gateway_configs;
    """)
    op.execute("""
CREATE POLICY tenant_gateway_configs_isolation_policy ON tenant_gateway_configs
        FOR ALL
        USING (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND is_app_admin()
            )
        )
        WITH CHECK (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND is_app_admin()
            )
        );
    """)

    # User Gateway Bindings
        op.execute("""
DROP POLICY IF EXISTS user_gateway_bindings_isolation_policy ON user_gateway_bindings;
    """)
    op.execute("""
CREATE POLICY user_gateway_bindings_isolation_policy ON user_gateway_bindings
        FOR ALL
        USING (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND user_id = current_app_user_id()
            )
        )
        WITH CHECK (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND user_id = current_app_user_id()
            )
        );
    """)

    # Gateway Conversational Sessions
        op.execute("""
DROP POLICY IF EXISTS gateway_conversational_sessions_isolation_policy ON gateway_conversational_sessions;
    """)
    op.execute("""
CREATE POLICY gateway_conversational_sessions_isolation_policy ON gateway_conversational_sessions
        FOR ALL
        USING (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND user_id = current_app_user_id()
            )
        )
        WITH CHECK (
            is_system_bypass()
            OR (
                tenant_id = current_app_tenant_id()
                AND user_id = current_app_user_id()
            )
        );
    """)


def downgrade() -> None:
    for table in TABLES_WITH_RLS:
        op.execute(f"DROP POLICY IF EXISTS {table}_isolation_policy ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.execute("DROP FUNCTION IF EXISTS search_hybrid_memories(UUID, UUID, TEXT, VECTOR, INT, INT);")
    op.execute("DROP FUNCTION IF EXISTS current_app_tenant_id();")
    op.execute("DROP FUNCTION IF EXISTS current_app_user_id();")
    op.execute("DROP FUNCTION IF EXISTS is_app_admin();")
    op.execute("DROP FUNCTION IF EXISTS is_system_bypass();")
