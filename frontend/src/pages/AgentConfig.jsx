import React, { useState, useEffect } from 'react';
import { Table, Card, Button, Modal, Form, Input, Select, Switch, Popconfirm, message, Tag, Space } from 'antd';
import { PlusOutlined, EditOutlined, DeleteOutlined, UserOutlined, ToolOutlined } from '@ant-design/icons';
import axios from 'axios';

const AgentConfig = () => {
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(false);
  const [modalVisible, setModalVisible] = useState(false);
  const [editingAgent, setEditingAgent] = useState(null);
  const [tools, setTools] = useState([]);
  const [form] = Form.useForm();

  // 获取工具列表
  useEffect(() => {
    const fetchTools = async () => {
      try {
        const response = await axios.get('/api/admin/tools');
        setTools(response.data || []);
      } catch (error) {
        console.error('Failed to fetch tools:', error);
        message.error('获取工具列表失败');
      }
    };

    const fetchAgents = async () => {
      setLoading(true);
      try {
        const token = localStorage.getItem('token');
        const response = await axios.get('/api/admin/agents', {
          headers: { Authorization: `Bearer ${token}` }
        });
        setAgents(response.data || []);
      } catch (error) {
        console.error('Failed to fetch agents:', error);
        message.error('获取数字员工列表失败');
        // 模拟数据用于演示
        setAgents([
          {
            id: 1,
            name: 'BrandBD',
            description: '品牌商务专家，负责KOL营销和品牌推广',
            tools_json: ['search_kols', 'analyze_performance', 'generate_report'],
            created_at: '2024-01-01T00:00:00Z',
            status: 'active'
          },
          {
            id: 2,
            name: 'CC',
            description: '内容创作专家，负责文案生成和内容编辑',
            tools_json: ['generate_script', 'edit_content'],
            created_at: '2024-01-01T00:00:00Z',
            status: 'active'
          },
          {
            id: 3,
            name: 'Amy',
            description: '数据分析专家，负责性能分析和策略建议',
            tools_json: ['analyze_data', 'generate_strategy'],
            created_at: '2024-01-01T00:00:00Z',
            status: 'inactive'
          }
        ]);
      } finally {
        setLoading(false);
      }
    };

    fetchTools();
    fetchAgents();
  }, []);

  const handleCreate = () => {
    setEditingAgent(null);
    form.resetFields();
    setModalVisible(true);
  };

  const handleEdit = (agent) => {
    setEditingAgent(agent);
    form.setFieldsValue({
      name: agent.name,
      description: agent.description,
      tools_json: agent.tools_json
    });
    setModalVisible(true);
  };

  const handleDelete = async (agentId) => {
    try {
      const token = localStorage.getItem('token');
      await axios.delete(`/api/admin/agents/${agentId}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      message.success('数字员工删除成功');
      // 重新获取列表
      const response = await axios.get('/api/admin/agents', {
        headers: { Authorization: `Bearer ${token}` }
      });
      setAgents(response.data || []);
    } catch (error) {
      console.error('Failed to delete agent:', error);
      message.error('删除数字员工失败');
    }
  };

  const handleToggleStatus = async (agent) => {
    try {
      const token = localStorage.getItem('token');
      const newStatus = agent.status === 'active' ? 'inactive' : 'active';
      await axios.put(`/api/admin/agents/${agent.id}`, {
        status: newStatus
      }, {
        headers: { Authorization: `Bearer ${token}` }
      });
      message.success(`数字员工已${newStatus === 'active' ? '启用' : '停用'}`);
      // 更新本地状态
      setAgents(agents.map(a => 
        a.id === agent.id ? { ...a, status: newStatus } : a
      ));
    } catch (error) {
      console.error('Failed to toggle agent status:', error);
      message.error('状态更新失败');
    }
  };

  const handleModalOk = async () => {
    try {
      const values = form.getFieldsValue();
      const token = localStorage.getItem('token');
      
      if (editingAgent) {
        // 编辑现有Agent
        await axios.put(`/api/admin/agents/${editingAgent.id}`, values, {
          headers: { Authorization: `Bearer ${token}` }
        });
        message.success('数字员工更新成功');
      } else {
        // 创建新Agent
        await axios.post('/api/admin/agents', values, {
          headers: { Authorization: `Bearer ${token}` }
        });
        message.success('数字员工创建成功');
      }
      
      setModalVisible(false);
      form.resetFields();
      // 重新获取列表
      const response = await axios.get('/api/admin/agents', {
        headers: { Authorization: `Bearer ${token}` }
      });
      setAgents(response.data || []);
    } catch (error) {
      console.error('Failed to save agent:', error);
      message.error('保存数字员工失败');
    }
  };

  const columns = [
    {
      title: 'ID',
      dataIndex: 'id',
      key: 'id',
      width: 60,
    },
    {
      title: '员工名称',
      dataIndex: 'name',
      key: 'name',
      render: (text) => <strong>{text}</strong>,
    },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      width: 300,
      ellipsis: true,
    },
    {
      title: '工具数量',
      dataIndex: 'tools_json',
      key: 'tools_count',
      width: 100,
      render: (tools) => (
        <Tag color="blue" icon={<ToolOutlined />}>
          {Array.isArray(tools) ? tools.length : 0}
        </Tag>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status) => (
        <Tag color={status === 'active' ? 'green' : 'red'}>
          {status === 'active' ? '在线' : '离线'}
        </Tag>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 150,
      render: (time) => new Date(time).toLocaleDateString(),
    },
    {
      title: '操作',
      key: 'actions',
      width: 200,
      render: (_, record) => (
        <Space>
          <Button
            type="link"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
            size="small"
          >
            编辑
          </Button>
          <Button
            type="link"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record.id)}
            size="small"
          >
            删除
          </Button>
          <Switch
            checked={record.status === 'active'}
            onChange={() => handleToggleStatus(record)}
            size="small"
            checkedChildren="启用"
            unCheckedChildren="停用"
          />
        </Space>
      ),
    },
  ];

  return (
    <div style={{ padding: '24px' }}>
      <Card
        title={
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '18px', fontWeight: 'bold' }}>
              <UserOutlined style={{ marginRight: '8px' }} />
              数字员工配置
            </span>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleCreate}
            >
              雇佣新员工
            </Button>
          </div>
        }
        style={{ marginBottom: '16px' }}
      >
        <Table
          columns={columns}
          dataSource={agents}
          rowKey="id"
          loading={loading}
          pagination={{
            pageSize: 10,
            showSizeChanger: true,
            showQuickJumper: true,
            showTotal: (total) => `共 ${total} 条记录`,
          }}
        />
      </Card>

      <Modal
        title={editingAgent ? '编辑数字员工' : '雇佣新员工'}
        open={modalVisible}
        onOk={handleModalOk}
        onCancel={() => setModalVisible(false)}
        width={600}
        okText="保存"
        cancelText="取消"
      >
        <Form
          form={form}
          layout="vertical"
          style={{ padding: '20px 0' }}
        >
          <Form.Item
            label="员工名称"
            name="name"
            rules={[{ required: true, message: '请输入员工名称' }]}
          >
            <Input placeholder="请输入员工名称" />
          </Form.Item>

          <Form.Item
            label="员工描述"
            name="description"
            rules={[{ required: true, message: '请输入员工描述' }]}
          >
            <Input.TextArea 
              rows={4} 
              placeholder="请输入员工描述" 
            />
          </Form.Item>

          <Form.Item
            label="工具列表"
            name="tools_json"
            rules={[{ required: true, message: '请选择工具' }]}
          >
            <Select
              mode="multiple"
              placeholder="请选择工具"
              style={{ width: '100%' }}
            >
              {tools.map(tool => (
                <Select.Option key={tool.name} value={tool.name}>
                  {tool.description || tool.name}
                </Select.Option>
              ))}
            </Select>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default AgentConfig;
