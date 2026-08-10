import { useLocation, useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { removeAuthToken } from "@/lib/api";
import {
  DashboardOutlined,
  TeamOutlined,
  FileTextOutlined,
  BarChartOutlined,
  SettingOutlined,
  LogoutOutlined,
  RobotOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from "@ant-design/icons";
import { Avatar, Button, Menu } from "antd";
import { useState } from "react";

const menuItems = [
  { icon: DashboardOutlined, label: "工作台概览", href: "/dashboard" },
  { icon: TeamOutlined, label: "数字员工", href: "/dashboard/agents" },
  { icon: FileTextOutlined, label: "任务管理", href: "/dashboard/tasks" },
  { icon: BarChartOutlined, label: "数据分析", href: "/dashboard/analytics" },
  { icon: SettingOutlined, label: "系统设置", href: "/dashboard/settings" },
];

export function DashboardSidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);

  const handleLogout = () => {
    removeAuthToken();
    navigate("/");
  };

  const menuData = menuItems.map((item) => ({
    key: item.href,
    icon: <item.icon />,
    label: item.label,
  }));

  return (
    <div style={{
      position: 'fixed',
      left: 0,
      top: 0,
      zIndex: 40,
      display: 'flex',
      height: '100vh',
      flexDirection: 'column',
      background: '#001529',
      color: '#fff',
      transition: 'all 0.3s',
      width: collapsed ? '80px' : '256px'
    }}>
      {/* Logo */}
      <div style={{ 
        display: 'flex', 
        height: '64px', 
        alignItems: 'center', 
        justifyContent: 'space-between', 
        borderBottom: '1px solid #1f2937', 
        padding: '0 16px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ 
            display: 'flex', 
            height: '32px', 
            width: '32px', 
            alignItems: 'center', 
            justifyContent: 'center', 
            borderRadius: '6px', 
            background: '#1890ff' 
          }}>
            <RobotOutlined style={{ color: '#fff' }} />
          </div>
          {!collapsed && (
            <span style={{ fontSize: '18px', fontWeight: 600 }}>AgentX</span>
          )}
        </div>
        <Button
          type="text"
          icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          style={{ 
            height: '32px', 
            width: '32px', 
            color: '#8b92a9',
            border: 'none'
          }}
          onClick={() => setCollapsed(!collapsed)}
        />
      </div>

      {/* Navigation */}
      <div style={{ flex: 1, padding: '8px' }}>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuData}
          inlineCollapsed={collapsed}
          style={{ 
            background: 'transparent', 
            border: 'none',
            color: '#8b92a9'
          }}
          onClick={({ key }) => navigate(key)}
        />
      </div>

      {/* User Section */}
      <div style={{ borderTop: '1px solid #1f2937', padding: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
          <Avatar size="small" style={{ backgroundColor: '#1890ff' }}>
            管
          </Avatar>
          {!collapsed && (
            <div style={{ flex: 1, overflow: 'hidden' }}>
              <div style={{ fontSize: '14px', fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                管理员
              </div>
              <div style={{ fontSize: '12px', color: '#8b92a9', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                admin@agentx.com
              </div>
            </div>
          )}
        </div>
        <Button
          type="text"
          icon={<LogoutOutlined />}
          block={collapsed}
          style={{ 
            color: '#8b92a9',
            border: 'none',
            height: '40px'
          }}
          onClick={handleLogout}
        >
          {!collapsed && '退出登录'}
        </Button>
      </div>
    </div>
  );
}
