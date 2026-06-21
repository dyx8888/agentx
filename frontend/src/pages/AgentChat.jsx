import { useState, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Layout, Typography, Input, Button, Card, Tag, Space, Spin,
  Avatar, Tooltip, Drawer, Empty, message, Badge, Divider, Segmented
} from 'antd';
import {
  SendOutlined, RobotOutlined, UserOutlined, ToolOutlined,
  CheckCircleOutlined, ExclamationCircleOutlined,
  ClockCircleOutlined, ThunderboltOutlined, LeftOutlined,
  AuditOutlined, ExpandOutlined, CompressOutlined,
  LoadingOutlined, ApiOutlined, BranchesOutlined
} from '@ant-design/icons';
import { chatWithAgent } from '@/lib/api';

const { Content } = Layout;
const { Text, Paragraph } = Typography;

const STATUS_ICON = {
  running: <LoadingOutlined spin style={{ color: '#1890ff' }} />,
  completed: <CheckCircleOutlined style={{ color: '#52c41a' }} />,
  failed: <ExclamationCircleOutlined style={{ color: '#ff4d4f' }} />,
  pending: <ClockCircleOutlined style={{ color: '#faad14' }} />,
};

const STATUS_LABEL = {
  running: '执行中',
  completed: '已完成',
  failed: '失败',
  pending: '等待审核',
};

function ToolCallCard({ call }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <Card size="small" style={{ marginBottom: 4, background: '#f0f5ff', border: '1px solid #d6e4ff' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
        onClick={() => setExpanded(!expanded)}>
        <Space>
          <ApiOutlined style={{ color: '#1890ff' }} />
          <Text strong style={{ fontSize: 13 }}>{call.tool_name}</Text>
          {STATUS_ICON[call.status]}
          <Text type="secondary" style={{ fontSize: 12 }}>{STATUS_LABEL[call.status]}</Text>
        </Space>
        <Button type="text" size="small" icon={expanded ? <CompressOutlined /> : <ExpandOutlined />} />
      </div>
      {expanded && call.input && (
        <div style={{ marginTop: 8, background: '#fff', padding: 8, borderRadius: 4, fontSize: 12 }}>
          <Text type="secondary">输入参数：</Text>
          <pre style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{JSON.stringify(call.input, null, 2)}</pre>
        </div>
      )}
      {expanded && call.output && (
        <div style={{ marginTop: 4, background: '#fff', padding: 8, borderRadius: 4, fontSize: 12 }}>
          <Text type="secondary">输出结果：</Text>
          <pre style={{ margin: 0, whiteSpace: 'pre-wrap', maxHeight: 150, overflow: 'auto' }}>
            {typeof call.output === 'string' ? call.output : JSON.stringify(call.output, null, 2)}
          </pre>
        </div>
      )}
    </Card>
  );
}

export default function AgentChat() {
  const { agentId } = useParams();
  const navigate = useNavigate();

  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [toolCalls, setToolCalls] = useState([]);
  const [showToolPanel, setShowToolPanel] = useState(false);
  const messagesEndRef = useRef(null);

  const [agentInfo] = useState({
    key: agentId,
    name: agentId?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()) || 'Unknown',
    type: agentId,
  });

  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const handleSend = async () => {
    const text = inputValue.trim();
    if (!text || streaming) return;

    const userMsg = { role: 'user', content: text, timestamp: Date.now() };
    setMessages(prev => [...prev, userMsg]);
    setInputValue('');
    setStreaming(true);
    setToolCalls([]);

    try {
      let assistantContent = '';
      const currentCalls = [];

      const assistantMsg = { role: 'assistant', content: '', timestamp: Date.now(), toolCalls: [] };
      setMessages(prev => [...prev, assistantMsg]);

      await chatWithAgent(agentId, text, (chunk) => {
        if (chunk.type === 'done') {
          setStreaming(false);
          return;
        }

        if (chunk.type === 'error') {
          message.error(chunk.content || '对话出错');
          setStreaming(false);
          return;
        }

        if (chunk.type === 'thinking') {
          return;
        }

        if (chunk.type === 'sources') {
          return;
        }

        if (chunk.type === 'tool_call') {
          const call = { tool_name: chunk.tool, input: chunk.args,
            status: 'running', output: null };
          currentCalls.push(call);
          setToolCalls([...currentCalls]);
          setMessages(prev => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === 'assistant') {
              updated[updated.length - 1] = { ...last, toolCalls: [...currentCalls] };
            }
            return updated;
          });
        } else if (chunk.type === 'tool_result') {
          const lastCall = currentCalls[currentCalls.length - 1];
          if (lastCall) {
            lastCall.output = chunk.result;
            lastCall.status = 'completed';
            setToolCalls([...currentCalls]);
            setMessages(prev => {
              const updated = [...prev];
              const last = updated[updated.length - 1];
              if (last?.role === 'assistant') {
                updated[updated.length - 1] = { ...last, toolCalls: [...currentCalls] };
              }
              return updated;
            });
          }
        } else if (chunk.type === 'text' || chunk.content) {
          assistantContent += chunk.content || chunk.text || '';
          setMessages(prev => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === 'assistant') {
              updated[updated.length - 1] = { ...last, content: assistantContent };
            }
            return updated;
          });
        } else if (chunk.type === 'review_required') {
          setMessages(prev => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === 'assistant') {
              updated[updated.length - 1] = { ...last, needsReview: true, reviewLevel: chunk.level };
            }
            return updated;
          });
        }
      });
    } catch (err) {
      message.error('对话出错：' + (err.message || '网络异常'));
    } finally {
      setStreaming(false);
    }
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <Layout style={{ minHeight: '100vh', background: '#f5f5f5' }}>
      <div style={{
        background: '#fff', padding: '8px 16px', display: 'flex', alignItems: 'center',
        boxShadow: '0 1px 4px rgba(0,0,0,0.06)', position: 'sticky', top: 0, zIndex: 10,
      }}>
        <Button type="text" icon={<LeftOutlined />} onClick={() => navigate('/dashboard')} />
        <Avatar icon={<RobotOutlined />} style={{ background: '#1890ff', marginLeft: 8 }} />
        <Text strong style={{ marginLeft: 8, fontSize: 16 }}>{agentInfo.name}</Text>
        <div style={{ flex: 1 }} />
        <Button type="text" icon={<AuditOutlined />}
          onClick={() => setShowToolPanel(!showToolPanel)}>
          审核
        </Button>
      </div>

      <Content style={{ maxWidth: 800, margin: '0 auto', width: '100%', padding: '16px', flex: 1, overflow: 'auto' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12, paddingBottom: 80 }}>
          {messages.length === 0 && (
            <div style={{ textAlign: 'center', marginTop: '20vh' }}>
              <RobotOutlined style={{ fontSize: 48, color: '#d9d9d9' }} />
              <div style={{ marginTop: 16 }}>
                <Text type="secondary">与 {agentInfo.name} 开始对话</Text>
              </div>
              <div style={{ marginTop: 12, display: 'flex', flexWrap: 'wrap', gap: 8, justifyContent: 'center' }}>
                {['帮我分析今天的销售数据', '查看最近的订单状态', '检查库存告警', '生成周报'].map(q => (
                  <Button key={q} size="small" onClick={() => { setInputValue(q); /* sends on next Enter */ }}>
                    {q}
                  </Button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} style={{
              display: 'flex', flexDirection: msg.role === 'user' ? 'row-reverse' : 'row',
              alignItems: 'flex-start', gap: 8,
            }}>
              <Avatar
                icon={msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
                style={{ background: msg.role === 'user' ? '#52c41a' : '#1890ff' }}
              />
              <div style={{ maxWidth: '75%' }}>
                {msg.needsReview && (
                  <Tag color={msg.reviewLevel === 'mandatory' ? 'red' : 'orange'} style={{ marginBottom: 4 }}>
                    {msg.reviewLevel === 'mandatory' ? '⏳ 强制审核中' : '⏳ 推荐审核中'}
                  </Tag>
                )}
                <Card size="small" style={{
                  background: msg.role === 'user' ? '#e6f7ff' : '#fff',
                  border: '1px solid #f0f0f0',
                }}>
                  {msg.role === 'assistant' && !msg.content && !msg.toolCalls?.length && (
                    <Space><LoadingOutlined /> <Text type="secondary">思考中...</Text></Space>
                  )}
                  {msg.content && <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{msg.content}</Paragraph>}
                  {msg.toolCalls?.length > 0 && (
                    <div style={{ marginTop: msg.content ? 8 : 0 }}>
                      {msg.toolCalls.map((tc, j) => (
                        <ToolCallCard key={j} call={tc} />
                      ))}
                    </div>
                  )}
                </Card>
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      </Content>

      <div style={{
        position: 'sticky', bottom: 0, background: '#fff', padding: '12px 16px',
        borderTop: '1px solid #f0f0f0', boxShadow: '0 -2px 8px rgba(0,0,0,0.04)',
      }}>
        <div style={{ maxWidth: 800, margin: '0 auto', display: 'flex', gap: 8, alignItems: 'flex-end' }}>
          <Input.TextArea
            value={inputValue}
            onChange={e => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={`向 ${agentInfo.name} 发送任务...`}
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={streaming}
            style={{ flex: 1 }}
          />
          <Button type="primary" icon={<SendOutlined />}
            onClick={handleSend} loading={streaming} disabled={!inputValue.trim()}>
            发送
          </Button>
        </div>
      </div>

      <Drawer title="工具调用详情" placement="right" open={showToolPanel}
        onClose={() => setShowToolPanel(false)} width={400}>
        {toolCalls.length === 0 ? (
          <Empty description="暂无工具调用" />
        ) : (
          toolCalls.map((tc, i) => (
            <ToolCallCard key={i} call={tc} />
          ))
        )}
      </Drawer>
    </Layout>
  );
}