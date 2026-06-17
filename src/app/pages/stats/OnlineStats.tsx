import { useState, useEffect } from 'react';
import { statsApi } from '@/api';
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
import { Users, MapPin, Monitor, Clock } from 'lucide-react';

interface GeoItem {
  region: string;
  count: number;
}

interface OnlineData {
  count: number;
  geo?: GeoItem[];
}

interface LoginRecord {
  id: number;
  username?: string;
  ip?: string;
  location?: string;
  login_time?: string;
  created_at?: string;
}

export default function OnlineStats() {
  const [online, setOnline] = useState<OnlineData | null>(null);
  const [logins, setLogins] = useState<LoginRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loginPage, setLoginPage] = useState(1);
  const [loginTotal, setLoginTotal] = useState(0);
  const pageSize = 10;

  useEffect(() => {
    loadOnlineStats();
  }, []);

  useEffect(() => {
    loadLoginHistory();
  }, [loginPage]);

  async function loadOnlineStats() {
    setLoading(true);
    try {
      const res = await statsApi.online();
      const data = res.data ?? res;
      setOnline(data);
    } catch (err) {
      console.error('Failed to fetch online stats:', err);
    } finally {
      setLoading(false);
    }
  }

  async function loadLoginHistory() {
    try {
      const res = await statsApi.loginHistory({ page: loginPage, page_size: pageSize });
      const data = res.data ?? res;
      setLogins(data.items ?? data.records ?? []);
      setLoginTotal(data.total ?? 0);
    } catch (err) {
      console.error('Failed to fetch login history:', err);
    }
  }

  const totalPages = Math.ceil(loginTotal / pageSize);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">在线统计</h1>
        <p className="text-muted-foreground">当前在线用户与地域分布</p>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">当前在线</CardTitle>
            <Users className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-8 w-20" />
            ) : (
              <div className="text-2xl font-bold">{online?.count ?? 0}</div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">活跃地区</CardTitle>
            <MapPin className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-8 w-20" />
            ) : (
              <div className="text-2xl font-bold">{online?.geo?.length ?? 0}</div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">今日登录</CardTitle>
            <Monitor className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            {loading ? (
              <Skeleton className="h-8 w-20" />
            ) : (
              <div className="text-2xl font-bold">{loginTotal}</div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium">登录记录</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{loginTotal}</div>
          </CardContent>
        </Card>
      </div>

      {/* Geo Distribution */}
      <Card>
        <CardHeader>
          <CardTitle>地域分布</CardTitle>
          <CardDescription>当前在线用户的地域分布情况</CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-1/2" />
            </div>
          ) : online?.geo && online.geo.length > 0 ? (
            <div className="space-y-3">
              {online.geo.map((item, idx) => (
                <div key={idx} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <MapPin className="h-4 w-4 text-muted-foreground" />
                    <span className="font-medium">{item.region}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div
                      className="h-2 rounded-full bg-primary"
                      style={{ width: `${Math.max(item.count * 10, 8)}px` }}
                    />
                    <span className="text-sm text-muted-foreground">{item.count} 人</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">暂无地域分布数据</p>
          )}
        </CardContent>
      </Card>

      {/* Login History Table */}
      <Card>
        <CardHeader>
          <CardTitle>登录历史</CardTitle>
          <CardDescription>最近用户登录记录</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>用户</TableHead>
                <TableHead>IP 地址</TableHead>
                <TableHead>登录地区</TableHead>
                <TableHead>登录时间</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {logins.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground">
                    暂无登录记录
                  </TableCell>
                </TableRow>
              ) : (
                logins.map((record) => (
                  <TableRow key={record.id}>
                    <TableCell className="font-medium">{record.username || '-'}</TableCell>
                    <TableCell>{record.ip || '-'}</TableCell>
                    <TableCell>{record.location || '-'}</TableCell>
                    <TableCell>
                      {record.login_time
                        ? new Date(record.login_time).toLocaleString('zh-CN')
                        : record.created_at
                          ? new Date(record.created_at).toLocaleString('zh-CN')
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
                disabled={loginPage <= 1}
                onClick={() => setLoginPage((p) => Math.max(1, p - 1))}
              >
                上一页
              </button>
              <span className="text-sm text-muted-foreground">
                第 {loginPage} / {totalPages} 页
              </span>
              <button
                className="px-3 py-1 text-sm border rounded-md hover:bg-accent disabled:opacity-50"
                disabled={loginPage >= totalPages}
                onClick={() => setLoginPage((p) => Math.min(totalPages, p + 1))}
              >
                下一页
              </button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
