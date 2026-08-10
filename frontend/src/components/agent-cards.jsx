import { useEffect, useState } from "react";
import { getAgents } from "@/lib/api";
import { Card, Avatar, Badge, Skeleton, Typography } from "antd";
import { RobotOutlined, CheckCircleOutlined, ClockCircleOutlined, TeamOutlined } from "@ant-design/icons";

const statusConfig = {
  online: { label: "在线", className: "bg-emerald-100 text-emerald-700" },
  offline: { label: "离线", className: "bg-slate-100 text-slate-600" },
  busy: { label: "忙碌", className: "bg-amber-100 text-amber-700" },
};

// 示例数据，当 API 失败时使用
const mockAgents = [
  {
    id: "1",
    name: "BrandBD",
    role: "品牌商务拓展",
    status: "online",
    tasksCompleted: 156,
    description: "负责达人合作与品牌推广",
  },
  {
    id: "2",
    name: "ContentAI",
    role: "内容创作助手",
    status: "online",
    tasksCompleted: 89,
    description: "生成营销文案与活动话术",
  },
  {
    id: "3",
    name: "DataBot",
    role: "数据分析师",
    status: "busy",
    tasksCompleted: 234,
    description: "分析运营数据与ROI报告",
  },
  {
    id: "4",
    name: "ServiceBot",
    role: "客户服务",
    status: "online",
    tasksCompleted: 178,
    description: "处理客户咨询与售后问题",
  },
];

export function AgentCards() {
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    async function fetchAgents() {
      try {
        const data = await getAgents();
        setAgents(data);
      } catch (err) {
        console.log("[v0] API not available, using mock data");
        setAgents(mockAgents);
        setError(null);
      } finally {
        setLoading(false);
      }
    }
    fetchAgents();
  }, []);

  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => (
          <Card key={i}>
            <CardContent className="p-4">
              <Skeleton className="mb-3 h-12 w-12 rounded-full" />
              <Skeleton className="mb-2 h-5 w-24" />
              <Skeleton className="h-4 w-32" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  // 统计卡片数据
  const stats = [
    {
      icon: Users,
      label: "在职员工数",
      value: agents.length || 4,
      change: "+2",
      positive: true,
    },
    {
      icon: CheckCircle2,
      label: "本月完成任务",
      value: agents.reduce((sum, a) => sum + (a.tasksCompleted || 0), 0) || 156,
      change: "+12.5%",
      positive: true,
    },
    {
      icon: Clock,
      label: "待处理任务",
      value: 23,
      change: "-5",
      positive: true,
    },
    {
      icon: Bot,
      label: "团队协作次数",
      value: 89,
      change: "+18%",
      positive: true,
    },
  ];

  return (
    <div className="space-y-6">
      {/* 统计卡片 */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat, index) => (
          <Card key={index} className="overflow-hidden">
            <CardContent className="p-4">
              <div className="flex items-start justify-between">
                <div>
                  <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                    <stat.icon className="h-5 w-5 text-primary" />
                  </div>
                  <p className="text-sm text-muted-foreground">{stat.label}</p>
                  <div className="mt-1 flex items-baseline gap-2">
                    <span className="text-2xl font-bold">{stat.value}</span>
                    <span
                      className={`text-xs font-medium ${
                        stat.positive ? "text-emerald-600" : "text-red-600"
                      }`}
                    >
                      {stat.change}
                    </span>
                  </div>
                </div>
                <div className="h-12 w-20">
                  {/* Mini sparkline placeholder */}
                  <svg className="h-full w-full" viewBox="0 0 80 48">
                    <path
                      d="M0 40 L20 30 L40 35 L60 20 L80 10"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      className="text-primary/30"
                    />
                    <path
                      d="M0 40 L20 30 L40 35 L60 20 L80 10 L80 48 L0 48 Z"
                      fill="currentColor"
                      className="text-primary/10"
                    />
                  </svg>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* 数字员工卡片 */}
      <div>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold">数字员工</h2>
          <button className="text-sm text-primary hover:underline">
            查看全部
          </button>
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {agents.map((agent) => (
            <Card
              key={agent.id}
              className="cursor-pointer transition-shadow hover:shadow-md"
            >
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <Avatar className="h-12 w-12 border-2 border-primary/20">
                    <AvatarImage src={agent.avatar} alt={agent.name} />
                    <AvatarFallback className="bg-primary/10 text-primary">
                      <Bot className="h-6 w-6" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="flex-1 overflow-hidden">
                    <div className="flex items-center justify-between">
                      <h3 className="truncate font-medium">{agent.name}</h3>
                      <Badge
                        variant="secondary"
                        className={statusConfig[agent.status].className}
                      >
                        {statusConfig[agent.status].label}
                      </Badge>
                    </div>
                    <p className="mt-0.5 text-sm text-muted-foreground">
                      {agent.role}
                    </p>
                    {agent.description && (
                      <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
                        {agent.description}
                      </p>
                    )}
                    {agent.tasksCompleted !== undefined && (
                      <div className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
                        <CheckCircle2 className="h-3 w-3" />
                        <span>已完成 {agent.tasksCompleted} 个任务</span>
                      </div>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}
