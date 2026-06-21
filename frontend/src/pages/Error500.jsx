import { useNavigate } from 'react-router-dom';
import { Button, Result } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';

export default function Error500() {
  const navigate = useNavigate();
  return (
    <Result
      status="500"
      title="500"
      subTitle="服务器遇到了一些问题，请稍后重试。"
      extra={[
        <Button key="retry" type="primary" icon={<ReloadOutlined />}
          onClick={() => window.location.reload()}>
          刷新页面
        </Button>,
        <Button key="home" onClick={() => navigate('/dashboard')}>
          返回工作台
        </Button>,
      ]}
    />
  );
}