import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Layout, Typography, Card, Tabs, Form, Input, Select, Button,
  Switch, Table, Tag, Space, message, Empty, Row, Col,
  Descriptions, Modal, Popconfirm, Divider, Badge
} from 'antd';
import {
  SettingOutlined, ApiOutlined, RobotOutlined, UserOutlined,
  PlusOutlined, DeleteOutlined, EditOutlined, CheckCircleOutlined,
  ExclamationCircleOutlined, KeyOutlined, TeamOutlined,
  BranchesOutlined, SafetyOutlined, ThunderboltOutlined,
  DollarOutlined
} from '@ant-design/icons';
import {
  getCompanySettings, updateCompanySettings,
  getCustomAgents, createCustomAgent, deleteCustomAgent,
  getAgents, updateAgentConfig,
} from '@/lib/api';
import { useAuth } from '@/lib/AuthContext';

const { Content } = Layout;
const { Text, Title } = Typography;

const PLATFORMS = [
  { value: 'douyin_shop', label: '抖音小店' },
  { value: 'douyin_star', label: '抖音达人' },
  { value: 'taobao', label: '淘宝' },
  { value: 'pinduoduo', label: '拼多多' },
  { value: 'xiaohongshu', label: '小红书' },
  { value: 'chanmama', label: '蝉妈妈' },
];

const LLM_PROVIDERS = [
  { value: 'deepseek', label: 'DeepSeek' },
  { value: 'openai', label: 'OpenAI' },
  { value: 'zhipu', label: '智谱 GLM' },
  { value: 'qwen', label: '通义千问' },
  { value: 'moonshot', label: 'Moonshot' },
  { value: 'minimax', label: 'MiniMax' },
  { value: 'custom', label: '自定义' },
];

const AGENT_TYPES = [
  { value: 'brand_bd', label: '品牌商务' },
  { value: 'content_ops', label: '内容运营' },
  { value: 'data_analyst', label: '数据分析' },
  { value: 'customer_service', label: '客服专员' },
  { value: 'warehouse_logistics', label: '仓储物流' },
  { value: 'visual_designer', label: '视觉设计' },
  { value: 'supply_chain', label: '供应链选品' },
  { value: 'ad_specialist', label: '智能投流' },
];

function PlatformCredentials() {
  const { user } = useAuth();
  const companyId = user?.company_id || 1;
  const [credentials, setCredentials] = useState({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getCompanySettings(companyId).then(d => {
      setCredentials(d?.platform_credentials || {});
    }).catch(() => {});
  }, [companyId]);

  const handleSave = async () => {
    setLoading(true);
    try {
      await updateCompanySettings(companyId, { platform_credentials: credentials });
      message.success('平台凭证已加密保存');
    } catch { message.error('保存失败'); }
    finally { setLoading(false); }
  };

  return (
    <div>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        配置各电商平台的 API 凭证，凭证将使用 AES-256 加密存储，仅运行时解密使用。
      </Text>
      {PLATFORMS.map(p => (
        <Card key={p.value} size="small" style={{ marginBottom: 8 }}
          title={<><ApiOutlined /> {p.label}</>}>
          <Form layout="vertical" size="small">
            <Row gutter={12}>
              <Col xs={24} sm={8}>
                <Form.Item label="App Key / Client ID" style={{ marginBottom: 0 }}>
                  <Input.Password placeholder="输入 App Key" value={credentials[p.value]?.app_key || ''}
                    onChange={e => setCredentials(prev => ({
                      ...prev, [p.value]: { ...prev[p.value], app_key: e.target.value }
                    }))} />
                </Form.Item>
              </Col>
              <Col xs={24} sm={8}>
                <Form.Item label="App Secret" style={{ marginBottom: 0 }}>
                  <Input.Password placeholder="输入 App Secret" value={credentials[p.value]?.app_secret || ''}
                    onChange={e => setCredentials(prev => ({
                      ...prev, [p.value]: { ...prev[p.value], app_secret: e.target.value }
                    }))} />
                </Form.Item>
              </Col>
              <Col xs={24} sm={8}>
                <Form.Item label="Access Token" style={{ marginBottom: 0 }}>
                  <Input.Password placeholder="输入 Access Token" value={credentials[p.value]?.access_token || ''}
                    onChange={e => setCredentials(prev => ({
                      ...prev, [p.value]: { ...prev[p.value], access_token: e.target.value }
                    }))} />
                </Form.Item>
              </Col>
            </Row>
          </Form>
        </Card>
      ))}
      <Button type="primary" onClick={handleSave} loading={loading}
        icon={<SafetyOutlined />} style={{ marginTop: 12 }}>
        加密保存平台凭证
      </Button>
    </div>
  );
}

function LLMModelConfig() {
  const { user } = useAuth();
  const companyId = user?.company_id || 1;
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    getAgents(companyId).then(d => setAgents(Array.isArray(d) ? d : d?.agents || d || [])).catch(() => {});
  }, [companyId]);

  const handleUpdate = async (agentId, field, value) => {
    try {
      await updateAgentConfig(agentId, { [field]: value });
      message.success('配置已更新');
    } catch { message.error('更新失败'); }
  };

  return (
    <div>
      <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
        为每个数字员工配置 LLM 提供商和模型。复杂任务（数据分析、品牌商务）建议使用高性能模型，简单任务可使用经济型模型。
      </Text>
      <Table dataSource={agents} rowKey="id" size="small" pagination={false}
        locale={{ emptyText: <Empty description="暂无 Agent" /> }}
        columns={[
          {
            title: 'Agent', dataIndex: 'name', key: 'name',
            render: (text) => <Text strong>{text || '-'}</Text>,
          },
          {
            title: '类型', dataIndex: 'agent_type', key: 'type', width: 100,
            render: (type) => {
              const info = AGENT_TYPES.find(t => t.value === type);
              return <Tag>{info?.label || type}</Tag>;
            },
          },
          {
            title: 'LLM 提供商', dataIndex: 'llm_provider', key: 'provider', width: 160,
            render: (provider, record) => (
              <Select size="small" style={{ width: 140 }}
                defaultValue={provider || 'deepseek'}
                onChange={v => handleUpdate(record.id, 'llm_provider', v)}>
                {LLM_PROVIDERS.map(p => (
                  <Select.Option key={p.value} value={p.value}>{p.label}</Select.Option>
                ))}
              </Select>
            ),
          },
          {
            title: '模型名称', dataIndex: 'llm_model', key: 'model', width: 200,
            render: (model, record) => (
              <Input size="small" defaultValue={model || 'deepseek-chat'}
                placeholder="模型名称"
                onBlur={e => e.target.value !== model && handleUpdate(record.id, 'llm_model', e.target.value)} />
            ),
          },
          {
            title: 'API Key', dataIndex: 'has_api_key', key: 'apikey', width: 120,
            render: (has, record) => (
              <Input.Password size="small" placeholder="企业提供"
                onBlur={e => { if (e.target.value) handleUpdate(record.id, 'api_key', e.target.value); }} />
            ),
          },
        ]} />
    </div>
  );
}

function CustomAgents() {
  const { user } = useAuth();
  const companyId = user?.company_id || 1;
  const [agents, setAgents] = useState([]);
  const [modalVisible, setModalVisible] = useState(false);
  const [form] = Form.useForm();

  const load = useCallback(async () => {
    try { setAgents(await getCustomAgents(companyId)); } catch { /* ignore */ }
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const handleCreate = async (values) => {
    try {
      await createCustomAgent(companyId, values);
      message.success('自定义员⼯创建成功');
      setModalVisible(false);
      form.resetFields();
      load();
    } catch { message.error('创建失败'); }
  };

  const handleDelete = async (agentId) => {
    try {
      await deleteCustomAgent(companyId, agentId);
      message.success('已删除');
      load();
    } catch { message.error('删除失败'); }
  };

  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Text type="secondary">创建公司专属数字员工，自定义角色名称、职责描述和工具集。</Text>
        <Button type="primary" icon={<PlusOutlined />}
          onClick={() => setModalVisible(true)}>创建自定义员⼯</Button>
      </div>

      <Table dataSource={agents} rowKey="id" size="small" pagination={false}
        locale={{ emptyText: <Empty description="暂无自定义员⼯，点击上方按钮创建" /> }}
        columns={[
          { title: '名称', dataIndex: 'name', key: 'name' },
          { title: '类型', dataIndex: 'agent_type', key: 'type', width: 110,
            render: (t) => <Tag>{t}</Tag> },
          { title: '描述', dataIndex: 'description', key: 'desc', ellipsis: true },
          { title: '工具数', dataIndex: 'tools', key: 'tools', width: 80,
            render: (t) => t?.length || 0 },
          {
            title: '操作', key: 'actions', width: 80,
            render: (_, r) => (
              <Popconfirm title="确定删除？" onConfirm={() => handleDelete(r.id)}>
                <Button type="link" danger size="small" icon={<DeleteOutlined />} />
              </Popconfirm>
            ),
          },
        ]} />

      <Modal title="创建自定义数字员⼯" open={modalVisible}
        onCancel={() => setModalVisible(false)} onOk={() => form.submit()}>
        <Form form={form} layout="vertical" onFinish={handleCreate}>
          <Form.Item name="name" label="员⼯名称" rules={[{ required: true }]}>
            <Input placeholder="如: 外贸BD助理" />
          </Form.Item>
          <Form.Item name="description" label="职责描述">
            <Input.TextArea rows={3} placeholder="描述该员⼯的工作内容和能力" />
          </Form.Item>
          <Form.Item name="agent_type" label="基础类型" rules={[{ required: true }]}>
            <Select options={AGENT_TYPES} placeholder="选择基础 Agent 类型" />
          </Form.Item>
          <Form.Item name="custom_prompt" label="自定义 System Prompt">
            <Input.TextArea rows={4} placeholder="可覆盖默认的 System Prompt" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

function MembersManagement() {
  return (
    <div>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Text type="secondary">管理公司成员账号，设置角色和权限。</Text>
        <Button type="primary" icon={<PlusOutlined />} disabled>邀请成员</Button>
      </div>
      <Empty description="成员管理功能将在后续版本上线" />
    </div>
  );
}

export default function SettingsPage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  const tabItems = [
    {
      key: 'platforms',
      label: <span><ApiOutlined /> 平台凭证</span>,
      children: <PlatformCredentials />,
    },
    {
      key: 'llm',
      label: <span><ThunderboltOutlined /> LLM 模型</span>,
      children: <LLMModelConfig />,
    },
    {
      key: 'custom-agents',
      label: <span><RobotOutlined /> 自定义员⼯</span>,
      children: <CustomAgents />,
    },
    {
      key: 'members',
      label: <span><TeamOutlined /> 成员管理</span>,
      children: <MembersManagement />,
    },
  ];

  return (
    <Layout style={{ minHeight: '100vh', background: '#f5f5f5' }}>
      <Content style={{ maxWidth: 1000, margin: '0 auto', width: '100%', padding: '16px' }}>
        <Card title={<><SettingOutlined /> 公司设置</>}
          extra={<Text type="secondary">当前企业: {user?.company_name || '未命名'}</Text>}>
          <Tabs defaultActiveKey="platforms" items={tabItems} />
        </Card>
      </Content>
    </Layout>
  );
}