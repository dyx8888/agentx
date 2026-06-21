import { useNavigate } from 'react-router-dom';
import { Button, Result } from 'antd';
import { HomeOutlined } from '@ant-design/icons';

export default function Error404() {
  const navigate = useNavigate();
  return (
    <Result
      status="404"
      title="404"
      subTitle="抱歉，您访问的页面不存在或已被移除。"
      extra={
        <Button type="primary" icon={<HomeOutlined />} onClick={() => navigate('/dashboard')}>
          返回工作台
        </Button>
      }
    />
  );
}