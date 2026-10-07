"""One-time adoption of schema upgrades applied by legacy init_db versions."""

from sqlalchemy import Connection, text


def upgrade(connection: Connection) -> None:
    connection.execute(text("ALTER TABLE preparation_task ADD COLUMN IF NOT EXISTS practice_status VARCHAR(20) NOT NULL DEFAULT 'idle'"))
    connection.execute(text("ALTER TABLE preparation_task ADD COLUMN IF NOT EXISTS practice_error TEXT"))
    connection.execute(text("ALTER TABLE position ADD COLUMN IF NOT EXISTS intel_revision INTEGER NOT NULL DEFAULT 0"))
    connection.execute(text("ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS user_message_id INTEGER REFERENCES intel_chat_message(id) ON DELETE CASCADE"))
    connection.execute(
        text(
            "ALTER TYPE application_status ADD VALUE IF NOT EXISTS '测评' "
            "BEFORE '笔试'"
        )
    )
    connection.execute(
        text(
            "ALTER TYPE application_status ADD VALUE IF NOT EXISTS 'AI面' "
            "BEFORE '一面'"
        )
    )
    connection.execute(
        text(
            "ALTER TYPE node_type ADD VALUE IF NOT EXISTS '测评' "
            "BEFORE '笔试'"
        )
    )
    connection.execute(
        text(
            "ALTER TYPE node_type ADD VALUE IF NOT EXISTS 'AI面' "
            "BEFORE '一面'"
        )
    )
    connection.execute(
        text(
            "ALTER TYPE planner_session_status ADD VALUE IF NOT EXISTS '已完成' "
            "BEFORE '已丢弃'"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE timeline_node "
            "ADD COLUMN IF NOT EXISTS ends_at TIMESTAMPTZ"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE resume_profile "
            "ADD COLUMN IF NOT EXISTS file_name VARCHAR(255)"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE timeline_node "
            "ADD COLUMN IF NOT EXISTS time_mode VARCHAR(20) "
            "NOT NULL DEFAULT '固定时间'"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE timeline_node "
            "ADD COLUMN IF NOT EXISTS title VARCHAR(200)"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE timeline_node "
            "ADD COLUMN IF NOT EXISTS detail TEXT"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_timeline_node_scheduled_at "
            "ON timeline_node (scheduled_at)"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE intel_session "
            "ADD COLUMN IF NOT EXISTS progress_payload JSONB"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE position "
            "ADD COLUMN IF NOT EXISTS intel_insight JSONB"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE intel_session "
            "ADD COLUMN IF NOT EXISTS round_type VARCHAR(20) NOT NULL DEFAULT '未注明'"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE intel_session "
            "ADD COLUMN IF NOT EXISTS image_texts JSONB NOT NULL DEFAULT '[]'::jsonb"
        )
    )
    for field in ("interview_provider", "planner_provider", "briefing_provider", "vision_provider"):
        connection.execute(text(f"ALTER TABLE llm_settings ADD COLUMN IF NOT EXISTS {field} VARCHAR(50)"))
    connection.execute(
        text(
            "ALTER TABLE interview_intel "
            "ADD COLUMN IF NOT EXISTS title VARCHAR(200) NOT NULL DEFAULT '未命名面经'"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE interview_intel "
            "ADD COLUMN IF NOT EXISTS round_type VARCHAR(20) NOT NULL DEFAULT '未注明'"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE interview_intel "
            "ADD COLUMN IF NOT EXISTS provider VARCHAR(50) NOT NULL DEFAULT 'qwen'"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE intel_chat_message "
            "ADD COLUMN IF NOT EXISTS status VARCHAR(20) "
            "NOT NULL DEFAULT '已完成'"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE parse_session "
            "ADD COLUMN IF NOT EXISTS llm_snapshot TEXT"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE parse_session "
            "ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(40)"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE intel_session "
            "ADD COLUMN IF NOT EXISTS llm_snapshot TEXT"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE intel_session "
            "ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(40)"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE planner_session "
            "ADD COLUMN IF NOT EXISTS llm_snapshot TEXT"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE planner_session "
            "ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(40)"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE intel_chat_message "
            "ADD COLUMN IF NOT EXISTS provider VARCHAR(50)"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE intel_chat_message "
            "ADD COLUMN IF NOT EXISTS llm_snapshot TEXT"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE intel_chat_message "
            "ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(40)"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE agent_run "
            "ADD COLUMN IF NOT EXISTS error_kind VARCHAR(50)"
        )
    )
    connection.execute(text("ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS queue_task_id VARCHAR(200)"))
    connection.execute(text("ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS attempt INTEGER NOT NULL DEFAULT 0"))
    connection.execute(text("ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ"))
    connection.execute(text("ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS insufficient_data BOOLEAN NOT NULL DEFAULT FALSE"))
    connection.execute(text("ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS used_tools JSONB NOT NULL DEFAULT '[]'::jsonb"))
    connection.execute(text("ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS answer_mode VARCHAR(30)"))
    connection.execute(text("ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS search_status VARCHAR(30)"))
    connection.execute(text("ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS last_error_kind VARCHAR(50)"))
    connection.execute(text("ALTER TABLE agent_run ADD COLUMN IF NOT EXISTS last_error_message TEXT"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_run_queue_task_id ON agent_run (queue_task_id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_agent_run_heartbeat_at ON agent_run (heartbeat_at)"))
    connection.execute(text("ALTER TABLE preparation_task ADD COLUMN IF NOT EXISTS evidence JSONB NOT NULL DEFAULT '[]'::jsonb"))
    connection.execute(text("ALTER TABLE preparation_task ADD COLUMN IF NOT EXISTS category VARCHAR(30) NOT NULL DEFAULT '八股'"))
    connection.execute(text("UPDATE preparation_task SET category = CASE WHEN category IN ('简历提问', '简历内容') THEN '简历内容' ELSE '八股' END"))
    connection.execute(text("ALTER TABLE preparation_task ADD COLUMN IF NOT EXISTS planned_date DATE"))
    connection.execute(text("ALTER TABLE preparation_task ADD COLUMN IF NOT EXISTS answer_payload JSONB"))
    connection.execute(text("ALTER TABLE preparation_task ADD COLUMN IF NOT EXISTS user_answer TEXT"))
    connection.execute(text("ALTER TABLE preparation_task ADD COLUMN IF NOT EXISTS feedback_payload JSONB"))
    connection.execute(text("ALTER TABLE preparation_task ALTER COLUMN estimated_minutes DROP NOT NULL"))
    connection.execute(text("ALTER TABLE llm_provider_config ADD COLUMN IF NOT EXISTS supports_tools BOOLEAN"))
    connection.execute(text("ALTER TABLE llm_provider_config ADD COLUMN IF NOT EXISTS supports_json BOOLEAN"))
    connection.execute(text("ALTER TABLE llm_provider_config ADD COLUMN IF NOT EXISTS supports_streaming BOOLEAN"))
    connection.execute(text("ALTER TABLE llm_provider_config ADD COLUMN IF NOT EXISTS supports_vision BOOLEAN"))
    connection.execute(text("ALTER TABLE llm_provider_config ADD COLUMN IF NOT EXISTS capability_checked_at TIMESTAMPTZ"))
    connection.execute(text("ALTER TABLE intel_session ADD COLUMN IF NOT EXISTS queue_task_id VARCHAR(200)"))
    connection.execute(text("ALTER TABLE intel_session ADD COLUMN IF NOT EXISTS supplement_web BOOLEAN NOT NULL DEFAULT FALSE"))
    connection.execute(text("ALTER TABLE llm_settings ADD COLUMN IF NOT EXISTS encrypted_search_api_key TEXT"))
    connection.execute(text("ALTER TABLE llm_settings ADD COLUMN IF NOT EXISTS search_endpoint TEXT"))
    connection.execute(text("ALTER TABLE llm_settings ADD COLUMN IF NOT EXISTS search_tool_name VARCHAR(100)"))
    connection.execute(text("ALTER TABLE planner_session ADD COLUMN IF NOT EXISTS queue_task_id VARCHAR(200)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_intel_session_queue_task_id ON intel_session (queue_task_id)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_planner_session_queue_task_id ON planner_session (queue_task_id)"))
    connection.execute(
        text(
            "ALTER TABLE preparation_task "
            "ALTER COLUMN scheduled_at DROP NOT NULL"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE preparation_task "
            "ALTER COLUMN ends_at DROP NOT NULL"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE preparation_task "
            "ADD COLUMN IF NOT EXISTS priority INTEGER NOT NULL DEFAULT 3"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE preparation_task "
            "ADD COLUMN IF NOT EXISTS action_index INTEGER"
        )
    )
    connection.execute(
        text(
            "ALTER TABLE preparation_task "
            "ADD COLUMN IF NOT EXISTS deferred_until TIMESTAMPTZ"
        )
    )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uq_preparation_task_session_action "
            "ON preparation_task (planner_session_id, action_index) "
            "WHERE action_index IS NOT NULL"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_preparation_task_deferred_until "
            "ON preparation_task (deferred_until)"
        )
    )
