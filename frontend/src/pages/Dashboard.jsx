import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Layout, Menu, Typography, Avatar, Dropdown, Space, Card, Row, Col,
  Tag, Statistic, Button, message, Badge, List, Empty, Tabs, Spin,
  Progress, Tooltip, Alert, Collapse, Modal, Input, Drawer, Segmented
} from 'antd';
import {
  UserOutlined, BellOutlined, DashboardOutlined, TeamOutlined,
  FileTextOutlined, BarChartOutlined, SettingOutlined,
  LogoutOutlined, CheckCircleOutlined, ClockCircleOutlined,
  ThunderboltOutlined, WarningOutlined, CheckOutlined, CloseOutlined,
  EyeOutlined, RobotOutlined, AuditOutlined, AlertOutlined,
  RiseOutlined, FallOutlined, MenuOutlined, AppstoreOutlined,
  OrderedListOutlined, ReloadOutlined, FieldTimeOutlined
} from '@ant-design/icons';
import { useAuth } from '@/lib/AuthContext';
import {
  getDashboardOverview, getDashboardAgents, getDashboardReviews,
  approveReview, rejectReview, getDashboardAlerts, markAlertRead,
  getDashboardTaskTrend, getDashboardTokenConsumption
} from '@/lib/api';

const { Header, Sider, Content } = Layout;
const { Panel } = Collapse;

const AGENT_TYPE_MAP = {
  brand_bd: { label: '品牌商务', color: '#1890ff' },
  content_ops: { label: '内容运营', color: '#52c41a' },
  data_analyst: { label: '数据分析', color: '#722ed1' },
  customer_service: { label: '客服专员', color: '#13c2c2' },
  warehouse_logistics: { label: '仓储物流', color: '#fa8c16' },
  visual_designer: { label: '视觉设计', color: '#eb2f96' },
  supply_chain: { label: '供应链选品', color: '#faad14' },
  ad_specialist: { label: '智能投流', color: '#2f54eb' },
};

const AGENT_ICONS = {
  brand_bd: '🤝', content_ops: '✍️', data_analyst: '📊',
  customer_service: '💬', warehouse_logistics: '📦',
  visual_designer: '🎨', supply_chain: '🔍', ad_specialist: '🎯',
};

function TrendIndicator({ value, label }) {
  const isUp = value >= 0;
  return (
    <span style={{ color: isUp ? '#52c41a' : '#ff4d4f', fontSize: 13 }}>
      {isUp ? <RiseOutlined /> : <FallOutlined />}
      {' '}{isUp ? '+' : ''}{value}% {label}
    </span>
  );
}

function MiniBarChart({ data, height }) {
  if (!data || data.length === 0) return <Empty description="暂无数据" />;
  const maxVal = Math.max(...data.map(d => d.value), 1);
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 2, height: height || 60 }}>
      {data.map((d, i) => (
        <div key={i} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', height: '100%' }}>
          <div style={{
            width: '100%', height: `${(d.value / maxVal) * 100}%`,
            background: 'linear-gradient(180deg, #1890ff, #69c0ff)',
            borderRadius: '2px 2px 0 0', minHeight: d.value > 0 ? 4 : 0,
          }} />
        </div>
      ))}
    </div>
  );
}

function ReviewItem({ review, onApprove, onReject }) {
  const [comment, setComment] = useState('');
  const [submitting, setSubmitting] = useState(false);

  return (
    <Card size="small" style={{ marginBottom: 12 }}
      extra={
        <Tag color={review.level === 'mandatory' ? 'red' : review.level === 'recommended' ? 'orange' : 'blue'}>
          {review.level === 'mandatory' ? '强制审核' : review.level === 'recommended' ? '推荐审核' : '自动通过'}
        </Tag>
      }>
      <div style={{ marginBottom: 8 }}>
        <Text strong>{review.agent_name}</Text>
        <Text type="secondary" style={{ marginLeft: 12 }}>{review.task_type}</Text>
      </div>
      <div style={{ background: '#fafafa', padding: 12, borderRadius: 4, marginBottom: 8, whiteSpace: 'pre-wrap', maxHeight: 150, overflow: 'auto' }}>
        <Text>{review.result_summary}</Text>
      </div>
      <Space>
        <Button size="small" type="primary" icon={<CheckOutlined />}
          loading={submitting}
          onClick={() => { setSubmitting(true); onApprove(review.id, comment).finally(() => setSubmitting(false)); }}>
          批准
        </Button>
        <Button size="small" danger icon={<CloseOutlined />}
          onClick={() => onReject(review.id)}>
          驳回
        </Button>
        <Input size="small" placeholder="审批意见（可选）" style={{ width: 160 }}
          value={comment} onChange={e => setComment(e.target.value)} />
      </Space>
    </Card>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [selectedMenu, setSelectedMenu] = useState('dashboard');
  const [mobileDrawer, setMobileDrawer] = useState(false);

  const companyId = user?.company_id || 1;

  const [overview, setOverview] = useState(null);
  const [agents, setAgents] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [taskTrend, setTaskTrend] = useState([]);
  const [tokenTrend, setTokenTrend] = useState([]);
  const [reviewFilter, setReviewFilter] = useState('mandatory');
  const [loading, setLoading] = useState(false);

  const loadOverview = useCallback(async () => {
    try { setOverview(await getDashboardOverview(companyId)); } catch { /* ignore */ }
  }, [companyId]);

  const loadAgents = useCallback(async () => {
    try { setAgents(await getDashboardAgents(companyId)); } catch { /* ignore */ }
  }, [companyId]);

  const loadReviews = useCallback(async (level) => {
    try {
      const data = await getDashboardReviews(companyId, level === 'all' ? undefined : level);
      setReviews(Array.isArray(data) ? data : data?.reviews || []);
    } catch { /* ignore */ }
  }, [companyId]);

  const loadAlerts = useCallback(async () => {
    try {
      const data = await getDashboardAlerts(companyId);
      setAlerts(Array.isArray(data) ? data : data?.alerts || []);
    } catch { /* ignore */ }
  }, [companyId]);

  const loadTrends = useCallback(async () => {
    try {
      const [tt, tk] = await Promise.all([
        getDashboardTaskTrend(companyId, 30),
        getDashboardTokenConsumption(companyId, 30),
      ]);
      setTaskTrend(Array.isArray(tt) ? tt : tt?.points || []);
      setTokenTrend(Array.isArray(tk) ? tk : tk?.points || []);
    } catch { /* ignore */ }
  }, [companyId]);

  const loadAll = useCallback(() => {
    setLoading(true);
    Promise.all([
      loadOverview(), loadAgents(), loadAlerts(), loadTrends(),
      loadReviews(reviewFilter),
    ]).finally(() => setLoading(false));
  }, [loadOverview, loadAgents, loadAlerts, loadTrends, loadReviews, reviewFilter]);

  useEffect(() => { loadAll(); }, [loadAll]);

  useEffect(() => { loadReviews(reviewFilter); }, [reviewFilter, loadReviews]);

  const handleApprove = async (reviewId, comment) => {
    try {
      await approveReview(reviewId, comment);
      message.success('已批准');
      loadReviews(reviewFilter);
    } catch { message.error('操作失败'); }
  };

  const handleReject = async (reviewId) => {
    try {
      await rejectReview(reviewId, '人工驳回');
      message.success('已驳回');
      loadReviews(reviewFilter);
    } catch { message.error('操作失败'); }
  };

  const handleMarkAlert = async (alertId) => {
    try { await markAlertRead(alertId); loadAlerts(); } catch { /* ignore */ }
  };

  const handleMenuClick = ({ key }) => {
    setSelectedMenu(key);
    setMobileDrawer(false);
    if (key === 'agents') navigate('/agents/customize');
    if (key === 'reviews') setSelectedMenu('reviews');
    if (key === 'analytics') setSelectedMenu('analytics');
    if (key === 'settings') navigate('/settings');
  };

  const handleLogout = () => { logout(); navigate('/login'); };

  const stats = overview?.stats || [];
  const pendingReviews = stats.find(s => s.label?.includes('待审核'))?.value || 0;

  const menuItems = [
    { key: 'dashboard', icon: <DashboardOutlined />, label: '工作台概览' },
    { key: 'reviews', icon: <AuditOutlined />, label: `审核管理 ${pendingReviews > 0 ? `(${pendingReviews})` : ''}` },
    { key: 'agents', icon: <TeamOutlined />, label: '数字员工' },
    { key: 'analytics', icon: <BarChartOutlined />, label: '数据中心' },
    { key: 'settings', icon: <SettingOutlined />, label: '系统设置' },
  ];

  const userMenuItems = [
    { key: 'profile', label: `当前公司: ${user?.company_name || '示例企业'}` },
    { key: 'logout', label: '退出登录', icon: <LogoutOutlined />, onClick: handleLogout },
  ];

  const alertCount = alerts.filter(a => !a.read).length;

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        background: '#fff', padding: '0 16px', boxShadow: '0 2px 8px rgba(0,0,0,0.06)',
        position: 'sticky', top: 0, zIndex: 100,
      }}>
        <div style={{ display: 'flex', alignItems: 'center' }}>
          <Button type="text" icon={<MenuOutlined />}
            className="md-hidden" style={{ display: 'none' }}
            onClick={() => setMobileDrawer(true)} />
          <div style={{
            width: 32, height: 32, background: '#1890ff', borderRadius: 8,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#fff', fontWeight: 'bold', marginRight: 12, fontSize: 16
          }}>A</div>
          <Typography.Title level={5} style={{ margin: 0, color: '#1890ff', whiteSpace: 'nowrap' }}>
            AgentX 老板驾驶舱
          </Typography.Title>
        </div>
        <Space>
          <Tooltip title="刷新数据">
            <Button type="text" icon={<ReloadOutlined />} loading={loading} onClick={loadAll} />
          </Tooltip>
          <Badge count={alertCount} size="small">
            <BellOutlined style={{ fontSize: 18, cursor: 'pointer' }}
              onClick={() => setSelectedMenu('alerts')} />
          </Badge>
          <Dropdown menu={{ items: userMenuItems }} placement="bottomRight">
            <Avatar icon={<UserOutlined />} style={{ cursor: 'pointer', background: '#1890ff' }} />
          </Dropdown>
        </Space>
      </Header>

      <Drawer title="导航菜单" placement="left" open={mobileDrawer} onClose={() => setMobileDrawer(false)} width={220}>
        <Menu mode="inline" selectedKeys={[selectedMenu]} onClick={handleMenuClick} items={menuItems}
          style={{ border: 'none' }} />
      </Drawer>

      <Layout>
        <Sider width={200} style={{ background: '#fff' }} theme="light"
          breakpoint="lg" collapsedWidth={0} trigger={null}
          className="sider-desktop">
          <Menu mode="inline" selectedKeys={[selectedMenu]} onClick={handleMenuClick}
            style={{ height: '100%', borderRight: 0, paddingTop: 8 }} items={menuItems} />
        </Sider>

        <Content style={{ padding: '16px 20px', background: '#f0f2f5', minHeight: 'calc(100vh - 64px)' }}>
          {loading && <Spin spinning style={{ position: 'fixed', top: '50%', left: '50%', zIndex: 999 }} />}

          {/* ---- Dashboard Overview ---- */}
          {selectedMenu === 'dashboard' && (
            <>
              <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
                {(overview?.stats || [
                  { label: '在线 Agent', value: '--', unit: '个', trend: 0, sub_label: '' },
                  { label: '进行中任务', value: '--', unit: '个', trend: 0, sub_label: '' },
                  { label: '今日完成', value: '--', unit: '个', trend: 0, sub_label: '' },
                  { label: '待审核', value: '--', unit: '个', sub_label: '' },
                  { label: '今日 Token', value: '--', unit: 'tokens', trend: 0 },
                  { label: '今日消耗', value: '--', unit: '元', trend: 0 },
                ]).map((s, i) => (
                  <Col xs={12} sm={8} md={8} lg={4} key={i}>
                    <Card size="small" hoverable style={{ textAlign: 'center' }}>
                      <Statistic title={s.label} value={s.value} suffix={s.unit}
                        valueStyle={{ fontSize: 22, color: ['#1890ff','#52c41a','#13c2c2','#faad14','#722ed1','#eb2f96'][i] }} />
                      {s.trend !== undefined && s.trend !== null && (
                        <TrendIndicator value={s.trend} label={s.sub_label || ''} />
                      )}
                    </Card>
                  </Col>
                ))}
              </Row>

              <Row gutter={[12, 12]}>
                <Col xs={24} lg={12}>
                  <Card title={<><RobotOutlined /> 数字员工状态</>} size="small">
                    {(agents).slice(0, 8).map((a, i) => {
                      const typeInfo = AGENT_TYPE_MAP[a.agent_type] || { label: a.agent_type, color: '#999' };
                      return (
                        <Row key={i} style={{ padding: '6px 0', borderBottom: '1px solid #f0f0f0' }}
                          align="middle">
                          <Col span={2}>{AGENT_ICONS[a.agent_type] || '🤖'}</Col>
                          <Col span={7}>
                            <Tag color={typeInfo.color}>{typeInfo.label}</Tag>
                          </Col>
                          <Col span={5}>
                            <Badge status={a.status === 'online' ? 'success' : a.status === 'busy' ? 'processing' : 'default'}
                              text={a.status === 'online' ? '在线' : a.status === 'busy' ? '忙碌' : '离线'} />
                          </Col>
                          <Col span={10} style={{ textAlign: 'right' }}>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              {a.recent_task || '空闲'}
                            </Text>
                          </Col>
                        </Row>
                      );
                    })}
                    {agents.length === 0 && <Empty description="暂无 Agent" />}
                    <div style={{ textAlign: 'center', marginTop: 8 }}>
                      <Button type="link" size="small" onClick={() => navigate('/agents/customize')}>
                        管理员工 &gt;
                      </Button>
                    </div>
                  </Card>

                  <Card title={<><AlertOutlined /> 告警面板</>} size="small" style={{ marginTop: 12 }}>
                    {alerts.filter(a => !a.read).length === 0 ? (
                      <Empty description="暂无告警" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                    ) : (
                      <List size="small" dataSource={alerts.filter(a => !a.read).slice(0, 5)}
                        renderItem={(item, i) => (
                          <List.Item
                            actions={[
                              <Button key="read" type="link" size="small"
                                onClick={() => handleMarkAlert(item.id)}>已读</Button>
                            ]}>
                            <List.Item.Meta
                              avatar={<WarningOutlined style={{ color: item.severity === 'critical' ? '#ff4d4f' : '#faad14' }} />}
                              title={<Text style={{ fontSize: 13 }}>{item.title}</Text>}
                              description={<Text type="secondary" style={{ fontSize: 11 }}>{item.description}</Text>}
                            />
                          </List.Item>
                        )}
                      />
                    )}
                  </Card>
                </Col>

                <Col xs={24} lg={12}>
                  <Card title={<><BarChartOutlined /> 30 天任务完成趋势</>} size="small">
                    <MiniBarChart data={taskTrend} height={80} />
                    <Row justify="space-between" style={{ marginTop: 4 }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>30 天前</Text>
                      <Text type="secondary" style={{ fontSize: 11 }}>今天</Text>
                    </Row>
                  </Card>

                  <Card title={<><ThunderboltOutlined /> Token 消耗趋势</>} size="small" style={{ marginTop: 12 }}>
                    <MiniBarChart data={tokenTrend} height={80} />
                    <Row justify="space-between" style={{ marginTop: 4 }}>
                      <Text type="secondary" style={{ fontSize: 11 }}>30 天前</Text>
                      <Text type="secondary" style={{ fontSize: 11 }}>今天</Text>
                    </Row>
                  </Card>

                  <Card title={<><FileTextOutlined /> 待处理审核</>} size="small" style={{ marginTop: 12 }}>
                    <Segmented block size="small" value={reviewFilter}
                      onChange={setReviewFilter}
                      options={[
                        { label: '强制审核', value: 'mandatory' },
                        { label: '推荐审核', value: 'recommended' },
                        { label: '全部', value: 'all' },
                      ]} />
                    <div style={{ maxHeight: 300, overflow: 'auto', marginTop: 12 }}>
                      {reviews.length === 0 ? (
                        <Empty description="暂无待审核项" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                      ) : (
                        reviews.map((r, i) => (
                          <ReviewItem key={i} review={r} onApprove={handleApprove} onReject={handleReject} />
                        ))
                      )}
                    </div>
                  </Card>
                </Col>
              </Row>
            </>
          )}

          {/* ---- Reviews ---- */}
          {selectedMenu === 'reviews' && (
            <Card title={<><AuditOutlined /> 审核工作台</>}
              extra={
                <Segmented size="small" value={reviewFilter} onChange={setReviewFilter}
                  options={[
                    { label: '强制审核', value: 'mandatory' },
                    { label: '推荐审核', value: 'recommended' },
                    { label: '全部', value: 'all' },
                  ]} />
              }>
              {reviews.length === 0 ? (
                <Empty description="暂无待审核内容" />
              ) : (
                reviews.map((r, i) => (
                  <ReviewItem key={i} review={r} onApprove={handleApprove} onReject={handleReject} />
                ))
              )}
            </Card>
          )}

          {/* ---- Analytics ---- */}
          {selectedMenu === 'analytics' && (
            <Row gutter={[16, 16]}>
              <Col xs={24} md={12}>
                <Card title="任务完成趋势" size="small">
                  <MiniBarChart data={taskTrend} height={120} />
                </Card>
              </Col>
              <Col xs={24} md={12}>
                <Card title="Token 消耗趋势" size="small">
                  <MiniBarChart data={tokenTrend} height={120} />
                </Card>
              </Col>
            </Row>
          )}

          {/* ---- Alerts ---- */}
          {selectedMenu === 'alerts' && (
            <Card title={<><AlertOutlined /> 告警中心</>} size="small">
              <List dataSource={alerts}
                renderItem={(item) => (
                  <List.Item
                    actions={item.read ? [] : [
                      <Button key="read" type="link" onClick={() => handleMarkAlert(item.id)}>标记已读</Button>
                    ]}>
                    <List.Item.Meta
                      avatar={<WarningOutlined style={{ color: item.severity === 'critical' ? '#ff4d4f' : '#faad14', fontSize: 20 }} />}
                      title={<><Text strong>{item.title}</Text> {!item.read && <Tag color="red" style={{ marginLeft: 8 }}>新</Tag>}</>}
                      description={<Text type="secondary">{item.description}</Text>}
                    />
                  </List.Item>
                )}
                locale={{ emptyText: <Empty description="暂无告警" /> }}
              />
            </Card>
          )}
        </Content>
      </Layout>

      <style>{`
        @media (max-width: 768px) {
          .sider-desktop { display: none !important; }
          .md-hidden { display: inline-flex !important; }
          .ant-card-body { padding: 12px !important; }
        }
      `}</style>
    </Layout>
  );
}