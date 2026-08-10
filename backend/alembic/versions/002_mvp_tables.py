"""add 7 new tables for MVP

Revision ID: 002_mvp_tables
Revises: 001_initial
Create Date: 2026-06-20

Add 7 new tables for AgentX MVP:
- conversations (对话会话)
- messages (对话消息)
- kol_profiles (达人档案)
- kol_search_history (搜索历史)
- content_scripts (内容脚本)
- logistics_tracking (物流跟踪)
- review_approvals (审批记录)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '002_mvp_tables'
down_revision: str | None = '001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ============================================
    # 1. conversations — 对话会话表
    # ============================================
    op.create_table(
        'conversations',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(200), nullable=False, server_default='新对话'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('message_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_conversations_id', 'conversations', ['id'])
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'])
    op.create_index('ix_conversations_company_id', 'conversations', ['company_id'])
    op.create_index('ix_conversations_status', 'conversations', ['status'])

    # ============================================
    # 2. messages — 对话消息表
    # ============================================
    op.create_table(
        'messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_type', sa.String(30), nullable=False, server_default='text'),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column('references_json', sa.Text(), nullable=True),
        sa.Column('trace_id', sa.String(100), nullable=True),
        sa.Column('token_count', sa.Integer(), nullable=True),
        sa.Column('sequence_num', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_messages_id', 'messages', ['id'])
    op.create_index('ix_messages_conversation_id', 'messages', ['conversation_id'])
    op.create_index('ix_messages_role', 'messages', ['role'])
    op.create_index('ix_messages_trace_id', 'messages', ['trace_id'])

    # ============================================
    # 3. kol_profiles — 达人档案表
    # ============================================
    op.create_table(
        'kol_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('platform', sa.String(50), nullable=False),
        sa.Column('platform_uid', sa.String(200), nullable=True),
        sa.Column('followers', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('engagement_rate', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('category', sa.String(100), nullable=False, server_default='其他'),
        sa.Column('sub_category', sa.String(100), nullable=True),
        sa.Column('avg_views', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('avg_likes', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('avg_comments', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('avg_shares', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('price_range_low', sa.Integer(), nullable=True),
        sa.Column('price_range_high', sa.Integer(), nullable=True),
        sa.Column('location', sa.String(200), nullable=True),
        sa.Column('verified', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('bio', sa.Text(), nullable=True),
        sa.Column('avatar_url', sa.Text(), nullable=True),
        sa.Column('contact_info', sa.Text(), nullable=True),
        sa.Column('data_source', sa.String(50), nullable=False, server_default='manual'),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_kol_profiles_id', 'kol_profiles', ['id'])
    op.create_index('ix_kol_profiles_company_id', 'kol_profiles', ['company_id'])
    op.create_index('ix_kol_profiles_platform', 'kol_profiles', ['platform'])
    op.create_index('ix_kol_profiles_category', 'kol_profiles', ['category'])
    op.create_index('ix_kol_profiles_name', 'kol_profiles', ['name'])

    # ============================================
    # 4. kol_search_history — 达人搜索历史表
    # ============================================
    op.create_table(
        'kol_search_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('query', sa.String(500), nullable=False),
        sa.Column('rewritten_query', sa.String(500), nullable=True),
        sa.Column('platform_filter', sa.String(50), nullable=True),
        sa.Column('category_filter', sa.String(100), nullable=True),
        sa.Column('result_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('clicked_kol_ids', sa.Text(), nullable=True),
        sa.Column('search_duration_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_kol_search_history_id', 'kol_search_history', ['id'])
    op.create_index('ix_kol_search_history_user_id', 'kol_search_history', ['user_id'])
    op.create_index('ix_kol_search_history_company_id', 'kol_search_history', ['company_id'])

    # ============================================
    # 5. content_scripts — 内容脚本表
    # ============================================
    op.create_table(
        'content_scripts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('conversation_id', sa.Integer(), nullable=True),
        sa.Column('message_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(300), nullable=False),
        sa.Column('script_type', sa.String(50), nullable=False),
        sa.Column('platform', sa.String(50), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('segments_json', sa.Text(), nullable=True),
        sa.Column('products_json', sa.Text(), nullable=True),
        sa.Column('kol_name', sa.String(200), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='draft'),
        sa.Column('review_comment', sa.Text(), nullable=True),
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_content_scripts_id', 'content_scripts', ['id'])
    op.create_index('ix_content_scripts_company_id', 'content_scripts', ['company_id'])
    op.create_index('ix_content_scripts_user_id', 'content_scripts', ['user_id'])
    op.create_index('ix_content_scripts_status', 'content_scripts', ['status'])

    # ============================================
    # 6. logistics_tracking — 物流跟踪表
    # ============================================
    op.create_table(
        'logistics_tracking',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('tracking_number', sa.String(100), nullable=False),
        sa.Column('carrier', sa.String(50), nullable=False),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('status_detail', sa.String(200), nullable=True),
        sa.Column('origin', sa.String(200), nullable=True),
        sa.Column('destination', sa.String(200), nullable=True),
        sa.Column('estimated_delivery', sa.DateTime(), nullable=True),
        sa.Column('actual_delivery', sa.DateTime(), nullable=True),
        sa.Column('kol_name', sa.String(200), nullable=True),
        sa.Column('sample_name', sa.String(300), nullable=True),
        sa.Column('tracking_history', sa.Text(), nullable=True),
        sa.Column('last_checked_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_logistics_tracking_id', 'logistics_tracking', ['id'])
    op.create_index('ix_logistics_tracking_company_id', 'logistics_tracking', ['company_id'])
    op.create_index('ix_logistics_tracking_tracking_number', 'logistics_tracking', ['tracking_number'])
    op.create_index('ix_logistics_tracking_status', 'logistics_tracking', ['status'])

    # ============================================
    # 7. review_approvals — 审批记录表
    # ============================================
    op.create_table(
        'review_approvals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('company_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('content_type', sa.String(30), nullable=False),
        sa.Column('content_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(30), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('previous_status', sa.String(30), nullable=True),
        sa.Column('new_status', sa.String(30), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_review_approvals_id', 'review_approvals', ['id'])
    op.create_index('ix_review_approvals_company_id', 'review_approvals', ['company_id'])
    op.create_index('ix_review_approvals_content_type', 'review_approvals', ['content_type'])
    op.create_index('ix_review_approvals_content_id', 'review_approvals', ['content_id'])


def downgrade() -> None:
    # 按依赖顺序反序删除表（先删除有外键引用的表）
    op.drop_table('review_approvals')
    op.drop_table('logistics_tracking')
    op.drop_table('content_scripts')
    op.drop_table('kol_search_history')
    op.drop_table('kol_profiles')
    op.drop_table('messages')
    op.drop_table('conversations')
