import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { money } from '../utils';

type Point = { month?: string; revenue?: number };

export default function RevenueChart({ data, compact = false }: { data: Point[]; compact?: boolean }) {
  if (compact) {
    return (
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <CartesianGrid stroke="#eee" vertical={false} />
          <XAxis dataKey="month" />
          <Tooltip formatter={(value: number) => money(value)} />
          <Area dataKey="revenue" stroke="#7666e9" fill="#7666e922" />
        </AreaChart>
      </ResponsiveContainer>
    );
  }
  return (
    <ResponsiveContainer width="100%" height="100%">
      <AreaChart data={data} margin={{ top: 10, right: 5, bottom: 0, left: -20 }}>
        <defs>
          <linearGradient id="revFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#7561ec" stopOpacity={0.19} />
            <stop offset="90%" stopColor="#7561ec" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#eeeeeb" vertical={false} />
        <XAxis dataKey="month" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: '#979791' }} dy={12} />
        <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: '#979791' }} tickFormatter={value => `₹${value / 1000}k`} />
        <Tooltip formatter={(value: number) => money(value)} contentStyle={{ border: '1px solid #ecece8', borderRadius: 10, fontSize: 12 }} />
        <Area type="monotone" dataKey="revenue" stroke="#7666e9" strokeWidth={2.5} fill="url(#revFill)" />
      </AreaChart>
    </ResponsiveContainer>
  );
}
