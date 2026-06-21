import { useState, useEffect, useCallback } from 'react';
import {
  Layout, Typography, Card, Tag, Button, Space, message, Empty,
  Segmented, Input, Row, Col, Badge, Tooltip, Modal, Descriptions,
  Timeline, Alert
} from 'antd';
import {
  CheckOutlined, CloseOutlined, EyeOutlined, ClockCircleOutlined,
  ExclamationCircleOutlined, ReloadOutlined, AuditOutlined,
  SendOutlined, EditOutlined
} from '@ant-design/icons';
import {
  getDashboardReviews, approveReview, rejectReview
} from '@/lib/api';
import { useAuth } from '@/lib/AuthContext';

const { Content } = Layout;
const { Text, Paragraph } = Typography;

const REVIEW_TIMEOUT_HOURS = 4;

export default function ReviewWorkflow() {
  const { user } = useAuth();
  const companyId = user?.company_id || 1;

  const [reviews, setReviews] = useState([]);
  const [levelFilter, setLevelFilter] = useState('mandatory');
  const [loading, setLoading] = useState(false);
  const [detailVisible, setDetailVisible] = useState(false);
  const [currentReview, setCurrentReview] = useState(null);
  const [comment, setComment] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const loadReviews = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getDashboardReviews(companyId, levelFilter === 'all' ? undefined : levelFilter);
      setReviews(Array.isArray(data) ? data : data?.reviews || []);
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, [companyId, levelFilter]);

  useEffect(() => { loadReviews(); }, [loadReviews]);

  const handleApprove = async (reviewId, approvalComment) => {
    try {
      await approveReview(reviewId, approvalComment || comment);
      message.success('已批准执行');
      loadReviews();
    } catch { message.error('操作失败'); }
  };

  const handleReject = async (reviewId, reason) => {
    try {
      await rejectReview(reviewId, reason || '人工驳回');
      message.success('已驳回');
      loadReviews();
    } catch { message.error('操作失败'); }
  };

  const handleBatchApprove = async () => {
    Modal.confirm({
      title: '批量批准',
      content: `确认批准 ${
        reviews.filter(r => r.level === (levelFilter === 'all' ? r.level : levelFilter)).length
      } 条审核？`,
      onOk: async () => {
        for (const r of reviews) {
          if (levelFilter === 'all' || r.level === levelFilter) {
            await handleApprove(r.id, '批量批准');
          }
        }
      },
    });
  };

  const isTimeout = (review) => {
    if (!review.created_at) return false;
    const created = new Date(review.created_at);
    return (Date.now() - created.getTime()) > REVIEW_TIMEOUT_HOURS * 3600 * 1000;
  };

  const mandatoryCount = reviews.filter(r => r.level === 'mandatory').length;
  const recommendedCount = reviews.filter(r => r.level === 'recommended').length;
  const timeoutCount = reviews.filter(r => isTimeout(r)).length;

  const levelColor = { mandatory: 'red', recommended: 'orange', auto: 'blue' };
  const levelLabel = { mandatory: '强制审核', recommended: '推荐审核', auto: '自动通过' };

  return (
    <Layout style={{ minHeight: '100vh', background: '#f5f5f5' }}>
      <Content style={{ maxWidth: 1000, margin: '0 auto', width: '100%', padding: '16px' }}>
        <Card style={{ marginBottom: 16 }}>
          <Row gutter={[16, 12]} align="middle">
            <Col flex="auto">
              <Space>
                <AuditOutlined style={{ fontSize: 20, color: '#1890ff' }} />
                <Text strong style={{ fontSize: 18 }}>审核工作台</Text>
              </Space>
            </Col>
            <Col>
              <Space>
                <Badge count={mandatoryCount} size="small">
                  <Tag color="red">强制审核</Tag>
                </Badge>
                <Badge count={recommendedCount} size="small">
                  <Tag color="orange">推荐审核</Tag>
                </Badge>
                {timeoutCount > 0 && (
                  <Tag color="red" icon={<ClockCircleOutlined />}>
                    {timeoutCount} 条超时
                  </Tag>
                )}
              </Space>
            </Col>
          </Row>
        </Card>

        {timeoutCount > 0 && (
          <Alert banner type="warning" showIcon
            message={`${timeoutCount} 条强制审核超过 ${REVIEW_TIMEOUT_HOURS} 小时未处理，已触发告警升级`}
            style={{ marginBottom: 16 }} />
        )}

        <Card
          extra={
            <Space>
              <Segmented value={levelFilter} onChange={setLevelFilter} size="small"
                options={[
                  { label: `强制 (${mandatoryCount})`, value: 'mandatory' },
                  { label: `推荐 (${recommendedCount})`, value: 'recommended' },
                  { label: '全部', value: 'all' },
                ]} />
              <Button icon={<ReloadOutlined />} onClick={loadReviews} loading={loading} />
              {reviews.length > 0 && (
                <Button type="primary" size="small" onClick={handleBatchApprove}>批量批准</Button>
              )}
            </Space>
          }>
          {reviews.length === 0 ? (
            <Empty description="所有审核已处理完毕" />
          ) : (
            reviews.map((r, i) => (
              <Card key={i} size="small" style={{ marginBottom: 12 }}
                title={
                  <Space>
                    <Tag color={levelColor[r.level]}>{levelLabel[r.level]}</Tag>
                    <Text strong>{r.agent_name || r.agent_key}</Text>
                    <Text type="secondary">{r.task_type}</Text>
                    {isTimeout(r) && <Tag color="red" icon={<ClockCircleOutlined />}>超时</Tag>}
                  </Space>
                }
                extra={
                  <Space>
                    <Button size="small" icon={<EyeOutlined />}
                      onClick={() => { setCurrentReview(r); setDetailVisible(true); }}>
                      详情
                    </Button>
                    <Button size="small" type="primary" icon={<CheckOutlined />}
                      onClick={() => handleApprove(r.id)}>
                      批准
                    </Button>
                    <Button size="small" danger icon={<CloseOutlined />}
                      onClick={() => handleReject(r.id)}>
                      驳回
                    </Button>
                  </Space>
                }>
                <div style={{
                  background: '#fafafa', padding: 12, borderRadius: 4,
                  whiteSpace: 'pre-wrap', maxHeight: 120, overflow: 'auto'
                }}>
                  <Text>{r.result_summary || r.content_summary || '无摘要'}</Text>
                </div>
                <Row style={{ marginTop: 8 }}>
                  <Col span={12}>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      创建: {r.created_at || '-'}
                    </Text>
                  </Col>
                  <Col span={12} style={{ textAlign: 'right' }}>
                    {isTimeout(r) && (
                      <Text type="danger" style={{ fontSize: 12 }}>
                        已超时 {Math.floor((Date.now() - new Date(r.created_at).getTime()) / 3600000)} 小时
                      </Text>
                    )}
                  </Col>
                </Row>
              </Card>
            ))
          )}
        </Card>

        <Modal title="审核详情" open={detailVisible} onCancel={() => setDetailVisible(false)}
          footer={[
            <Button key="close" onClick={() => setDetailVisible(false)}>关闭</Button>,
            <Button key="reject" danger icon={<CloseOutlined />}
              onClick={() => { handleReject(currentReview?.id); setDetailVisible(false); }}>
              驳回
            </Button>,
            <Button key="approve" type="primary" icon={<CheckOutlined />}
              onClick={() => { handleApprove(currentReview?.id); setDetailVisible(false); }}>
              批准执行
            </Button>,
          ]}
          width={650}>
          {currentReview && (
            <>
              <Descriptions column={2} size="small" bordered style={{ marginBottom: 16 }}>
                <Descriptions.Item label="审核级别">
                  <Tag color={levelColor[currentReview.level]}>{levelLabel[currentReview.level]}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="执行 Agent">
                  {currentReview.agent_name || currentReview.agent_key}
                </Descriptions.Item>
                <Descriptions.Item label="任务类型">{currentReview.task_type}</Descriptions.Item>
                <Descriptions.Item label="创建时间">{currentReview.created_at}</Descriptions.Item>
                {isTimeout(currentReview) && (
                  <Descriptions.Item label="超时状态" span={2}>
                    <Tag color="red">已超时 {Math.floor((Date.now() - new Date(currentReview.created_at).getTime()) / 3600000)} 小时</Tag>
                  </Descriptions.Item>
                )}
              </Descriptions>
              <Text strong>执行结果：</Text>
              <div style={{ background: '#fafafa', padding: 16, borderRadius: 4, marginTop: 8, whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>
                {currentReview.result_summary || JSON.stringify(currentReview, null, 2)}
              </div>
              <div style={{ marginTop: 16 }}>
                <Input.TextArea rows={3} placeholder="审批意见（可选）"
                  value={comment} onChange={e => setComment(e.target.value)} />
              </div>
            </>
          )}
        </Modal>
      </Content>
    </Layout>
  );
}