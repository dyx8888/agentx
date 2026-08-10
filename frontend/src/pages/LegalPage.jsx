import { Link } from 'react-router-dom';
import { ArrowLeft, FileText, ShieldCheck } from 'lucide-react';

const LEGAL_CONTENT = {
  terms: {
    title: '服务条款',
    icon: FileText,
    updatedAt: '2026-08-09',
    sections: [
      {
        heading: '服务范围',
        body: 'AgentX 提供电商运营辅助能力，包括达人数据管理、知识库问答、内容草稿生成、平台授权管理和运营分析。系统输出用于辅助判断，不替代人工审核或商业决策。',
      },
      {
        heading: '数据真实性',
        body: '业务结果必须基于用户导入、授权平台、官方 API 或明确标注的公开来源数据。未连接真实数据源时，系统应提示数据不可用，不应以 mock、demo 或 fallback 数据冒充真实结果。',
      },
      {
        heading: '高风险操作',
        body: '私信外发、内容发布、广告预算调整、删除数据、扣费、修改密码等高风险动作必须经过用户明确确认。系统默认只生成待审核草稿，不自动执行外部副作用。',
      },
      {
        heading: '用户责任',
        body: '用户应确保上传、导入或授权的数据来源合法，并在对外沟通、投放、发布前复核内容准确性、合规性和商业授权范围。',
      },
    ],
  },
  privacy: {
    title: '隐私政策',
    icon: ShieldCheck,
    updatedAt: '2026-08-09',
    sections: [
      {
        heading: '收集的信息',
        body: '系统会处理账号信息、公司资料、达人数据、知识库文档、平台授权状态、对话内容、操作记录和必要的模型调用元数据，用于提供租户内业务功能。',
      },
      {
        heading: '数据隔离',
        body: '业务数据按 company_id 进行租户隔离。跨企业读取、搜索或展示数据应被拒绝；缺少企业上下文时，系统应避免返回可能混淆来源的业务结果。',
      },
      {
        heading: '敏感凭证',
        body: '平台凭证、API Key 和访问令牌应加密存储并以脱敏形式展示。前端采用 httpOnly cookie 管理登录态，避免在浏览器脚本中读取访问令牌。',
      },
      {
        heading: '数据来源标注',
        body: '当结果来自人工导入、公开网页、缓存快照、官方 API 或合作方 API 时，界面和对话输出应尽量展示来源说明，帮助用户判断可信度。',
      },
    ],
  },
};

export default function LegalPage({ type = 'terms' }) {
  const content = LEGAL_CONTENT[type] || LEGAL_CONTENT.terms;
  const Icon = content.icon;

  return (
    <main className="min-h-svh bg-background px-6 py-10 text-foreground">
      <div className="mx-auto max-w-3xl">
        <Link
          to="/login"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="size-4" />
          返回登录
        </Link>

        <header className="mt-8 border-b border-border pb-6">
          <div className="flex items-center gap-3">
            <span className="flex size-11 items-center justify-center rounded-xl bg-primary text-primary-foreground">
              <Icon className="size-5" />
            </span>
            <div>
              <h1 className="font-heading text-3xl font-semibold">{content.title}</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                最近更新：{content.updatedAt}
              </p>
            </div>
          </div>
        </header>

        <section className="mt-8 space-y-6">
          {content.sections.map((section) => (
            <article key={section.heading}>
              <h2 className="text-base font-semibold">{section.heading}</h2>
              <p className="mt-2 text-sm leading-7 text-muted-foreground">
                {section.body}
              </p>
            </article>
          ))}
        </section>
      </div>
    </main>
  );
}
