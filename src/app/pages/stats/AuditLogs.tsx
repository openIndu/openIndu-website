import { useState, useEffect } from 'react';
import { api } from '@/api';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import { ShieldAlert, Search } from 'lucide-react';

interface AuditLog {
  id: number;
  admin_username?: string;
  admin_id?: number;
  target_user?: string;
  target_user_id?: number;
  action?: string;
  detail?: string;
  ip?: string;
  created_at?: string;
}

export default function AuditLogs() {
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [endpointMissing, setEndpointMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const pageSize = 15;

  useEffect(() => {
    loadLogs();
  }, [page]);

  async function loadLogs() {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get('/admin/audit-logs', {
        params: { page, page_size: pageSize },
      });
      const data = res.data ?? res;
      if (data.items) {
        setLogs(data.items);
        setTotal(data.total ?? 0);
      } else if (Array.isArray(data)) {
        setLogs(data);
        setTotal(data.length);
      } else {
        setLogs([]);
        setTotal(0);
      }
    } catch (err: any) {
      if (err?.response?.status === 404 || err?.code === 'ERR_BAD_REQUEST') {
        setEndpointMissing(true);
      } else {
        setError('加载审计日志失败，请检查后端服务。');
      }
      setLogs([]);
    } finally {
      setLoading(false);
    }
  }

  const totalPages = Math.ceil(total / pageSize);

  // Show "Coming Soon" if the API endpoint doesn't exist yet
  if (endpointMissing) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">审计日志</h1>
          <p className="text-muted-foreground">管理员操作记录与审计追踪</p>
        </div>
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-16">
            <ShieldAlert className="h-12 w-12 text-muted-foreground mb-4" />
            <h2 className="text-lg font-semibold mb-2">功能即将上线</h2>
            <p className="text-muted-foreground text-center max-w-md">
              审计日志功能正在开发中。后端需要提供{' '}
              <code className="px-1.5 py-0.5 bg-muted rounded text-sm">
                GET /api/admin/audit-logs
              </code>{' '}
              接口，查询 <code className="px-1.5 py-0.5 bg-muted rounded text-sm">admin_audit_logs</code>{' '}
              表数据。
            </p>
            <div className="mt-4 p-4 bg-muted rounded-lg text-sm text-left font-mono">
              <p className="font-semibold mb-1">期望返回字段：</p>
              <p>id, admin_username, target_user, action, detail, ip, created_at</p>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">审计日志</h1>
        <p className="text-muted-foreground">管理员操作记录与审计追踪</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Search className="h-5 w-5" />
            操作记录
          </CardTitle>
          <CardDescription>所有管理员的关键操作记录</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : error ? (
            <div className="text-center py-8 text-muted-foreground">
              <p>{error}</p>
            </div>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>操作管理员</TableHead>
                    <TableHead>目标用户</TableHead>
                    <TableHead>操作类型</TableHead>
                    <TableHead>详情</TableHead>
                    <TableHead>操作时间</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {logs.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={5} className="text-center text-muted-foreground">
                        暂无审计记录
                      </TableCell>
                    </TableRow>
                  ) : (
                    logs.map((log) => (
                      <TableRow key={log.id}>
                        <TableCell className="font-medium">
                          {log.admin_username ?? (log.admin_id ? `ID:${log.admin_id}` : '-')}
                        </TableCell>
                        <TableCell>
                          {log.target_user ?? (log.target_user_id ? `ID:${log.target_user_id}` : '-')}
                        </TableCell>
                        <TableCell>
                          <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-muted">
                            {log.action || '-'}
                          </span>
                        </TableCell>
                        <TableCell className="max-w-xs truncate" title={log.detail}>
                          {log.detail || '-'}
                        </TableCell>
                        <TableCell>
                          {log.created_at
                            ? new Date(log.created_at).toLocaleString('zh-CN')
                            : '-'}
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>

              {totalPages > 1 && (
                <div className="flex items-center justify-end gap-2 mt-4">
                  <button
                    className="px-3 py-1 text-sm border rounded-md hover:bg-accent disabled:opacity-50"
                    disabled={page <= 1}
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                  >
                    上一页
                  </button>
                  <span className="text-sm text-muted-foreground">
                    第 {page} / {totalPages} 页
                  </span>
                  <button
                    className="px-3 py-1 text-sm border rounded-md hover:bg-accent disabled:opacity-50"
                    disabled={page >= totalPages}
                    onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  >
                    下一页
                  </button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
