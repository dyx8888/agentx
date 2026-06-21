import { BellOutlined, QuestionCircleOutlined, SearchOutlined, DownOutlined } from "@ant-design/icons";
import { Input, Button, Avatar, Badge, Dropdown, Space, Menu } from "antd";
import { removeAuthToken } from "@/lib/api";
import { useNavigate } from "react-router-dom";

export function DashboardHeader() {
  const navigate = useNavigate();

  const handleLogout = () => {
    removeAuthToken();
    navigate("/");
  };

  const userMenuItems = [
    {
      key: 'profile',
      label: '个人设置',
    },
    {
      key: 'account',
      label: '账户管理',
    },
    {
      type: 'divider',
    },
    {
      key: 'logout',
      label: '退出登录',
      danger: true,
      onClick: handleLogout,
    },
  ];

  return (
    <header style={{ 
      position: 'sticky', 
      top: 0, 
      zIndex: 30, 
      display: 'flex', 
      height: '64px', 
      alignItems: 'center', 
      justifyContent: 'space-between', 
      borderBottom: '1px solid #d9d9d9', 
      background: '#fff', 
      padding: '0 24px'
    }}>
      {/* Search */}
      <div style={{ position: 'relative', width: '100%', maxWidth: '400px' }}>
        <Input
          placeholder="搜索..."
          prefix={<SearchOutlined />}
          style={{ height: '40px' }}
        />
      </div>

      {/* Right Actions */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        {/* Notifications */}
        <Badge count={3} size="small">
          <Button
            type="text"
            icon={<BellOutlined />}
            style={{ height: '40px', width: '40px' }}
          />
        </Badge>

        {/* Help */}
        <Button
          type="text"
          icon={<QuestionCircleOutlined />}
          style={{ height: '40px', width: '40px' }}
        />

        {/* User Menu */}
        <Dropdown
          menu={{ items: userMenuItems }}
          placement="bottomRight"
        >
          <Button
            type="text"
            style={{ display: 'flex', alignItems: 'center', gap: '8px', height: '40px', padding: '0 8px' }}
          >
            <Avatar size="small" style={{ backgroundColor: '#1890ff' }}>
              管
            </Avatar>
            <span style={{ fontSize: '14px', fontWeight: 500 }}>
              管理员
            </span>
            <DownOutlined />
          </Button>
        </Dropdown>
      </div>
    </header>
  );
}
