import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { message } from 'antd';
import { RocketOutlined, LoadingOutlined } from '@ant-design/icons';
import { login as loginApi } from '@/api/auth';
import { useAuth } from '@/lib/AuthContext';

export default function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const doLogin = async (user, pass) => {
    setIsLoading(true);
    setErrorMsg('');
    try {
      const data = await loginApi(user, pass);
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

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!username.trim()) { setErrorMsg('请输入用户名'); return; }
    if (!password || password.length < 8) { setErrorMsg('密码至少 8 位'); return; }
    doLogin(username, password);
  };

  const handleDemoLogin = async () => {
    setUsername('demo');
    setPassword('demo123456');
    await doLogin('demo', 'demo123456');
  };

  return (
    <div className="min-h-screen flex items-center justify-center relative overflow-hidden bg-gray-50">
      {/* Decorative gradient blobs */}
      <div className="absolute top-[-20%] right-[-10%] w-[600px] h-[600px] rounded-full opacity-20 pointer-events-none"
        style={{ background: 'radial-gradient(circle, #6366f1 0%, transparent 70%)' }} />
      <div className="absolute bottom-[-10%] left-[-5%] w-[400px] h-[400px] rounded-full opacity-10 pointer-events-none"
        style={{ background: 'radial-gradient(circle, #8b5cf6 0%, transparent 70%)' }} />

      {/* Card */}
      <div className="relative max-w-[460px] w-[90vw] p-10 bg-white
        rounded-3xl shadow-lg animate-slide-up">

        {/* Brand — single row */}
        <div className="flex items-center gap-4 mb-10">
          <div className="w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0 shadow-sm"
            style={{ background: 'linear-gradient(135deg, #6366f1, #8b5cf6)' }}>
            <RocketOutlined className="text-lg text-white" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900 tracking-tight leading-tight">
              AgentX <span className="text-sm font-medium text-gray-500">AI 工作助手</span>
            </h1>
          </div>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label className="block text-xs font-medium text-gray-500 mb-2">用户名</label>
            <input
              value={username}
              onChange={(e) => { setUsername(e.target.value); setErrorMsg(''); }}
              placeholder="请输入用户名"
              autoComplete="username"
              className="w-full h-12 px-4 text-sm text-gray-900 bg-white
                border border-gray-200 rounded-xl
                placeholder:text-gray-400
                outline-none transition-all duration-150
                focus:border-gray-400 focus:ring-2 focus:ring-gray-200/50"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-2">密码</label>
            <input
              type="password"
              value={password}
              onChange={(e) => { setPassword(e.target.value); setErrorMsg(''); }}
              placeholder="请输入密码"
              autoComplete="current-password"
              className="w-full h-12 px-4 text-sm text-gray-900 bg-white
                border border-gray-200 rounded-xl
                placeholder:text-gray-400
                outline-none transition-all duration-150
                focus:border-gray-400 focus:ring-2 focus:ring-gray-200/50"
            />
          </div>

          {errorMsg && (
            <p className="text-xs text-red-500 -mt-1">{errorMsg}</p>
          )}

          <button
            type="submit"
            disabled={isLoading}
            className="w-full h-12 rounded-xl text-sm font-medium
              bg-gray-900 text-white
              hover:bg-gray-800 hover:shadow-sm
              transition-all duration-150
              disabled:opacity-50 disabled:cursor-not-allowed
              flex items-center justify-center gap-2"
          >
            {isLoading && <LoadingOutlined className="animate-spin" />}
            {isLoading ? '登录中...' : '登 录'}
          </button>
        </form>
      </div>

      {/* Demo login — tiny, bottom-right corner of screen */}
      <button
        onClick={handleDemoLogin}
        disabled={isLoading}
        className="absolute bottom-6 right-6 text-xs text-gray-400
          hover:text-gray-700 transition-colors
          disabled:opacity-30 disabled:cursor-not-allowed"
      >
        演示账号登录
      </button>
    </div>
  );
}