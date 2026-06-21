import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Button, Input, Form, Select, message } from 'antd';
import {
  UserOutlined,
  LockOutlined,
  MailOutlined,
  BankOutlined,
  TagOutlined,
  AppstoreOutlined,
} from '@ant-design/icons';
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
      {/* Left Brand Panel */}
      <div
        className="hidden lg:flex w-[45%] flex-col justify-between p-12 relative overflow-hidden"
        style={{
          background: 'linear-gradient(135deg, #7928ca 0%, #ff0080 50%, #f9cb28 100%)',
        }}
      >
        <div>
          <div className="flex items-center gap-3 mb-8">
            <div className="w-10 h-10 bg-white/20 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold text-lg">A</span>
            </div>
            <span className="text-white text-2xl font-semibold">AgentX</span>
          </div>
        </div>

        <div className="flex-1 flex flex-col justify-center">
          <h1 className="text-5xl font-semibold text-white mb-6 leading-tight">
            开启智能
            <br />
            电商之旅
          </h1>
          <p className="text-xl text-white/80 max-w-md">
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

      {/* Right Register Form */}
      <div className="flex-1 flex items-center justify-center p-8 bg-[var(--color-canvas-soft)] overflow-y-auto">
        <div className="w-full max-w-[440px] py-8">
          <div className="text-center mb-8">
            <h2 className="text-2xl font-semibold text-[var(--color-ink)] mb-2">
              创建账号
            </h2>
            <p className="text-sm text-[var(--color-mute)]">
              填写以下信息，注册 AgentX 账号
            </p>
          </div>

          <div className="bg-white rounded-xl p-8 shadow-[0_4px_12px_rgba(0,0,0,0.08)] border border-[var(--color-hairline)]">
            <Form
              form={form}
              onFinish={handleSubmit}
              layout="vertical"
              size="large"
              scrollToFirstError
            >
              {/* 账号信息 */}
              <div className="mb-4">
                <h3 className="text-sm font-semibold text-[var(--color-ink)] mb-3">
                  账号信息
                </h3>

                <Form.Item
                  name="username"
                  label="用户名"
                  rules={[
                    { required: true, message: '请输入用户名' },
                    { min: 3, message: '用户名至少 3 个字符' },
                    { max: 50, message: '用户名最多 50 个字符' },
                  ]}
                >
                  <Input
                    prefix={<UserOutlined className="text-[var(--color-mute)]" />}
                    placeholder="请输入用户名"
                    autoComplete="username"
                  />
                </Form.Item>

                <Form.Item
                  name="password"
                  label="密码"
                  rules={[
                    { required: true, message: '请输入密码' },
                    { min: 8, message: '密码至少 8 位' },
                  ]}
                >
                  <Input.Password
                    prefix={<LockOutlined className="text-[var(--color-mute)]" />}
                    placeholder="至少 8 位密码"
                    autoComplete="new-password"
                  />
                </Form.Item>

                <Form.Item
                  name="email"
                  label="邮箱（选填）"
                  rules={[
                    { type: 'email', message: '请输入有效的邮箱地址' },
                  ]}
                >
                  <Input
                    prefix={<MailOutlined className="text-[var(--color-mute)]" />}
                    placeholder="example@company.com"
                    autoComplete="email"
                  />
                </Form.Item>
              </div>

              {/* 企业信息 */}
              <div className="mb-4">
                <h3 className="text-sm font-semibold text-[var(--color-ink)] mb-3">
                  企业信息
                </h3>

                <Form.Item
                  name="company_name"
                  label="公司名称"
                  rules={[
                    { required: true, message: '请输入公司名称' },
                    { max: 100, message: '公司名称最多 100 个字符' },
                  ]}
                >
                  <Input
                    prefix={<BankOutlined className="text-[var(--color-mute)]" />}
                    placeholder="请输入公司名称"
                  />
                </Form.Item>

                <Form.Item
                  name="brand_name"
                  label="品牌名称"
                  rules={[
                    { required: true, message: '请输入品牌名称' },
                    { max: 100, message: '品牌名称最多 100 个字符' },
                  ]}
                >
                  <Input
                    prefix={<TagOutlined className="text-[var(--color-mute)]" />}
                    placeholder="请输入品牌名称"
                  />
                </Form.Item>

                <Form.Item
                  name="category"
                  label="行业分类"
                  rules={[
                    { required: true, message: '请选择行业分类' },
                  ]}
                >
                  <Select
                    placeholder="请选择行业分类"
                    options={INDUSTRY_CATEGORIES}
                    suffixIcon={<AppstoreOutlined className="text-[var(--color-mute)]" />}
                  />
                </Form.Item>
              </div>

              {errorMsg && (
                <div className="mb-4 p-3 rounded-lg text-sm bg-[var(--color-error-soft)] text-[var(--color-error)] border border-[var(--color-error)]/20">
                  {errorMsg}
                </div>
              )}

              <Form.Item>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={isLoading}
                  block
                  className="h-11 font-medium"
                  style={{
                    background: 'var(--color-ink)',
                    borderRadius: '8px',
                  }}
                >
                  注册
                </Button>
              </Form.Item>
            </Form>

            <div className="mt-4 text-center text-sm text-[var(--color-mute)]">
              已有账号？
              <Link
                to="/login"
                className="ml-1 text-[var(--color-link)] hover:text-[var(--color-link-deep)] font-medium"
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