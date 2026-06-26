import { useNavigate } from 'react-router-dom';
import { RocketOutlined } from '@ant-design/icons';

export default function Error404() {
  const navigate = useNavigate();
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-[var(--color-bg-primary)]">
      <div className="text-center">
        <div
          className="w-20 h-20 rounded-[var(--radius-xl)] flex items-center justify-center mx-auto mb-6
            shadow-[var(--shadow-md)]"
          style={{ background: 'var(--gradient-accent)' }}
        >
          <RocketOutlined className="text-3xl text-white" />
        </div>
        <h1 className="text-5xl font-bold text-[var(--color-text-primary)] mb-4">404</h1>
        <p className="text-[var(--font-size-base)] text-[var(--color-text-tertiary)] mb-8 max-w-md">
          抱歉，您访问的页面不存在或已被移除。
        </p>
        <button
          onClick={() => navigate('/chat')}
          className="px-6 py-3 bg-[var(--color-text-primary)] text-white
            rounded-[var(--radius-md)] text-[var(--font-size-sm)] font-medium
            hover:bg-[var(--color-text-secondary)] hover:shadow-[var(--shadow-md)]
            transition-all duration-150"
        >
          返回首页
        </button>
      </div>
    </div>
  );
}