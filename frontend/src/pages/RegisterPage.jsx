import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Form, message } from 'antd';
import { RocketOutlined } from '@ant-design/icons';
import { register as registerApi } from '@/api/auth';

const INDUSTRY_CATEGORIES = [
  { value: 'meizhuang', label: '美妆护肤' },
  { value: 'fushi', label: '服饰鞋包' },
  { value: 'shipin', label: '食品饮料' },
  { value: 'jiaju', label: '家居百货' },
  { value: '3c', label: '3C 数码' },
  { value: 'muying', label: '母婴用品' },
  { value: 'yundong', label: '运动户外' },
  { value: 'jiadian', label: '家用电器' },
  { value: 'qiche', label: '汽车用品' },
  { value: 'yiyao', label: '医药健康' },
  { value: 'wenju', label: '文具办公' },
  { value: 'chongwu', label: '宠物用品' },
  { value: 'qita', label: '其他' },
];

export default function RegisterPage() {
  const navigate = useNavigate();
  const [form] = Form.useForm();
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const handleSubmit = async (values) => {
    setIsLoading(true);
    setErrorMsg('');
    try {
      await registerApi(values);
      message.success('注册成功，请登录');
      navigate('/login');
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || '注册失败';
      setErrorMsg(msg);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen">
      {/* Left panel — gradient accent */}
      <div
        className="hidden lg:flex w-[45%] flex-col justify-between p-12 relative overflow-hidden"
        style={{ background: 'var(--gradient-accent)' }}
      >
        <div>
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-white/25 rounded-[var(--radius-md)] flex items-center justify-center">
              <RocketOutlined className="text-white" />
            </div>
            <span className="text-white text-xl font-semibold">AgentX</span>
          </div>
        </div>

        <div className="flex-1 flex flex-col justify-center">
          <h1 className="text-4xl font-semibold text-white mb-6 leading-tight">
            开启智能
            <br />
            电商之旅
          </h1>
          <p className="text-lg text-white/80 max-w-md">
            注册 AgentX，即刻拥有专属 AI 数字团队
          </p>
        </div>

        <div>
          <div className="border-t border-white/20 pt-6">
            <p className="text-sm text-white/60">
              免费注册，无需信用卡
            </p>
          </div>
        </div>
      </div>

      {/* Right panel — form */}
      <div className="flex-1 flex items-center justify-center p-8 bg-[var(--color-bg-primary)] overflow-y-auto">
        <div className="w-full max-w-[440px] py-8">
          <div className="text-center mb-8">
            <h2 className="text-[var(--font-size-xl)] font-semibold text-[var(--color-text-primary)] mb-2">
              创建账号
            </h2>
            <p className="text-[var(--font-size-sm)] text-[var(--color-text-tertiary)]">
              填写以下信息，注册 AgentX 账号
            </p>
          </div>

          <div className="bg-[var(--color-bg-surface)] rounded-[var(--radius-2xl)] p-8 shadow-[var(--shadow-card)]">
            <Form
              form={form}
              onFinish={handleSubmit}
              layout="vertical"
              scrollToFirstError
            >
              <div className="mb-6">
                <h3 className="text-[var(--font-size-xs)] font-semibold text-[var(--color-text-tertiary)] uppercase tracking-wider mb-4">
                  账号信息
                </h3>

                <Form.Item
                  name="username"
                  label={<span className="text-[var(--font-size-xs)] font-medium text-[var(--color-text-secondary)]">用户名</span>}
                  rules={[
                    { required: true, message: '请输入用户名' },
                    { min: 3, message: '用户名至少 3 个字符' },
                    { max: 50, message: '用户名最多 50 个字符' },
                  ]}
                >
                  <input
                    placeholder="请输入用户名"
                    autoComplete="username"
                    className="w-full px-4 py-3 border border-[var(--color-border)] rounded-[var(--radius-md)]
                      text-[var(--font-size-sm)] text-[var(--color-text-primary)] bg-[var(--color-bg-surface)]
                      placeholder:text-[var(--color-text-disabled)] outline-none transition-all duration-150
                      focus:border-[var(--color-accent)] focus:shadow-[var(--shadow-input)]"
                  />
                </Form.Item>

                <Form.Item
                  name="password"
                  label={<span className="text-[var(--font-size-xs)] font-medium text-[var(--color-text-secondary)]">密码</span>}
                  rules={[
                    { required: true, message: '请输入密码' },
                    { min: 8, message: '密码至少 8 位' },
                  ]}
                >
                  <input
                    type="password"
                    placeholder="至少 8 位密码"
                    autoComplete="new-password"
                    className="w-full px-4 py-3 border border-[var(--color-border)] rounded-[var(--radius-md)]
                      text-[var(--font-size-sm)] text-[var(--color-text-primary)] bg-[var(--color-bg-surface)]
                      placeholder:text-[var(--color-text-disabled)] outline-none transition-all duration-150
                      focus:border-[var(--color-accent)] focus:shadow-[var(--shadow-input)]"
                  />
                </Form.Item>

                <Form.Item
                  name="email"
                  label={<span className="text-[var(--font-size-xs)] font-medium text-[var(--color-text-secondary)]">邮箱（选填）</span>}
                  rules={[
                    { type: 'email', message: '请输入有效的邮箱地址' },
                  ]}
                >
                  <input
                    type="email"
                    placeholder="example@company.com"
                    autoComplete="email"
                    className="w-full px-4 py-3 border border-[var(--color-border)] rounded-[var(--radius-md)]
                      text-[var(--font-size-sm)] text-[var(--color-text-primary)] bg-[var(--color-bg-surface)]
                      placeholder:text-[var(--color-text-disabled)] outline-none transition-all duration-150
                      focus:border-[var(--color-accent)] focus:shadow-[var(--shadow-input)]"
                  />
                </Form.Item>
              </div>

              <div className="mb-6">
                <h3 className="text-[var(--font-size-xs)] font-semibold text-[var(--color-text-tertiary)] uppercase tracking-wider mb-4">
                  企业信息
                </h3>

                <Form.Item
                  name="company_name"
                  label={<span className="text-[var(--font-size-xs)] font-medium text-[var(--color-text-secondary)]">公司名称</span>}
                  rules={[
                    { required: true, message: '请输入公司名称' },
                    { max: 100, message: '公司名称最多 100 个字符' },
                  ]}
                >
                  <input
                    placeholder="请输入公司名称"
                    className="w-full px-4 py-3 border border-[var(--color-border)] rounded-[var(--radius-md)]
                      text-[var(--font-size-sm)] text-[var(--color-text-primary)] bg-[var(--color-bg-surface)]
                      placeholder:text-[var(--color-text-disabled)] outline-none transition-all duration-150
                      focus:border-[var(--color-accent)] focus:shadow-[var(--shadow-input)]"
                  />
                </Form.Item>

                <Form.Item
                  name="brand_name"
                  label={<span className="text-[var(--font-size-xs)] font-medium text-[var(--color-text-secondary)]">品牌名称</span>}
                  rules={[
                    { required: true, message: '请输入品牌名称' },
                    { max: 100, message: '品牌名称最多 100 个字符' },
                  ]}
                >
                  <input
                    placeholder="请输入品牌名称"
                    className="w-full px-4 py-3 border border-[var(--color-border)] rounded-[var(--radius-md)]
                      text-[var(--font-size-sm)] text-[var(--color-text-primary)] bg-[var(--color-bg-surface)]
                      placeholder:text-[var(--color-text-disabled)] outline-none transition-all duration-150
                      focus:border-[var(--color-accent)] focus:shadow-[var(--shadow-input)]"
                  />
                </Form.Item>

                <Form.Item
                  name="category"
                  label={<span className="text-[var(--font-size-xs)] font-medium text-[var(--color-text-secondary)]">行业分类</span>}
                  rules={[
                    { required: true, message: '请选择行业分类' },
                  ]}
                >
                  <select
                    className="w-full px-4 py-3 border border-[var(--color-border)] rounded-[var(--radius-md)]
                      text-[var(--font-size-sm)] text-[var(--color-text-primary)] bg-[var(--color-bg-surface)]
                      outline-none transition-all duration-150 appearance-none
                      focus:border-[var(--color-accent)] focus:shadow-[var(--shadow-input)]"
                  >
                    <option value="">请选择行业分类</option>
                    {INDUSTRY_CATEGORIES.map((cat) => (
                      <option key={cat.value} value={cat.value}>{cat.label}</option>
                    ))}
                  </select>
                </Form.Item>
              </div>

              {errorMsg && (
                <div className="mb-6 p-4 rounded-[var(--radius-md)] text-[var(--font-size-sm)] 
                  bg-[var(--color-error-light)] text-[var(--color-error)] border border-[var(--color-error)]/20">
                  {errorMsg}
                </div>
              )}

              <Form.Item>
                <button
                  type="submit"
                  disabled={isLoading}
                  className="w-full py-3 px-4 border-none rounded-[var(--radius-md)]
                    text-[var(--font-size-sm)] font-medium cursor-pointer
                    transition-all duration-150
                    bg-[var(--color-text-primary)] text-white
                    hover:bg-[var(--color-text-secondary)] hover:shadow-[var(--shadow-md)]
                    disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isLoading ? '注册中...' : '注 册'}
                </button>
              </Form.Item>
            </Form>

            <div className="mt-6 text-center text-[var(--font-size-xs)] text-[var(--color-text-tertiary)]">
              已有账号？
              <Link
                to="/login"
                className="ml-1 text-[var(--color-accent)] hover:text-[var(--color-accent-hover)] font-medium"
              >
                立即登录
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}