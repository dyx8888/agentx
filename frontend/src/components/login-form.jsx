import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { Button, Input, Checkbox, Card, Form, message, Typography } from "antd"
import { EyeInvisibleOutlined, EyeOutlined, UserOutlined, LockOutlined, LoadingOutlined } from "@ant-design/icons"
import { loginApi } from "@/lib/api"
import { useAuth } from "@/lib/AuthContext"

const { Title, Text } = Typography

export function LoginForm() {
  const navigate = useNavigate()
  const { login, setUser } = useAuth()
  const [form] = Form.useForm()
  const [isLoading, setIsLoading] = useState(false)

  const handleSubmit = async (values) => {
    setIsLoading(true)

    try {
      const data = await loginApi(values.username, values.password)

      if (data.access_token) {
        login(data.access_token, data.refresh_token || null)
        if (data.user) setUser(data.user)
        message.success('登录成功')
        navigate("/dashboard")
      } else {
        throw new Error("未获取到有效的访问令牌")
      }
    } catch (err) {
      message.error(err.message || "登录失败，请检查用户名和密码")
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'row' }}>
      <div style={{ 
        width: '45%', 
        background: 'linear-gradient(to bottom right, #ffecd2, #fcb69f, #ffecd2)', 
        padding: '48px', 
        display: 'flex', 
        flexDirection: 'column', 
        justifyContent: 'space-between',
        position: 'relative',
        overflow: 'hidden'
      }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '32px' }}>
            <div style={{ 
              width: '40px', 
              height: '40px', 
              background: '#1890ff', 
              borderRadius: '8px', 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'center' 
            }}>
              <span style={{ color: 'white', fontWeight: 'bold', fontSize: '18px' }}>A</span>
            </div>
            <span style={{ fontSize: '24px', fontWeight: 'bold', color: '#333' }}>AgentX</span>
          </div>
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <Title level={1} style={{ fontSize: '48px', marginBottom: '24px' }}>
            数字员工派遣平台
          </Title>
          <Text style={{ fontSize: '20px', color: '#666', maxWidth: '400px' }}>
            用AI重塑电商运营，让每个人拥有专属数字团队
          </Text>
        </div>

        <div>
          <div style={{ borderTop: '1px solid rgba(0,0,0,0.1)', paddingTop: '24px' }}>
            <Text style={{ fontSize: '14px', color: '#999' }}>
              已有超过 10,000+ 企业信赖我们
            </Text>
          </div>
        </div>
      </div>

      <div style={{ 
        width: '55%', 
        display: 'flex', 
        alignItems: 'center', 
        justifyContent: 'center', 
        padding: '48px',
        background: '#f5f5f5'
      }}>
        <Card style={{ width: '100%', maxWidth: '400px', border: 'none', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}>
          <div style={{ textAlign: 'center', marginBottom: '32px' }}>
            <Title level={2}>欢迎回来</Title>
            <Text type="secondary">请输入您的账号信息登录系统</Text>
          </div>
          
          <Form form={form} onFinish={handleSubmit} layout="vertical">
            <Form.Item 
              name="username" 
              label="用户名 / 邮箱"
              rules={[{ required: true, message: '请输入用户名或邮箱' }]}
            >
              <Input 
                prefix={<UserOutlined />}
                placeholder="请输入用户名或邮箱"
                size="large"
                disabled={isLoading}
              />
            </Form.Item>

            <Form.Item 
              name="password" 
              label="密码"
              rules={[{ required: true, message: '请输入密码' }]}
            >
              <Input.Password 
                prefix={<LockOutlined />}
                placeholder="请输入密码"
                size="large"
                disabled={isLoading}
              />
            </Form.Item>

            <Form.Item>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Checkbox disabled={isLoading}>记住我</Checkbox>
                <Button type="link" size="small" disabled={isLoading}>
                  忘记密码？
                </Button>
              </div>
            </Form.Item>

            <Form.Item>
              <Button 
                type="primary" 
                htmlType="submit" 
                size="large" 
                block 
                loading={isLoading}
              >
                登录
              </Button>
            </Form.Item>

            <div style={{ textAlign: 'center', margin: '24px 0' }}>
              <Text type="secondary">或</Text>
            </div>

            <Form.Item>
              <Button 
                size="large" 
                block 
                disabled={isLoading}
                onClick={() => navigate('/register')}
              >
                注册新公司
              </Button>
            </Form.Item>
          </Form>

          <div style={{ textAlign: 'center', marginTop: '32px' }}>
            <Text type="secondary" style={{ fontSize: '12px' }}>
              &copy; 2025 AgentX. All rights reserved.
            </Text>
          </div>
        </Card>
      </div>
    </div>
  )
}