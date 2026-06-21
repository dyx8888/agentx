import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Layout, Typography, Card, Button, Space, message, Empty, Tag,
  Row, Col, Modal, Form, Input, Select, Badge, Tooltip
} from 'antd';
import {
  RobotOutlined, PlusOutlined, EditOutlined, DeleteOutlined,
  SettingOutlined, ThunderboltOutlined, MessageOutlined,
  BarChartOutlined, ApiOutlined, TeamOutlined
} from '@ant-design/icons';
import { getAgents, getCustomAgents, createCustomAgent, deleteCustomAgent } from '@/lib/api';
import { useAuth } from '@/lib/AuthContext';

const { Content } = Layout;
const { Text, Title } = Typography;

const AGENT_TYPE_INFO = {
  brand_bd: { label: '品牌商务', icon: '🤝', color: '#1890ff', desc: 'KOL 达人对接、品牌合作洽谈、商务沟通' },
  content_ops: { label: '内容运营', icon: '✍️', color: '#52c41a', desc: '短视频脚本、直播策划、多平台内容分发' },
  data_analyst: { label: '数据分析', icon: '📊', color: '#722ed1', desc: '销售分析、数据看板、预测建模' },
  customer_service: { label: '客服专员', icon: '💬', color: '#13c2c2', desc: '智能客服、工单处理、售后跟进' },
  warehouse_logistics: { label: '仓储物流', icon: '📦', color: '#fa8c16', desc: '库存监控、物流追踪、发货管理' },
  visual_designer: { label: '视觉设计', icon: '🎨', color: '#eb2f96', desc: '主图设计、详情页、广告素材生成' },
  supply_chain: { label: '供应链选品', icon: '🔍', color: '#faad14', desc: '商品选品、供应商评估、趋势挖掘' },
  ad_specialist: { label: '智能投流', icon: '🎯', color: '#2f54eb', desc: '千川投放、ROI 优化、预算分配' },
};

export default function AgentCustomize() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const companyId = user?.company_id || 1;

  const [agents, setAgents] = useState([]);
  const [customAgents, setCustomAgents] = useState([]);
  const [modalVisible, setModalVisible] = useState(false);
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  const load = async () => {
    try {
      const [data, custom] = await Promise.all([
        getAgents(companyId),
        getCustomAgents(companyId),
      ]);
      setAgents(Array.isArray(data) ? data : data?.agents || []);
      setCustomAgents(Array.isArray(custom) ? custom : custom?.agents || []);
    } catch { /* ignore */ }
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async (values) => {
    setLoading(true);
    try {
      await createCustomAgent(companyId, values);
      message.success('自定义员工创建成功');
      setModalVisible(false);
      form.resetFields();
      load();
    } catch { message.error('创建失败'); }
    finally { setLoading(false); }
  };

  const handleDelete = async (agentId) => {
    try {
      await deleteCustomAgent(companyId, agentId);
      message.success('已删除');
      load();
    } catch { message.error('删除失败'); }
  };

  const allAgents = [
    ...(agents || []),
    ...(customAgents || []),
  ];

  return (
    <Layout style={{ minHeight: '100vh', background: '#f5f5f5' }}>
      <Content style={{ maxWidth: 1100, margin: '0 auto', width: '100%', padding: '16px' }}>
        <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Space>
            <RobotOutlined style={{ fontSize: 24, color: '#1890ff' }} />
            <Title level={4} style={{ margin: 0 }}>数字员工管理</Title>
            <Tag>{allAgents.length} 位员工</Tag>
          </Space>
          <Space>
            <Button onClick={() => navigate('/settings')} icon={<SettingOutlined />}>
              全局设置
            </Button>
            <Button type="primary" icon={<PlusOutlined />}
              onClick={() => setModalVisible(true)}>
              创建自定义员工
            </Button>
          </Space>
        </div>

        <Row gutter={[12, 12]}>
          {allAgents.length === 0 ? (
            <Col span={24}>
              <Empty description="暂无数字员工，请先初始化系统" />
            </Col>
          ) : (
            allAgents.map((agent, i) => {
              const typeInfo = AGENT_TYPE_INFO[agent.agent_type] || {
                label: agent.agent_type || '自定义',
                icon: '🤖',
                color: '#8c8c8c',
                desc: agent.description || '',
              };
              const isCustom = !!customAgents.find(c => c.id === agent.id);

              return (
                <Col xs={24} sm={12} md={8} lg={6} key={agent.id || i}>
                  <Card hoverable size="small"
                    actions={[
                      <Tooltip title="对话" key="chat">
                        <MessageOutlined onClick={() => navigate(`/agents/${agent.agent_type || agent.id}/chat`)} />
                      </Tooltip>,
                      <Tooltip title="配置" key="config">
                        <SettingOutlined onClick={() => navigate(`/agents/${agent.agent_type || agent.id}/customize`)} />
                      </Tooltip>,
                      isCustom && (
                        <Tooltip title="删除" key="delete">
                          <DeleteOutlined style={{ color: '#ff4d4f' }}
                            onClick={() => handleDelete(agent.id)} />
                        </Tooltip>
                      ),
                    ]}>
                    <Card.Meta
                      avatar={<span style={{ fontSize: 28 }}>{typeInfo.icon}</span>}
                      title={
                        <Space>
                          <Text strong>{agent.name || agent.display_name || typeInfo.label}</Text>
                          {isCustom && <Tag color="purple" style={{ fontSize: 10 }}>自定义</Tag>}
                        </Space>
                      }
                      description={
                        <div>
                          <Tag color={typeInfo.color} style={{ marginBottom: 8 }}>{typeInfo.label}</Tag>
                          <Badge
                            status={agent.status === 'online' ? 'success' : 'default'}
                            text={agent.status === 'online' ? '在线' : '离线'}
                            style={{ marginLeft: 8 }}
                          />
                          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4, lineHeight: 1.4 }}>
                            {typeInfo.desc}
                          </Text>
                        </div>
                      }
                    />
                  </Card>
                </Col>
              );
            })
          )}
        </Row>

        <Modal title="创建自定义数字员工" open={modalVisible}
          onCancel={() => setModalVisible(false)}
          onOk={() => form.submit()}
          confirmLoading={loading}>
          <Form form={form} layout="vertical" onFinish={handleCreate}>
            <Form.Item name="name" label="员工名称" rules={[{ required: true, message: '请输入名称' }]}>
              <Input placeholder="例如: 海外BD顾问" />
            </Form.Item>
            <Form.Item name="description" label="职责描述">
              <Input.TextArea rows={3} placeholder="描述该员工的工作职责" />
            </Form.Item>
            <Form.Item name="agent_type" label="基础类型" rules={[{ required: true }]}>
              <Select placeholder="选择基础 Agent 类型"
                options={Object.entries(AGENT_TYPE_INFO).map(([k, v]) => ({
                  value: k, label: `${v.icon} ${v.label}`,
                }))} />
            </Form.Item>
            <Form.Item name="custom_prompt" label="自定义 System Prompt（可选）">
              <Input.TextArea rows={4}
                placeholder="覆盖默认的 System Prompt，定义专属角色行为" />
            </Form.Item>
          </Form>
        </Modal>
      </Content>
    </Layout>
  );
}