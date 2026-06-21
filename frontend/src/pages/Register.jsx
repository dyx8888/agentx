import React, { useState } from 'react';
import { Form, Input, Select, Button, message, Checkbox, Card } from 'antd';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { UserOutlined, ShopOutlined } from '@ant-design/icons';

const Register = () => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const onFinish = async (values) => {
    setLoading(true);
    try {
      // 先创建公司
      const companyRes = await axios.post('/api/admin/companies', {
        name: values.companyName,
        brand_name: values.brandName,
        category: values.category,
        platforms: values.platforms.join(',')
      });

      if (companyRes.data && companyRes.data.id) {
        // 再注册管理员用户
        const registerRes = await axios.post('/api/auth/users/register', {
          username: values.adminUsername,
          password: values.adminPassword,
          company_id: companyRes.data.id
        });

        if (registerRes.data && registerRes.data.id) {
          message.success('公司注册成功！请登录使用系统。');
          navigate('/login');
        } else {
          message.error('用户注册失败，请重试。');
        }
      } else {
        message.error('公司创建失败，请重试。');
      }
    } catch (error) {
      console.error('Registration error:', error);
      if (error.response?.status === 401) {
        message.error('需要管理员权限创建公司，请联系系统管理员。');
      } else {
        message.error('注册失败，请检查网络连接或联系管理员。');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ 
      minHeight: '100vh', 
      display: 'flex', 
      justifyContent: 'center', 
      alignItems: 'center',
      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)'
    }}>
      <Card 
        style={{ 
          width: 500, 
          boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
          borderRadius: '8px'
        }}
        title={
          <div style={{ textAlign: 'center', fontSize: '24px', fontWeight: 'bold' }}>
            <ShopOutlined style={{ marginRight: '8px', color: '#1890ff' }} />
            AgentX 注册新公司
          </div>
        }
      >
        <Form
          form={form}
          name="register"
          onFinish={onFinish}
          layout="vertical"
          size="large"
          style={{ padding: '20px 0' }}
        >
          <Form.Item
            label="公司名称"
            name="companyName"
            rules={[{ required: true, message: '请输入公司名称' }]}
          >
            <Input 
              prefix={<UserOutlined />}
              placeholder="请输入公司名称"
            />
          </Form.Item>

          <Form.Item
            label="品牌名称"
            name="brandName"
            rules={[{ required: true, message: '请输入品牌名称' }]}
          >
            <Input 
              prefix={<ShopOutlined />}
              placeholder="请输入品牌名称"
            />
          </Form.Item>

          <Form.Item
            label="行业类别"
            name="category"
            rules={[{ required: true, message: '请选择行业类别' }]}
          >
            <Select placeholder="请选择行业类别">
              <Select.Option value="美妆">美妆</Select.Option>
              <Select.Option value="服饰">服饰</Select.Option>
              <Select.Option value="食品">食品</Select.Option>
              <Select.Option value="科技">科技</Select.Option>
              <Select.Option value="教育">教育</Select.Option>
              <Select.Option value="其他">其他</Select.Option>
            </Select>
          </Form.Item>

          <Form.Item
            label="平台选择"
            name="platforms"
            rules={[{ required: true, message: '请至少选择一个平台' }]}
          >
            <Checkbox.Group>
              <Checkbox value="小红书">小红书</Checkbox>
              <Checkbox value="抖音">抖音</Checkbox>
              <Checkbox value="淘宝">淘宝</Checkbox>
              <Checkbox value="微博">微博</Checkbox>
              <Checkbox value="微信">微信</Checkbox>
              <Checkbox value="B站">B站</Checkbox>
            </Checkbox.Group>
          </Form.Item>

          <Form.Item
            label="管理员用户名"
            name="adminUsername"
            rules={[{ required: true, message: '请输入管理员用户名' }]}
          >
            <Input 
              prefix={<UserOutlined />}
              placeholder="请输入管理员用户名"
            />
          </Form.Item>

          <Form.Item
            label="管理员密码"
            name="adminPassword"
            rules={[{ required: true, message: '请输入管理员密码' }]}
          >
            <Input.Password 
              placeholder="请输入管理员密码"
            />
          </Form.Item>

          <Form.Item style={{ textAlign: 'center', marginTop: '20px' }}>
            <Button 
              type="primary" 
              htmlType="submit" 
              loading={loading}
              style={{ 
                width: '100%', 
                height: '45px',
                fontSize: '16px',
                fontWeight: 'bold'
              }}
            >
              注册公司
            </Button>
          </Form.Item>

          <Form.Item style={{ textAlign: 'center' }}>
            <Button 
              type="link" 
              onClick={() => navigate('/login')}
            >
              已有账户？立即登录
            </Button>
          </Form.Item>
        </Form>
      </Card>
    </div>
  );
};

export default Register;
