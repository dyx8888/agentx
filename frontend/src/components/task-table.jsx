"use client";

import { useEffect, useState } from "react";
import { getTasks } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Search, Filter } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

const statusConfig = {
  pending: { label: "待处理", className: "bg-amber-100 text-amber-700" },
  in_progress: { label: "进行中", className: "bg-blue-100 text-blue-700" },
  review: { label: "待审核", className: "bg-purple-100 text-purple-700" },
  completed: { label: "已完成", className: "bg-emerald-100 text-emerald-700" },
};

const priorityConfig = {
  low: { label: "低", className: "text-slate-500" },
  medium: { label: "中", className: "text-amber-600" },
  high: { label: "高", className: "text-red-600" },
};

// 示例数据，当 API 失败时使用
const mockTasks = [
  {
    id: "1",
    name: "为新品寻找美妆达人",
    assignee: "BrandBD",
    status: "in_progress",
    dueDate: "2025-05-15",
    priority: "high",
    description: "寻找适合新品推广的美妆博主进行合作",
  },
  {
    id: "2",
    name: "生成618活动话术",
    assignee: "ContentAI",
    status: "review",
    dueDate: "2025-05-12",
    priority: "high",
    description: "为即将到来的618活动生成营销话术",
  },
  {
    id: "3",
    name: "上季度ROI复盘报告",
    assignee: "DataBot",
    status: "completed",
    dueDate: "2025-05-10",
    priority: "medium",
    description: "整理并分析上季度的投资回报数据",
  },
  {
    id: "4",
    name: "处理客户售后问题",
    assignee: "ServiceBot",
    status: "in_progress",
    dueDate: "2025-05-11",
    priority: "medium",
    description: "跟进并解决客户的售后投诉",
  },
  {
    id: "5",
    name: "竞品分析报告",
    assignee: "DataBot",
    status: "pending",
    dueDate: "2025-05-20",
    priority: "low",
    description: "分析主要竞争对手的市场表现",
  },
];

export function TaskTable() {
  const [tasks, setTasks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");

  useEffect(() => {
    async function fetchTasks() {
      try {
        const data = await getTasks();
        setTasks(data);
      } catch (err) {
        console.log("[v0] API not available, using mock data");
        setTasks(mockTasks);
      } finally {
        setLoading(false);
      }
    }
    fetchTasks();
  }, []);

  const filteredTasks = tasks.filter(
    (task) =>
      task.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      task.assignee.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleDateString("zh-CN", {
      month: "short",
      day: "numeric",
    });
  };

  if (loading) {
    return (
      <Card>
        <CardHeader>
          <Skeleton className="h-6 w-32" />
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[...Array(5)].map((_, i) => (
              <Skeleton key={i} className="h-12 w-full" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
        <CardTitle className="text-lg font-semibold">最近任务</CardTitle>
        <button className="text-sm text-primary hover:underline">
          查看全部
        </button>
      </CardHeader>
      <CardContent>
        {/* Search and Filter */}
        <div className="mb-4 flex items-center gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              type="text"
              placeholder="搜索任务..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
            />
          </div>
          <Button variant="outline" size="icon">
            <Filter className="h-4 w-4" />
          </Button>
        </div>

        {/* Table */}
        <div className="rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/50">
                <TableHead className="font-medium">任务名称</TableHead>
                <TableHead className="font-medium">负责人</TableHead>
                <TableHead className="font-medium">状态</TableHead>
                <TableHead className="font-medium">优先级</TableHead>
                <TableHead className="text-right font-medium">截止日期</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredTasks.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                    暂无任务数据
                  </TableCell>
                </TableRow>
              ) : (
                filteredTasks.map((task) => (
                  <TableRow
                    key={task.id}
                    className="cursor-pointer transition-colors hover:bg-muted/50"
                  >
                    <TableCell>
                      <div>
                        <p className="font-medium">{task.name}</p>
                        {task.description && (
                          <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                            {task.description}
                          </p>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="text-sm">{task.assignee}</span>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant="secondary"
                        className={statusConfig[task.status]?.className || ""}
                      >
                        {statusConfig[task.status]?.label || task.status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {task.priority && (
                        <span
                          className={`text-sm font-medium ${
                            priorityConfig[task.priority]?.className || ""
                          }`}
                        >
                          {priorityConfig[task.priority]?.label || task.priority}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right text-sm text-muted-foreground">
                      {formatDate(task.dueDate)}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>
      </CardContent>
    </Card>
  );
}
