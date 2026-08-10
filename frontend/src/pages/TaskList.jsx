import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Layout, Typography, Table, Tag, Button, Space, Card, Input,
  Select, Row, Col, message, Modal, Descriptions, Empty, Badge,
  Tooltip, Segmented, Progress
} from 'antd';
import {
  ReloadOutlined, EyeOutlined, StopOutlined, PlusOutlined,
  SearchOutlined, FilterOutlined, ClockCircleOutlined,
  CheckCircleOutlined, SyncOutlined, ExclamationCircleOutlined,
  AuditOutlined
} from '@ant-design/icons';
import { getTasks, getTask, cancelTask } from '@/lib/api';
import { useAuth } from '@/lib/AuthContext';

const { Content } = Layout;
const { Text } = Typography;

const STATUS_MAP = {
  pending: { color: 'default', label: '待分配', icon: <ClockCircleOutlined /> },
  running: { color: 'processing', label: '执行中', icon: <SyncOutlined spin /> },
  waiting_review: { color: 'warning', label: '待审核', icon: <AuditOutlined /> },
  completed: { color: 'success', label: '已完成', icon: <CheckCircleOutlined /> },
  failed: { color: 'error', label: '失败', icon: <ExclamationCircleOutlined /> },
  cancelled: { color: 'default', label: '已取消', icon: <StopOutlined /> },
};

const AGENT_LABELS = {
  brand_bd: '品牌商务', content_ops: '内容运营',
  data_analyst: '数据分析', customer_service: '客服专员',
  warehouse_logistics: '仓储物流', visual_designer: '视觉设计',
  supply_chain: '供应链选品', ad_specialist: '智能投流',
};

export default function TaskList() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const companyId = user?.company_id || 1;

  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [detailVisible, setDetailVisible] = useState(false);
  const [currentTask, setCurrentTask] = useState(null);
  const [statusFilter, setStatusFilter] = useState('all');
  const [searchText, setSearchText] = useState('');

  const loadTasks = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (statusFilter !== 'all') params.status = statusFilter;
      const data = await getTasks(companyId, params);
      setTasks(Array.isArray(data) ? data : data?.tasks || []);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [companyId, statusFilter]);

  useEffect(() => { loadTasks(); }, [loadTasks]);

  const handleView = async (taskId) => {
    try {
      const data = await getTask(taskId);
      setCurrentTask(data);
      setDetailVisible(true);
    } catch { message.error('获取任务详情失败'); }
  };

  const handleCancel = async (taskId) => {
    Modal.confirm({
      title: '确认取消任务',
      content: '取消后任务将停止执行，此操作不可撤销。',
      okText: '确认取消',
      cancelText: '保留',
      okType: 'danger',
      onOk: async () => {
        try {
          await cancelTask(taskId);
          message.success('任务已取消');
          loadTasks();
        } catch { message.error('操作失败'); }
      },
    });
  };

  const filtered = tasks.filter(t =>
    !searchText || t.title?.includes(searchText) || t.description?.includes(searchText)
  );

  const columns = [
    {
      title: '任务',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (text, record) => (
        <Space direction="vertical" size={0}>
          <Text strong>{text || record.task_name || '未命名任务'}</Text>
          {record.description && (
            <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
              {record.description}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '执行 Agent',
      dataIndex: 'agent_type',
      key: 'agent_type',
      width: 110,
      render: (type) => (
        <Tag>{AGENT_LABELS[type] || type || '未指定'}</Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status) => {
        const info = STATUS_MAP[status] || STATUS_MAP.pending;
        return (
          <Tag color={info.color} icon={info.icon}>{info.label}</Tag>
        );
      },
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 120,
      render: (text) => <Text type="secondary" style={{ fontSize: 12 }}>{text || '-'}</Text>,
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_, record) => (
        <Space>
          <Button type="link" size="small" icon={<EyeOutlined />}
            onClick={() => handleView(record.id)}>详情</Button>
          {(record.status === 'pending' || record.status === 'running') && (
            <Button type="link" size="small" danger icon={<StopOutlined />}
              onClick={() => handleCancel(record.id)}>取消</Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Layout style={{ minHeight: '100vh', background: '#f5f5f5' }}>
      <Content style={{ maxWidth: 1100, margin: '0 auto', width: '100%', padding: '16px' }}>
        <Card style={{ marginBottom: 12 }}>
          <Row gutter={12} align="middle">
            <Col flex="auto">
              <Space>
                <Button icon={<ReloadOutlined />} onClick={loadTasks} loading={loading}>刷新</Button>
                <Input placeholder="搜索任务..." prefix={<SearchOutlined />}
                  value={searchText} onChange={e => setSearchText(e.target.value)}
                  style={{ width: 200 }} allowClear />
              </Space>
            </Col>
            <Col>
              <Segmented value={statusFilter} onChange={setStatusFilter} size="small"
                options={[
                  { label: '全部', value: 'all' },
                  { label: '执行中', value: 'running' },
                  { label: '待审核', value: 'waiting_review' },
                  { label: '已完成', value: 'completed' },
                ]} />
            </Col>
          </Row>
        </Card>

        <Table columns={columns} dataSource={filtered} rowKey="id"
          loading={loading} size="middle" pagination={{ pageSize: 15, showSizeChanger: false }}
          locale={{ emptyText: <Empty description="暂无任务" /> }}
          onRow={(record) => ({
            style: { cursor: 'pointer' },
            onClick: () => handleView(record.id),
          })} />

        <Modal title="任务详情" open={detailVisible} onCancel={() => setDetailVisible(false)}
          footer={[
            <Button key="close" onClick={() => setDetailVisible(false)}>关闭</Button>,
            currentTask?.status === 'waiting_review' && (
              <Button key="review" type="primary" onClick={() => {
                setDetailVisible(false);
                navigate('/reviews');
              }}>去审核</Button>
            ),
          ]} width={600}>
          {currentTask && (
            <Descriptions column={2} size="small" bordered>
              <Descriptions.Item label="任务名称" span={2}>{currentTask.title || currentTask.task_name}</Descriptions.Item>
              <Descriptions.Item label="状态">
                {(() => { const info = STATUS_MAP[currentTask.status] || STATUS_MAP.pending;
                  return <Tag color={info.color}>{info.label}</Tag>; })()}
              </Descriptions.Item>
              <Descriptions.Item label="执行 Agent">
                {AGENT_LABELS[currentTask.agent_type] || currentTask.agent_key || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="创建时间">{currentTask.created_at || '-'}</Descriptions.Item>
              <Descriptions.Item label="更新时间">{currentTask.updated_at || '-'}</Descriptions.Item>
              <Descriptions.Item label="描述" span={2}>{currentTask.description || '-'}</Descriptions.Item>
            </Descriptions>
          )}
        </Modal>
      </Content>
    </Layout>
  );
}