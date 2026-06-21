import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { Button, Input, Form, message } from 'antd';
import { UserOutlined, LockOutlined } from '@ant-design/icons';
import { login as loginApi } from '@/api/auth';
import { useAuth } from '@/lib/AuthContext';

export default function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [form] = Form.useForm();
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const handleSubmit = async (values) => {
    setIsLoading(true);
    setErrorMsg('');
    try {
      const data = await loginApi(values.username, values.password);
      if (data.access_token) {
        await login(data.access_token, data.refresh_token || null);
        message.success('登录成功');
        navigate('/chat');
      } else {
        setErrorMsg('未获取到有效的访问令牌');
      }
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || '登录失败';
      setErrorMsg(msg === 'Incorrect username or password' ? '用户名或密码错误' : msg);
    } finally {
      setIsLoading(false);
    }
  };

  const handleDemoLogin = async () => {
    setIsLoading(true);
    setErrorMsg('');
    try {
      const data = await loginApi('demo', 'demo123456');
      if (data.access_token) {
        await login(data.access_token, data.refresh_token || null);
        message.success('演示账号登录成功');
        navigate('/chat');
      }
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || '登录失败';
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
          background: 'linear-gradient(135deg, #007cf0 0%, #00dfd8 50%, #7928ca 100%)',
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
            数字员工
            <br />
            派遣平台
          </h1>
          <p className="text-xl text-white/80 max-w-md">
            用AI重塑电商运营，让每个人拥有专属数字团队
          </p>
        </div>

        <div>
          <div className="border-t border-white/20 pt-6">
            <p className="text-sm text-white/60">已有超过 10,000+ 企业信赖我们</p>
          </div>
        </div>
      </div>

      {/* Right Login Form */}
      <div className="flex-1 flex items-center justify-center p-8 bg-[var(--color-canvas-soft)]">
        <div className="w-full max-w-[400px]">
          <div className="text-center mb-8">
            <h2 className="text-2xl font-semibold text-[var(--color-ink)] mb-2">欢迎回来</h2>
            <p className="text-sm text-[var(--color-mute)]">
              请输入您的账号信息登录系统
            </p>
          </div>

          <div className="bg-white rounded-xl p-8 shadow-[0_4px_12px_rgba(0,0,0,0.08)] border border-[var(--color-hairline)]">
            <Form form={form} onFinish={handleSubmit} layout="vertical" size="large">
              <Form.Item
                name="username"
                rules={[
                  { required: true, message: '请输入用户名' },
                  { min: 1, message: '用户名不能为空' },
                ]}
              >
                <Input
                  prefix={<UserOutlined className="text-[var(--color-mute)]" />}
                  placeholder="用户名"
                  className="h-11"
                  autoComplete="username"
                />
              </Form.Item>

              <Form.Item
                name="password"
                rules={[
                  { required: true, message: '请输入密码' },
                  { min: 8, message: '密码至少 8 位' },
                ]}
              >
                <Input.Password
                  prefix={<LockOutlined className="text-[var(--color-mute)]" />}
                  placeholder="密码"
                  className="h-11"
                  autoComplete="current-password"
                />
              </Form.Item>

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
                  登录
                </Button>
              </Form.Item>
            </Form>

            <div className="relative my-4">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-[var(--color-hairline)]" />
              </div>
              <div className="relative flex justify-center text-xs">
                <span className="px-2 bg-white text-[var(--color-mute)]">或</span>
              </div>
            </div>

            <Button
              block
              onClick={handleDemoLogin}
              loading={isLoading}
              className="h-11 font-medium"
              style={{
                border: '1px solid var(--color-hairline)',
                borderRadius: '8px',
                color: 'var(--color-ink)',
              }}
            >
              演示账号登录
            </Button>

            <div className="mt-6 text-center text-sm text-[var(--color-mute)]">
              还没有账号？
              <Link
                to="/register"
                className="ml-1 text-[var(--color-link)] hover:text-[var(--color-link-deep)] font-medium"
              >
                立即注册
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}